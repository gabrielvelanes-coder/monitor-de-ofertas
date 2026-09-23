from decimal import Decimal

from django.http import Http404, HttpResponse
from django.shortcuts import render

from apps.lojas.models import Loja
from apps.produtos.models import RebaixaProduto
from apps.verba.services import (
    PERCENTUAL_VERBA_FABRICANTE, anexar_cmv, cmv_pct, cmv_pct_com_verba, verba_apurada,
)

from .apuracao import (
    escrever_excel_apuracao, gerar_dataframe_apuracao, nome_arquivo_apuracao,
    resumo_apuracao_industria, resumo_apuracao_leve3,
)
from .erp import tag_sem_prefixo
from .models import Lancamento
from .services import (
    ACOES_INFO, bandeira_da_request, calcular_cestoes,
    calcular_impacto_fabricante, calcular_impacto_leve3_fabricante,
    calcular_kimberly, calcular_leve3, calcular_marketing,
    calcular_supracorp, filtrar_por_bandeira, grafico_mensal,
    mes_da_request, meses_disponiveis, querystring_extra, serie_diaria,
    serie_semanal,
)

ZERO = Decimal('0')

FABRICANTES = {
    'kenvue': (Lancamento.KENVUE, 'Kenvue'),
    'principia': (Lancamento.PRINCIPIA, 'Principia'),
    'botica': (Lancamento.BOTICA, 'Botica Nacional'),
    'procter': (Lancamento.PROCTER, 'Procter & Gamble'),
}

# Promoções pontuais restritas a 1 bandeira (Deu a Louca só Velanes, Ultra
# Queimão só Ultra Popular) — mesma lógica oferta/base de FABRICANTES, mas
# sem relatório dedicado do ERP ainda (importar_promocao_bandeira).
PROMOCOES = {
    'deu_a_louca': (Lancamento.DEU_A_LOUCA, 'Deu a Louca'),
    'ultra_queimao': (Lancamento.ULTRA_QUEIMAO, 'Ultra Queimão'),
}


def _dados_periodo(queryset_sem_mes, mes):
    """Abas Semana/Dia do gráfico único (pedido 22/09/26 -- "apenas 1
    gráfico... escolher olhar por mês, semana ou dia") -- a aba Mês usa o
    `grafico_mensal` de sempre (drill-down/clique-pra-filtrar), essas 2
    granularidades novas usam o mesmo formato simples do antigo gráfico
    semanal. `tem_semana`/`tem_dia` decidem se a aba aparece — mecânica
    com cobertura parcial de `data` (Leve3, Deu a Louca/Ultra Queimão) pode
    ficar sem nenhuma semana/dia pro recorte de mês/fabricante escolhido."""
    semanas = serie_semanal(queryset_sem_mes, mes)['periodos']
    dias = serie_diaria(queryset_sem_mes, mes)['periodos']
    return {
        'dados_periodo': {'semana': semanas, 'dia': dias},
        'tem_semana': bool(semanas),
        'tem_dia': bool(dias),
    }


