"""Importa uma mecânica direto do banco do ERP (somente leitura), no lugar
do .xls exportado à mão. Mesmas regras de classificação base/oferta de
`importar_relatorio_fabricante`.

Uso:
    python manage.py importar_do_banco kenvue --comparar   # só confere, NÃO grava
    python manage.py importar_do_banco kenvue               # carga completa (desde 01/01/2026)
    python manage.py importar_do_banco kenvue --dias 7      # atualização incremental (últimos 7 dias)
    python manage.py importar_do_banco todas --dias 7       # todas as mecânicas já liberadas

Piloto (23/09/26): Kenvue, Principia, Botica, Procter e Marketing.

2 "tipos" de mecânica: `'fabricante'` (a maioria -- 1 ou mais fabricantes
do ERP, `consultar_venda_por_item`) e `'tag'` (Marketing -- não é de 1
fabricante só, filtra por padrão de nome do caderno de oferta em vez de
fabricante, `consultar_venda_por_tag`; usa `fabricante=None` em
`importar_relatorio_fabricante` pra pegar o fabricante por linha do
próprio banco, já que a mecânica espalha por vários)."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Max, Sum

from apps.lojas.models import Loja
from apps.ofertas.erp import codigo_loja, tag_sem_prefixo
from apps.ofertas.erp_banco import consultar_venda_por_item, consultar_venda_por_tag
from apps.ofertas.importadores import importar_relatorio_fabricante
from apps.ofertas.management.commands.importar_botica import TAGS_BOTICA
from apps.ofertas.models import Lancamento

# 2 tags = 2 campanhas coexistindo na mesma tela (promoção mensal + Semana
# do Cliente) -- `importar_relatorio_fabricante` já separa por campanha
# (agrupa por `tag_origem`) quando `tag_alvo` é uma lista, mesmo mecanismo
# usado pro Botica. Isso substitui o fluxo antigo de 2 arquivos/2 comandos
# com `escopo_delete='arquivo'` -- o banco traz os 2 numa consulta só.
TAGS_PROCTER = ['PROMOÇÃO PROCTER', 'OFERTAS PROCTER SEMANA DO CLIENTE']

# mecânica -> {tipo, mecanica, tags (só tipo='fabricante'), fabricante (rótulo fixo
# ou None = por linha), filtro (padrão ILIKE/lista exata de fabricante, ou padrão
# ILIKE do nome do caderno de oferta quando tipo='tag')}
MECANICAS = {
    'kenvue': {
        'tipo': 'fabricante', 'mecanica': Lancamento.KENVUE, 'tags': 'PROMOÇÃO KENVUE',
        'fabricante': 'Kenvue', 'filtro': '%KENVUE%',
    },
    'principia': {
        'tipo': 'fabricante', 'mecanica': Lancamento.PRINCIPIA, 'tags': 'PROMOÇÃO PRINCIPIA 15 %',
        'fabricante': 'Principia', 'filtro': '%PRINCIPIA%',
    },
    # Confirmado com o Gabriel (23/09/26): o grupo "Botica" no painel é
    # Botica + Siage + Vult -- NÃO inclui "BOTICA LA PIEL" (fabricante
    # separado no ERP, achado ao investigar a divergência banco x planilha).
    'botica': {
        'tipo': 'fabricante', 'mecanica': Lancamento.BOTICA, 'tags': TAGS_BOTICA,
        'fabricante': 'Botica', 'filtro': ['BOTICA', 'SIAGE EUDORA', 'VULT'],
    },
    # Achado (23/09/26): o banco tem "PROCTER & GAMBLE" e "PROCTER FARMA"
    # separados -- diferente do Botica/Siage/Vult, "PROCTER FARMA" (R$42mil
    # em jan/26 sozinho, nada pequeno) NÃO carrega nenhuma das 2 tags de
    # oferta em nenhum mês (jan-set/26 conferido) -- não participa da
    # promoção, fica de fora sem precisar perguntar ao Gabriel. String sem
    # "%" = ILIKE exato (case-insensitive), não pega "PROCTER FARMA".
    'procter': {
        'tipo': 'fabricante', 'mecanica': Lancamento.PROCTER, 'tags': TAGS_PROCTER,
        'fabricante': 'Procter & Gamble', 'filtro': 'PROCTER & GAMBLE',
    },
    # Diferente dos outros: qualquer fabricante, filtro é o padrão do CADERNO
    # DE OFERTA ("PRODUTOS MARKETING <mês>" -- o mês varia, daí o padrão em
    # vez de lista fixa). Achado (23/09/26): o banco tem jan-set/26 inteiro
    # (80.791 linhas) -- a planilha antiga só tinha agosto (pendência antiga
    # "Marketing só tem 1 mês" fica resolvida de graça com o banco).
    'marketing': {
        'tipo': 'tag', 'mecanica': Lancamento.MARKETING, 'fabricante': None,
        'filtro': 'PRODUTOS MARKETING%',
    },
}
INICIO_PADRAO = date(2026, 1, 1)
ORIGEM = 'banco'


def _data(texto: str) -> date:
    return datetime.strptime(texto, '%Y-%m-%d').date()


class Command(BaseCommand):
    help = 'Importa uma mecânica direto do banco do ERP (somente leitura).'

    def add_arguments(self, parser):
        parser.add_argument('mecanica', choices=[*MECANICAS, 'todas'])
        parser.add_argument('--comparar', action='store_true',
                            help='Só compara banco x dados atuais do painel, mês a mês. Não grava nada.')
        parser.add_argument('--dias', type=int, default=None,
                            help='Atualização incremental: refaz só os últimos N dias.')
        parser.add_argument('--inicio', type=_data, default=None, help='AAAA-MM-DD (padrão 2026-01-01).')
        parser.add_argument('--fim', type=_data, default=None,
                            help='AAAA-MM-DD, exclusivo (padrão: hoje, ou seja, até ontem).')

    def handle(self, *args, **opts):
        nomes = list(MECANICAS) if opts['mecanica'] == 'todas' else [opts['mecanica']]
        for nome in nomes:
            self._processar(nome, opts)

    def _processar(self, nome, opts):
        cfg = MECANICAS[nome]
        mecanica, fabricante, filtro = cfg['mecanica'], cfg['fabricante'], cfg['filtro']
        hoje = date.today()

        if opts['comparar']:
            inicio = opts['inicio'] or INICIO_PADRAO
            # Exclui o último dia do painel (a exportação costuma ser no meio
            # do dia) -- se a mecânica nunca teve dado diário no painel (ex.
            # Marketing, cujo import antigo só guardava "Ano-mês"), cai pra
            # "até hoje" -- não dá pra alinhar com um corte que não existe.
            ultimo = Lancamento.objects.filter(
                mecanica=mecanica, data__isnull=False
            ).aggregate(m=Max('data'))['m']
            fim = opts['fim'] or ultimo or hoje
        elif opts['dias']:
            inicio = hoje - timedelta(days=opts['dias'])
            fim = opts['fim'] or hoje
        else:
            inicio = opts['inicio'] or INICIO_PADRAO
            fim = opts['fim'] or hoje

        self.stdout.write(f'{nome}: consultando o banco de {inicio:%d/%m/%Y} até {fim - timedelta(days=1):%d/%m/%Y}...')
        if cfg['tipo'] == 'fabricante':
            df = consultar_venda_por_item(inicio, fim, filtro)
            tags_alvo = {cfg['tags'].upper()} if isinstance(cfg['tags'], str) else {t.upper() for t in cfg['tags']}
        else:  # 'tag'
            df = consultar_venda_por_tag(inicio, fim, filtro)
            # Todo mundo que a consulta trouxe já bate o padrão da tag --
            # deriva a lista de tags EXATAS achadas (pode variar por mês,
            # ex. "PRODUTOS MARKETING AGOSTO"/"...SETEMBRO") em vez de fixar
            # uma lista, senão um mês novo nunca visto ficaria de fora.
            tags_alvo = {tag_sem_prefixo(t).upper() for t in df['detalhe_desconto'].dropna().unique()}
        self.stdout.write(f'{nome}: {len(df)} linhas no banco '
                          f'(fabricantes: {", ".join(sorted(df["fabricante"].dropna().unique())) or "-"}).')

        if opts['comparar']:
            self._comparar(nome, mecanica, df, tags_alvo, inicio, fim)
            return

        desde = inicio if opts['dias'] else None
        resultado = importar_relatorio_fabricante(
            None, mecanica, sorted(tags_alvo), fabricante=fabricante,
            df=df, origem=ORIGEM, desde=desde,
        )
        self.stdout.write(self.style.SUCCESS(
            f"{nome}: {resultado['importados']} lançamentos gravados "
            f"({resultado['apagados']} substituídos), fonte: banco."
        ))
        if resultado['lojas_sem_cadastro']:
            self.stdout.write(self.style.WARNING(
                f"Lojas sem cadastro (ignoradas): {', '.join(sorted(resultado['lojas_sem_cadastro']))}."
            ))

    def _comparar(self, nome, mecanica, df, tags_alvo, inicio, fim):
        lojas = set(Loja.objects.values_list('codigo', flat=True))
        banco = defaultdict(lambda: defaultdict(float))
        for linha in df.itertuples(index=False):
            if codigo_loja(linha.cod_un_neg) not in lojas:
                continue
            mes = f'{linha.data:%Y-%m}'
            banco[mes]['itens'] += linha.itens
            banco[mes]['venda'] += linha.venda
            banco[mes]['custo'] += linha.custo
            if tag_sem_prefixo(linha.detalhe_desconto).upper() in tags_alvo:
                banco[mes]['venda_oferta'] += linha.venda

        painel = defaultdict(lambda: defaultdict(float))
        # Por 'ano_mes' (sempre preenchido), não por 'data' -- algumas
        # mecânicas (ex. Marketing, antes de vir do banco) nunca guardaram
        # data por linha, só o mês; filtrar por 'data' excluiria elas inteiras.
        mes_inicio, mes_fim = f'{inicio:%Y-%m}', f'{fim - timedelta(days=1):%Y-%m}'
        qs = Lancamento.objects.filter(mecanica=mecanica, ano_mes__gte=mes_inicio, ano_mes__lte=mes_fim)
        for r in qs.values('ano_mes', 'grupo').annotate(i=Sum('itens'), v=Sum('venda'), c=Sum('custo')):
            p = painel[r['ano_mes']]
            p['itens'] += float(r['i']); p['venda'] += float(r['v']); p['custo'] += float(r['c'])
            if r['grupo'] == Lancamento.GRUPO_OFERTA:
                p['venda_oferta'] += float(r['v'])

        def pct(a, b):
            return f'{(a - b) / b * 100:+.2f}%' if b else '   -  '

        self.stdout.write('')
        self.stdout.write(f'{nome.upper()} -- banco x painel atual (planilha), '
                          f'{inicio:%d/%m} a {fim - timedelta(days=1):%d/%m/%Y}')
        cab = f"{'mês':8} {'venda banco':>14} {'venda painel':>14} {'dif':>8}  {'custo dif':>9}  {'itens dif':>9}  {'oferta dif':>10}"
        self.stdout.write(cab)
        self.stdout.write('-' * len(cab))
        tot_b = defaultdict(float); tot_p = defaultdict(float)
        for mes in sorted(set(banco) | set(painel)):
            b, p = banco[mes], painel[mes]
            for k in ('itens', 'venda', 'custo', 'venda_oferta'):
                tot_b[k] += b[k]; tot_p[k] += p[k]
            self.stdout.write(
                f"{mes:8} {b['venda']:>14,.2f} {p['venda']:>14,.2f} {pct(b['venda'], p['venda']):>8}  "
                f"{pct(b['custo'], p['custo']):>9}  {pct(b['itens'], p['itens']):>9}  "
                f"{pct(b['venda_oferta'], p['venda_oferta']):>10}"
            )
        self.stdout.write('-' * len(cab))
        self.stdout.write(
            f"{'TOTAL':8} {tot_b['venda']:>14,.2f} {tot_p['venda']:>14,.2f} {pct(tot_b['venda'], tot_p['venda']):>8}  "
            f"{pct(tot_b['custo'], tot_p['custo']):>9}  {pct(tot_b['itens'], tot_p['itens']):>9}  "
            f"{pct(tot_b['venda_oferta'], tot_p['venda_oferta']):>10}"
        )
        self.stdout.write(self.style.WARNING('Modo --comparar: nada foi gravado.'))
