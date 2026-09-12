"""Lookup produto -> fabricante a partir do cadastro (`Produto`), usado por
`importar_leve3` no lugar da heurística `erp.fabricante_generico()`.
"""
from __future__ import annotations

from .models import Produto

# Nome bruto do cadastro (coluna "Fabricante" do .xlsx) -> rótulo curto já
# usado em Lancamento.fabricante do Leve3 antes deste cadastro existir.
# Mantém os 4 primeiros pra não quebrar o cruzamento com Sellout
# (importar_sellout grava fabricante='EMS'/'Eurofarma'/'Germed'/'Prati' —
# ver calcular_impacto_leve3_fabricante). "U Química"/"Nova Química" são
# rótulos novos: o cadastro revelou que a heurística antiga mapeava os
# dois errado como "Neo Química" (token "QUIM" no fim do nome), quando na
# verdade são fabricantes diferentes — nenhum Sellout foi importado pra
# eles ainda, então não há nome legado a preservar.
_CANONICO = {
    'EMS GENERICO S/A': 'EMS',
    'EUROFARMA GENERICO': 'Eurofarma',
    'GERMED': 'Germed',
    'PRATI': 'Prati',
    'MEDLEY GENERICO': 'Medley',
    'TEUTO': 'Teuto',
    'NATULAB': 'Natulab',
    'U QUIMICA': 'U Química',
    'NOVA QUIMICA GENERIC': 'Nova Química',
}


def fabricante_canonico(nome_cadastro: str) -> str:
    """Normaliza o nome bruto do cadastro pro rótulo curto histórico, onde
    existir um mapeamento conhecido; senão devolve o nome do cadastro como
    está — sempre mais preciso que "Não identificado"."""
    nome_cadastro = (nome_cadastro or '').strip()
    return _CANONICO.get(nome_cadastro.upper(), nome_cadastro)


def mapa_fabricantes(descricoes=None) -> dict[str, str]:
    """{descricao: fabricante_canonico} pronto pra lookup em memória — os
    importadores processam milhares de linhas, então 1 dict carregado uma
    vez é melhor que 1 query por linha. `descricoes`, se passado, restringe
    a query (útil quando o importador já sabe o conjunto de produtos do
    arquivo)."""
    queryset = Produto.objects.all()
    if descricoes is not None:
        queryset = queryset.filter(descricao__in=descricoes)
    return {
        descricao: fabricante_canonico(fabricante)
        for descricao, fabricante in queryset.values_list('descricao', 'fabricante')
    }