def _resumo_executivo(bandeira, mes=''):
    """1 linha por ação, com a fatia de venda/lucro/itens que representa a
    oferta (não o catálogo de referência inteiro) — pra home funcionar como
    dashboard executivo. `mes` (AAAA-MM) filtra pra 1 mês só; vazio = todos."""
    def qs(mecanica):
        queryset = filtrar_por_bandeira(Lancamento.objects.filter(mecanica=mecanica), bandeira)
        if mes:
            queryset = queryset.filter(ano_mes=mes)
        return queryset

    acoes = []

    d = calcular_leve3(qs(Lancamento.LEVE3))
    acoes.append({
        # lucro contábil (sem verba) — a versão "com verba" soma
        # verba_apurada() logo abaixo, não a margem_ajustada direto, pra
        # não misturar as duas visões que o Gabriel pediu pra separar.
        'chave': 'leve3', 'rotulo': 'Leve 3 Pague 2', 'url': 'ofertas:leve3',
        'venda': d['kpis']['venda'], 'lucro': d['kpis']['margem_contabil'], 'itens': d['kpis']['itens'],
    })

    d = calcular_cestoes(qs(Lancamento.CESTOES))
    acoes.append({
        'chave': 'cestoes', 'rotulo': 'Cestões', 'url': 'ofertas:cestoes',
        'venda': d['kpis']['venda'], 'lucro': d['kpis']['lucro'], 'itens': d['kpis']['itens'],
    })

    d = calcular_supracorp(qs(Lancamento.SUPRACORP))
    acoes.append({
        'chave': 'supracorp', 'rotulo': 'Supra Corp Day', 'url': 'ofertas:supracorp',
        'venda': d['kpis']['venda_evento'], 'lucro': ZERO, 'itens': d['kpis']['itens_evento'],
    })

    for fab_chave, (mecanica, rotulo) in FABRICANTES.items():
        d = calcular_impacto_fabricante(qs(mecanica))
        acoes.append({
            'chave': fab_chave, 'rotulo': rotulo, 'url': 'ofertas:impacto_fabricante', 'url_arg': fab_chave,
            'venda': d['kpis']['venda_oferta'], 'lucro': d['kpis']['lucro_oferta'], 'itens': d['kpis']['itens_oferta'],
        })

    d = calcular_marketing(qs(Lancamento.MARKETING))
    acoes.append({
        'chave': 'marketing', 'rotulo': 'Itens do Marketing', 'url': 'ofertas:marketing',
        'venda': d['kpis']['venda'], 'lucro': d['kpis']['lucro'], 'itens': d['kpis']['itens'],
    })

    d = calcular_kimberly(qs(Lancamento.KIMBERLY))
    acoes.append({
        'chave': 'kimberly', 'rotulo': 'Kimberly', 'url': 'ofertas:kimberly',
        'venda': d['kpis_oferta']['venda'], 'lucro': d['kpis_oferta']['lucro'], 'itens': d['kpis_oferta']['itens'],
    })

    for promo_chave, (mecanica, rotulo) in PROMOCOES.items():
        d = calcular_impacto_fabricante(qs(mecanica))
        acoes.append({
            'chave': promo_chave, 'rotulo': rotulo, 'url': 'ofertas:impacto_promocao', 'url_arg': promo_chave,
            'venda': d['kpis']['venda_oferta'], 'lucro': d['kpis']['lucro_oferta'], 'itens': d['kpis']['itens_oferta'],
        })

    for a in acoes:
        a['cmv_pct_sem_verba'] = cmv_pct(a['venda'], a['lucro'])
        a['verba_apurada'] = verba_apurada(a['chave'], mes)
        a['cmv_pct_com_verba'] = cmv_pct_com_verba(a['venda'], a['lucro'], a['verba_apurada'])

    acoes.sort(key=lambda a: a['venda'], reverse=True)
    return {
        'acoes': acoes,
        'total_venda': sum((a['venda'] for a in acoes), ZERO),
        'total_lucro': sum((a['lucro'] for a in acoes), ZERO),
        'total_itens': sum((a['itens'] for a in acoes), ZERO),
    }


def home(request):
    bandeira = bandeira_da_request(request)
    meses = meses_disponiveis()
    mes = mes_da_request(request)

    lojas_velanes = Loja.objects.filter(bandeira=Loja.VELANES).count()
    lojas_ultra = Loja.objects.filter(bandeira=Loja.ULTRA_POPULAR).count()

    resumo = _resumo_executivo(bandeira, mes)
    grafico = {
        'labels': [a['rotulo'] for a in resumo['acoes']],
        'series': [{'label': 'Venda', 'data': [float(a['venda']) for a in resumo['acoes']]}],
    }

    contexto = {
        'secao': 'home',
        'bandeira_atual': bandeira,
        'querystring_extra': querystring_extra(request),
        'meses_disponiveis': meses,
        'mes_atual': mes,
        'lojas_velanes': lojas_velanes,
        'lojas_ultra': lojas_ultra,
        'grafico': grafico,
        **resumo,
    }
    return render(request, 'ofertas/home.html', contexto)


