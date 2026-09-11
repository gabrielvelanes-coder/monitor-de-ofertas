"""Serviços de cálculo por mecânica de oferta.

Cada `calcular_<mecanica>(queryset)` recebe um queryset de `Lancamento` já
filtrado por mecânica (e por bandeira, se for o caso) e devolve os números
prontos pra tela — sem pré-agregação em banco, pra granularidade bater com
o filtro de bandeira em qualquer combinação (ver docx, seção 9).
"""
from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from .models import Lancamento

ZERO = Decimal('0')

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

    por_mes = defaultdict(lambda: {'investimento': ZERO, 'margem_contabil': ZERO, 'margem_ajustada': ZERO})
    por_loja = defaultdict(lambda: {'codigo': '', 'bandeira': '', 'margem_contabil': ZERO, 'margem_ajustada': ZERO, 'investimento': ZERO})
    por_produto = defaultdict(lambda: {'itens': ZERO, 'ciclos': ZERO, 'investimento': ZERO, 'venda': ZERO, 'custo': ZERO, 'lucro': ZERO})

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
        mes['investimento'] += investimento
        mes['margem_contabil'] += lucro
        mes['margem_ajustada'] += margem_ajustada

        loja = por_loja[linha['loja_id']]
        loja['codigo'] = linha['loja__codigo']
        loja['bandeira'] = linha['loja__bandeira']
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

    produtos = [
        {'produto': nome, **valores} for nome, valores in por_produto.items()
        if not busca or busca.lower() in nome.lower()
    ]
    produtos.sort(key=lambda p: p['venda'], reverse=True)

    return {
        'kpis': {
            'itens': total_itens,
            'ciclos': total_ciclos,
            'investimento': total_investimento,
            'venda': total_venda,
            'margem_contabil': total_margem_contabil,
            'margem_ajustada': total_margem_contabil + total_investimento,
        },
        'por_mes': [
            {'ano_mes': mes, **valores} for mes, valores in sorted(por_mes.items())
        ],
        'ranking_lojas': sorted(por_loja.values(), key=lambda l: l['investimento'], reverse=True),
        'produtos': produtos,
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

    produtos = [
        {'produto': nome, **valores} for nome, valores in por_produto.items()
        if not busca or busca.lower() in nome.lower()
    ]
    produtos.sort(key=lambda p: p['venda'], reverse=True)

    margem_pct = (total_lucro / total_venda * 100) if total_venda else ZERO

    return {
        'kpis': {
            'itens': total_itens,
            'venda': total_venda,
            'lucro': total_lucro,
            'margem_pct': margem_pct,
            'produtos': len(por_produto),
        },
        'por_mes': [
            {'ano_mes': mes, **valores} for mes, valores in sorted(por_mes.items())
        ],
        'ranking_lojas': sorted(por_loja.values(), key=lambda l: l['venda'], reverse=True),
        'produtos': produtos,
    }


def calcular_supracorp(queryset):
    """Degustação Supra Corp Day (docx, seção 5.2): impacto = itens vendidos
    na janela do evento (dia do evento + o dia seguinte) ÷ média diária de
    vendas no resto do mês — geral, por loja e por produto."""
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
    por_produto = defaultdict(lambda: {'itens_evento': ZERO, 'venda_evento': ZERO})

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

        dia = por_dia[data]
        dia['itens'] += itens
        dia['venda'] += venda

        loja = por_loja[linha['loja_id']]
        loja['codigo'] = linha['loja__codigo']
        loja['bandeira'] = linha['loja__bandeira']

        if na_janela:
            total_itens_evento += itens
            total_venda_evento += venda
            loja['itens_evento'] += itens
            produto = por_produto[linha['produto_descricao']]
            produto['itens_evento'] += itens
            produto['venda_evento'] += venda
        else:
            total_itens_resto += itens
            loja['itens_resto'] += itens

    media_diaria_geral = (total_itens_resto / dias_resto) if dias_resto else ZERO
    impacto_geral = (total_itens_evento / media_diaria_geral) if media_diaria_geral else None

    ranking_lojas = []
    for loja in por_loja.values():
        media = (loja['itens_resto'] / dias_resto) if dias_resto else ZERO
        impacto = (loja['itens_evento'] / media) if media else None
        ranking_lojas.append({**loja, 'media_diaria': media, 'impacto': impacto})
    ranking_lojas.sort(key=lambda l: l['itens_evento'], reverse=True)

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
        'produtos': produtos,
        'evento_data': EVENTO_SUPRACORP,
    }


def calcular_impacto_fabricante(queryset):
    """Impacto por fabricante — Kenvue/Principia/Botica/Procter (docx,
    seção 5.3): compara volume/venda/margem "sem desconto" (base) com a
    promoção do fabricante, mês a mês e por loja."""
    linhas = queryset.select_related('loja').values(
        'loja_id', 'loja__codigo', 'loja__bandeira', 'grupo', 'ano_mes',
        'itens', 'venda', 'custo', 'lucro',
    )

    por_mes = defaultdict(lambda: {
        'itens_base': ZERO, 'venda_base': ZERO,
        'itens_oferta': ZERO, 'venda_oferta': ZERO,
    })
    por_loja = defaultdict(lambda: {
        'codigo': '', 'bandeira': '',
        'itens_oferta': ZERO, 'venda_oferta': ZERO, 'lucro_oferta': ZERO,
    })

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

    def _margem_pct(g):
        venda = totais[g]['venda']
        return (totais[g]['lucro'] / venda * 100) if venda else ZERO

    kpis = {
        'itens_base': totais[Lancamento.GRUPO_BASE]['itens'],
        'venda_base': totais[Lancamento.GRUPO_BASE]['venda'],
        'margem_base_pct': _margem_pct(Lancamento.GRUPO_BASE),
        'itens_oferta': totais[Lancamento.GRUPO_OFERTA]['itens'],
        'venda_oferta': totais[Lancamento.GRUPO_OFERTA]['venda'],
        'lucro_oferta': totais[Lancamento.GRUPO_OFERTA]['lucro'],
        'margem_oferta_pct': _margem_pct(Lancamento.GRUPO_OFERTA),
    }

    return {
        'kpis': kpis,
        'por_mes': [
            {'ano_mes': mes, **valores} for mes, valores in sorted(por_mes.items())
        ],
        'ranking_lojas': sorted(
            por_loja.values(), key=lambda l: l['venda_oferta'], reverse=True
        ),
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
    por_produto = defaultdict(lambda: {'itens': ZERO, 'venda': ZERO, 'custo': ZERO, 'lucro': ZERO})

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

        produto = por_produto[linha['produto_descricao']]
        produto['itens'] += itens
        produto['venda'] += venda
        produto['custo'] += custo
        produto['lucro'] += lucro

    produtos = [
        {'produto': nome, **valores} for nome, valores in por_produto.items()
        if not busca or busca.lower() in nome.lower()
    ]
    produtos.sort(key=lambda p: p['venda'], reverse=True)

    return {
        'kpis': {
            'itens': total_itens,
            'venda': total_venda,
            'lucro': total_lucro,
            'produtos': len(por_produto),
        },
        'por_mes': [
            {'ano_mes': mes, **valores} for mes, valores in sorted(por_mes.items())
        ],
        'por_fabricante': sorted(
            [{'fabricante': nome, **valores} for nome, valores in por_fabricante.items()],
            key=lambda f: f['venda'], reverse=True,
        ),
        'produtos': produtos,
    }


MECANICAS_INFO = [
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
