from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


def _formatar(valor, casas=2) -> str:
    try:
        valor = Decimal(valor)
    except (InvalidOperation, TypeError):
        return str(valor)
    negativo = valor < 0
    valor = abs(valor)
    inteiro, _, fracao = f'{valor:.{casas}f}'.partition('.')
    grupos = []
    while len(inteiro) > 3:
        grupos.insert(0, inteiro[-3:])
        inteiro = inteiro[:-3]
    grupos.insert(0, inteiro)
    texto = '.'.join(grupos)
    if casas:
        texto = f'{texto},{fracao}'
    return f'-{texto}' if negativo else texto


@register.filter
def brl(valor) -> str:
    """R$ no formato pt-BR: 1.234,56."""
    return f'R$ {_formatar(valor, 2)}'


@register.filter
def numero(valor, casas=0) -> str:
    """Número no formato pt-BR (separador de milhar '.', decimal ',')."""
    return _formatar(valor, int(casas))
