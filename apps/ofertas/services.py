"""Serviços de cálculo por ação de oferta.

Cada `calcular_<ação>(queryset)` recebe um queryset de `Lancamento` já
filtrado por ação (e por bandeira, se for o caso) e devolve os números
prontos pra tela — sem pré-agregação em banco, pra granularidade bater com
o filtro de bandeira em qualquer combinação (ver docx, seção 9).

Cada função também devolve, além da visão "loja a loja", uma visão macro
por bandeira (`ranking_bandeiras`) e uma série mensal por produto/grupo
alinhada aos mesmos meses do gráfico geral (`series_produtos`), usada pra
trocar a linha do gráfico ao clicar numa linha da tabela.
"""
from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from apps.lojas.models import Loja

from .erp import ano_mes_de
from .models import Lancamento

ZERO = Decimal('0')
ROTULOS_BANDEIRA = {'velanes': 'Velanes', 'ultra_popular': 'Ultra Popular'}

# Evento pontual de degustação Supra Corp Day (docx, seção 5.2) — data fixa,
# não um padrão recorrente. Se um novo evento acontecer, este valor (e o
# import) precisam ser atualizados/generalizados.
EVENTO_SUPRACORP = date(2026, 8, 5)
JANELA_SUPRACORP = {EVENTO_SUPRACORP, EVENTO_SUPRACORP + timedelta(days=1)}


def bandeira_da_request(request) -> str:
    """Lê o filtro global de bandeira (?bandeira=velanes|ultra_popular) —
    usado por toda view que lista `Lancamento`."""
    valor = request.GET.get('bandeira', '')
    if valor not in ('velanes', 'ultra_popular'):
        return ''
    return valor


def filtrar_por_bandeira(queryset, bandeira: str):
    if bandeira:
        return queryset.filter(loja__bandeira=bandeira)
    return queryset


def meses_disponiveis(mecanica: str = '') -> list:
    """ano_mes distintos já importados — de todas as ações (dashboard) ou
    só de uma (`mecanica`, pro filtro de mês dentro de cada tela de ação)."""
    queryset = Lancamento.objects.all()
    if mecanica:
        queryset = queryset.filter(mecanica=mecanica)
    return sorted(v for v in queryset.values_list('ano_mes', flat=True).distinct() if v)


def mes_da_request(request, mecanica: str = '') -> str:
    """Lê o filtro global de mês (?mes=AAAA-MM), validando contra os meses
    que existem pra essa mecânica — mês inexistente (ou de outra ação)
    vira 'Todos os meses' em vez de zerar a tela."""
    valor = request.GET.get('mes', '').strip()
    return valor if valor in meses_disponiveis(mecanica) else ''


def querystring_extra(request, excluir=('bandeira', 'mes')) -> dict:
    """Parâmetros de GET a preservar no form de bandeira/mês (busca,
    fabricante selecionado etc.) — pra trocar um filtro sem perder o
    resto."""
    return {chave: valor for chave, valor in request.GET.items() if chave not in excluir and valor}


def grafico_mensal(por_mes, campos) -> dict:
    """Converte uma série `por_mes` (lista de dicts com 'ano_mes' + Decimals)
    em {labels, series} pronto pro `graficoLinha`/`graficoBarra` do JS —
    Decimal não serializa em JSON, então converte pra float aqui.

    `campos` é uma lista de `(chave, rótulo)` ou `(chave, rótulo, eixo)` —
    `eixo` é 'moeda' (padrão, escala à esquerda em R$) ou 'unidades'
    (escala à direita, sem grade, pro JS não misturar item com dinheiro
    numa métrica só)."""
    labels = [item['ano_mes'] for item in por_mes]
    series = [
        {
            'label': campo[1],
            'eixo': campo[2] if len(campo) > 2 else 'moeda',
            'data': [float(item.get(campo[0]) or 0) for item in por_mes],
        }
        for campo in campos
    ]
    return {'labels': labels, 'series': series}


