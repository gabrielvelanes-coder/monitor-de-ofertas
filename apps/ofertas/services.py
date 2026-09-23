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

from django.db.models import Sum

from apps.lojas.models import Loja

from .erp import ano_mes_de, tag_sem_prefixo
from .models import Lancamento

ZERO = Decimal('0')
ROTULOS_BANDEIRA = {'velanes': 'Velanes', 'ultra_popular': 'Ultra Popular'}

# Evento pontual de degustação Supra Corp Day (docx, seção 5.2) — 1 janela
# por mês (dia do evento, +1 dia quando durou 2 dias), não um padrão
# recorrente. Acrescentar aqui quando um novo evento acontecer.
JANELAS_SUPRACORP = {
    '2026-08': {date(2026, 8, 5), date(2026, 8, 5) + timedelta(days=1)},
    '2026-09': {date(2026, 9, 4)},
}


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

    por_mes = defaultdict(lambda: {
        'itens': ZERO, 'venda': ZERO, 'investimento': ZERO, 'margem_contabil': ZERO,
        'margem_ajustada': ZERO, '_venda_bandeira': defaultdict(lambda: ZERO),
        '_itens_bandeira': defaultdict(lambda: ZERO),
    })
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
        mes['_venda_bandeira'][linha['loja__bandeira']] += venda
        mes['_itens_bandeira'][linha['loja__bandeira']] += itens

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

    # `bandeira_dominante` por mês -- gráfico "Mês" do Leve3 pintado por
    # bandeira também (pedido 22/09/26: "no mes, nao foi implantado as
    # cores das bandeiras?" -- só tinha ido pro Semana/Dia).
    for mes in por_mes.values():
        mes.update(_campos_bandeira(mes.pop('_venda_bandeira')))
        # Unidades também separadas por bandeira no gráfico Mês (pedido
        # 23/09/26, logo depois da barra empilhada de venda: "separar as
        # unidades tambem, por bandeira") -- reaproveita o mesmo helper com
        # outro prefixo, só `bandeira_dominante` (calculado a partir da
        # venda, acima) não precisa ser recalculado de novo aqui.
        itens_bandeira = mes.pop('_itens_bandeira')
        mes['itens_velanes'] = float(itens_bandeira.get('velanes', ZERO))
        mes['itens_ultra_popular'] = float(itens_bandeira.get('ultra_popular', ZERO))

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

    # "dias_resto" precisa somar o mês inteiro de CADA evento presente nos
    # dados (não só um mês fixo) -- só sei quais meses estão presentes depois
    # de rodar o loop abaixo, por isso é calculado depois, não antes.
    meses_presentes = set()
    janelas_presentes = set()

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
        ano_mes = f'{data.year:04d}-{data.month:02d}'
        na_janela = data in JANELAS_SUPRACORP.get(ano_mes, set())
        meses_presentes.add(ano_mes)
        if na_janela:
            janelas_presentes.add(data)

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

    dias_resto = sum(
        calendar.monthrange(int(am[:4]), int(am[5:7]))[1] - len(JANELAS_SUPRACORP.get(am, set()))
        for am in meses_presentes
    )

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
        {'data': dia, 'na_janela': dia in janelas_presentes, **valores}
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
        # 1 evento (mais comum, filtro de mês ativo) -> data única, igual
        # antes. Vários (ex. "todos os meses" com 2 eventos) -> lista, o
        # template decide como mostrar.
        'eventos_datas': sorted(janelas_presentes),
    }


def _meses_antes(ano_mes: str, quantos: int) -> list[str]:
    """'2026-09', 3 -> ['2026-08', '2026-07', '2026-06'] (mais recente
    primeiro)."""
    ano, mes_num = int(ano_mes[:4]), int(ano_mes[5:7])
    meses = []
    for i in range(1, quantos + 1):
        m = mes_num - i
        a = ano
        while m <= 0:
            m += 12
            a -= 1
        meses.append(f'{a:04d}-{m:02d}')
    return meses


