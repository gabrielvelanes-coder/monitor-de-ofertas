from decimal import Decimal

from django.http import Http404
from django.shortcuts import render

from apps.lojas.models import Loja

from .models import Lancamento
from .services import (
    ACOES_INFO, bandeira_da_request, calcular_cestoes,
    calcular_impacto_fabricante, calcular_impacto_leve3_fabricante,
    calcular_kimberly, calcular_leve3, calcular_marketing,
    calcular_supracorp, filtrar_por_bandeira, grafico_mensal,
    meses_disponiveis, querystring_extra,
)

ZERO = Decimal('0')

FABRICANTES = {
    'kenvue': (Lancamento.KENVUE, 'Kenvue'),
    'principia': (Lancamento.PRINCIPIA, 'Principia'),
    'botica': (Lancamento.BOTICA, 'Botica Nacional'),
    'procter': (Lancamento.PROCTER, 'Procter & Gamble'),
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
        'chave': 'leve3', 'rotulo': 'Leve 3 Pague 2', 'url': 'ofertas:leve3',
        'venda': d['kpis']['venda'], 'lucro': d['kpis']['margem_ajustada'], 'itens': d['kpis']['itens'],
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

    for a in acoes:
        a['cmv_pct'] = (100 - (a['lucro'] / a['venda'] * 100)) if a['venda'] else ZERO

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
    mes = request.GET.get('mes', '').strip()
    if mes not in meses:
        mes = ''

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

    queryset = filtrar_por_bandeira(
        Lancamento.objects.filter(mecanica=Lancamento.LEVE3), bandeira
    )
    fabricantes_disponiveis = sorted(
        v for v in queryset.values_list('fabricante', flat=True).distinct() if v
    )
    if fabricante:
        queryset = queryset.filter(fabricante=fabricante)

    dados = calcular_leve3(queryset, busca=busca)
    grafico = grafico_mensal(dados['por_mes'], [('venda', 'Venda')])
    impacto_fabricantes = calcular_impacto_leve3_fabricante()

    contexto = {
        'secao': 'leve3',
        'bandeira_atual': bandeira,
        'querystring_extra': querystring_extra(request),
        'busca': busca,
        'fabricante_atual': fabricante,
        'fabricantes_disponiveis': fabricantes_disponiveis,
        'grafico': grafico,
        'impacto_fabricantes': impacto_fabricantes,
        **dados,
    }
    return render(request, 'ofertas/leve3.html', contexto)


def cestoes(request):
    bandeira = bandeira_da_request(request)
    busca = request.GET.get('busca', '').strip()

    queryset = filtrar_por_bandeira(
        Lancamento.objects.filter(mecanica=Lancamento.CESTOES), bandeira
    )
    dados = calcular_cestoes(queryset, busca=busca)
    grafico = grafico_mensal(dados['por_mes'], [('venda', 'Venda')])

    contexto = {
        'secao': 'cestoes',
        'bandeira_atual': bandeira,
        'querystring_extra': querystring_extra(request),
        'busca': busca,
        'grafico': grafico,
        **dados,
    }
    return render(request, 'ofertas/cestoes.html', contexto)


def supracorp(request):
    bandeira = bandeira_da_request(request)

    queryset = filtrar_por_bandeira(
        Lancamento.objects.filter(mecanica=Lancamento.SUPRACORP), bandeira
    )
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
    queryset = filtrar_por_bandeira(
        Lancamento.objects.filter(mecanica=mecanica), bandeira
    )
    dados = calcular_impacto_fabricante(queryset, busca=busca)
    grafico = grafico_mensal(dados['por_mes'], [
        ('venda_base', 'Venda base'), ('venda_oferta', 'Venda oferta'),
    ])

    contexto = {
        'secao': f'fabricante_{fabricante}',
        'bandeira_atual': bandeira,
        'querystring_extra': querystring_extra(request),
        'busca': busca,
        'fabricante_chave': fabricante,
        'fabricante_rotulo': rotulo,
        'grafico': grafico,
        **dados,
    }
    return render(request, 'ofertas/impacto_fabricante.html', contexto)


def marketing(request):
    bandeira = bandeira_da_request(request)
    busca = request.GET.get('busca', '').strip()

    queryset = filtrar_por_bandeira(
        Lancamento.objects.filter(mecanica=Lancamento.MARKETING), bandeira
    )
    dados = calcular_marketing(queryset, busca=busca)
    grafico = grafico_mensal(dados['por_mes'], [('venda', 'Venda'), ('lucro', 'Lucro')])

    contexto = {
        'secao': 'marketing',
        'bandeira_atual': bandeira,
        'querystring_extra': querystring_extra(request),
        'busca': busca,
        'grafico': grafico,
        **dados,
    }
    return render(request, 'ofertas/marketing.html', contexto)


def kimberly(request):
    bandeira = bandeira_da_request(request)
    busca = request.GET.get('busca', '').strip()

    queryset = filtrar_por_bandeira(
        Lancamento.objects.filter(mecanica=Lancamento.KIMBERLY), bandeira
    )
    dados = calcular_kimberly(queryset, busca=busca)
    grafico = grafico_mensal(dados['por_mes'], [('venda', 'Venda'), ('lucro', 'Lucro')])

    contexto = {
        'secao': 'kimberly',
        'bandeira_atual': bandeira,
        'querystring_extra': querystring_extra(request),
        'busca': busca,
        'grafico': grafico,
        **dados,
    }
    return render(request, 'ofertas/kimberly.html', contexto)
