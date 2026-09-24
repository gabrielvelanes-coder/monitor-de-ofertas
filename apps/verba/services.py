"""Sincronização de apuração automática + CMV com/sem verba.

`calcular_leve3`/`calcular_impacto_fabricante` (`apps.ofertas.services`)
continuam exatamente como estão — esta camada só lê o resultado deles e
cruza com `VerbaMensal`, sem mudar assinatura nem comportamento deles.
Plano completo em `docs/PLANO_VERBA.md`.
"""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Sum

from apps.ofertas.models import Lancamento
from apps.ofertas.services import calcular_leve3

from .models import VerbaMensal

ZERO = Decimal('0')

# Fórmulas de verba confirmadas com o Gabriel por fabricante (23/09/26) --
# % fixo sobre o custo dos itens vendidos na oferta (`grupo=oferta`).
# Diferente de Kenvue/Procter (rebaixa por EAN, `RebaixaProduto`, valor já
# vem pronto do fabricante) -- aqui é só 1 percentual, sem tabela nenhuma.
# Botica ainda sem regra (Gabriel vai mandar as regras já usadas em 2026).
PERCENTUAL_VERBA_FABRICANTE = {
    Lancamento.PRINCIPIA: Decimal('0.20'),
}


def sincronizar_verba_leve3(ano_mes: str | None = None) -> list[VerbaMensal]:
    """Recalcula VerbaMensal(mecanica=LEVE3).valor_apurado a partir do
    investimento apurado por `calcular_leve3`, mês a mês. Nunca toca
    valor_recebido/data_recebimento/status/observação — campos editados à
    mão no admin, com ciclo de vida independente da apuração.

    Chamada no fim de `importar_leve3` (pra manter em dia a cada import) e
    também disponível via `manage.py sincronizar_verba` pra backfill dos
    meses já importados antes do módulo de verba existir.
    """
    queryset = Lancamento.objects.filter(mecanica=Lancamento.LEVE3)
    if ano_mes:
        queryset = queryset.filter(ano_mes=ano_mes)

    meses = sorted(set(queryset.values_list('ano_mes', flat=True)))
    atualizados = []
    for mes in meses:
        dados = calcular_leve3(queryset.filter(ano_mes=mes))
        verba, _ = VerbaMensal.objects.get_or_create(mecanica=Lancamento.LEVE3, ano_mes=mes)
        verba.valor_apurado = dados['kpis']['investimento']
        verba.apuracao_automatica = True
        verba.save(update_fields=['valor_apurado', 'apuracao_automatica', 'atualizado_em'])
        atualizados.append(verba)
    return atualizados


def sincronizar_verba_percentual_custo(mecanica: str, ano_mes: str | None = None) -> list[VerbaMensal]:
    """Fórmula de verba simples (% fixo sobre o custo dos itens vendidos na
    oferta, `PERCENTUAL_VERBA_FABRICANTE`) -- hoje só Principia (20%,
    confirmado 23/09/26: "principia é 20% sobre o custo do produto, esse é
    o investimento da industria"). Mesmo padrão de `sincronizar_verba_leve3`
    (1 VerbaMensal por mês, nunca toca valor_recebido/data_recebimento/
    status/observação). Não faz nada (lista vazia) se a mecânica não tiver
    percentual definido em `PERCENTUAL_VERBA_FABRICANTE`."""
    percentual = PERCENTUAL_VERBA_FABRICANTE.get(mecanica)
    if percentual is None:
        return []

    queryset = Lancamento.objects.filter(mecanica=mecanica, grupo=Lancamento.GRUPO_OFERTA)
    if ano_mes:
        queryset = queryset.filter(ano_mes=ano_mes)

    meses = sorted(set(queryset.values_list('ano_mes', flat=True)))
    atualizados = []
    for mes in meses:
        total_custo = queryset.filter(ano_mes=mes).aggregate(total=Sum('custo'))['total'] or ZERO
        verba, _ = VerbaMensal.objects.get_or_create(mecanica=mecanica, ano_mes=mes)
        verba.valor_apurado = total_custo * percentual
        verba.apuracao_automatica = True
        verba.save(update_fields=['valor_apurado', 'apuracao_automatica', 'atualizado_em'])
        atualizados.append(verba)
    return atualizados


