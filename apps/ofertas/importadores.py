"""Lógica de importação compartilhada pelas 4 mecânicas de "impacto por
fabricante" (Kenvue, Principia, Botica, Procter — docx seção 5.3): cada
arquivo baseline_<fabricante>_2026.xls traz linhas com a tag de promoção
específica do fabricante (grupo oferta — o produto saiu do caderno de
oferta daquela promoção) e linhas com qualquer outra tag, incluindo "Sem
Desconto" e outras campanhas do próprio fabricante (grupo base — tudo que
não é essa promoção específica). Corrigido em 12/09/26: antes a base era
só "Sem Desconto" e todo o resto (Todo Dia, Cestão, Marketing, etc.) era
descartado, subestimando a base — ver [[projeto-painel-ofertas]].
"""
from __future__ import annotations

import re

from django.db import transaction

from apps.lojas.models import Loja

from .erp import (
    ano_mes_de, codigo_loja, coluna, ler_relatorio_erp, remover_linha_total,
    tag_sem_prefixo,
)
from .models import Lancamento


def importar_relatorio_fabricante(caminho, mecanica: str, tag_alvo: str, fabricante: str) -> dict:
    df, _, _ = ler_relatorio_erp(caminho)

    col_loja = coluna(df, 'Cód. Un. Neg.')
    col_ano_mes = coluna(df, 'Ano-mês')
    col_produto = coluna(df, 'Embalagem')
    col_tag = coluna(df, 'Detalhe Desconto', 'Cad. Oferta')
    col_itens = coluna(df, 'Itens')
    col_venda = coluna(df, 'Venda')
    col_desconto = coluna(df, 'Desconto')
    col_custo = coluna(df, 'Custo')
    col_lucro = coluna(df, 'Lucro')
    faltando = [
        nome for nome, col in {
            'loja': col_loja, 'ano_mes': col_ano_mes, 'produto': col_produto,
            'tag': col_tag, 'itens': col_itens, 'venda': col_venda,
            'custo': col_custo, 'lucro': col_lucro,
        }.items() if col is None
    ]
    if faltando:
        raise ValueError(f'Colunas não encontradas no arquivo: {", ".join(faltando)}.')

    df = remover_linha_total(df, col_ano_mes)

    lojas = {loja.codigo: loja for loja in Loja.objects.all()}
    lancamentos = []
    lojas_sem_cadastro = set()

    for _, linha in df.iterrows():
        tag_bruta = str(linha.get(col_tag, '') or '').strip()
        tag_limpa = tag_sem_prefixo(tag_bruta)
        # Oferta = só a tag exata da promoção (saiu do caderno de oferta
        # daquele fabricante). Base = tudo mais — "Sem Desconto" e qualquer
        # outra tag/campanha — porque a pergunta de negócio é "o produto
        # vendeu mais dentro ou fora dessa promoção", não "vendeu mais em
        # preço cheio ou nesta promoção".
        grupo = (
            Lancamento.GRUPO_OFERTA if tag_limpa.upper() == tag_alvo.upper()
            else Lancamento.GRUPO_BASE
        )

        codigo = codigo_loja(linha[col_loja])
        loja = lojas.get(codigo)
        if loja is None:
            lojas_sem_cadastro.add(codigo)
            continue

        lancamentos.append(Lancamento(
            mecanica=mecanica,
            loja=loja,
            produto_descricao=str(linha[col_produto]).strip(),
            fabricante=fabricante,
            tag_origem=tag_bruta,
            grupo=grupo,
            ano_mes=str(linha[col_ano_mes]).strip(),
            itens=linha[col_itens],
            venda=linha[col_venda],
            desconto=linha.get(col_desconto) or 0,
            custo=linha[col_custo],
            lucro=linha[col_lucro],
            arquivo_origem=caminho.name,
        ))

    with transaction.atomic():
        apagados, _ = Lancamento.objects.filter(mecanica=mecanica).delete()
        Lancamento.objects.bulk_create(lancamentos, batch_size=1000)

    return {
        'importados': len(lancamentos),
        'apagados': apagados,
        'lojas_sem_cadastro': lojas_sem_cadastro,
    }