def leve3(request):
    bandeira = bandeira_da_request(request)
    busca = request.GET.get('busca', '').strip()
    fabricante = request.GET.get('fabricante', '').strip()
    meses = meses_disponiveis(Lancamento.LEVE3)
    mes = mes_da_request(request, Lancamento.LEVE3)

    queryset = filtrar_por_bandeira(
        Lancamento.objects.filter(mecanica=Lancamento.LEVE3), bandeira
    )
    fabricantes_disponiveis = sorted(
        v for v in queryset.values_list('fabricante', flat=True).distinct() if v
    )
    if fabricante:
        queryset = queryset.filter(fabricante=fabricante)
    queryset_sem_mes = queryset
    if mes:
        queryset = queryset.filter(ano_mes=mes)

    dados = calcular_leve3(queryset, busca=busca)
    # Venda dividida em 2 séries (Velanes/Ultra Popular) em vez de 1 série
    # só pintada pela bandeira "dominante" do mês -- a versão anterior
    # (dominante) saía sempre laranja/Velanes em TODO mês (Velanes vende
    # mais que a Ultra Popular o ano inteiro, mesmo cada uma rodando sua
    # própria semana), ficando monótona/sem informação nenhuma (achado do
    # Gabriel: "kenvue esta assim [rico, 4 séries] / leve3 eta assim
    # [tudo laranja] ... vamos arrumar isso"). Empilhada, mostra a
    # proporção real de cada bandeira por mês em vez de só "quem ganhou".
    # Unidades também divididas por bandeira (pedido 23/09/26, mesmo
    # motivo da venda acima) -- antes era 1 série cinza só ("Itens"),
    # agnóstica de bandeira.
    grafico = {
        'labels': [m['ano_mes'] for m in dados['por_mes']],
        'venda_velanes': [m['venda_velanes'] for m in dados['por_mes']],
        'venda_ultra_popular': [m['venda_ultra_popular'] for m in dados['por_mes']],
        'itens_velanes': [m['itens_velanes'] for m in dados['por_mes']],
        'itens_ultra_popular': [m['itens_ultra_popular'] for m in dados['por_mes']],
    }
    # Leve3 não tem `grupo` preenchido (só importa a venda que já é a
    # própria oferta, sem contraparte "base" pra comparar) -- todo período
    # com venda já é, por definição, semana/dia de oferta (fallback em
    # `_periodos_com_destaque`, services.py), então sai todo destacado,
    # mas sem % (não tem baseline "sem oferta" nenhum pra comparar). Útil
    # pra ver em qual semana cada bandeira rodou o combo, já que Velanes e
    # Ultra Popular giram em semanas diferentes.
    dados_periodo = _dados_periodo(queryset_sem_mes, mes)
    impacto_fabricantes = calcular_impacto_leve3_fabricante()
    apuracao_resumo = resumo_apuracao_leve3(ano_mes=mes)
    apuracao_total = sum((r['investimento'] for r in apuracao_resumo), ZERO)

    # CMV com/sem verba usando o investimento já calculado pro recorte atual
    # (bandeira/fabricante/busca/mês) — não o agregado de VerbaMensal, que
    # é sempre "todas as lojas, todos os meses" e não reflete esses filtros.
    dados['kpis']['cmv_pct_sem_verba'] = cmv_pct(dados['kpis']['venda'], dados['kpis']['margem_contabil'])
    dados['kpis']['cmv_pct_com_verba'] = cmv_pct_com_verba(
        dados['kpis']['venda'], dados['kpis']['margem_contabil'], dados['kpis']['investimento']
    )
    anexar_cmv(dados['ranking_lojas'], 'venda', 'margem_contabil', 'investimento')
    anexar_cmv(dados['ranking_bandeiras'], 'venda', 'margem_contabil', 'investimento')
    anexar_cmv(dados['produtos'], 'venda', 'lucro', 'investimento')

    contexto = {
        'secao': 'leve3',
        'bandeira_atual': bandeira,
        'querystring_extra': querystring_extra(request),
        'busca': busca,
        'fabricante_atual': fabricante,
        'fabricantes_disponiveis': fabricantes_disponiveis,
        'meses_disponiveis': meses,
        'mes_atual': mes,
        'grafico': grafico,
        'impacto_fabricantes': impacto_fabricantes,
        'apuracao_resumo': apuracao_resumo,
        'apuracao_total': apuracao_total,
        **dados_periodo,
        **dados,
    }
    return render(request, 'ofertas/leve3.html', contexto)


