from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.lojas.models import Loja
from apps.ofertas.erp import (
    ano_mes_de, codigo_barras, codigo_loja, coluna, encontrar_arquivo,
    ler_relatorio_erp, remover_linha_total,
)
from apps.ofertas.models import Lancamento


class Command(BaseCommand):
    help = (
        'Importa a mecânica Leve 3 Pague 2 (genéricos) a partir do '
        '"LEVE 3 PAGUE 2.xls". O arquivo já vem filtrado pelo ERP só com as '
        'vendas dessa oferta — cada linha é uma venda (cupom), no nível que '
        'a fórmula de ciclos precisa (docx, seção 5.1).'
    )

    def add_arguments(self, parser):
        parser.add_argument('--arquivo', default=None, help='Caminho do .xls.')
        parser.add_argument(
            '--ano-mes', default=None,
            help='AAAA-MM. Se omitido, usa o período do título do relatório.',
        )

    def handle(self, *args, **options):
        caminho = Path(options['arquivo']) if options['arquivo'] else encontrar_arquivo(
            '*leve*3*pague*2*.xls'
        )
        df, periodo_inicio, _ = ler_relatorio_erp(caminho)

        ano_mes = options['ano_mes'] or (ano_mes_de(periodo_inicio) if periodo_inicio else None)
        if not ano_mes:
            raise CommandError(
                'Não consegui achar o período no título do relatório — passe --ano-mes AAAA-MM.'
            )

        col_loja = coluna(df, 'Cód. Un. Neg.')
        col_barras = coluna(df, 'Cód. Barras/Etiq.')
        col_produto = coluna(df, 'Embalagem')
        col_itens = coluna(df, 'Itens')
        col_venda = coluna(df, 'Venda')
        col_desconto = coluna(df, 'Desconto')
        col_custo = coluna(df, 'Custo')
        col_lucro = coluna(df, 'Lucro')
        faltando = [
            nome for nome, col in {
                'loja': col_loja, 'produto': col_produto, 'itens': col_itens,
                'venda': col_venda, 'custo': col_custo, 'lucro': col_lucro,
            }.items() if col is None
        ]
        if faltando:
            raise CommandError(f'Colunas não encontradas no arquivo: {", ".join(faltando)}.')

        df = remover_linha_total(df, col_loja)

        lojas = {loja.codigo: loja for loja in Loja.objects.all()}
        lancamentos = []
        lojas_sem_cadastro = set()

        for _, linha in df.iterrows():
            codigo = codigo_loja(linha[col_loja])
            loja = lojas.get(codigo)
            if loja is None:
                lojas_sem_cadastro.add(codigo)
                continue

            lancamentos.append(Lancamento(
                mecanica=Lancamento.LEVE3,
                loja=loja,
                produto_descricao=str(linha.get(col_produto, '') or '').strip(),
                produto_codigo_barras=codigo_barras(linha.get(col_barras)),
                ano_mes=ano_mes,
                itens=linha[col_itens],
                venda=linha[col_venda],
                desconto=linha.get(col_desconto) or 0,
                custo=linha[col_custo],
                lucro=linha[col_lucro],
                arquivo_origem=caminho.name,
            ))

        with transaction.atomic():
            apagados, _ = Lancamento.objects.filter(
                mecanica=Lancamento.LEVE3, ano_mes=ano_mes
            ).delete()
            Lancamento.objects.bulk_create(lancamentos, batch_size=1000)

        self.stdout.write(self.style.SUCCESS(
            f'Leve 3 Pague 2 [{ano_mes}]: {len(lancamentos)} lançamentos importados '
            f'({apagados} substituídos), fonte {caminho.name}.'
        ))
        if lojas_sem_cadastro:
            self.stdout.write(self.style.WARNING(
                f'Lojas sem cadastro (linhas ignoradas): {", ".join(sorted(lojas_sem_cadastro))}. '
                'Rode importar_lojas primeiro.'
            ))
