from datetime import datetime
from decimal import Decimal
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
        'Importa Ofertas Kimberly. Diferente das outras mecânicas de '
        'fabricante, não existe tag "Cad. Oferta" limpa pra promoção '
        'Hipzinha nos relatórios — o recorte é manual (docx não cobre '
        'Kimberly; achado inspecionando os arquivos). Sem filtro, importa '
        'o portfólio inteiro só pra exploração (grupo em branco). Com '
        '--produto/--venda-max/--data-inicio/--data-fim, marca as linhas '
        'batidas como grupo=oferta (a promoção identificada manualmente) — '
        'confirme com o Gabriel antes de usar os números pra decisão.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--arquivo', default=None, help='Caminho do .xls.')
        parser.add_argument(
            '--produto', default=None,
            help='Filtro de texto (case-insensitive) na descrição do produto.',
        )
        parser.add_argument(
            '--venda-max', type=str, default=None,
            help='Só marca como oferta linhas com "Venda" <= esse valor.',
        )
        parser.add_argument('--data-inicio', default=None, help='AAAA-MM-DD.')
        parser.add_argument('--data-fim', default=None, help='AAAA-MM-DD.')

    def handle(self, *args, **options):
        caminho = Path(options['arquivo']) if options['arquivo'] else encontrar_arquivo(
            '*kimberly*.xls'
        )
        df, _, _ = ler_relatorio_erp(caminho)

        col_loja = coluna(df, 'Cód. Un. Neg.')
        col_produto = coluna(df, 'Embalagem')
        col_tag = coluna(df, 'Detalhe Desconto', 'Cad. Oferta')
        col_ano_mes = coluna(df, 'Ano-mês')
        col_data = coluna(df, 'Data')
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
        if not col_ano_mes and not col_data:
            raise CommandError('Arquivo sem coluna "Ano-mês" nem "Data" — não sei o mês das linhas.')

        col_referencia = col_ano_mes or col_loja
        df = remover_linha_total(df, col_referencia)

        produto_filtro = (options['produto'] or '').strip().lower()
        venda_max = Decimal(options['venda_max']) if options['venda_max'] else None
        data_inicio = (
            datetime.strptime(options['data_inicio'], '%Y-%m-%d').date()
            if options['data_inicio'] else None
        )
        data_fim = (
            datetime.strptime(options['data_fim'], '%Y-%m-%d').date()
            if options['data_fim'] else None
        )
        algum_filtro = any([produto_filtro, venda_max is not None, data_inicio, data_fim])

        lojas = {loja.codigo: loja for loja in Loja.objects.all()}
        lancamentos = []
        lojas_sem_cadastro = set()
        marcadas_oferta = 0

        for _, linha in df.iterrows():
            codigo = codigo_loja(linha[col_loja])
            loja = lojas.get(codigo)
            if loja is None:
                lojas_sem_cadastro.add(codigo)
                continue

            produto = str(linha[col_produto]).strip()
            venda = Decimal(str(linha[col_venda]))

            if col_data and linha.get(col_data) is not None:
                data = linha[col_data]
                data = data.date() if hasattr(data, 'date') else data
                ano_mes = ano_mes_de(data)
            else:
                data = None
                ano_mes = str(linha[col_ano_mes]).strip()

            grupo = ''
            if algum_filtro:
                bate = True
                if produto_filtro and produto_filtro not in produto.lower():
                    bate = False
                if venda_max is not None and venda > venda_max:
                    bate = False
                if data_inicio and (data is None or data < data_inicio):
                    bate = False
                if data_fim and (data is None or data > data_fim):
                    bate = False
                if bate:
                    grupo = Lancamento.GRUPO_OFERTA
                    marcadas_oferta += 1

            lancamentos.append(Lancamento(
                mecanica=Lancamento.KIMBERLY,
                loja=loja,
                produto_descricao=produto,
                tag_origem=str(linha.get(col_tag, '') or '').strip(),
                grupo=grupo,
                ano_mes=ano_mes,
                data=data,
                itens=linha[col_itens],
                venda=venda,
                desconto=linha.get(col_desconto) or 0,
                custo=linha[col_custo],
                lucro=linha[col_lucro],
                arquivo_origem=caminho.name,
            ))

        with transaction.atomic():
            apagados, _ = Lancamento.objects.filter(
                mecanica=Lancamento.KIMBERLY, arquivo_origem=caminho.name
            ).delete()
            Lancamento.objects.bulk_create(lancamentos, batch_size=1000)

        self.stdout.write(self.style.SUCCESS(
            f'Kimberly: {len(lancamentos)} lançamentos importados '
            f'({apagados} substituídos), fonte {caminho.name}.'
        ))
        if algum_filtro:
            self.stdout.write(
                f'{marcadas_oferta} linhas marcadas como oferta pelo filtro manual '
                '(confirme com o Gabriel antes de usar pra decisão).'
            )
        else:
            self.stdout.write(
                'Nenhum filtro passado — importado só o portfólio geral, pra exploração. '
                'Use --produto/--venda-max/--data-inicio/--data-fim pra marcar a promoção.'
            )
        if lojas_sem_cadastro:
            self.stdout.write(self.style.WARNING(
                f'Lojas sem cadastro (linhas ignoradas): {", ".join(sorted(lojas_sem_cadastro))}.'
            ))