def cestoes(request):
    bandeira = bandeira_da_request(request)
    busca = request.GET.get('busca', '').strip()
    meses = meses_disponiveis(Lancamento.CESTOES)
    mes = mes_da_request(request, Lancamento.CESTOES)

    queryset = filtrar_por_bandeira(
        Lancamento.objects.filter(mecanica=Lancamento.CESTOES), bandeira
    )
    if mes:
        queryset = queryset.filter(ano_mes=mes)
    dados = calcular_cestoes(queryset, busca=busca)
    grafico = grafico_mensal(dados['por_mes'], [
        ('venda', 'Venda'), ('itens', 'Itens', 'unidades'),
    ])
    anexar_cmv(dados['ranking_lojas'], 'venda', 'lucro')
    anexar_cmv(dados['ranking_bandeiras'], 'venda', 'lucro')
    anexar_cmv(dados['produtos'], 'venda', 'lucro')

    contexto = {
        'secao': 'cestoes',
        'bandeira_atual': bandeira,
        'querystring_extra': querystring_extra(request),
        'busca': busca,
        'meses_disponiveis': meses,
        'mes_atual': mes,
        'grafico': grafico,
        **dados,
    }
    return render(request, 'ofertas/cestoes.html', contexto)


def supracorp(request):
    bandeira = bandeira_da_request(request)
    meses = meses_disponiveis(Lancamento.SUPRACORP)
    mes = mes_da_request(request, Lancamento.SUPRACORP)

    queryset = filtrar_por_bandeira(
        Lancamento.objects.filter(mecanica=Lancamento.SUPRACORP), bandeira
    )
    if mes:
        queryset = queryset.filter(ano_mes=mes)
    dados = calcular_supracorp(queryset)

    serie_diaria = dados['serie_diaria']
    grafico = {
        'labels': [item['data'].strftime('%d/%m') for item in serie_diaria],
        'series': [{'label': 'Itens', 'data': [float(item['itens']) for item in serie_diaria]}],
        'destaque': [i for i, item in enumerate(serie_diaria) if item['na_janela']],
    }

    contexto = {
        'secao': 'supracorp',
        'bandeira_atual': bandeira,
        'querystring_extra': querystring_extra(request),
        'meses_disponiveis': meses,
        'mes_atual': mes,
        'grafico': grafico,
        **dados,
    }
    return render(request, 'ofertas/supracorp.html', contexto)