def agrupar_por_bandeira(por_loja_items, campos) -> list:
    """Soma `campos` (numéricos, aditivos) de uma lista loja-a-loja em até
    2 linhas por bandeira — a visão "macro" ao lado do loja-a-loja. Só serve
    pra campos que são soma pura (venda, itens, investimento...); campos que
    são razão (margem %, impacto) precisam ser recalculados à parte."""
    agregados = {}
    for item in por_loja_items:
        chave = item['bandeira']
        alvo = agregados.setdefault(
            chave, {'bandeira': ROTULOS_BANDEIRA.get(chave, chave), **{c: ZERO for c in campos}}
        )
        for c in campos:
            alvo[c] += item.get(c) or ZERO
    return [agregados[c] for c in ('velanes', 'ultra_popular') if c in agregados]


def alinhar_com_labels(acumulador, labels) -> dict:
    """{chave: {ano_mes: valor}} -> {chave: [valores alinhados a `labels`]}
    — pronto pro JS trocar a linha do gráfico ao clicar numa linha da
    tabela (produto, fabricante etc.)."""
    return {
        chave: [float(meses.get(mes, ZERO)) for mes in labels]
        for chave, meses in acumulador.items()
    }


def calcular_leve3(queryset, busca: str = ''):
    """Leve 3 Pague 2 (docx, seção 5.1 e 6):
    ciclos = INT(itens / 3); investimento = ciclos × (custo da linha / itens
    da linha); margem ajustada = margem contábil (lucro) + investimento.
    Tudo calculado linha a linha, antes de somar.
    """
    linhas = queryset.select_related('loja').values(
        'loja_id', 'loja__codigo', 'loja__bandeira', 'produto_descricao',
        'ano_mes', 'itens', 'venda', 'custo', 'lucro',
    )

    total_itens = ZERO
    total_ciclos = ZERO
    total_investimento = ZERO
    total_venda = ZERO
    total_margem_contabil = ZERO

    por_mes = defaultdict(lambda: {'itens': ZERO, 'venda': ZERO, 'investimento': ZERO, 'margem_contabil': ZERO, 'margem_ajustada': ZERO})
    por_loja = defaultdict(lambda: {
        'codigo': '', 'bandeira': '', 'itens': ZERO, 'venda': ZERO,
        'margem_contabil': ZERO, 'margem_ajustada': ZERO, 'investimento': ZERO,
    })
    por_produto = defaultdict(lambda: {'itens': ZERO, 'ciclos': ZERO, 'investimento': ZERO, 'venda': ZERO, 'custo': ZERO, 'lucro': ZERO})
    por_produto_mes = defaultdict(lambda: defaultdict(lambda: ZERO))

    for linha in linhas:
        itens = linha['itens'] or ZERO
        custo = linha['custo'] or ZERO
        lucro = linha['lucro'] or ZERO
        venda = linha['venda'] or ZERO

        ciclos = itens // 3
        custo_unitario = (custo / itens) if itens else ZERO
        investimento = ciclos * custo_unitario
        margem_ajustada = lucro + investimento

        total_itens += itens
        total_ciclos += ciclos
        total_investimento += investimento
        total_venda += venda
        total_margem_contabil += lucro

        mes = por_mes[linha['ano_mes']]
        mes['itens'] += itens
        mes['venda'] += venda
        mes['investimento'] += investimento
        mes['margem_contabil'] += lucro
        mes['margem_ajustada'] += margem_ajustada

        loja = por_loja[linha['loja_id']]
        loja['codigo'] = linha['loja__codigo']
        loja['bandeira'] = linha['loja__bandeira']
        loja['itens'] += itens
        loja['venda'] += venda
        loja['margem_contabil'] += lucro
        loja['margem_ajustada'] += margem_ajustada
        loja['investimento'] += investimento

        produto = por_produto[linha['produto_descricao']]
        produto['itens'] += itens
        produto['ciclos'] += ciclos
        produto['investimento'] += investimento
        produto['venda'] += venda
        produto['custo'] += custo
        produto['lucro'] += lucro
        por_produto_mes[linha['produto_descricao']][linha['ano_mes']] += venda

    produtos = [
        {'produto': nome, **valores} for nome, valores in por_produto.items()
        if not busca or busca.lower() in nome.lower()
    ]
    produtos.sort(key=lambda p: p['venda'], reverse=True)

    por_mes_lista = [{'ano_mes': mes, **valores} for mes, valores in sorted(por_mes.items())]
    labels = [item['ano_mes'] for item in por_mes_lista]

    return {
        'kpis': {
            'itens': total_itens,
            'ciclos': total_ciclos,
            'investimento': total_investimento,
            'venda': total_venda,
            'margem_contabil': total_margem_contabil,
            'margem_ajustada': total_margem_contabil + total_investimento,
        },
        'por_mes': por_mes_lista,
        'ranking_lojas': sorted(por_loja.values(), key=lambda l: l['investimento'], reverse=True),
        'ranking_bandeiras': agrupar_por_bandeira(
            por_loja.values(), ['itens', 'venda', 'investimento', 'margem_contabil', 'margem_ajustada']
        ),
        'produtos': produtos,
        'series_produtos': alinhar_com_labels(por_produto_mes, labels),
    }


