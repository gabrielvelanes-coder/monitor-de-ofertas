"""Sincronização de apuração automática + CMV com/sem verba.

`calcular_leve3`/`calcular_impacto_fabricante` (`apps.ofertas.services`)
continuam exatamente como estão — esta camada só lê o resultado deles e
cruza com `VerbaMensal`, sem mudar assinatura nem comportamento deles.
Plano completo em `docs/PLANO_VERBA.md`.
"""
from __future__ import annotations

from decimal import Decimal

from apps.ofertas.models import Lancamento
from apps.ofertas.services import calcular_leve3

from .models import VerbaMensal

ZERO = Decimal('0')


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


def verba_apurada(mecanica: str, ano_mes: str = '') -> Decimal | None:
    """Soma de `valor_apurado` da mecânica — 1 mês (`ano_mes` preenchido) ou
    todos os meses com apuração (`ano_mes` vazio, usado quando o dashboard
    não tem filtro de mês). `None` quando não há nenhuma linha apurada
    ainda pra essa mecânica (ação sem fórmula de verba definida) — nunca
    0 silencioso, que pareceria "sem verba a receber" em vez de "pendente
    de definição"."""
    queryset = VerbaMensal.objects.filter(mecanica=mecanica, valor_apurado__isnull=False)
    if ano_mes:
        queryset = queryset.filter(ano_mes=ano_mes)
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