def _campos_bandeira(venda_bandeira: dict) -> dict:
    """`venda_bandeira` = `{bandeira: venda_do_período_nela}` -- devolve
    `bandeira_dominante` (a que mais vendeu, usada no gráfico do Leve3 --
    roda 1 semana por mês, POR bandeira, em semanas diferentes, pedido
    22/09/26: "semana de ultra barra vermelha, semana de velanes,
    laranja") + `venda_velanes`/`venda_ultra_popular` (usadas na barra
    empilhada das outras mecânicas -- essas rodam nas 2 bandeiras ao
    mesmo tempo, "de quem foi" não faz sentido, mas "quanto foi de cada"
    sim; pedido 22/09/26, mesmo dia: "faze isso tambem, para os outros,
    talvez dividido nas barras"). Sempre calculado, mesmo quando a tela
    não usa (fica no payload sem custo nenhum)."""
    return {
        'bandeira_dominante': max(venda_bandeira, key=venda_bandeira.get) if venda_bandeira else None,
        'venda_velanes': float(venda_bandeira.get('velanes', ZERO)),
        'venda_ultra_popular': float(venda_bandeira.get('ultra_popular', ZERO)),
    }


def _periodos_com_destaque(grupos: dict, data_max=None) -> list:
    """Recebe `{chave_ordenavel: {'venda', 'tem_oferta', 'rotulo', 'tooltip',
    'parcial'}}` já montado por período (mês/semana/dia) e devolve a lista
    ordenada com `crescimento_pct` calculado (venda do período vs. média
    dos períodos SEM oferta e SEM estar parcial) -- lógica compartilhada
    pelas 3 granularidades do gráfico único "Mês/Semana/Dia" (pedido
    22/09/26: "prefiro que tenhamos apenas 1 gráfico... escolher olhar
    por mês, semana ou dia"). `venda`/`crescimento_pct` viram `float` e as
    datas internas já devem ter virado string antes de chegar aqui --
    Decimal/date não passam direto pro `json_script` do template."""
    periodos = [v for _, v in sorted(grupos.items())]

    # Mecânica sem separação base/oferta (Leve3: só importa a venda que
    # já É a própria oferta, `grupo` nunca vem preenchido) -- toda linha
    # presente já é, por definição, semana/dia de oferta. Sem esse
    # fallback, `tem_oferta` comparava sempre contra `grupo=oferta` (que
    # essas mecânicas nunca usam) e ficava False pra tudo, o gráfico
    # nunca destacava nada (achado real 22/09/26, Gabriel: "no genérico,
    # o gráfico não está destacado as semanas que foram da oferta").
    if periodos and not any(p['tem_oferta'] for p in periodos):
        for p in periodos:
            p['tem_oferta'] = True

    vendas_baseline = [p['venda'] for p in periodos if not p['tem_oferta'] and not p['parcial']]
    media_baseline = (sum(vendas_baseline, ZERO) / len(vendas_baseline)) if vendas_baseline else None

    # Preserva qualquer chave extra que o chamador tenha deixado no grupo
    # (ex.: `_chave_mes`, usado por `serie_semanal`/`serie_diaria` pra
    # filtrar por mês DEPOIS de já ter calculado a baseline -- ver comentário
    # lá) -- só os campos padrão abaixo são garantidos/normalizados.
    resultado = []
    for p in periodos:
        crescimento_pct = (
            float((p['venda'] / media_baseline - 1) * 100)
            if p['tem_oferta'] and not p['parcial'] and media_baseline else None
        )
        item = dict(p)
        item.update({'venda': float(p['venda']), 'crescimento_pct': crescimento_pct})
        resultado.append(item)
    return resultado