def verba_apurada(
    mecanica: str, ano_mes: str = '', ano_mes_de: str = '', ano_mes_ate: str = '',
) -> Decimal | None:
    """Soma de `valor_apurado` da mecânica — 1 mês (`ano_mes` preenchido),
    um intervalo (`ano_mes_de`/`ano_mes_ate`, 23/09/26, dashboard "escolher
    mais datas") ou todos os meses com apuração (nenhum dos 3 preenchido).
    `None` quando não há nenhuma linha apurada ainda pra essa mecânica
    (ação sem fórmula de verba definida) — nunca 0 silencioso, que
    pareceria "sem verba a receber" em vez de "pendente de definição"."""
    queryset = VerbaMensal.objects.filter(mecanica=mecanica, valor_apurado__isnull=False)
    if ano_mes:
        queryset = queryset.filter(ano_mes=ano_mes)
    elif ano_mes_de or ano_mes_ate:
        if ano_mes_de:
            queryset = queryset.filter(ano_mes__gte=ano_mes_de)
        if ano_mes_ate:
            queryset = queryset.filter(ano_mes__lte=ano_mes_ate)
    valores = list(queryset.values_list('valor_apurado', flat=True))
    return sum(valores, ZERO) if valores else None


def cmv_pct(venda: Decimal, lucro: Decimal) -> Decimal:
    """CMV sem verba: 100 - (lucro/venda*100). Mesma fórmula que já rodava
    inline em `_resumo_executivo`, só extraída pra reuso."""
    return (100 - (lucro / venda * 100)) if venda else ZERO


def cmv_pct_com_verba(venda: Decimal, lucro: Decimal, valor_apurado: Decimal | None) -> Decimal | None:
    """CMV com verba: soma o valor apurado (teórico, calculado no mês da
    venda) ao lucro contábil antes de tirar o percentual sobre a venda.
    `None` quando a mecânica ainda não tem apuração — o template mostra
    "—" em vez de repetir o CMV sem verba como se fosse igual."""
    if not venda or valor_apurado is None:
        return None
    return 100 - ((lucro + valor_apurado) / venda * 100)


def anexar_cmv(linhas, campo_venda: str, campo_lucro: str, campo_verba: str | None = None):
    """Acrescenta 'cmv_pct_sem_verba'/'cmv_pct_com_verba' em cada dict de
    `linhas` (ranking_lojas, produtos, ranking_bandeiras, por_fabricante —
    qualquer lista de dict que calcular_* devolve), pros nomes de tabela
    ficarem iguais em toda ação (docx não define isso, foi pedido do
    Gabriel de consistência visual).

    `campo_venda`/`campo_lucro` variam por mecânica (ex. 'venda'/'lucro'
    ou 'venda_oferta'/'lucro_oferta') — passe o nome do campo, não o
    valor. `campo_verba`, se informado, é o nome do campo que já traz o
    valor de verba calculado POR LINHA (hoje só existe isso no Leve3:
    'investimento', calculado linha a linha desde calcular_leve3). Sem
    esse campo, cmv_pct_com_verba fica None — nunca ratear o valor
    agregado de VerbaMensal por loja/produto sem uma fórmula validada
    pra isso."""
    for linha in linhas:
        venda = linha[campo_venda] or ZERO
        lucro = linha[campo_lucro] or ZERO
        linha['cmv_pct_sem_verba'] = cmv_pct(venda, lucro)
        valor_verba = linha.get(campo_verba) if campo_verba else None
        linha['cmv_pct_com_verba'] = cmv_pct_com_verba(venda, lucro, valor_verba)
    return linhas