def importar_promocao_bandeira(
    caminho, mecanica: str, padrao_tag: re.Pattern, bandeira: str,
) -> dict:
    """Importa uma promoção pontual restrita a 1 bandeira (Deu a Louca só
    Velanes, Ultra Queimão só Ultra Popular — não têm relatório dedicado do
    ERP ainda, a tag aparece misturada num "Análise de Venda por Item"
    geral). Linhas de lojas de outra bandeira são ignoradas de propósito
    (a promoção não existe lá). Dentro da bandeira, oferta = tag da
    promoção (`padrao_tag`, regex case-insensitive já compilado); base =
    todo o resto do portfólio da bandeira — mesma lógica de
    `importar_relatorio_fabricante`.

    Aditivo por arquivo (como Marketing), não por mecânica/mês inteiro: o
    Gabriel exporta o período aos poucos ao longo do mês, cada import
    substitui só o que o próprio arquivo trouxe."""
    df, _, _ = ler_relatorio_erp(caminho)

    col_loja = coluna(df, 'Cód. Un. Neg.')
    col_ano_mes = coluna(df, 'Ano-mês')
    col_data = coluna(df, 'Data')
    col_produto = coluna(df, 'Embalagem')
    col_tag = coluna(df, 'Detalhe Desconto', 'Cad. Oferta')
    col_itens = coluna(df, 'Itens')
    col_venda = coluna(df, 'Venda')
    col_desconto = coluna(df, 'Desconto')
    col_custo = coluna(df, 'Custo')
    col_lucro = coluna(df, 'Lucro')
    faltando = [
        nome for nome, col in {
            'loja': col_loja, 'produto': col_produto, 'tag': col_tag,
            'itens': col_itens, 'venda': col_venda, 'custo': col_custo,
            'lucro': col_lucro,
        }.items() if col is None
    ]
    if faltando:
        raise ValueError(f'Colunas não encontradas no arquivo: {", ".join(faltando)}.')
    if col_ano_mes is None and col_data is None:
        raise ValueError('Precisa de coluna "Ano-mês" ou "Data" pra determinar o mês.')

    df = remover_linha_total(df, col_ano_mes or col_loja)

    lojas_da_bandeira = {loja.codigo: loja for loja in Loja.objects.filter(bandeira=bandeira)}
    lancamentos = []
    lojas_sem_cadastro = set()

    for _, linha in df.iterrows():
        codigo = codigo_loja(linha[col_loja])
        loja = lojas_da_bandeira.get(codigo)
        if loja is None:
            if not Loja.objects.filter(codigo=codigo).exists():
                lojas_sem_cadastro.add(codigo)
            continue  # loja de outra bandeira — promoção não existe lá

        tag_bruta = str(linha.get(col_tag, '') or '').strip()
        grupo = (
            Lancamento.GRUPO_OFERTA if padrao_tag.search(tag_sem_prefixo(tag_bruta))
            else Lancamento.GRUPO_BASE
        )

        if col_ano_mes:
            ano_mes = str(linha[col_ano_mes]).strip()
            data_linha = None
        else:
            data_linha = linha[col_data]
            data_linha = data_linha.date() if hasattr(data_linha, 'date') else data_linha
            ano_mes = ano_mes_de(data_linha)

        lancamentos.append(Lancamento(
            mecanica=mecanica,
            loja=loja,
            produto_descricao=str(linha[col_produto]).strip(),
            tag_origem=tag_bruta,
            grupo=grupo,
            ano_mes=ano_mes,
            data=data_linha,
            itens=linha[col_itens],
            venda=linha[col_venda],
            desconto=linha.get(col_desconto) or 0,
            custo=linha[col_custo],
            lucro=linha[col_lucro],
            arquivo_origem=caminho.name,
        ))

    with transaction.atomic():
        apagados, _ = Lancamento.objects.filter(
            mecanica=mecanica, arquivo_origem=caminho.name
        ).delete()
        Lancamento.objects.bulk_create(lancamentos, batch_size=1000)

    return {
        'importados': len(lancamentos),
        'apagados': apagados,
        'lojas_sem_cadastro': lojas_sem_cadastro,
    }