def serie_semanal(queryset, mes: str | None = None) -> dict:
    """Venda por semana (segunda a domingo), semana com `grupo=oferta`
    destacada + % de crescimento vs. a média das semanas sem oferta.
    Precisa de `data` -- linha de relatório agregado por "Ano-mês" não
    entra, não dá pra saber a semana dela.

    `queryset` deve vir SEM filtro de mês (achado real: filtrar por mês
    antes de chamar aqui corta ao meio uma semana que cruza a virada do
    mês -- Kimberly mostrou -78% numa semana que só tinha 2 dos 7 dias
    contados, o resto tinha caído no mês anterior e ficou de fora). `mes`
    (opcional, "AAAA-MM") só filtra quais semanas aparecem no RESULTADO —
    a média/baseline usa todas as semanas disponíveis no queryset, não só
    as do mês exibido (mais dado, comparação mais robusta, mesma lógica já
    usada no "crescimento" dos KPIs com os 3 meses antes)."""
    linhas = list(queryset.exclude(data=None).values('data', 'grupo', 'venda', 'loja__bandeira'))
    if not linhas:
        return {'periodos': []}

    data_max = max(l['data'] for l in linhas)

    grupos = defaultdict(lambda: {'venda': ZERO, 'tem_oferta': False, '_venda_bandeira': defaultdict(lambda: ZERO)})
    for l in linhas:
        dia = l['data']
        segunda = dia - timedelta(days=dia.weekday())
        chave = segunda.isoformat()
        g = grupos[chave]
        g['venda'] += l['venda'] or ZERO
        if l['grupo'] == Lancamento.GRUPO_OFERTA:
            g['tem_oferta'] = True
        g['_venda_bandeira'][l['loja__bandeira']] += l['venda'] or ZERO
        g['_segunda'] = segunda

    for chave, g in grupos.items():
        segunda = g.pop('_segunda')
        domingo = segunda + timedelta(days=6)
        g['rotulo'] = segunda.strftime('%d/%m')
        g['tooltip'] = f'{segunda.strftime("%d/%m")} a {domingo.strftime("%d/%m")}'
        # A última semana pode estar pela metade (dado só vai até
        # `data_max`, não até domingo) -- contar ela na média ou dar % de
        # crescimento compararia 7 dias de verdade contra menos de 7,
        # dado errado disfarçado de real (achado ao testar: mostrou
        # "-87%" numa semana que só tinha 1 dia de dado ainda).
        g['parcial'] = domingo > data_max
        g['_chave_mes'] = (segunda.strftime('%Y-%m'), domingo.strftime('%Y-%m'))
        g.update(_campos_bandeira(g.pop('_venda_bandeira')))

    # `_periodos_com_destaque` roda ANTES do filtro de `mes` -- a média/
    # baseline usa todas as semanas do queryset (histórico completo), `mes`
    # só decide quais entram no resultado devolvido pro template. Calcular
    # a baseline DEPOIS de já ter cortado por mês repetiria o mesmo bug já
    # corrigido antes (Kimberly: -78% numa semana cortada, baseline de
    # amostra pequena/errada).
    periodos = _periodos_com_destaque(grupos)
    if mes:
        periodos = [p for p in periodos if mes in p['_chave_mes']]
    for p in periodos:
        p.pop('_chave_mes', None)

    return {'periodos': periodos}


def serie_diaria(queryset, mes: str | None = None) -> dict:
    """Venda por dia, dia com `grupo=oferta` destacado + % de crescimento
    vs. a média dos dias sem oferta. Precisa de `data`. Mesmo padrão do
    `serie_semanal`: `queryset` sem filtro de mês (usa todo o histórico
    disponível pra baseline), `mes` só filtra quais dias aparecem no
    resultado."""
    linhas = list(queryset.exclude(data=None).values('data', 'grupo', 'venda', 'loja__bandeira'))
    if not linhas:
        return {'periodos': []}

    grupos = defaultdict(lambda: {'venda': ZERO, 'tem_oferta': False, '_venda_bandeira': defaultdict(lambda: ZERO)})
    for l in linhas:
        dia = l['data']
        g = grupos[dia.isoformat()]
        g['venda'] += l['venda'] or ZERO
        if l['grupo'] == Lancamento.GRUPO_OFERTA:
            g['tem_oferta'] = True
        g['_venda_bandeira'][l['loja__bandeira']] += l['venda'] or ZERO
        g['_data'] = dia

    for g in grupos.values():
        dia = g.pop('_data')
        g['rotulo'] = dia.strftime('%d/%m')
        g['tooltip'] = dia.strftime('%d/%m/%Y')
        g['parcial'] = False
        g['_ano_mes'] = ano_mes_de(dia)
        g.update(_campos_bandeira(g.pop('_venda_bandeira')))

    # Mesmo padrão do `serie_semanal`: baseline calculada ANTES do filtro
    # de mês, com o histórico completo.
    periodos = _periodos_com_destaque(grupos)
    if mes:
        periodos = [p for p in periodos if p['_ano_mes'] == mes]
    for p in periodos:
        p.pop('_ano_mes', None)

    return {'periodos': periodos}