def calcular_cestoes(queryset, busca: str = ''):
    """Cestões (docx, seção 5.4 e 7.4): sem mecânica de verba por ora — só
    performance (venda, unidades, margem), com o histórico completo desde
    janeiro dos produtos hoje marcados em cestão."""
    linhas = queryset.select_related('loja').values(
        'loja_id', 'loja__codigo', 'loja__bandeira', 'produto_descricao',
        'ano_mes', 'itens', 'venda', 'custo', 'lucro',
    )

    total_itens = ZERO
    total_venda = ZERO
    total_custo = ZERO
    total_lucro = ZERO

    por_mes = defaultdict(lambda: {'itens': ZERO, 'venda': ZERO, 'lucro': ZERO})
    por_loja = defaultdict(lambda: {'codigo': '', 'bandeira': '', 'itens': ZERO, 'venda': ZERO, 'lucro': ZERO})
    por_produto = defaultdict(lambda: {'itens': ZERO, 'venda': ZERO, 'custo': ZERO, 'lucro': ZERO})
    por_produto_mes = defaultdict(lambda: defaultdict(lambda: ZERO))

    for linha in linhas:
        itens = linha['itens'] or ZERO
        venda = linha['venda'] or ZERO
        custo = linha['custo'] or ZERO
        lucro = linha['lucro'] or ZERO

        total_itens += itens
        total_venda += venda
        total_custo += custo
        total_lucro += lucro

        mes = por_mes[linha['ano_mes']]
        mes['itens'] += itens
        mes['venda'] += venda
        mes['lucro'] += lucro

        loja = por_loja[linha['loja_id']]
        loja['codigo'] = linha['loja__codigo']
        loja['bandeira'] = linha['loja__bandeira']
        loja['itens'] += itens
        loja['venda'] += venda
        loja['lucro'] += lucro

        produto = por_produto[linha['produto_descricao']]
        produto['itens'] += itens
        produto['venda'] += venda
        produto['custo'] += custo
        produto['lucro'] += lucro
        por_produto_mes[linha['produto_descricao']][linha['ano_mes']] += venda

    produtos = [
        {'produto': nome, **valores} for nome, valores in por_produto.items()
        if not busca or busca.lower() in nome.lower()
    ]
    produtos.sort(key=lambda p: p['venda'], reverse=True)

    margem_pct = (total_lucro / total_venda * 100) if total_venda else ZERO
    por_mes_lista = [{'ano_mes': mes, **valores} for mes, valores in sorted(por_mes.items())]
    labels = [item['ano_mes'] for item in por_mes_lista]

    return {
        'kpis': {
            'itens': total_itens,
            'venda': total_venda,
            'lucro': total_lucro,
            'margem_pct': margem_pct,
            'produtos': len(por_produto),
        },
        'por_mes': por_mes_lista,
        'ranking_lojas': sorted(por_loja.values(), key=lambda l: l['venda'], reverse=True),
        'ranking_bandeiras': agrupar_por_bandeira(por_loja.values(), ['itens', 'venda', 'lucro']),
        'produtos': produtos,
        'series_produtos': alinhar_com_labels(por_produto_mes, labels),
    }


