"""Serviços de cálculo por mecânica de oferta.

Cada `calcular_<mecanica>(queryset)` recebe um queryset de `Lancamento` já
filtrado por mecânica (e por bandeira, se for o caso) e devolve os números
prontos pra tela — sem pré-agregação em banco, pra granularidade bater com
o filtro de bandeira em qualquer combinação (ver docx, seção 9).
"""
from __future__ import annotations

from .models import Lancamento


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