def impacto_fabricante(request, fabricante):
    if fabricante not in FABRICANTES:
        raise Http404('Fabricante desconhecido.')
    mecanica, rotulo = FABRICANTES[fabricante]

    bandeira = bandeira_da_request(request)
    busca = request.GET.get('busca', '').strip()
    meses = meses_disponiveis(mecanica)
    mes = mes_da_request(request, mecanica)

    queryset_sem_mes = filtrar_por_bandeira(
        Lancamento.objects.filter(mecanica=mecanica), bandeira
    )
    # A mecânica pode ter campanha que só rodou em outro mês (ex.: a
    # promoção mensal normal da Procter ainda não tem dado de setembro,
    # só a Semana do Cliente) -- "tem mais de 1 campanha" precisa olhar
    # TODOS os meses, senão a seção "Campanhas" pisca escondida ao trocar
    # o filtro de mês pra um em que só 1 delas tem lançamento.
    tags_brutas = queryset_sem_mes.filter(
        grupo=Lancamento.GRUPO_OFERTA
    ).exclude(tag_origem='').values_list('tag_origem', flat=True).distinct()
    tem_multiplas_campanhas = len({tag_sem_prefixo(t) for t in tags_brutas}) > 1

    # Botão "Baixar apuração" só aparece pras campanhas que já têm regra de
    # rebaixa cadastrada (`importar_rebaixas`) -- sem isso o arquivo sairia
    # com Investimento R$0 em tudo, mais confuso que útil.
    campanhas_com_rebaixa = list(
        RebaixaProduto.objects.filter(mecanica=mecanica).values_list('campanha', flat=True).distinct()
    )

    percentual_verba = PERCENTUAL_VERBA_FABRICANTE.get(mecanica)

    queryset = queryset_sem_mes
    if mes:
        queryset = queryset.filter(ano_mes=mes)
    dados = calcular_impacto_fabricante(
        queryset, busca=busca, queryset_baseline=queryset_sem_mes, percentual_verba=percentual_verba,
    )
    grafico = grafico_mensal(dados['por_mes'], [
        ('venda_base', 'Venda base'), ('venda_oferta', 'Venda oferta'),
        ('itens_base', 'Itens base', 'unidades'), ('itens_oferta', 'Itens oferta', 'unidades'),
    ])
    dados_periodo = _dados_periodo(queryset_sem_mes, mes)
    apuracao_resumo = resumo_apuracao_industria(mecanica, campanhas_com_rebaixa, ano_mes=mes)
    apuracao_total = sum((r['investimento'] for r in apuracao_resumo), ZERO)

    # CMV geral (base + oferta) com/sem verba. Fabricante com fórmula
    # própria (`percentual_verba`, hoje só Principia) usa o investimento já
    # calculado linha a linha pro recorte atual (mesmo padrão do Leve3) --
    # os outros 3 (sem fórmula ainda, ver PLANO_VERBA.md) caem pro agregado
    # de VerbaMensal (`verba_apurada`, sempre None enquanto ninguém
    # cadastrar `valor_apurado` manual), e o template mostra "—" em vez de
    # R$0/0% mudo. Nas tabelas de loja/produto usa só a fatia "oferta"
    # (venda_oferta/lucro_oferta) — "base" não é a promoção, misturar dilui
    # o que a tabela quer mostrar.
    venda_total = dados['kpis']['venda_base'] + dados['kpis']['venda_oferta']
    lucro_total = dados['kpis']['lucro_base'] + dados['kpis']['lucro_oferta']
    investimento_kpi = (
        dados['kpis']['investimento_oferta'] if percentual_verba is not None
        else verba_apurada(mecanica, mes)
    )
    dados['kpis']['cmv_pct_sem_verba'] = cmv_pct(venda_total, lucro_total)
    dados['kpis']['cmv_pct_com_verba'] = cmv_pct_com_verba(venda_total, lucro_total, investimento_kpi)
    campo_verba = 'investimento_oferta' if percentual_verba is not None else None
    anexar_cmv(dados['ranking_lojas'], 'venda_oferta', 'lucro_oferta', campo_verba)
    anexar_cmv(dados['ranking_bandeiras'], 'venda_oferta', 'lucro_oferta', campo_verba)
    anexar_cmv(dados['produtos'], 'venda_oferta', 'lucro_oferta', campo_verba)

    contexto = {
        'secao': f'fabricante_{fabricante}',
        'bandeira_atual': bandeira,
        'querystring_extra': querystring_extra(request),
        'busca': busca,
        'fabricante_chave': fabricante,
        'fabricante_rotulo': rotulo,
        'meses_disponiveis': meses,
        'mes_atual': mes,
        'tem_multiplas_campanhas': tem_multiplas_campanhas,
        'campanhas_com_rebaixa': campanhas_com_rebaixa,
        # Aviso "verba pendente de definição" não pode olhar só
        # `campanhas_com_rebaixa` (isso é só o cadastro de rebaixa por EAN,
        # usado pro arquivo de apuração) -- Principia tem fórmula (20% do
        # custo) sem depender de rebaixa nenhuma, ver `PERCENTUAL_VERBA_FABRICANTE`.
        'tem_formula_verba': percentual_verba is not None or bool(campanhas_com_rebaixa),
        'apuracao_resumo': apuracao_resumo,
        'apuracao_total': apuracao_total,
        'grafico': grafico,
        **dados_periodo,
        **dados,
    }
    return render(request, 'ofertas/impacto_fabricante.html', contexto)