def calcular_supracorp(queryset):
    """Degustação Supra Corp Day (docx, seção 5.2): impacto = itens vendidos
    na janela do evento (dia do evento + o dia seguinte) ÷ média diária de
    vendas no resto do mês — geral, por loja/bandeira e por produto."""
    linhas = list(queryset.select_related('loja').values(
        'loja_id', 'loja__codigo', 'loja__bandeira', 'produto_descricao',
        'data', 'itens', 'venda',
    ))

    dias_no_mes = calendar.monthrange(EVENTO_SUPRACORP.year, EVENTO_SUPRACORP.month)[1]
    dias_resto = dias_no_mes - len(JANELA_SUPRACORP)

    por_dia = defaultdict(lambda: {'itens': ZERO, 'venda': ZERO})
    por_loja = defaultdict(lambda: {
        'codigo': '', 'bandeira': '',
        'itens_evento': ZERO, 'itens_resto': ZERO,
    })
    por_bandeira_raw = defaultdict(lambda: {'itens_evento': ZERO, 'itens_resto': ZERO})
    por_produto = defaultdict(lambda: {'itens_evento': ZERO, 'venda_evento': ZERO})
    por_produto_mes = defaultdict(lambda: defaultdict(lambda: ZERO))

    total_itens_evento = ZERO
    total_venda_evento = ZERO
    total_itens_resto = ZERO

    for linha in linhas:
        data = linha['data']
        if data is None:
            continue
        itens = linha['itens'] or ZERO
        venda = linha['venda'] or ZERO
        na_janela = data in JANELA_SUPRACORP
        ano_mes = f'{data.year:04d}-{data.month:02d}'

        dia = por_dia[data]
        dia['itens'] += itens
        dia['venda'] += venda

        loja = por_loja[linha['loja_id']]
        loja['codigo'] = linha['loja__codigo']
        loja['bandeira'] = linha['loja__bandeira']
        bandeira_raw = por_bandeira_raw[linha['loja__bandeira']]

        if na_janela:
            total_itens_evento += itens
            total_venda_evento += venda
            loja['itens_evento'] += itens
            bandeira_raw['itens_evento'] += itens
            produto = por_produto[linha['produto_descricao']]
            produto['itens_evento'] += itens
            produto['venda_evento'] += venda
        else:
            total_itens_resto += itens
            loja['itens_resto'] += itens
            bandeira_raw['itens_resto'] += itens
            por_produto_mes[linha['produto_descricao']][ano_mes] += itens

    media_diaria_geral = (total_itens_resto / dias_resto) if dias_resto else ZERO
    impacto_geral = (total_itens_evento / media_diaria_geral) if media_diaria_geral else None

    ranking_lojas = []
    for loja in por_loja.values():
        media = (loja['itens_resto'] / dias_resto) if dias_resto else ZERO
        impacto = (loja['itens_evento'] / media) if media else None
        ranking_lojas.append({**loja, 'media_diaria': media, 'impacto': impacto})
    ranking_lojas.sort(key=lambda l: l['itens_evento'], reverse=True)

    ranking_bandeiras = []
    for chave in ('velanes', 'ultra_popular'):
        if chave not in por_bandeira_raw:
            continue
        d = por_bandeira_raw[chave]
        media = (d['itens_resto'] / dias_resto) if dias_resto else ZERO
        impacto = (d['itens_evento'] / media) if media else None
        ranking_bandeiras.append({
            'bandeira': ROTULOS_BANDEIRA[chave], 'itens_evento': d['itens_evento'],
            'media_diaria': media, 'impacto': impacto,
        })

    produtos = sorted(por_produto.items(), key=lambda kv: kv[1]['venda_evento'], reverse=True)
    produtos = [{'produto': nome, **valores} for nome, valores in produtos]

    serie_diaria = [
        {'data': dia, 'na_janela': dia in JANELA_SUPRACORP, **valores}
        for dia, valores in sorted(por_dia.items())
    ]

    return {
        'kpis': {
            'itens_evento': total_itens_evento,
            'venda_evento': total_venda_evento,
            'media_diaria_geral': media_diaria_geral,
            'impacto_geral': impacto_geral,
        },
        'serie_diaria': serie_diaria,
        'ranking_lojas': ranking_lojas,
        'ranking_bandeiras': ranking_bandeiras,
        'produtos': produtos,
        'evento_data': EVENTO_SUPRACORP,
    }


