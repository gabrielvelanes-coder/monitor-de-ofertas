from django.db.models import Count
from django.http import Http404
from django.shortcuts import render

from apps.lojas.models import Loja

from .models import Lancamento
from .services import (
    MECANICAS_INFO, bandeira_da_request, calcular_cestoes,
    calcular_impacto_fabricante, calcular_leve3, calcular_supracorp,
    filtrar_por_bandeira,
)

FABRICANTES = {
    'kenvue': (Lancamento.KENVUE, 'Kenvue'),
    'principia': (Lancamento.PRINCIPIA, 'Principia'),
    'botica': (Lancamento.BOTICA, 'Botica Nacional'),
    'procter': (Lancamento.PROCTER, 'Procter & Gamble'),
}


def home(request):
    bandeira = bandeira_da_request(request)

    lojas = Loja.objects.filter(bandeira=bandeira) if bandeira else Loja.objects.all()
    total_lojas = lojas.count()
    lojas_velanes = Loja.objects.filter(bandeira=Loja.VELANES).count()
    lojas_ultra = Loja.objects.filter(bandeira=Loja.ULTRA_POPULAR).count()

    contagem_por_mecanica = dict(
        filtrar_por_bandeira(Lancamento.objects.all(), bandeira)
        .values_list('mecanica')
        .annotate(total=Count('id'))
        .values_list('mecanica', 'total')
    )
    mecanicas = [
        {'chave': chave, 'rotulo': rotulo, 'lancamentos': contagem_por_mecanica.get(chave, 0)}
        for chave, rotulo in MECANICAS_INFO
    ]

    contexto = {
        'secao': 'home',
        'bandeira_atual': bandeira,
        'total_lojas': total_lojas,
        'lojas_velanes': lojas_velanes,
        'lojas_ultra': lojas_ultra,
        'mecanicas': mecanicas,
    }
    return render(request, 'ofertas/home.html', contexto)


def leve3(request):
    bandeira = bandeira_da_request(request)
    busca = request.GET.get('busca', '').strip()

    queryset = filtrar_por_bandeira(
        Lancamento.objects.filter(mecanica=Lancamento.LEVE3), bandeira
    )
    dados = calcular_leve3(queryset, busca=busca)

    contexto = {
        'secao': 'leve3',
        'bandeira_atual': bandeira,
        'busca': busca,
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

    contexto = {
        'secao': 'cestoes',
        'bandeira_atual': bandeira,
        'busca': busca,
        **dados,
    }
    return render(request, 'ofertas/cestoes.html', contexto)


def supracorp(request):
    bandeira = bandeira_da_request(request)

    queryset = filtrar_por_bandeira(
        Lancamento.objects.filter(mecanica=Lancamento.SUPRACORP), bandeira
    )
    dados = calcular_supracorp(queryset)

    contexto = {
        'secao': 'supracorp',
        'bandeira_atual': bandeira,
        **dados,
    }
    return render(request, 'ofertas/supracorp.html', contexto)


def impacto_fabricante(request, fabricante):
    if fabricante not in FABRICANTES:
        raise Http404('Fabricante desconhecido.')
    mecanica, rotulo = FABRICANTES[fabricante]

    bandeira = bandeira_da_request(request)
    queryset = filtrar_por_bandeira(
        Lancamento.objects.filter(mecanica=mecanica), bandeira
    )
    dados = calcular_impacto_fabricante(queryset)

    contexto = {
        'secao': f'fabricante_{fabricante}',
        'bandeira_atual': bandeira,
        'fabricante_chave': fabricante,
        'fabricante_rotulo': rotulo,
        'fabricantes': [
            {'chave': chave, 'rotulo': rotulo} for chave, (_, rotulo) in FABRICANTES.items()
        ],
        **dados,
    }
    return render(request, 'ofertas/impacto_fabricante.html', contexto)