def impacto_promocao(request, promocao):
    """Deu a Louca e Ultra Queimão já nascem restritas a 1 bandeira cada
    (Velanes / Ultra Popular) — diferente das outras ações, não faz
    sentido oferecer o filtro de bandeira nem uma visão "por bandeira"
    aqui, sempre daria 1 linha só. `filtrar_por_bandeira` não é chamado."""
    if promocao not in PROMOCOES:
        raise Http404('Promoção desconhecida.')
    mecanica, rotulo = PROMOCOES[promocao]

    busca = request.GET.get('busca', '').strip()
    meses = meses_disponiveis(mecanica)
    mes = mes_da_request(request, mecanica)

    queryset_sem_mes = Lancamento.objects.filter(mecanica=mecanica)
    queryset = queryset_sem_mes
    if mes:
        queryset = queryset.filter(ano_mes=mes)
    dados = calcular_impacto_fabricante(queryset, busca=busca)
    grafico = grafico_mensal(dados['por_mes'], [
        ('venda_base', 'Venda base'), ('venda_oferta', 'Venda oferta'),
        ('itens_base', 'Itens base', 'unidades'), ('itens_oferta', 'Itens oferta', 'unidades'),
    ])
    dados_periodo = _dados_periodo(queryset_sem_mes, mes)

    # Mesma decisão de CMV do impacto_fabricante: sem fórmula de verba
    # definida ainda pra estas 2 promoções, então com_verba fica None (o
    # template mostra "—") até alguém apurar isso.
    venda_total = dados['kpis']['venda_base'] + dados['kpis']['venda_oferta']
    lucro_total = dados['kpis']['lucro_base'] + dados['kpis']['lucro_oferta']
    dados['kpis']['cmv_pct_sem_verba'] = cmv_pct(venda_total, lucro_total)
    dados['kpis']['cmv_pct_com_verba'] = cmv_pct_com_verba(
        venda_total, lucro_total, verba_apurada(mecanica, mes)
    )
    anexar_cmv(dados['ranking_lojas'], 'venda_oferta', 'lucro_oferta')
    anexar_cmv(dados['produtos'], 'venda_oferta', 'lucro_oferta')

    contexto = {
        'secao': f'promocao_{promocao}',
        'esconder_filtro_bandeira': True,
        'querystring_extra': querystring_extra(request),
        'busca': busca,
        'promocao_chave': promocao,
        'promocao_rotulo': rotulo,
        'meses_disponiveis': meses,
        'mes_atual': mes,
        'grafico': grafico,
        **dados_periodo,
        **dados,
    }
    return render(request, 'ofertas/impacto_promocao.html', contexto)


