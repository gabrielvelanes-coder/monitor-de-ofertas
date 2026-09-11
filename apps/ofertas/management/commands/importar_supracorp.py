from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.lojas.models import Loja
from apps.ofertas.erp import (
    ano_mes_de, codigo_loja, coluna, encontrar_arquivo, ler_relatorio_erp,
    remover_linha_total,
)
from apps.ofertas.models import Lancamento


class Command(BaseCommand):
    help = (
        'Importa a Degustação Supra Corp Day a partir do supracorp day.xls '
        '(relatório diário, jun/whey e creatina).'
    )

    def add_arguments(self, parser):
        parser.add_argument('--arquivo', default=None, help='Caminho do .xls.')

    def handle(self, *args, **options):
        caminho = Path(options['arquivo']) if options['arquivo'] else encontrar_arquivo(
            '*supracorp*.xls'
        )
        df, _, _ = ler_relatorio_erp(caminho)

        col_loja = coluna(df, 'Cód. Un. Neg.')
        col_data = coluna(df, 'Data')
        col_produto = coluna(df, 'Embalagem')
        col_itens = coluna(df, 'Itens')
        col_venda = coluna(df, 'Venda')
        col_desconto = coluna(df, 'Desconto')
        col_custo = coluna(df, 'Custo')
        col_lucro = coluna(df, 'Lucro')
        faltando = [
            nome for nome, col in {
                'loja': col_loja, 'data': col_data, 'produto': col_produto,
                'itens': col_itens, 'venda': col_venda, 'custo': col_custo,
                'lucro': col_lucro,
            }.items() if col is None
        ]
        if faltando:
            raise CommandError(f'Colunas não encontradas no arquivo: {", ".join(faltando)}.')

        df = remover_linha_total(df, col_loja)
        df = df[df[col_produto].notna()]

        lojas = {loja.codigo: loja for loja in Loja.objects.all()}
        lancamentos = []
        lojas_sem_cadastro = set()

        for _, linha in df.iterrows():
            codigo = codigo_loja(linha[col_loja])
            loja = lojas.get(codigo)
            if loja is None:
                lojas_sem_cadastro.add(codigo)
                continue

            data = linha[col_data].date() if hasattr(linha[col_data], 'date') else linha[col_data]

            lancamentos.append(Lancamento(
                mecanica=Lancamento.SUPRACORP,
                loja=loja,
                produto_descricao=str(linha[col_produto]).strip(),
                ano_mes=ano_mes_de(data),
                data=data,
                itens=linha[col_itens],
                venda=linha[col_venda],
                desconto=linha.get(col_desconto) or 0,
                custo=linha[col_custo],
                lucro=linha[col_lucro],
                arquivo_origem=caminho.name,
            ))

        with transaction.atomic():
            apagados, _ = Lancamento.objects.filter(mecanica=Lancamento.SUPRACORP).delete()
            Lancamento.objects.bulk_create(lancamentos, batch_size=1000)

        self.stdout.write(self.style.SUCCESS(
            f'Supra Corp Day: {len(lancamentos)} lançamentos importados '
            f'({apagados} substituídos), fonte {caminho.name}.'
        ))
        if lojas_sem_cadastro:
            self.stdout.write(self.style.WARNING(
                f'Lojas sem cadastro (linhas ignoradas): {", ".join(sorted(lojas_sem_cadastro))}.'
            ))