def calcular_impacto_fabricante(queryset, busca: str = ''):
    """Oferta por fabricante — Kenvue/Principia/Botica/Procter (docx, seção
    5.3): compara volume/venda/margem da promoção do fabricante (oferta —
    tag exata) com todo o resto das vendas dele, incluindo "Sem Desconto"
    (base), mês a mês, por loja/bandeira e por produto."""
    linhas = queryset.select_related('loja').values(
        'loja_id', 'loja__codigo', 'loja__bandeira', 'produto_descricao',
        'grupo', 'ano_mes', 'itens', 'venda', 'custo', 'lucro',
    )

    por_mes = defaultdict(lambda: {
        'itens_base': ZERO, 'venda_base': ZERO,
        'itens_oferta': ZERO, 'venda_oferta': ZERO,
    })
    por_loja = defaultdict(lambda: {
        'codigo': '', 'bandeira': '',
        'itens_oferta': ZERO, 'venda_oferta': ZERO, 'lucro_oferta': ZERO,
    })
    por_produto = defaultdict(lambda: {'itens_oferta': ZERO, 'venda_oferta': ZERO, 'lucro_oferta': ZERO})
    por_produto_mes = defaultdict(lambda: defaultdict(lambda: ZERO))

    totais = {g: {'itens': ZERO, 'venda': ZERO, 'custo': ZERO, 'lucro': ZERO}
              for g in (Lancamento.GRUPO_BASE, Lancamento.GRUPO_OFERTA)}

    for linha in linhas:
        grupo = linha['grupo']
        if grupo not in totais:
            continue
        itens = linha['itens'] or ZERO
        venda = linha['venda'] or ZERO
        custo = linha['custo'] or ZERO
        lucro = linha['lucro'] or ZERO

        totais[grupo]['itens'] += itens
        totais[grupo]['venda'] += venda
        totais[grupo]['custo'] += custo
        totais[grupo]['lucro'] += lucro

        mes = por_mes[linha['ano_mes']]
        mes[f'itens_{grupo}'] += itens
        mes[f'venda_{grupo}'] += venda

        if grupo == Lancamento.GRUPO_OFERTA:
            loja = por_loja[linha['loja_id']]
            loja['codigo'] = linha['loja__codigo']
            loja['bandeira'] = linha['loja__bandeira']
            loja['itens_oferta'] += itens
            loja['venda_oferta'] += venda
            loja['lucro_oferta'] += lucro

            produto = por_produto[linha['produto_descricao']]
            produto['itens_oferta'] += itens
            produto['venda_oferta'] += venda
            produto['lucro_oferta'] += lucro
            por_produto_mes[linha['produto_descricao']][linha['ano_mes']] += venda

    def _margem_pct(g):
        venda = totais[g]['venda']
        return (totais[g]['lucro'] / venda * 100) if venda else ZERO

    kpis = {
        'itens_base': totais[Lancamento.GRUPO_BASE]['itens'],
        'venda_base': totais[Lancamento.GRUPO_BASE]['venda'],
        'lucro_base': totais[Lancamento.GRUPO_BASE]['lucro'],
        'margem_base_pct': _margem_pct(Lancamento.GRUPO_BASE),
        'itens_oferta': totais[Lancamento.GRUPO_OFERTA]['itens'],
        'venda_oferta': totais[Lancamento.GRUPO_OFERTA]['venda'],
        'lucro_oferta': totais[Lancamento.GRUPO_OFERTA]['lucro'],
        'margem_oferta_pct': _margem_pct(Lancamento.GRUPO_OFERTA),
    }

    produtos = [
        {'produto': nome, **valores} for nome, valores in por_produto.items()
        if not busca or busca.lower() in nome.lower()
    ]
    produtos.sort(key=lambda p: p['venda_oferta'], reverse=True)

    por_mes_lista = [{'ano_mes': mes, **valores} for mes, valores in sorted(por_mes.items())]
    labels = [item['ano_mes'] for item in por_mes_lista]

    return {
        'kpis': kpis,
        'por_mes': por_mes_lista,
        'ranking_lojas': sorted(por_loja.values(), key=lambda l: l['venda_oferta'], reverse=True),
        'ranking_bandeiras': agrupar_por_bandeira(
            por_loja.values(), ['itens_oferta', 'venda_oferta', 'lucro_oferta']
        ),
        'produtos': produtos,
        'series_produtos': alinhar_com_labels(por_produto_mes, labels),
    }


