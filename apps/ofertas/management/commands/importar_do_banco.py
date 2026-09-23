"""Importa uma mecânica direto do banco do ERP (somente leitura), no lugar
do .xls exportado à mão. Mesmas regras de classificação base/oferta de
`importar_relatorio_fabricante`.

Uso:
    python manage.py importar_do_banco kenvue --comparar   # só confere, NÃO grava
    python manage.py importar_do_banco kenvue               # carga completa (desde 01/01/2026)
    python manage.py importar_do_banco kenvue --dias 7      # atualização incremental (últimos 7 dias)
    python manage.py importar_do_banco todas --dias 7       # todas as mecânicas já liberadas

Piloto (23/09/26): Kenvue, Principia, Botica, Procter, Marketing,
Cestões e Leve 3.

Tipos de mecânica: `'fabricante'` (a maioria -- 1 ou mais fabricantes do
ERP, `consultar_venda_por_item`); `'tag'` (Marketing -- não é de 1
fabricante só, filtra por padrão de nome do caderno de oferta,
`consultar_venda_por_tag`, `fabricante=None` pega o fabricante por linha
do próprio banco); `'produtos_com_tag'` (Cestões -- acha produtos que já
tiveram a tag, depois traz o histórico completo deles,
`consultar_venda_por_produtos`); `'leve3'` (parecido com `'tag'`, mas o
fabricante do banco não serve -- genéricos de laboratórios diferentes
com o MESMO nome de produto entre eles, o painel precisa do cadastro
`apps.produtos` pra bater com o rótulo curto que `calcular_impacto_
leve3_fabricante`/Sellout usam, ex. "EMS"/"Eurofarma", não "EMS GENERICO
S/A" como o ERP chama); `'kimberly'` -- 1 fabricante só (como `'fabricante'`),
mas sem tag limpa pra oferta no ERP (achado antigo, não documentado no
docx) -- "oferta" é um filtro MANUAL (produto/venda máxima/janela de
data) aplicado linha a linha via `classificar_grupo`, não por tag."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Max, Sum

from apps.lojas.models import Loja
from apps.ofertas.erp import codigo_loja, fabricante_generico, tag_sem_prefixo
from apps.ofertas.erp_banco import (
    consultar_venda_por_item, consultar_venda_por_produtos, consultar_venda_por_tag,
)
from apps.ofertas.importadores import importar_relatorio_fabricante
from apps.ofertas.management.commands.importar_botica import TAGS_BOTICA
from apps.ofertas.models import Lancamento
from apps.produtos.services import mapa_fabricantes
from apps.verba.services import sincronizar_verba_leve3

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
    # 3º tipo, só pra Cestões: acha os produtos (Embalagem) que JÁ tiveram
    # a tag "OFERTAS CESTAO" alguma vez (histórico completo, não só o
    # período pedido -- senão um import incremental com --dias esqueceria
    # produto tageado fora da janela) e importa o HISTÓRICO INTEIRO desses
    # produtos, com ou sem a tag, de qualquer fabricante (docx, seção 5.4 --
    # mesma regra do importador antigo, "lista de produtos recalculada a
    # cada importação, não é fixa"). Achado (23/09/26): "CESTAO" com "%"
    # dos 2 lados também pegava "CESTAO PREÇO UNICO LOJA NN" -- caderno de
    # OUTRO projeto do Grupo Velanes (Cestão Preço Único, ferramenta
    # separada, nada a ver com esta mecânica), inflava de 24 pra 1.843
    # produtos. Sem "%" = ILIKE exato -- só "OFERTAS CESTAO" mesmo.
    'cestoes': {
        'tipo': 'produtos_com_tag', 'mecanica': Lancamento.CESTOES, 'fabricante': None,
        'filtro': 'OFERTAS CESTAO',
    },
    # 4º tipo: como 'tag' (não é 1 fabricante, filtra pela tag da promoção),
    # mas o fabricante do BANCO (razão social/pessoa jurídica) não serve --
    # ex. "EMS GENERICO S/A" -- o resto do painel (Sellout, `calcular_
    # impacto_leve3_fabricante`) espera o rótulo curto do cadastro
    # `apps.produtos` ("EMS"). `_processar` troca a coluna 'fabricante' do
    # df pelo cadastro (com a heurística velha de fallback) ANTES de
    # importar. Confirmado (23/09/26): só 2 variações de tag no banco
    # ("OFERTA GENERICOS LEVE 3 PAGUE 2" e "... -", claramente a mesma
    # promoção) -- diferente do Cestões, sem risco de pegar caderno de
    # outro projeto.
    'leve3': {
        'tipo': 'leve3', 'mecanica': Lancamento.LEVE3, 'fabricante': None,
        'filtro': '%LEVE 3%',
    },
    # 5º tipo: 1 fabricante só, mas sem tag de oferta limpa -- "Hipzinha" é
    # curadoria manual (docstring de `importar_kimberly` antigo). Achado
    # (23/09/26): o banco tem "KIMBERLY CLARK KENKO", "KLABIN KIMBERLY S/A"
    # e "KLABIN KIMBERLY SA" -- só o 1º tem venda no ano inteiro (os outros
    # 2, zero linhas jan-set/26), então nome exato sem "%" já resolve sem
    # precisar de lista. Filtro validado em 22/09/26 (backfill que bateu
    # exato com os 35 registros manuais de antes): produto contém
    # "HIPZINHA", venda da linha <= R$60, 27/07 a 02/08/2026.
    'kimberly': {
        'tipo': 'kimberly', 'mecanica': Lancamento.KIMBERLY, 'tags': [],
        'fabricante': 'Kimberly Clark', 'filtro': 'KIMBERLY CLARK KENKO',
    },
}

# Filtro manual da promoção Hipzinha (Kimberly) -- ver comentário acima.
HIPZINHA_PRODUTO = 'HIPZINHA'
HIPZINHA_VENDA_MAX = 60
HIPZINHA_INICIO = date(2026, 7, 27)
HIPZINHA_FIM = date(2026, 8, 2)


def _classificar_hipzinha(linha) -> str:
    produto = str(linha['embalagem'] or '')
    if HIPZINHA_PRODUTO not in produto.upper():
        return ''
    venda = linha['venda']
    if venda is not None and float(venda) > HIPZINHA_VENDA_MAX:
        return ''
    data = linha['data']
    if hasattr(data, 'date'):
        data = data.date()
    if data is None or not (HIPZINHA_INICIO <= data <= HIPZINHA_FIM):
        return ''
    return Lancamento.GRUPO_OFERTA
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
        if cfg['tipo'] in ('fabricante', 'kimberly'):
            df = consultar_venda_por_item(inicio, fim, filtro)
            tags_alvo = {cfg['tags'].upper()} if isinstance(cfg['tags'], str) else {t.upper() for t in cfg['tags']}
        elif cfg['tipo'] in ('tag', 'leve3'):
            df = consultar_venda_por_tag(inicio, fim, filtro)
            # Todo mundo que a consulta trouxe já bate o padrão da tag --
            # deriva a lista de tags EXATAS achadas (pode variar por mês,
            # ex. "PRODUTOS MARKETING AGOSTO"/"...SETEMBRO") em vez de fixar
            # uma lista, senão um mês novo nunca visto ficaria de fora.
            tags_alvo = {tag_sem_prefixo(t).upper() for t in df['detalhe_desconto'].dropna().unique()}
            if cfg['tipo'] == 'leve3':
                # O fabricante do BANCO é a razão social (ex. "EMS GENERICO
                # S/A") -- troca pelo rótulo curto do cadastro `apps.produtos`
                # (ex. "EMS"), que é o que Sellout/impacto por fabricante
                # esperam. Heurística velha só como fallback de segurança.
                mapa_fab = mapa_fabricantes()
                df['fabricante'] = df['embalagem'].map(
                    lambda p: mapa_fab.get(p) or fabricante_generico(p)
                )
        else:  # 'produtos_com_tag' (Cestões)
            # A descoberta de QUAIS produtos usa sempre o histórico completo
            # (INICIO_PADRAO-hoje), nunca só a janela [inicio, fim] -- senão
            # um `--dias 7` esqueceria produto tageado fora da janela e o
            # próximo import apagaria o histórico dele por engano.
            candidatos = consultar_venda_por_tag(INICIO_PADRAO, hoje, filtro)
            produtos = sorted(candidatos['embalagem'].dropna().unique())
            if not produtos:
                raise CommandError(f'{nome}: nenhum produto com a tag "{filtro}" encontrado no banco.')
            tags_alvo = {tag_sem_prefixo(t).upper() for t in candidatos['detalhe_desconto'].dropna().unique()}
            df = consultar_venda_por_produtos(inicio, fim, produtos)
            self.stdout.write(f'{nome}: {len(produtos)} produtos com a tag (histórico completo).')
        self.stdout.write(f'{nome}: {len(df)} linhas no banco '
                          f'(fabricantes: {", ".join(sorted(df["fabricante"].dropna().unique())) or "-"}).')

        if opts['comparar']:
            self._comparar(nome, mecanica, df, tags_alvo, inicio, fim)
            return

        desde = inicio if opts['dias'] else None
        classificar_grupo = _classificar_hipzinha if cfg['tipo'] == 'kimberly' else None
        resultado = importar_relatorio_fabricante(
            None, mecanica, sorted(tags_alvo), fabricante=fabricante,
            df=df, origem=ORIGEM, desde=desde, classificar_grupo=classificar_grupo,
        )
        self.stdout.write(self.style.SUCCESS(
            f"{nome}: {resultado['importados']} lançamentos gravados "
            f"({resultado['apagados']} substituídos), fonte: banco."
        ))
        if resultado['lojas_sem_cadastro']:
            self.stdout.write(self.style.WARNING(
                f"Lojas sem cadastro (ignoradas): {', '.join(sorted(resultado['lojas_sem_cadastro']))}."
            ))

        if cfg['tipo'] == 'leve3':
            verbas = sincronizar_verba_leve3()
            self.stdout.write(self.style.SUCCESS(
                f'Verba: valor_apurado atualizado em {len(verbas)} mês(es) (VerbaMensal, mecânica leve3).'
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
