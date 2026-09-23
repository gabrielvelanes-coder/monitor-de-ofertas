# -*- coding: utf-8 -*-
"""
Backup do que nunca vai pro Git (é dado, não código -- ver .gitignore):
o banco `db.sqlite3` e os arquivos brutos de `dados/entrada/`.

Mesmo princípio já usado no monitor-precos (banco, via backup API do
SQLite -- seguro mesmo com o banco em uso, ao contrário de copiar o
arquivo cru) e no PERDAS (arquivos de dado, cópia direta). Aqui reúne
os dois porque esse projeto tem ambos.

Uso manual:
    python backup_tudo.py

Guarda em `OneDrive\\Área de Trabalho\\BACKUPS DB\\painel-ofertas\\`:
- `db_<carimbo>.sqlite3` -- mantém os 10 mais recentes.
- `dados_<carimbo>\\` (cópia de tudo em dados/entrada/) -- mantém as 5
  rodadas mais recentes.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

MANTER_BANCOS = 10
MANTER_RODADAS_DADOS = 5

PASTA_PROJETO = Path(__file__).resolve().parent
PASTA_BACKUPS = PASTA_PROJETO.parent.parent / "BACKUPS DB" / "painel-ofertas"
# O banco vive FORA da pasta do projeto desde 23/09/26 (OneDrive deixava
# toda consulta lenta, ver commit da mudança) -- mesmo caminho padrão e
# mesma variável de ambiente (PAINEL_DB_PATH) de `config/settings.py`.
CAMINHO_DB = Path(
    os.environ.get("PAINEL_DB_PATH")
    or r"C:\Users\E.C Velanes\painel-ofertas-dados\db.sqlite3"
)
PASTA_DADOS_ENTRADA = PASTA_PROJETO / "dados" / "entrada"


def _backup_banco():
    if not CAMINHO_DB.exists():
        print(f"[banco] não encontrei '{CAMINHO_DB}' -- pulando.")
        return

    PASTA_BACKUPS.mkdir(parents=True, exist_ok=True)
    carimbo = datetime.now().strftime("%Y-%m-%d_%Hh%M")
    destino = PASTA_BACKUPS / f"db_{carimbo}.sqlite3"

    origem_con = sqlite3.connect(f"file:{CAMINHO_DB}?mode=ro", uri=True)
    destino_con = sqlite3.connect(destino)
    try:
        origem_con.backup(destino_con)
    finally:
        destino_con.close()
        origem_con.close()

    tamanho_mb = destino.stat().st_size / (1024 * 1024)
    print(f"[banco] backup criado: {destino.name} ({tamanho_mb:.1f} MB)")

    existentes = sorted(PASTA_BACKUPS.glob("db_*.sqlite3"), key=lambda p: p.stat().st_mtime, reverse=True)
    for antigo in existentes[MANTER_BANCOS:]:
        antigo.unlink()
        print(f"[banco] removido backup antigo: {antigo.name}")


def _backup_dados_entrada():
    if not PASTA_DADOS_ENTRADA.exists():
        print(f"[dados] não encontrei '{PASTA_DADOS_ENTRADA}' -- pulando.")
        return
    arquivos = [p for p in PASTA_DADOS_ENTRADA.iterdir() if p.is_file() and p.name != ".gitkeep"]
    if not arquivos:
        print("[dados] pasta dados/entrada/ vazia -- nada pra copiar.")
        return

    carimbo = datetime.now().strftime("%Y-%m-%d_%Hh%M")
    destino_rodada = PASTA_BACKUPS / f"dados_{carimbo}"
    destino_rodada.mkdir(parents=True, exist_ok=True)

    total_mb = 0.0
    for origem in arquivos:
        destino = destino_rodada / origem.name
        shutil.copy2(origem, destino)
        total_mb += destino.stat().st_size / (1024 * 1024)
    print(f"[dados] backup criado: {destino_rodada.name} ({total_mb:.1f} MB, {len(arquivos)} arquivo(s))")

    rodadas = sorted(
        (p for p in PASTA_BACKUPS.glob("dados_*") if p.is_dir()),
        key=lambda p: p.stat().st_mtime, reverse=True,
    )
    for antiga in rodadas[MANTER_RODADAS_DADOS:]:
        shutil.rmtree(antiga)
        print(f"[dados] removida rodada antiga: {antiga.name}")


def main():
    print(f"Pasta de backup: {PASTA_BACKUPS}\n")
    _backup_banco()
    print()
    _backup_dados_entrada()
    return 0


if __name__ == "__main__":
    sys.exit(main())
