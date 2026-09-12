from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.lojas.models import Loja
from apps.ofertas.erp import (
    ano_mes_de, codigo_loja, coluna, ler_relatorio_erp, remover_linha_total,
)
from apps.ofertas.models import Lancamento


class Command(BaseCommand):
    help = (
        'Importa o sellout completo de um fabricante genérico (ex.: "ems gen '
        '2026 com data.xls") — TODAS as vendas do catálogo dele, qualquer '
        'tag, não só a oferta Leve 3 Pague 2. Aceita tanto relatório mensal '
        '(coluna "Ano-mês") quanto diário (coluna "Data", preferível — '
        'permite comparar a semana da promoção com o resto do mês). Serve '
        'de referência (giro "antes" e "durante" a promoção) pra medir o '
        'impacto do Leve 3 sobre o fabricante, na tela /leve3/. Pode rodar '
        'várias vezes com arquivos que cobrem períodos diferentes do mesmo '
        'fabricante (ex.: jan-abr num arquivo, mai-set noutro) — cada '
        'arquivo só substitui os meses que ele mesmo traz.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--arquivo', required=True, help='Caminho do .xls.')
        parser.add_argument(
            '--fabricante', required=True,
            help='Nome do fabricante (ex.: EMS, Eurofarma, Germed, Prati) — '
                 'precisa bater com o valor usado em Lancamento.fabricante do Leve 3.',
        )

    def handle(self, *args, **options):
        caminho = Path(options['arquivo'])
        fabricante = options['fabricante'].strip()
        if not caminho.exists():
            raise CommandError(f'Arquivo não encontrado: {caminho}')

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
                'loja': col_loja, 'produto': col_produto, 'itens': col_itens,
                'venda': col_venda, 'custo': col_custo, 'lucro': col_lucro,
            }.items() if col is None
        ]
        if faltando:
            raise CommandError(f'Colunas não encontradas no arquivo: {", ".join(faltando)}.')
        if not col_ano_mes and not col_data:
            raise CommandError('Arquivo sem coluna "Ano-mês" nem "Data" — não sei o mês das linhas.')

        df = remover_linha_total(df, col_loja)

        lojas = {loja.codigo: loja for loja in Loja.objects.all()}
        lancamentos = []
        lojas_sem_cadastro = set()
        meses_do_arquivo = set()

        for _, linha in df.iterrows():
            codigo = codigo_loja(linha[col_loja])
            loja = lojas.get(codigo)
            if loja is None:
                lojas_sem_cadastro.add(codigo)
                continue

            data = None
            if col_data and linha.get(col_data) is not None and str(linha[col_data]) != 'NaT':
                bruta = linha[col_data]
                data = bruta.date() if hasattr(bruta, 'date') else bruta
                ano_mes = ano_mes_de(data)
            else:
                ano_mes = str(linha[col_ano_mes]).strip()
            meses_do_arquivo.add(ano_mes)

            lancamentos.append(Lancamento(
                mecanica=Lancamento.SELLOUT,
                loja=loja,
                produto_descricao=str(linha[col_produto]).strip(),
                fabricante=fabricante,
                tag_origem=str(linha.get(col_tag, '') or '').strip() if col_tag else '',
                ano_mes=ano_mes,
                data=data,
                itens=linha[col_itens],
                venda=linha[col_venda],
                desconto=linha.get(col_desconto) or 0,
                custo=linha[col_custo],
                lucro=linha[col_lucro],
                arquivo_origem=caminho.name,
            ))

        with transaction.atomic():
            apagados, _ = Lancamento.objects.filter(
                mecanica=Lancamento.SELLOUT, fabricante=fabricante, ano_mes__in=meses_do_arquivo,
            ).delete()
            Lancamento.objects.bulk_create(lancamentos, batch_size=1000)

        self.stdout.write(self.style.SUCCESS(
            f'Sellout {fabricante}: {len(lancamentos)} lançamentos em '
            f'{len(meses_do_arquivo)} mês(es) ({", ".join(sorted(meses_do_arquivo))}) '
            f'— {apagados} substituídos, fonte {caminho.name}.'
        ))
        if lojas_sem_cadastro:
            self.stdout.write(self.style.WARNING(
                f'Lojas sem cadastro (linhas ignoradas): {", ".join(sorted(lojas_sem_cadastro))}.'
            ))