def calcular_marketing(queryset, busca: str = ''):
    """Itens do Marketing (docx, seção 10 — tag "PRODUTOS MARKETING <mês>"):
    ainda sem mecânica de verba mapeada, só performance."""
    linhas = queryset.select_related('loja').values(
        'loja_id', 'loja__codigo', 'loja__bandeira', 'produto_descricao',
        'fabricante', 'ano_mes', 'itens', 'venda', 'custo', 'lucro',
    )

    total_itens = ZERO
    total_venda = ZERO
    total_lucro = ZERO

    por_mes = defaultdict(lambda: {'itens': ZERO, 'venda': ZERO, 'lucro': ZERO})
    por_fabricante = defaultdict(lambda: {'itens': ZERO, 'venda': ZERO, 'lucro': ZERO})
    por_loja = defaultdict(lambda: {'codigo': '', 'bandeira': '', 'itens': ZERO, 'venda': ZERO, 'lucro': ZERO})
    por_produto = defaultdict(lambda: {'itens': ZERO, 'venda': ZERO, 'custo': ZERO, 'lucro': ZERO})
    por_produto_mes = defaultdict(lambda: defaultdict(lambda: ZERO))

    for linha in linhas:
        itens = linha['itens'] or ZERO
        venda = linha['venda'] or ZERO
        custo = linha['custo'] or ZERO
        lucro = linha['lucro'] or ZERO

        total_itens += itens
        total_venda += venda
        total_lucro += lucro

        mes = por_mes[linha['ano_mes']]
        mes['itens'] += itens
        mes['venda'] += venda
        mes['lucro'] += lucro

        fabricante = por_fabricante[linha['fabricante'] or 'Não informado']
        fabricante['itens'] += itens
        fabricante['venda'] += venda
        fabricante['lucro'] += lucro

        loja = por_loja[linha['loja_id']]
        loja['codigo'] = linha['loja__codigo']
        loja['bandeira'] = linha['loja__bandeira']
        loja['itens'] += itens
        loja['venda'] += venda
        loja['lucro'] += lucro

        produto = por_produto[linha['produto_descricao']]
        produto['itens'] += itens
        produto['venda'] += venda
        produto['custo'] += custo
        produto['lucro'] += lucro
        por_produto_mes[linha['produto_descricao']][linha['ano_mes']] += venda

    produtos = [
        {'produto': nome, **valores} for nome, valores in por_produto.items()
        if not busca or busca.lower() in nome.lower()
    ]
    produtos.sort(key=lambda p: p['venda'], reverse=True)

    por_mes_lista = [{'ano_mes': mes, **valores} for mes, valores in sorted(por_mes.items())]
    labels = [item['ano_mes'] for item in por_mes_lista]

    return {
        'kpis': {
            'itens': total_itens,
            'venda': total_venda,
            'lucro': total_lucro,
            'produtos': len(por_produto),
        },
        'por_mes': por_mes_lista,
        'por_fabricante': sorted(
            [{'fabricante': nome, **valores} for nome, valores in por_fabricante.items()],
            key=lambda f: f['venda'], reverse=True,
        ),
        'ranking_bandeiras': agrupar_por_bandeira(por_loja.values(), ['itens', 'venda', 'lucro']),
        'produtos': produtos,
        'series_produtos': alinhar_com_labels(por_produto_mes, labels),
    }


