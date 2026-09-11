from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.lojas.models import Loja
from apps.ofertas.erp import (
    codigo_loja, coluna, encontrar_arquivo, ler_relatorio_erp,
    remover_linha_total,
)
from apps.ofertas.models import Lancamento


class Command(BaseCommand):
    help = (
        'Importa a mecânica Cestões a partir do CESTOES_2026.xls. A tag '
        '"OFERTAS CESTAO" só existe no relatório a partir de jun/2026 — o '
        'comando primeiro acha os produtos marcados assim em qualquer mês '
        'e depois importa o histórico inteiro desses mesmos produtos desde '
        'o início do arquivo (docx, seção 5.4). A lista de produtos é '
        'recalculada a cada importação, não é fixa.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--arquivo', default=None, help='Caminho do .xls.')

    def handle(self, *args, **options):
        caminho = Path(options['arquivo']) if options['arquivo'] else encontrar_arquivo(
            '*cestoes*.xls'
        )
        df, _, _ = ler_relatorio_erp(caminho)

        col_ano_mes = coluna(df, 'Ano-mês')
        col_tag = coluna(df, 'Detalhe Desconto', 'Cad. Oferta')
        col_produto = coluna(df, 'Embalagem')
        col_loja = coluna(df, 'Cód. Un. Neg.')
        col_itens = coluna(df, 'Itens')
        col_venda = coluna(df, 'Venda')
        col_desconto = coluna(df, 'Desconto')
        col_custo = coluna(df, 'Custo')
        col_lucro = coluna(df, 'Lucro')
        faltando = [
            nome for nome, col in {
                'ano_mes': col_ano_mes, 'tag': col_tag, 'produto': col_produto,
                'loja': col_loja, 'itens': col_itens, 'venda': col_venda,
                'custo': col_custo, 'lucro': col_lucro,
            }.items() if col is None
        ]
        if faltando:
            raise CommandError(f'Colunas não encontradas no arquivo: {", ".join(faltando)}.')

        df = remover_linha_total(df, col_ano_mes)

        em_cestao = df[col_tag].astype(str).str.contains('CESTAO', case=False, na=False)
        produtos_cestao = set(df.loc[em_cestao, col_produto].dropna().unique())
        if not produtos_cestao:
            raise CommandError('Nenhum produto com tag "OFERTAS CESTAO" encontrado no arquivo.')

        historico = df[df[col_produto].isin(produtos_cestao)]

        lojas = {loja.codigo: loja for loja in Loja.objects.all()}
        lancamentos = []
        lojas_sem_cadastro = set()

        for _, linha in historico.iterrows():
            codigo = codigo_loja(linha[col_loja])
            loja = lojas.get(codigo)
            if loja is None:
                lojas_sem_cadastro.add(codigo)
                continue

            lancamentos.append(Lancamento(
                mecanica=Lancamento.CESTOES,
                loja=loja,
                produto_descricao=str(linha[col_produto]).strip(),
                tag_origem=str(linha.get(col_tag, '') or '').strip(),
                ano_mes=str(linha[col_ano_mes]).strip(),
                itens=linha[col_itens],
                venda=linha[col_venda],
                desconto=linha.get(col_desconto) or 0,
                custo=linha[col_custo],
                lucro=linha[col_lucro],
                arquivo_origem=caminho.name,
            ))

        with transaction.atomic():
            apagados, _ = Lancamento.objects.filter(mecanica=Lancamento.CESTOES).delete()
            Lancamento.objects.bulk_create(lancamentos, batch_size=1000)

        self.stdout.write(self.style.SUCCESS(
            f'Cestões: {len(produtos_cestao)} produtos, {len(lancamentos)} lançamentos '
            f'({apagados} substituídos), fonte {caminho.name}.'
        ))
        if lojas_sem_cadastro:
            self.stdout.write(self.style.WARNING(
                f'Lojas sem cadastro (linhas ignoradas): {", ".join(sorted(lojas_sem_cadastro))}.'
            ))
