"""Importa uma mecânica de "impacto por fabricante" direto do banco do ERP
(somente leitura), no lugar do .xls exportado à mão. Mesmas regras de
classificação base/oferta de `importar_relatorio_fabricante`.

Uso:
    python manage.py importar_do_banco kenvue --comparar   # só confere, NÃO grava
    python manage.py importar_do_banco kenvue               # carga completa (desde 01/01/2026)
    python manage.py importar_do_banco kenvue --dias 7      # atualização incremental (últimos 7 dias)
    python manage.py importar_do_banco todas --dias 7       # todas as mecânicas já liberadas

Piloto (23/09/26): Kenvue, Principia, Botica e Procter.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Max, Sum

from apps.lojas.models import Loja
from apps.ofertas.erp import codigo_loja, tag_sem_prefixo
from apps.ofertas.erp_banco import consultar_venda_por_item
from apps.ofertas.importadores import importar_relatorio_fabricante
from apps.ofertas.management.commands.importar_botica import TAGS_BOTICA
from apps.ofertas.models import Lancamento

# 2 tags = 2 campanhas coexistindo na mesma tela (promoção mensal + Semana
# do Cliente) -- `importar_relatorio_fabricante` já separa por campanha
# (agrupa por `tag_origem`) quando `tag_alvo` é uma lista, mesmo mecanismo
# usado pro Botica. Isso substitui o fluxo antigo de 2 arquivos/2 comandos
# com `escopo_delete='arquivo'` -- o banco traz os 2 numa consulta só.
TAGS_PROCTER = ['PROMOÇÃO PROCTER', 'OFERTAS PROCTER SEMANA DO CLIENTE']

# mecânica -> (tag(s) da oferta, rótulo do fabricante no painel, filtro do fabricante no ERP:
# 1 padrão ILIKE ou uma lista de nomes EXATOS quando agrupa mais de 1 fabricante do ERP)
MECANICAS = {
    'kenvue': (Lancamento.KENVUE, 'PROMOÇÃO KENVUE', 'Kenvue', '%KENVUE%'),
    'principia': (Lancamento.PRINCIPIA, 'PROMOÇÃO PRINCIPIA 15 %', 'Principia', '%PRINCIPIA%'),
    # Confirmado com o Gabriel (23/09/26): o grupo "Botica" no painel é
    # Botica + Siage + Vult -- NÃO inclui "BOTICA LA PIEL" (fabricante
    # separado no ERP, achado ao investigar a divergência banco x planilha).
    'botica': (Lancamento.BOTICA, TAGS_BOTICA, 'Botica', ['BOTICA', 'SIAGE EUDORA', 'VULT']),
    # Achado (23/09/26): o banco tem "PROCTER & GAMBLE" e "PROCTER FARMA"
    # separados -- diferente do Botica/Siage/Vult, "PROCTER FARMA" (R$42mil
    # em jan/26 sozinho, nada pequeno) NÃO carrega nenhuma das 2 tags de
    # oferta em nenhum mês (jan-set/26 conferido) -- não participa da
    # promoção, fica de fora sem precisar perguntar ao Gabriel. String sem
    # "%" = ILIKE exato (case-insensitive), não pega "PROCTER FARMA".
    'procter': (Lancamento.PROCTER, TAGS_PROCTER, 'Procter & Gamble', 'PROCTER & GAMBLE'),
}
INICIO_PADRAO = date(2026, 1, 1)
ORIGEM = 'banco'


def _data(texto: str) -> date:
    return datetime.strptime(texto, '%Y-%m-%d').date()


class Command(BaseCommand):
    help = 'Importa ofertas de fabricante direto do banco do ERP (somente leitura).'

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
        mecanica, tags, fabricante, fabricante_like = MECANICAS[nome]
        tags_alvo = {tags.upper()} if isinstance(tags, str) else {t.upper() for t in tags}
        hoje = date.today()

        if opts['comparar']:
            ultimo = Lancamento.objects.filter(mecanica=mecanica).aggregate(m=Max('data'))['m']
            if ultimo is None:
                raise CommandError(f'{nome}: o painel não tem dados diários pra comparar.')
            inicio = opts['inicio'] or INICIO_PADRAO
            # exclui o último dia do painel (a exportação costuma ser no meio do dia)
            fim = opts['fim'] or ultimo
        elif opts['dias']:
            inicio = hoje - timedelta(days=opts['dias'])
            fim = opts['fim'] or hoje
        else:
            inicio = opts['inicio'] or INICIO_PADRAO
            fim = opts['fim'] or hoje

        self.stdout.write(f'{nome}: consultando o banco de {inicio:%d/%m/%Y} até {fim - timedelta(days=1):%d/%m/%Y}...')
        df = consultar_venda_por_item(inicio, fim, fabricante_like)
        self.stdout.write(f'{nome}: {len(df)} linhas no banco '
                          f'(fabricantes: {", ".join(sorted(df["fabricante"].dropna().unique())) or "-"}).')

        if opts['comparar']:
            self._comparar(nome, mecanica, df, tags_alvo, inicio, fim)
            return

        desde = inicio if opts['dias'] else None
        resultado = importar_relatorio_fabricante(
            None, mecanica, tags, fabricante=fabricante,
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
        qs = Lancamento.objects.filter(mecanica=mecanica, data__gte=inicio, data__lt=fim)
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