def calcular_kimberly(queryset, busca: str = ''):
    """Ofertas Kimberly: sem tag limpa nos relatórios pra promoção Hipzinha
    (achado inspecionando os arquivos, não documentado no docx) — o
    portfólio geral é importado pra exploração, e o subconjunto marcado
    manualmente como oferta (`importar_kimberly --produto/--venda-max/...`)
    vira um bloco separado, deixando claro que é curadoria manual."""
    linhas = queryset.select_related('loja').values(
        'loja_id', 'loja__codigo', 'loja__bandeira', 'produto_descricao',
        'grupo', 'ano_mes', 'itens', 'venda', 'custo', 'lucro',
    )

    total_itens = ZERO
    total_venda = ZERO
    total_lucro = ZERO
    oferta_itens = ZERO
    oferta_venda = ZERO
    oferta_lucro = ZERO

    por_mes = defaultdict(lambda: {'itens': ZERO, 'venda': ZERO, 'lucro': ZERO})
    por_loja = defaultdict(lambda: {'codigo': '', 'bandeira': '', 'itens': ZERO, 'venda': ZERO, 'lucro': ZERO})
    por_produto = defaultdict(lambda: {'itens': ZERO, 'venda': ZERO, 'custo': ZERO, 'lucro': ZERO, 'em_oferta': False})
    por_produto_mes = defaultdict(lambda: defaultdict(lambda: ZERO))

    for linha in linhas:
        itens = linha['itens'] or ZERO
        venda = linha['venda'] or ZERO
        custo = linha['custo'] or ZERO
        lucro = linha['lucro'] or ZERO
        em_oferta = linha['grupo'] == Lancamento.GRUPO_OFERTA

        total_itens += itens
        total_venda += venda
        total_lucro += lucro
        if em_oferta:
            oferta_itens += itens
            oferta_venda += venda
            oferta_lucro += lucro

        mes = por_mes[linha['ano_mes']]
        mes['itens'] += itens
        mes['venda'] += venda
        mes['lucro'] += lucro

        loja = por_loja[linha['loja_id']]
        loja['codigo'] = linha['loja__codigo']
        loja['bandeira'] = linha['loja__bandeira']
        loja['itens'] += itens
        loja['venda'] += venda
        loja['lucro'] += lucro

        produto = por_produto[linha['produto_descricao']]
        produto['itens'] += itens
        produto['venda'] += venda
        produto['custo'] += custo
        produto['lucro'] += lucro
        produto['em_oferta'] = produto['em_oferta'] or em_oferta
        por_produto_mes[linha['produto_descricao']][linha['ano_mes']] += venda

    produtos = [
        {'produto': nome, **valores} for nome, valores in por_produto.items()
        if not busca or busca.lower() in nome.lower()
    ]
    produtos.sort(key=lambda p: p['venda'], reverse=True)

    por_mes_lista = [{'ano_mes': mes, **valores} for mes, valores in sorted(por_mes.items())]
    labels = [item['ano_mes'] for item in por_mes_lista]

    return {
        'kpis': {
            'itens': total_itens, 'venda': total_venda, 'lucro': total_lucro,
            'produtos': len(por_produto),
        },
        'kpis_oferta': {
            'itens': oferta_itens, 'venda': oferta_venda, 'lucro': oferta_lucro,
        },
        'tem_oferta_marcada': oferta_itens > 0,
        'por_mes': por_mes_lista,
        'ranking_bandeiras': agrupar_por_bandeira(por_loja.values(), ['itens', 'venda', 'lucro']),
        'produtos': produtos,
        'series_produtos': alinhar_com_labels(por_produto_mes, labels),
    }


