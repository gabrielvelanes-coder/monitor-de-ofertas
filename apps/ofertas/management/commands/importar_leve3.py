from collections import defaultdict
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.lojas.models import Loja
from apps.ofertas.erp import (
    PASTA_ENTRADA, codigo_loja, coluna, fabricante_generico,
    ler_relatorio_erp, remover_linha_total,
)
from apps.ofertas.models import Lancamento


class Command(BaseCommand):
    help = (
        'Importa a mecânica Leve 3 Pague 2 (genéricos) a partir dos relatórios '
        '"genericos_<bimestre>_2026.xls" — a tag "OFERTA GENERICOS LEVE 3 PAGUE 2" '
        'só aparece de maio/2026 em diante nesses arquivos, já agregada por '
        'loja/produto/mês. Sem --arquivo, importa todos os "*genericos*.xls" '
        'achados em dados/entrada/ (um mês pode vir de um arquivo só).'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--arquivo', action='append', default=None,
            help='Caminho de um .xls. Repita a flag pra importar vários de uma vez.',
        )

    def handle(self, *args, **options):
        if options['arquivo']:
            caminhos = [Path(a) for a in options['arquivo']]
        else:
            caminhos = sorted(PASTA_ENTRADA.glob('*genericos*.xls'))
        if not caminhos:
            raise CommandError(
                'Nenhum arquivo "*genericos*.xls" em dados/entrada/. Copie os '
                'relatórios bimestrais pra lá ou passe --arquivo com o caminho.'
            )

        lojas = {loja.codigo: loja for loja in Loja.objects.all()}
        lojas_sem_cadastro = set()
        total_importados = 0
        meses_processados = {}

        for caminho in caminhos:
            df, _, _ = ler_relatorio_erp(caminho)

            col_loja = coluna(df, 'Cód. Un. Neg.')
            col_ano_mes = coluna(df, 'Ano-mês')
            col_tag = coluna(df, 'Detalhe Desconto', 'Cad. Oferta')
            col_produto = coluna(df, 'Embalagem')
            col_itens = coluna(df, 'Itens')
            col_venda = coluna(df, 'Venda')
            col_desconto = coluna(df, 'Desconto')
            col_custo = coluna(df, 'Custo')
            col_lucro = coluna(df, 'Lucro')
            faltando = [
                nome for nome, col in {
                    'loja': col_loja, 'ano_mes': col_ano_mes, 'tag': col_tag,
                    'produto': col_produto, 'itens': col_itens, 'venda': col_venda,
                    'custo': col_custo, 'lucro': col_lucro,
                }.items() if col is None
            ]
            if faltando:
                raise CommandError(
                    f'{caminho.name}: colunas não encontradas: {", ".join(faltando)}.'
                )

            df = remover_linha_total(df, col_ano_mes)
            subset = df[df[col_tag].astype(str).str.contains('LEVE 3', case=False, na=False)]

            por_mes = defaultdict(list)
            for _, linha in subset.iterrows():
                codigo = codigo_loja(linha[col_loja])
                loja = lojas.get(codigo)
                if loja is None:
                    lojas_sem_cadastro.add(codigo)
                    continue

                produto = str(linha[col_produto]).strip()
                ano_mes = str(linha[col_ano_mes]).strip()
                por_mes[ano_mes].append(Lancamento(
                    mecanica=Lancamento.LEVE3,
                    loja=loja,
                    produto_descricao=produto,
                    fabricante=fabricante_generico(produto),
                    ano_mes=ano_mes,
                    itens=linha[col_itens],
                    venda=linha[col_venda],
                    desconto=linha.get(col_desconto) or 0,
                    custo=linha[col_custo],
                    lucro=linha[col_lucro],
                    arquivo_origem=caminho.name,
                ))

            for ano_mes, lancamentos in por_mes.items():
                with transaction.atomic():
                    Lancamento.objects.filter(mecanica=Lancamento.LEVE3, ano_mes=ano_mes).delete()
                    Lancamento.objects.bulk_create(lancamentos, batch_size=1000)
                meses_processados[ano_mes] = meses_processados.get(ano_mes, 0) + len(lancamentos)
                total_importados += len(lancamentos)

        resumo_meses = ', '.join(f'{mes} ({n})' for mes, n in sorted(meses_processados.items()))
        self.stdout.write(self.style.SUCCESS(
            f'Leve 3 Pague 2: {total_importados} lançamentos em {len(meses_processados)} '
            f'mês(es) — {resumo_meses}. Fontes: {", ".join(c.name for c in caminhos)}.'
        ))
        if lojas_sem_cadastro:
            self.stdout.write(self.style.WARNING(
                f'Lojas sem cadastro (linhas ignoradas): {", ".join(sorted(lojas_sem_cadastro))}. '
                'Rode importar_lojas primeiro.'
            ))
