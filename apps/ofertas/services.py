"""Serviços de cálculo por mecânica de oferta.

Cada `calcular_<mecanica>(queryset)` recebe um queryset de `Lancamento` já
filtrado por mecânica (e por bandeira, se for o caso) e devolve os números
prontos pra tela — sem pré-agregação em banco, pra granularidade bater com
o filtro de bandeira em qualquer combinação (ver docx, seção 9).
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from .models import Lancamento

ZERO = Decimal('0')


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