def marketing(request):
    bandeira = bandeira_da_request(request)
    busca = request.GET.get('busca', '').strip()
    meses = meses_disponiveis(Lancamento.MARKETING)
    mes = mes_da_request(request, Lancamento.MARKETING)

    queryset = filtrar_por_bandeira(
        Lancamento.objects.filter(mecanica=Lancamento.MARKETING), bandeira
    )
    if mes:
        queryset = queryset.filter(ano_mes=mes)
    dados = calcular_marketing(queryset, busca=busca)
    grafico = grafico_mensal(dados['por_mes'], [
        ('venda', 'Venda'), ('lucro', 'Lucro'), ('itens', 'Itens', 'unidades'),
    ])
    anexar_cmv(dados['ranking_bandeiras'], 'venda', 'lucro')
    anexar_cmv(dados['por_fabricante'], 'venda', 'lucro')
    anexar_cmv(dados['produtos'], 'venda', 'lucro')

    contexto = {
        'secao': 'marketing',
        'bandeira_atual': bandeira,
        'querystring_extra': querystring_extra(request),
        'busca': busca,
        'meses_disponiveis': meses,
        'mes_atual': mes,
        'grafico': grafico,
        **dados,
    }
    return render(request, 'ofertas/marketing.html', contexto)


def kimberly(request):
    bandeira = bandeira_da_request(request)
    busca = request.GET.get('busca', '').strip()
    meses = meses_disponiveis(Lancamento.KIMBERLY)
    mes = mes_da_request(request, Lancamento.KIMBERLY)

    queryset_sem_mes = filtrar_por_bandeira(
        Lancamento.objects.filter(mecanica=Lancamento.KIMBERLY), bandeira
    )
    queryset = queryset_sem_mes
    if mes:
        queryset = queryset.filter(ano_mes=mes)
    dados = calcular_kimberly(queryset, busca=busca)
    grafico = grafico_mensal(dados['por_mes'], [
        ('venda', 'Venda'), ('lucro', 'Lucro'), ('itens', 'Itens', 'unidades'),
    ])
    dados_periodo = _dados_periodo(queryset_sem_mes, mes)
    anexar_cmv(dados['ranking_bandeiras'], 'venda', 'lucro')
    anexar_cmv(dados['produtos'], 'venda', 'lucro')

    contexto = {
        'secao': 'kimberly',
        'bandeira_atual': bandeira,
        'querystring_extra': querystring_extra(request),
        'busca': busca,
        'meses_disponiveis': meses,
        'mes_atual': mes,
        'grafico': grafico,
        **dados_periodo,
        **dados,
    }
    return render(request, 'ofertas/kimberly.html', contexto)


def exportar_apuracao(request, mecanica):
    """Botão "Baixar apuração" das telas de Leve3/Procter -- mesma lógica
    do management command `exportar_apuracao_industria`
    (`gerar_dataframe_apuracao`, compartilhada), só que devolve o .xlsx
    direto como download em vez de salvar em `dados/saida/`. Nome do
    arquivo: "apuracao_<oferta>_<mês>.xlsx" (pedido do Gabriel, 22/09) --
    `<oferta>` é o fabricante no caso do Leve3 (1 arquivo por fabricante,
    não 1 só com todos juntos) ou a campanha nas demais."""
    campanha = request.GET.get('campanha') or None
    mes = request.GET.get('mes') or None
    fabricante = request.GET.get('fabricante') or None

    if mecanica != Lancamento.LEVE3 and not campanha:
        raise Http404('Falta a campanha pra essa mecânica.')
    if mecanica == Lancamento.LEVE3 and not fabricante:
        raise Http404('Falta o fabricante -- o Leve3 sai separado por fabricante, não 1 arquivo só.')

    df, dados = gerar_dataframe_apuracao(mecanica, campanha=campanha, ano_mes=mes, fabricante=fabricante)
    if df.empty:
        raise Http404('Nenhum lançamento encontrado pra gerar a apuração.')

    nome_oferta = fabricante if mecanica == Lancamento.LEVE3 else campanha
    resposta = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    resposta['Content-Disposition'] = f'attachment; filename="{nome_arquivo_apuracao(nome_oferta, mes)}"'
    escrever_excel_apuracao(df, dados, nome_oferta, resposta)
    return resposta