def calcular_impacto_fabricante(queryset, busca: str = '', queryset_baseline=None, percentual_verba=None):
    """Oferta por fabricante — Kenvue/Principia/Botica/Procter (docx, seção
    5.3): compara volume/venda/margem da promoção do fabricante (oferta —
    tag exata) com todo o resto das vendas dele, incluindo "Sem Desconto"
    (base), mês a mês, por loja/bandeira e por produto.

    `queryset_baseline` (opcional): mesma mecânica/bandeira SEM o filtro de
    mês (pra "% crescimento" poder olhar os 3 meses ANTES do mês da oferta,
    mesmo com um mês específico selecionado na tela — sem isso, o cálculo
    ficaria sem dado nenhum de meses anteriores). Quando omitido, cai pra
    comparar com o resto do PRÓPRIO mês (comportamento anterior, 22/09).

    `percentual_verba` (opcional, ex. `Decimal('0.20')` pra Principia,
    confirmado pelo Gabriel 23/09: "principia é 20% sobre o custo do
    produto, esse é o investimento da industria") -- quando informado,
    calcula `investimento_oferta` linha a linha (`custo × percentual`,
    só nas linhas `grupo=oferta`) igual ao padrão já usado no Leve3
    (`calcular_leve3`), habilitando CMV com verba nas tabelas de loja/
    produto/campanha, não só no card agregado. Kenvue/Botica/Procter ainda
    não têm fórmula (`None`) -- fica tudo igual a antes pra eles."""
    linhas = queryset.select_related('loja').values(
        'loja_id', 'loja__codigo', 'loja__bandeira', 'produto_descricao',
        'grupo', 'tag_origem', 'ano_mes', 'data', 'itens', 'venda', 'custo', 'lucro',
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
    # Uma mecânica pode ter mais de 1 campanha rodando (ex. Procter: a
    # promoção mensal normal + a Semana do Cliente no mesmo mês, tags
    # diferentes) -- agrupado pela tag original (`tag_origem`, já salva por
    # linha), não mistura o investimento das duas. Quando só existe 1 tag de
    # oferta, isso vira uma tabela de 1 linha só (a tela esconde nesse caso).
    por_campanha = defaultdict(lambda: {'itens_oferta': ZERO, 'venda_oferta': ZERO, 'lucro_oferta': ZERO})
    total_investimento = ZERO
    por_campanha_mes = defaultdict(lambda: defaultdict(lambda: ZERO))
    # "% crescimento" (pedido pelo Gabriel, 22/09): venda média por DIA
    # durante a oferta vs. venda média por dia no resto do mês (mesma
    # lógica do Supra Corp Day -- `calcular_supracorp`). `dias_oferta_mes`
    # vem dos dias com `data` presentes numa linha de oferta (só existe
    # quando o relatório de origem tem coluna "Data" -- relatórios
    # agregados por "Ano-mês" não têm, ficam de fora dessa conta, não
    # travam o resto). `venda_base` por produto/mês só é rastreada aqui
    # (não existia antes -- `por_produto` só tinha o lado oferta).
    por_produto_base_mes = defaultdict(lambda: defaultdict(lambda: ZERO))
    dias_oferta_por_mes = defaultdict(set)

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

        if grupo == Lancamento.GRUPO_BASE:
            por_produto_base_mes[linha['produto_descricao']][linha['ano_mes']] += venda

        if grupo == Lancamento.GRUPO_OFERTA:
            if linha['data']:
                dias_oferta_por_mes[linha['ano_mes']].add(linha['data'])

            investimento = (custo * percentual_verba) if percentual_verba is not None else None

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

            nome_campanha = tag_sem_prefixo(linha['tag_origem']) or '(sem tag)'
            campanha = por_campanha[nome_campanha]
            campanha['itens_oferta'] += itens
            campanha['venda_oferta'] += venda
            campanha['lucro_oferta'] += lucro
            por_campanha_mes[nome_campanha][linha['ano_mes']] += venda

            if investimento is not None:
                total_investimento += investimento
                mes['investimento_oferta'] = mes.get('investimento_oferta', ZERO) + investimento
                loja['investimento_oferta'] = loja.get('investimento_oferta', ZERO) + investimento
                produto['investimento_oferta'] = produto.get('investimento_oferta', ZERO) + investimento
                campanha['investimento_oferta'] = campanha.get('investimento_oferta', ZERO) + investimento

    def _margem_pct(g):
        venda = totais[g]['venda']
        return (totais[g]['lucro'] / venda * 100) if venda else ZERO

    # "% crescimento" (pedido 22/09, decidido junto com o Gabriel depois de
    # comparar as opções): venda média por DIA durante a oferta vs. venda
    # média por dia dos 3 MESES ANTERIORES ao mês da oferta (não "resto do
    # próprio mês" — 1 mês só de base é amostra fina demais pra um produto
    # promocional, viu no dado real: 1 linha, R$37 no mês inteiro). Só é
    # possível quando `queryset_baseline` foi passado (precisa enxergar
    # meses fora do filtro de mês da tela); sem ele, cai pra "resto do
    # próprio mês" (comportamento de 22/09, pra não quebrar quem ainda não
    # foi adaptado pra passar o baseline).
    base_3meses_por_produto_mes = None
    if queryset_baseline is not None:
        base_3meses_por_produto_mes = defaultdict(lambda: defaultdict(lambda: ZERO))
        for linha in (
            queryset_baseline.filter(grupo=Lancamento.GRUPO_BASE)
            .values('produto_descricao', 'ano_mes')
            .annotate(venda_total=Sum('venda'))
        ):
            base_3meses_por_produto_mes[linha['produto_descricao']][linha['ano_mes']] += (
                linha['venda_total'] or ZERO
            )

    def _crescimento_pct(nomes_produtos, venda_oferta_por_mes):
        """`nomes_produtos`: 1 produto (lista de 1) pra linha da tabela, ou
        todos os produtos da oferta (lista) pro KPI agregado -- soma a base
        só DESSES produtos, nunca do catálogo inteiro do fabricante (achado
        real 22/09: comparar contra o catálogo inteiro dava crescimento
        geral NEGATIVO enquanto cada produto individual dava positivo,
        inconsistente — o denominador tinha que ser o mesmo conjunto).
        `None` quando não dá pra calcular: sem dia de oferta identificado
        (relatório sem coluna "Data") ou sem nenhuma venda base nos meses
        de referência (produto novo, ou meses antes de jan/26 — não tem
        dado, não força um número inventado)."""
        total_oferta, total_dias_oferta = ZERO, 0
        total_base, total_dias_base = ZERO, 0
        for ano_mes, venda_oferta_mes in venda_oferta_por_mes.items():
            dias_oferta_mes = len(dias_oferta_por_mes.get(ano_mes, set()))
            if not dias_oferta_mes:
                continue
            total_oferta += venda_oferta_mes
            total_dias_oferta += dias_oferta_mes

            if base_3meses_por_produto_mes is not None:
                meses_ref = _meses_antes(ano_mes, 3)
                fonte = base_3meses_por_produto_mes
                desconto_dias = 0
            else:
                meses_ref = [ano_mes]
                fonte = por_produto_base_mes
                desconto_dias = dias_oferta_mes

            for mes_ref in meses_ref:
                for nome in nomes_produtos:
                    total_base += fonte[nome].get(mes_ref, ZERO)
                ano, mes_num = int(mes_ref[:4]), int(mes_ref[5:7])
                total_dias_base += calendar.monthrange(ano, mes_num)[1] - desconto_dias
        if not total_dias_oferta or not total_dias_base or not total_base:
            return None
        media_oferta = total_oferta / total_dias_oferta
        media_base = total_base / total_dias_base
        return ((media_oferta / media_base - 1) * 100) if media_base else None

    kpis = {
        'itens_base': totais[Lancamento.GRUPO_BASE]['itens'],
        'venda_base': totais[Lancamento.GRUPO_BASE]['venda'],
        'lucro_base': totais[Lancamento.GRUPO_BASE]['lucro'],
        'margem_base_pct': _margem_pct(Lancamento.GRUPO_BASE),
        'itens_oferta': totais[Lancamento.GRUPO_OFERTA]['itens'],
        'venda_oferta': totais[Lancamento.GRUPO_OFERTA]['venda'],
        'lucro_oferta': totais[Lancamento.GRUPO_OFERTA]['lucro'],
        'margem_oferta_pct': _margem_pct(Lancamento.GRUPO_OFERTA),
        'crescimento_pct': _crescimento_pct(
            list(por_produto.keys()),
            {mes: valores['venda_oferta'] for mes, valores in por_mes.items()},
        ),
        'investimento_oferta': total_investimento if percentual_verba is not None else None,
    }

    produtos = [
        {
            'produto': nome, **valores,
            'crescimento_pct': _crescimento_pct([nome], por_produto_mes[nome]),
        }
        for nome, valores in por_produto.items()
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
            por_loja.values(), ['itens_oferta', 'venda_oferta', 'lucro_oferta', 'investimento_oferta']
        ),
        'produtos': produtos,
        'series_produtos': alinhar_com_labels(por_produto_mes, labels),
        'campanhas': sorted(
            [
                {
                    'campanha': nome, **valores,
                    'margem_pct': (valores['lucro_oferta'] / valores['venda_oferta'] * 100)
                    if valores['venda_oferta'] else ZERO,
                }
                for nome, valores in por_campanha.items()
            ],
            key=lambda c: c['venda_oferta'], reverse=True,
        ),
        'series_campanhas': alinhar_com_labels(por_campanha_mes, labels),
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
