"""Arquivo de apuração pra enviar à indústria (docx, pendência aberta desde
13/09/26) — base = relatório de vendas por item, linha a linha (não
agregado), + investimento que o fabricante deve pagar. 2 fórmulas
diferentes, dependendo da mecânica:

- Ofertas de fabricante (Kenvue/Principia/Botica/Procter, `grupo=oferta`):
  `montar_apuracao_industria` -- valor de rebaixa por EAN (`RebaixaProduto`,
  o fabricante manda a tabela; 1ª implementação real: Procter Semana do
  Cliente).
- Leve 3 Pague 2: `montar_apuracao_leve3` -- fórmula própria automática já
  validada (ciclos × custo), não depende de tabela de rebaixa nenhuma.

Cestões/Marketing/Kimberly/Supra Corp ainda não têm fórmula definida (ver
README, seção Pendências) -- não têm função de apuração ainda.
"""
from __future__ import annotations

from decimal import Decimal

import pandas as pd

from apps.produtos.models import Produto, RebaixaProduto

from .erp import tag_sem_prefixo
from .models import Lancamento

ZERO = Decimal('0')

_COLUNAS_FABRICANTE = {
    'loja': 'Loja', 'bandeira': 'Bandeira', 'data': 'Data', 'ean': 'EAN',
    'produto': 'Produto', 'itens': 'Itens', 'venda': 'Venda',
    'desconto': 'Desconto', 'custo': 'Custo', 'lucro': 'Lucro',
    'valor_rebaixa_unitario': 'Valor da Rebaixa (R$/un.)',
    'investimento': 'Investimento (R$)',
}
_COLUNAS_LEVE3 = {
    'loja': 'Loja', 'bandeira': 'Bandeira', 'data': 'Data', 'ano_mes': 'Ano-mês',
    'produto': 'Produto', 'itens': 'Itens', 'venda': 'Venda', 'custo': 'Custo',
    'lucro': 'Lucro', 'ciclos': 'Ciclos', 'custo_unitario': 'Custo Unitário (R$)',
    'investimento': 'Investimento (R$)',
}


def gerar_dataframe_apuracao(mecanica: str, campanha: str | None = None, ano_mes: str | None = None):
    """Monta os dados (`montar_apuracao_leve3`/`montar_apuracao_industria`,
    conforme a mecânica) e devolve `(dataframe_pronto_pra_excel, dados)` --
    usado tanto pelo management command quanto pelo botão de download no
    painel, pra não duplicar a lógica de renomear coluna/arredondar em 2
    lugares."""
    if mecanica == Lancamento.LEVE3:
        dados = montar_apuracao_leve3(ano_mes=ano_mes)
        colunas = _COLUNAS_LEVE3
    else:
        if not campanha:
            raise ValueError('campanha é obrigatória pra essa mecânica (só o Leve3 dispensa).')
        dados = montar_apuracao_industria(mecanica, campanha)
        colunas = _COLUNAS_FABRICANTE

    df = pd.DataFrame(dados['linhas'])
    if not df.empty:
        # Arredonda só aqui, pra exibir -- `dados['total_investimento']`
        # já foi somado em precisão cheia antes disso (ver comentário em
        # `montar_apuracao_leve3` sobre a diferença de 7 centavos achada
        # ao conferir contra o painel).
        df['investimento'] = df['investimento'].astype(float).round(2)
    df = df.rename(columns=colunas)
    return df, dados


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
            # Sem quantize aqui pelo mesmo motivo do Leve3 (ver
            # montar_apuracao_leve3) -- soma em precisão cheia, arredondar
            # só na exportação.
            'investimento': itens * valor_rebaixa,
        })

    return {
        'linhas': resultado,
        'total_investimento': sum((r['investimento'] for r in resultado), ZERO),
        'total_itens': sum((r['itens'] for r in resultado), ZERO),
        'produtos_sem_rebaixa': sorted(sem_rebaixa),
    }


def montar_apuracao_leve3(ano_mes: str | None = None) -> dict:
    """Leve 3 Pague 2 tem fórmula própria automática (docx, seção 5.1/6) --
    não depende de tabela de rebaixa nenhuma, diferente das ofertas de
    fabricante. Mesmo cálculo linha a linha do `calcular_leve3`
    (`services.py`), só que devolvendo cada linha pronta pra exportar em
    vez de já agregada: ciclos = itens // 3; investimento = ciclos ×
    (custo da linha / itens da linha). `ano_mes` (opcional, "AAAA-MM")
    filtra pra 1 mês só; omitido = todos."""
    queryset = Lancamento.objects.filter(mecanica=Lancamento.LEVE3)
    if ano_mes:
        queryset = queryset.filter(ano_mes=ano_mes)
    linhas = queryset.select_related('loja').values(
        'loja__codigo', 'loja__bandeira', 'data', 'ano_mes',
        'produto_descricao', 'itens', 'venda', 'custo', 'lucro',
    )

    resultado = []
    for l in linhas:
        itens = l['itens'] or ZERO
        custo = l['custo'] or ZERO
        custo_unitario = (custo / itens) if itens else ZERO
        ciclos = itens // 3
        # Sem arredondar aqui -- arredondar cada linha pra 2 casas e DEPOIS
        # somar dá um total diferente da soma em precisão cheia (achado
        # real: R$50.646,77 vs R$50.646,84 do painel, 3.286 linhas, 7
        # centavos de diferença acumulada). O painel (`calcular_leve3`)
        # nunca arredonda linha a linha -- fica igual aqui, o
        # arredondamento pra 2 casas só acontece na exportação (cosmético,
        # não usado pra somar `total_investimento` abaixo).
        investimento = ciclos * custo_unitario
        resultado.append({
            'loja': l['loja__codigo'],
            'bandeira': l['loja__bandeira'],
            'data': l['data'],
            'ano_mes': l['ano_mes'],
            'produto': l['produto_descricao'],
            'itens': itens,
            'venda': l['venda'] or ZERO,
            'custo': custo,
            'lucro': l['lucro'] or ZERO,
            'ciclos': ciclos,
            'custo_unitario': custo_unitario.quantize(Decimal('0.0001')),
            'investimento': investimento,
        })

    return {
        'linhas': resultado,
        'total_investimento': sum((r['investimento'] for r in resultado), ZERO),
        'total_itens': sum((r['itens'] for r in resultado), ZERO),
    }