def calcular_impacto_leve3_fabricante():
    """Impacto do Leve 3 Pague 2 sobre o giro geral do fabricante.

    A oferta roda 1 semana por mês em cada bandeira (semanas diferentes
    entre Velanes e Ultra Popular — Gabriel confirmou em conversa, não é
    dado do ERP). Sem um calendário exato de qual semana foi cada mês,
    a semana da promoção é DETECTADA nos próprios dados: a janela de 7
    dias corridos com maior giro dos SKUs do Leve 3 daquele fabricante,
    dentro de cada mês e bandeira. Compara a média diária dessa janela
    com a média diária do resto do mês, nos mesmos SKUs — heurística,
    não fórmula validada; o detalhe por mês/janela fica exposto pra
    conferência.

    Precisa de sellout com data por linha (`manage.py importar_sellout`
    num arquivo com coluna "Data") — sellout só com "Ano-mês" não entra
    (não dá pra achar a semana).
    """
    fabricantes = sorted(set(
        Lancamento.objects.filter(mecanica=Lancamento.SELLOUT, data__isnull=False)
        .values_list('fabricante', flat=True)
    ))

    resultado = []
    for fabricante in fabricantes:
        linha_fabricante = {'fabricante': fabricante, 'bandeiras': []}
        for bandeira_chave, bandeira_rotulo in Loja.BANDEIRA_CHOICES:
            skus = set(
                Lancamento.objects.filter(
                    mecanica=Lancamento.LEVE3, fabricante=fabricante, loja__bandeira=bandeira_chave,
                ).values_list('produto_descricao', flat=True).distinct()
            )
            if not skus:
                continue

            linhas = Lancamento.objects.filter(
                mecanica=Lancamento.SELLOUT, fabricante=fabricante, loja__bandeira=bandeira_chave,
                produto_descricao__in=skus, data__isnull=False,
            ).values('data', 'itens')

            por_dia = defaultdict(lambda: ZERO)
            for linha in linhas:
                por_dia[linha['data']] += linha['itens'] or ZERO
            if not por_dia:
                continue

            por_mes_dias = defaultdict(dict)
            for dia, itens in por_dia.items():
                por_mes_dias[ano_mes_de(dia)][dia] = itens

            detalhes_mes = []
            total_promo_itens, total_promo_dias = ZERO, 0
            total_resto_itens, total_resto_dias = ZERO, 0

            for mes, dias in sorted(por_mes_dias.items()):
                datas = sorted(dias.keys())
                melhor_janela, melhor_soma = None, None
                for inicio in datas:
                    fim = inicio + timedelta(days=6)
                    soma = sum(v for d, v in dias.items() if inicio <= d <= fim)
                    if melhor_soma is None or soma > melhor_soma:
                        melhor_soma, melhor_janela = soma, (inicio, fim)
                if melhor_janela is None:
                    continue

                ini, fim = melhor_janela
                dias_promo = [d for d in datas if ini <= d <= fim]
                dias_resto = [d for d in datas if d not in dias_promo]
                itens_promo = sum(dias[d] for d in dias_promo)
                itens_resto = sum(dias[d] for d in dias_resto)

                total_promo_itens += itens_promo
                total_promo_dias += len(dias_promo)
                total_resto_itens += itens_resto
                total_resto_dias += len(dias_resto)

                media_resto_mes = (itens_resto / len(dias_resto)) if dias_resto else ZERO
                media_promo_mes = (itens_promo / len(dias_promo)) if dias_promo else ZERO
                detalhes_mes.append({
                    'mes': mes, 'semana_inicio': ini, 'semana_fim': fim,
                    'itens_semana': itens_promo,
                    'media_diaria_semana': media_promo_mes,
                    'media_diaria_resto': media_resto_mes,
                    'impacto': (media_promo_mes / media_resto_mes) if media_resto_mes else None,
                })

            media_promo = (total_promo_itens / total_promo_dias) if total_promo_dias else ZERO
            media_resto = (total_resto_itens / total_resto_dias) if total_resto_dias else ZERO
            linha_fabricante['bandeiras'].append({
                'bandeira': bandeira_rotulo,
                'skus': len(skus),
                'media_diaria_semana': media_promo,
                'media_diaria_resto': media_resto,
                'impacto': (media_promo / media_resto) if media_resto else None,
                'meses': detalhes_mes,
            })

        if linha_fabricante['bandeiras']:
            resultado.append(linha_fabricante)

    return resultado


ACOES_INFO = [
    (Lancamento.LEVE3, 'Leve 3 Pague 2'),
    (Lancamento.SUPRACORP, 'Degustação Supra Corp Day'),
    (Lancamento.KENVUE, 'Ofertas Kenvue'),
    (Lancamento.PRINCIPIA, 'Ofertas Principia'),
    (Lancamento.BOTICA, 'Ofertas Botica'),
    (Lancamento.PROCTER, 'Ofertas Procter'),
    (Lancamento.KIMBERLY, 'Ofertas Kimberly'),
    (Lancamento.CESTOES, 'Cestões'),
    (Lancamento.MARKETING, 'Itens do Marketing'),
]
