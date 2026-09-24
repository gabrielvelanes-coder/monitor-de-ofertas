"""Leitura direta do banco PostgreSQL do ERP (somente leitura), no lugar
dos .xls "Análise de Venda por Item" exportados à mão.

A consulta reproduz exatamente as colunas do relatório (conferido com o
Gabriel em 23/09/26, loja 02, 02/01/2026, produtos Kenvue: itens, venda,
desconto, custo e tag "Cad. Oferta" batem com o .xls):

    Cód. Un. Neg.  -> unidadenegocio.codigo
    Data           -> itemvenda.datahora::date
    Embalagem      -> embalagem.descricao
    Detalhe Desc.  -> 'Cad. Oferta: ' || cadernooferta.nome  (ou 'Sem Desconto')
    Itens / Venda / Desconto -> itemvenda.quantidade / valortotal / desconto
    Custo          -> itemvenda.quantidade * movimentacaoestoque.custo
    Lucro          -> Venda - Custo
    Fabricante     -> produto.fabricanteid -> fabricante.pessoaid -> pessoa.nome

Só vendas E itens finalizados (venda.status = 'F' e itemvenda.status =
'F'). Sem o filtro no item o banco dava +0,3% sobre o .xls; em jan/2026
Kenvue os itens C+D somavam R$ 707,25, exatamente a diferença. O DataFrame devolvido usa os
mesmos nomes de coluna normalizados de `erp.ler_relatorio_erp`, então os
importadores existentes funcionam sem mudança de regra.

Credenciais: arquivo `.env` na raiz do projeto (fora do Git), ver
`.env.exemplo`. A conexão é aberta com `default_transaction_read_only=on`
-- mesmo que algum código tentasse gravar, o PostgreSQL recusaria.
"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pandas as pd
from django.conf import settings

ARQUIVO_ENV = Path(settings.BASE_DIR) / '.env'

CONSULTA_VENDA_POR_ITEM = """
SELECT u.codigo                                   AS cod_un_neg,
       iv.datahora::date                          AS data,
       e.descricao                                AS embalagem,
       e.codigobarras                             AS codigo_barras,
       pf.nome                                    AS fabricante,
       COALESCE('Cad. Oferta: ' || co.nome, 'Sem Desconto') AS detalhe_desconto,
       SUM(iv.quantidade)                         AS itens,
       SUM(iv.valortotal)                         AS venda,
       SUM(iv.desconto)                           AS desconto,
       SUM(iv.quantidade * COALESCE(me.custo, 0)) AS custo
FROM itemvenda iv
JOIN venda v               ON v.id = iv.vendaid AND v.status = 'F'
JOIN unidadenegocio u      ON u.id = iv.unidadenegocioid
JOIN embalagem e           ON e.id = iv.embalagemid
JOIN produto p             ON p.id = e.produtoid
LEFT JOIN fabricante f     ON f.id = p.fabricanteid
LEFT JOIN pessoa pf        ON pf.id = f.pessoaid
LEFT JOIN cadernooferta co ON co.id = iv.cadernoofertaid
LEFT JOIN movimentacaoestoque me ON me.id = iv.movimentacaoestoqueid
WHERE iv.status = 'F'  -- item finalizado (C/D = item cancelado/devolvido, fora do relatório do ERP)
  AND iv.datahora >= %(inicio)s
  AND iv.datahora <  %(fim)s
  AND {filtro_fabricante}
