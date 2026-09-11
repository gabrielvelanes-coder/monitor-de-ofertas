import re
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.lojas.models import Loja
from apps.ofertas.erp import (
    ano_mes_de, codigo_loja, coluna, encontrar_arquivo, ler_relatorio_erp,
    remover_linha_total, tag_sem_prefixo,
)
from apps.ofertas.models import Lancamento

PADRAO_TAG = re.compile(r'^produtos\s+marketing\b', re.IGNORECASE)


class Command(BaseCommand):
    help = (
        'Importa "Itens do Marketing": linhas com a tag "PRODUTOS MARKETING '
        '<mês>" (visto em ofertas agosto.xls e em outros relatórios — docx, '
        'seção 10). Diferente dos outros importadores, este é aditivo por '
        'arquivo (não apaga o que veio de outro arquivo), porque a tag '
        'aparece espalhada em relatórios diferentes.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--arquivo', default=None, help='Caminho do .xls.')
        parser.add_argument(
            '--ano-mes', default=None,
            help='AAAA-MM. Só necessário se o arquivo não tiver coluna de mês/data.',
        )

    def handle(self, *args, **options):
        caminho = Path(options['arquivo']) if options['arquivo'] else encontrar_arquivo(
            '*ofertas*.xls'
        )
        df, periodo_inicio, _ = ler_relatorio_erp(caminho)

        col_loja = coluna(df, 'Cód. Un. Neg.')
        col_tag = coluna(df, 'Detalhe Desconto', 'Cad. Oferta')
        col_produto = coluna(df, 'Embalagem')
        col_fabricante = coluna(df, 'Fabricante')
        col_ano_mes = coluna(df, 'Ano-mês')
        col_data = coluna(df, 'Data')
        col_itens = coluna(df, 'Itens')
        col_venda = coluna(df, 'Venda')
        col_desconto = coluna(df, 'Desconto')
        col_custo = coluna(df, 'Custo')
        col_lucro = coluna(df, 'Lucro')
        faltando = [
            nome for nome, col in {
                'loja': col_loja, 'tag': col_tag, 'produto': col_produto,
                'itens': col_itens, 'venda': col_venda, 'custo': col_custo,
                'lucro': col_lucro,
            }.items() if col is None
        ]
        if faltando:
            raise CommandError(f'Colunas não encontradas no arquivo: {", ".join(faltando)}.')

        col_referencia = col_ano_mes or col_loja
        df = remover_linha_total(df, col_referencia)

        ano_mes_padrao = options['ano_mes'] or (ano_mes_de(periodo_inicio) if periodo_inicio else None)

        lojas = {loja.codigo: loja for loja in Loja.objects.all()}
        lancamentos = []
        lojas_sem_cadastro = set()

        for _, linha in df.iterrows():
            tag_bruta = str(linha.get(col_tag, '') or '').strip()
            if not PADRAO_TAG.match(tag_sem_prefixo(tag_bruta)):
                continue

            codigo = codigo_loja(linha[col_loja])
            loja = lojas.get(codigo)
            if loja is None:
                lojas_sem_cadastro.add(codigo)
                continue

            if col_ano_mes:
                ano_mes = str(linha[col_ano_mes]).strip()
            elif col_data and linha.get(col_data) is not None:
                data = linha[col_data]
                data = data.date() if hasattr(data, 'date') else data
                ano_mes = ano_mes_de(data)
            else:
                ano_mes = ano_mes_padrao

            if not ano_mes:
                raise CommandError(
                    'Não consegui determinar o mês desta linha — passe --ano-mes AAAA-MM.'
                )

            lancamentos.append(Lancamento(
                mecanica=Lancamento.MARKETING,
                loja=loja,
                produto_descricao=str(linha[col_produto]).strip(),
                fabricante=str(linha.get(col_fabricante, '') or '').strip() if col_fabricante else '',
                tag_origem=tag_bruta,
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
                mecanica=Lancamento.MARKETING, arquivo_origem=caminho.name
            ).delete()
            Lancamento.objects.bulk_create(lancamentos, batch_size=1000)

        self.stdout.write(self.style.SUCCESS(
            f'Itens do Marketing: {len(lancamentos)} lançamentos importados '
            f'({apagados} substituídos), fonte {caminho.name}.'
        ))
        if lojas_sem_cadastro:
            self.stdout.write(self.style.WARNING(
                f'Lojas sem cadastro (linhas ignoradas): {", ".join(sorted(lojas_sem_cadastro))}.'
            ))
