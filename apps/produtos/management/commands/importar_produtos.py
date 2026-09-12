from pathlib import Path

import pandas as pd
from django.core.management.base import BaseCommand, CommandError

from apps.ofertas.erp import coluna, encontrar_arquivo, normalizar
from apps.produtos.models import Produto


class Command(BaseCommand):
    help = (
        'Importa o cadastro de produtos ("cadastro arvore nova com ean.xlsx" — '
        'Código de Barras/Produto/Fabricante) — fonte de verdade de produto -> '
        'fabricante usada por importar_leve3 no lugar da heurística '
        'fabricante_generico(). Idempotente: roda de novo pra atualizar o cadastro.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--arquivo', default=None,
            help='Caminho do .xlsx. Se omitido, procura em dados/entrada/.',
        )

    def handle(self, *args, **options):
        caminho = Path(options['arquivo']) if options['arquivo'] else encontrar_arquivo(
            '*cadastro*ean*.xlsx'
        )
        df = pd.read_excel(caminho, sheet_name=0)
        df.columns = [normalizar(c) for c in df.columns]

        col_produto = coluna(df, 'Produto')
        col_fabricante = coluna(df, 'Fabricante')
        col_barras = coluna(df, 'Código de Barras')
        faltando = [
            nome for nome, col in {'produto': col_produto, 'fabricante': col_fabricante}.items()
            if col is None
        ]
        if faltando:
            raise CommandError(f'{caminho.name}: colunas não encontradas: {", ".join(faltando)}.')

        # O cadastro repete a mesma descrição de produto com fabricantes
        # diferentes num punhado de casos (embalagem igual, fornecedor
        # diferente — achado ao investigar, ~9 em 44 mil produtos). Como o
        # cruzamento com Lancamento é pela descrição, fica a 1ª ocorrência;
        # não há como desambiguar sem código de barras nos relatórios de
        # venda do ERP. strip() antes do dedup — sem isso, "X" e "X " (só
        # espaço a mais) contam como produtos diferentes aqui mas colidem
        # depois no unique_fields do bulk_create de qualquer jeito.
        df[col_produto] = df[col_produto].astype(str).str.strip()
        df = df.drop_duplicates(subset=[col_produto], keep='first')

        produtos = []
        for _, linha in df.iterrows():
            descricao = str(linha[col_produto]).strip()
            if not descricao or descricao.lower() == 'nan':
                continue
            fabricante = str(linha[col_fabricante] or '').strip()
            codigo_barras = ''
            if col_barras is not None:
                bruto = linha[col_barras]
                if pd.notna(bruto):
                    try:
                        codigo_barras = str(int(bruto))
                    except (TypeError, ValueError):
                        codigo_barras = str(bruto).strip()
            produtos.append(Produto(
                descricao=descricao, fabricante=fabricante, codigo_barras=codigo_barras,
            ))

        Produto.objects.bulk_create(
            produtos, batch_size=1000,
            update_conflicts=True, unique_fields=['descricao'],
            update_fields=['fabricante', 'codigo_barras'],
        )

        self.stdout.write(self.style.SUCCESS(
            f'Cadastro de produtos: {len(produtos)} produtos (fonte: {caminho.name}). '
            'Rode "importar_leve3" de novo pra atualizar o fabricante dos lançamentos já importados.'
        ))