GROUP BY 1, 2, 3, 4, 5, 6
ORDER BY 2, 1, 3
"""


def _ler_env() -> dict:
    """Lê `.env` (CHAVE=valor por linha) sem depender de pacote extra.
    Variáveis de ambiente de verdade têm prioridade sobre o arquivo."""
    valores = {}
    if ARQUIVO_ENV.exists():
        for linha in ARQUIVO_ENV.read_text(encoding='utf-8').splitlines():
            linha = linha.strip()
            if not linha or linha.startswith('#') or '=' not in linha:
                continue
            chave, valor = linha.split('=', 1)
            valores[chave.strip()] = valor.strip().strip('"').strip("'")
    for chave in list(valores) + ['ERP_HOST', 'ERP_PORTA', 'ERP_BANCO', 'ERP_USUARIO', 'ERP_SENHA']:
        if os.environ.get(chave):
            valores[chave] = os.environ[chave]
    return valores


def conectar():
    """Abre conexão SOMENTE LEITURA com o banco do ERP."""
    import psycopg  # import tardio: o painel continua rodando sem o pacote

    env = _ler_env()
    faltando = [c for c in ('ERP_HOST', 'ERP_BANCO', 'ERP_USUARIO', 'ERP_SENHA') if not env.get(c)]
    if faltando:
        raise RuntimeError(
            f'Faltam no arquivo .env: {", ".join(faltando)}. '
            'Copie .env.exemplo para .env e preencha.'
        )
    return psycopg.connect(
        host=env['ERP_HOST'],
        port=env.get('ERP_PORTA', '5432'),
        dbname=env['ERP_BANCO'],
        user=env['ERP_USUARIO'],
        password=env['ERP_SENHA'],
        connect_timeout=15,
        options='-c default_transaction_read_only=on -c statement_timeout=600000',
        application_name='painel-ofertas',
    )


def _executar_consulta(inicio: date, fim: date, filtro_sql: str, **parametros) -> pd.DataFrame:
    """Roda `CONSULTA_VENDA_POR_ITEM` com `{filtro_fabricante}` substituído
    por `filtro_sql` (fragmento SQL cru) e `parametros` como parâmetros
    nomeados extras do `WHERE` (além de `inicio`/`fim`, sempre presentes)."""
    consulta = CONSULTA_VENDA_POR_ITEM.format(filtro_fabricante=filtro_sql)
    with conectar() as conn, conn.cursor() as cur:
        cur.execute(consulta, {'inicio': inicio, 'fim': fim, **parametros})
        colunas = [d.name for d in cur.description]
        df = pd.DataFrame(cur.fetchall(), columns=colunas)
    for col in ('itens', 'venda', 'desconto', 'custo'):
        df[col] = pd.to_numeric(df[col]).astype(float)
    df['lucro'] = df['venda'] - df['custo']
    df['data'] = pd.to_datetime(df['data'])
    return df


def consultar_venda_por_item(inicio: date, fim: date, fabricante_like: str | list[str]) -> pd.DataFrame:
    """Equivalente ao .xls "Análise de Venda por Item" filtrado por
    fabricante, de `inicio` (inclusive) a `fim` (exclusive).

    `fabricante_like`: padrão ILIKE do nome do fabricante no ERP (ex.
    '%KENVUE%'), OU uma lista de nomes EXATOS quando a mecânica agrupa mais
    de 1 fabricante do ERP (ex. Botica: `['BOTICA', 'SIAGE EUDORA', 'VULT']`
    -- confirmado com o Gabriel 23/09/26; exclui de propósito 'BOTICA LA
    PIEL', que é outro fabricante, não faz parte do grupo)."""
    if isinstance(fabricante_like, str):
        return _executar_consulta(inicio, fim, 'pf.nome ILIKE %(fabricante)s', fabricante=fabricante_like)
    return _executar_consulta(inicio, fim, 'pf.nome = ANY(%(fabricante)s)', fabricante=list(fabricante_like))


def consultar_venda_por_tag(inicio: date, fim: date, padrao_tag: str) -> pd.DataFrame:
    """Todas as vendas (qualquer fabricante) cujo caderno de oferta bate o
    padrão ILIKE `padrao_tag` (ex. 'PRODUTOS MARKETING%'). Pra mecânicas
    tipo "Itens do Marketing" que não são de 1 fabricante só."""
    return _executar_consulta(inicio, fim, 'co.nome ILIKE %(tag)s', tag=padrao_tag)


def consultar_venda_por_produtos(inicio: date, fim: date, produtos) -> pd.DataFrame:
    """Todas as vendas (qualquer fabricante, qualquer tag) dos produtos com
    descrição EXATA em `produtos` (a coluna 'Embalagem'). Pra Cestões: 1ª
    passada acha os produtos que já tiveram a tag "OFERTAS CESTAO" (via
    `consultar_venda_por_tag`), 2ª passada traz o histórico COMPLETO
    desses produtos, dentro ou fora da tag (docx, seção 5.4)."""
    return _executar_consulta(inicio, fim, 'e.descricao = ANY(%(produtos)s)', produtos=list(produtos))


def consultar_venda_por_produtos_e_lojas(inicio: date, fim: date, produtos, codigos_loja) -> pd.DataFrame:
    """Como `consultar_venda_por_produtos`, mas também restrito a uma lista
    de códigos de loja -- pra Deu a Louca/Ultra Queimão (23/09/26): a
    promoção é restrita a 1 bandeira, e o próprio código da loja já resolve
    isso (`Loja.objects.filter(bandeira=...)`, sem precisar de heurística
    no banco). `unidadenegocio.codigo` no ERP vem com zero à esquerda
    ('02', '03'...) -- diferente do `Loja.codigo` do painel (sem padding,
    '2', '3'...), daí o `zfill(2)` antes de comparar."""
    return _executar_consulta(
        inicio, fim, 'e.descricao = ANY(%(produtos)s) AND u.codigo = ANY(%(codigos)s)',
        produtos=list(produtos), codigos=[str(c).zfill(2) for c in codigos_loja],
    )


CONSULTA_VENDA_GERAL_MENSAL = """
SELECT date_trunc('month', iv.datahora)::date AS mes,
       u.codigo                                   AS cod_un_neg,
       SUM(iv.quantidade)                         AS itens,
       SUM(iv.valortotal)                         AS venda,
       SUM(iv.quantidade * COALESCE(me.custo, 0)) AS custo
FROM itemvenda iv
JOIN venda v          ON v.id = iv.vendaid AND v.status = 'F'
JOIN unidadenegocio u ON u.id = iv.unidadenegocioid
LEFT JOIN movimentacaoestoque me ON me.id = iv.movimentacaoestoqueid
WHERE iv.status = 'F'
  AND iv.datahora >= %(inicio)s
  AND iv.datahora <  %(fim)s
GROUP BY 1, 2
ORDER BY 1, 2
"""


def consultar_venda_geral_mensal(inicio: date, fim: date) -> pd.DataFrame:
    """Faturamento do MÊS INTEIRO por loja -- TODO produto, com ou sem
    oferta, de `inicio` (inclusive) a `fim` (exclusive). Pra "vendas
    gerais" do dashboard (23/09/26) -- diferente das outras consultas
    deste módulo, não filtra por fabricante/tag/produto nenhum, e já
    agrega por mês (não por dia/produto): o catálogo inteiro por item
    seria centenas de milhares de linhas/mês, sem necessidade nenhuma
    pra essa pergunta ("que fatia do faturamento total são as ofertas?").
    Medido: ~7s pra 9 meses × todas as lojas -- por isso `importar_do_
    banco vendas_gerais` grava o resultado (`VendaGeralMensal`) em vez do
    dashboard consultar o banco a cada carregamento de página."""
    with conectar() as conn, conn.cursor() as cur:
        cur.execute(CONSULTA_VENDA_GERAL_MENSAL, {'inicio': inicio, 'fim': fim})
        colunas = [d.name for d in cur.description]
        df = pd.DataFrame(cur.fetchall(), columns=colunas)
    for col in ('itens', 'venda', 'custo'):
        df[col] = pd.to_numeric(df[col]).astype(float)
    return df
