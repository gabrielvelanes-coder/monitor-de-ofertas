"""Leitura dos relatórios "Análise de Venda por Item" do ERP (.xls, gerados
pelo JasperReports) que alimentam o painel.

Todos os arquivos seguem o mesmo formato de exportação, mas com colunas em
ordens diferentes: linha 0 é um título com o período do relatório, linha 1
é o cabeçalho de verdade. Este módulo concentra essa leitura pra não
duplicar o parsing em cada comando `importar_*`.
"""
from __future__ import annotations

import fnmatch
import re
import unicodedata
from datetime import date, datetime
from pathlib import Path

import pandas as pd
from django.conf import settings

PASTA_ENTRADA = Path(settings.BASE_DIR) / 'dados' / 'entrada'


def encontrar_arquivo(padrao: str, pasta: Path = PASTA_ENTRADA) -> Path:
    """Acha em `pasta` o único arquivo cujo nome bate com `padrao` (glob,
    case-insensitive). Usado pelos comandos `importar_*` quando o caminho
    do arquivo não é passado explicitamente — Gabriel só joga o .xls em
    `dados/entrada/` e roda o comando.
    """
    candidatos = [
        p for p in pasta.glob('*')
        if p.is_file() and fnmatch.fnmatch(p.name.lower(), padrao.lower())
    ]
    if not candidatos:
        raise FileNotFoundError(
            f'Nenhum arquivo em "{pasta}" bate com "{padrao}". '
            'Copie o .xls pra lá ou passe --arquivo com o caminho completo.'
        )
    if len(candidatos) > 1:
        nomes = ', '.join(p.name for p in candidatos)
        raise FileNotFoundError(
            f'Mais de um arquivo em "{pasta}" bate com "{padrao}": {nomes}. '
            'Passe --arquivo com o caminho completo pra desambiguar.'
        )
    return candidatos[0]


def normalizar(texto) -> str:
    """'Cód. Un. Neg.' -> 'cod_un_neg' — pra comparar nomes de coluna sem
    depender de acento/maiúscula/pontuação, que variam entre arquivos."""
    texto = str(texto).strip()
    texto = ''.join(
        c for c in unicodedata.normalize('NFKD', texto) if not unicodedata.combining(c)
    )
    texto = texto.lower()
    texto = re.sub(r'[^a-z0-9]+', '_', texto).strip('_')
    return texto


def _periodo_do_titulo(caminho, sheet_name=0) -> tuple[date | None, date | None]:
    bruto = pd.read_excel(caminho, sheet_name=sheet_name, header=None, nrows=1)
    titulo = str(bruto.iloc[0, 0])
    m = re.search(r'(\d{2}/\d{2}/\d{4}).*?a\s+(\d{2}/\d{2}/\d{4})', titulo)
    if not m:
        return None, None
    inicio = datetime.strptime(m.group(1), '%d/%m/%Y').date()
    fim = datetime.strptime(m.group(2), '%d/%m/%Y').date()
    return inicio, fim


def ler_relatorio_erp(caminho, sheet_name=0):
    """Lê um export "Análise de Venda por Item" do ERP.

    Devolve (df, periodo_inicio, periodo_fim) — df com colunas normalizadas
    (`normalizar`) e o período coberto pelo relatório, extraído do título
    da linha 0 (útil quando o arquivo não traz uma coluna de mês/data por
    linha, ex. `LEVE 3 PAGUE 2.xls`).
    """
    periodo_inicio, periodo_fim = _periodo_do_titulo(caminho, sheet_name)
    df = pd.read_excel(caminho, sheet_name=sheet_name, header=1)
    df.columns = [normalizar(c) for c in df.columns]
    df = df.dropna(how='all')
    return df, periodo_inicio, periodo_fim


def coluna(df, *candidatos) -> str | None:
    """Acha a 1ª coluna do df cujo nome normalizado bate com um dos
    candidatos (também normalizados antes de comparar)."""
    for candidato in candidatos:
        alvo = normalizar(candidato)
        if alvo in df.columns:
            return alvo
    return None


def ano_mes_de(d: date) -> str:
    return f'{d.year:04d}-{d.month:02d}'
