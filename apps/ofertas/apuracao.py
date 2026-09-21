"""Arquivo de apuração pra enviar à indústria (docx, pendência aberta desde
13/09/26) — base = relatório de vendas por item da campanha (linha a linha,
não agregado), + valor da rebaixa por unidade + investimento total que o
fabricante deve pagar. 1ª implementação real: Procter Semana do Cliente,
usando a tabela de rebaixa que o Gabriel mandou (`RebaixaProduto`).
"""
from __future__ import annotations

from decimal import Decimal

from apps.produtos.models import Produto, RebaixaProduto

from .erp import tag_sem_prefixo
from .models import Lancamento

ZERO = Decimal('0')


def montar_apuracao_industria(mecanica: str, campanha: str) -> dict:
    """Devolve as linhas de venda da campanha (grupo=oferta) + rebaixa/
    investimento por linha, prontas pra exportar. Resolve o EAN de cada
    produto pelo cadastro (`Produto.descricao` -> `codigo_barras`) e cruza
    com `RebaixaProduto`; quando o cadastro não tem EAN pro produto (achado
    real: acontece, ver commit), cai pro 2º critério — nome do produto
    batendo exato com `RebaixaProduto.produto_descricao`."""
    linhas = list(
        Lancamento.objects.filter(mecanica=mecanica, grupo=Lancamento.GRUPO_OFERTA)
        .select_related('loja')
        .values(
            'loja__codigo', 'loja__bandeira', 'data', 'ano_mes',
            'produto_descricao', 'tag_origem', 'itens', 'venda', 'desconto',
            'custo', 'lucro',
        )
    )
    linhas = [l for l in linhas if tag_sem_prefixo(l['tag_origem']) == campanha]

    descricoes = {l['produto_descricao'] for l in linhas}
    ean_por_descricao = dict(
        Produto.objects.filter(descricao__in=descricoes).values_list('descricao', 'codigo_barras')
    )

    rebaixas = list(RebaixaProduto.objects.filter(mecanica=mecanica, campanha=campanha))
    rebaixa_por_ean = {r.ean: r.valor_rebaixa for r in rebaixas if r.ean}
    rebaixa_por_nome = {r.produto_descricao: r.valor_rebaixa for r in rebaixas}

    resultado = []
    sem_rebaixa = set()
    for l in linhas:
        descricao = l['produto_descricao']
        ean = ean_por_descricao.get(descricao, '')
        valor_rebaixa = rebaixa_por_ean.get(ean) if ean else None
        if valor_rebaixa is None:
            valor_rebaixa = rebaixa_por_nome.get(descricao)
        if valor_rebaixa is None:
            sem_rebaixa.add(descricao)
            valor_rebaixa = ZERO

        itens = l['itens'] or ZERO
        resultado.append({
            'loja': l['loja__codigo'],
            'bandeira': l['loja__bandeira'],
            'data': l['data'],
            'ean': ean,
            'produto': descricao,
            'itens': itens,
            'venda': l['venda'] or ZERO,
            'desconto': l['desconto'] or ZERO,
            'custo': l['custo'] or ZERO,
            'lucro': l['lucro'] or ZERO,
            'valor_rebaixa_unitario': valor_rebaixa,
            'investimento': (itens * valor_rebaixa).quantize(Decimal('0.01')),
        })

    return {
        'linhas': resultado,
        'total_investimento': sum((r['investimento'] for r in resultado), ZERO),
        'total_itens': sum((r['itens'] for r in resultado), ZERO),
        'produtos_sem_rebaixa': sorted(sem_rebaixa),
    }
