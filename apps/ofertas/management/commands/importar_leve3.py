from collections import defaultdict
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.lojas.models import Loja
from apps.ofertas.erp import (
    PASTA_ENTRADA, ano_mes_de, codigo_loja, coluna, fabricante_generico,
    ler_relatorio_erp, remover_linha_total,
)
from apps.ofertas.models import Lancamento
from apps.produtos.services import mapa_fabricantes
from apps.verba.services import sincronizar_verba_leve3


class Command(BaseCommand):
    help = (
        'Importa a mecânica Leve 3 Pague 2 (genéricos) a partir dos relatórios '
        '"genericos_<bimestre>_2026.xls" (agregado por loja/produto/mês, tag '
        '"OFERTA GENERICOS LEVE 3 PAGUE 2" a partir de maio/2026) ou, quando o '
        'bimestral do mês corrente ainda não saiu, de um "Análise de Venda por '
        'Item" bruto (--arquivo, com coluna "Data" em vez de "Ano-mês") — útil '
        'pra atualizações parciais por bandeira no meio do mês. Sem --arquivo, '
        'importa todos os "*genericos*.xls" achados em dados/entrada/.'
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
        mapa_fab = mapa_fabricantes()
        produtos_sem_cadastro = set()
        lojas_sem_cadastro = set()
        total_importados = 0
        meses_processados = {}

        for caminho in caminhos:
            df, _, _ = ler_relatorio_erp(caminho)

            col_loja = coluna(df, 'Cód. Un. Neg.')
            col_ano_mes = coluna(df, 'Ano-mês')
            col_data = coluna(df, 'Data')
            col_tag = coluna(df, 'Detalhe Desconto', 'Cad. Oferta')
            col_produto = coluna(df, 'Embalagem')
            col_itens = coluna(df, 'Itens')
            col_venda = coluna(df, 'Venda')
            col_desconto = coluna(df, 'Desconto')
            col_custo = coluna(df, 'Custo')
            col_lucro = coluna(df, 'Lucro')
            faltando = [
                nome for nome, col in {
                    'loja': col_loja, 'tag': col_tag,
                    'produto': col_produto, 'itens': col_itens, 'venda': col_venda,
                    'custo': col_custo, 'lucro': col_lucro,
                }.items() if col is None
            ]
            if faltando:
                raise CommandError(
                    f'{caminho.name}: colunas não encontradas: {", ".join(faltando)}.'
                )
            if col_ano_mes is None and col_data is None:
                raise CommandError(
                    f'{caminho.name}: precisa de coluna "Ano-mês" (relatório bimestral '
                    'agregado) ou "Data" (relatório "Análise de Venda por Item" bruto, '
                    'usado quando o bimestral ainda não saiu).'
                )

            df = remover_linha_total(df, col_ano_mes or col_loja)
            subset = df[df[col_tag].astype(str).str.contains('LEVE 3', case=False, na=False)]

            por_mes = defaultdict(list)
            for _, linha in subset.iterrows():
                codigo = codigo_loja(linha[col_loja])
                loja = lojas.get(codigo)
                if loja is None:
                    lojas_sem_cadastro.add(codigo)
                    continue

                produto = str(linha[col_produto]).strip()
                if col_ano_mes:
                    ano_mes = str(linha[col_ano_mes]).strip()
                    data_linha = None
                else:
                    data_linha = linha[col_data]
                    data_linha = data_linha.date() if hasattr(data_linha, 'date') else data_linha
                    ano_mes = ano_mes_de(data_linha)
                fabricante = mapa_fab.get(produto)
                if fabricante is None:
                    # Cadastro (apps.produtos) não tem o produto — cai pra
                    # heurística antiga como rede de segurança, não trava
                    # o import. Hoje (12/09/26) isso não acontece nenhuma
                    # vez pro Leve3: os 150 produtos distintos bateram
                    # 100% com o cadastro que o Gabriel mandou.
                    fabricante = fabricante_generico(produto)
                    produtos_sem_cadastro.add(produto)
                por_mes[ano_mes].append(Lancamento(
                    mecanica=Lancamento.LEVE3,
                    loja=loja,
                    produto_descricao=produto,
                    fabricante=fabricante,
                    ano_mes=ano_mes,
                    data=data_linha,
                    itens=linha[col_itens],
                    venda=linha[col_venda],
                    desconto=linha.get(col_desconto) or 0,
                    custo=linha[col_custo],
                    lucro=linha[col_lucro],
                    arquivo_origem=caminho.name,
                ))

            for ano_mes, lancamentos in por_mes.items():
                # Apaga só as lojas que este arquivo traz pro mês (não o mês
                # inteiro): um relatório bruto parcial pode cobrir só uma
                # bandeira (ex. update de setembro só da Ultra Popular,
                # enquanto a semana da Velanes ainda não aconteceu), e não
                # pode apagar lançamentos de outras lojas já importados.
                lojas_do_arquivo = {l.loja_id for l in lancamentos}
                with transaction.atomic():
                    Lancamento.objects.filter(
                        mecanica=Lancamento.LEVE3, ano_mes=ano_mes,
                        loja_id__in=lojas_do_arquivo,
                    ).delete()
                    Lancamento.objects.bulk_create(lancamentos, batch_size=1000)
                meses_processados[ano_mes] = meses_processados.get(ano_mes, 0) + len(lancamentos)
                total_importados += len(lancamentos)

        resumo_meses = ', '.join(f'{mes} ({n})' for mes, n in sorted(meses_processados.items()))
        self.stdout.write(self.style.SUCCESS(
            f'Leve 3 Pague 2: {total_importados} lançamentos em {len(meses_processados)} '
            f'mês(es) — {resumo_meses}. Fontes: {", ".join(c.name for c in caminhos)}.'
        ))

        verbas = sincronizar_verba_leve3()
        self.stdout.write(self.style.SUCCESS(
            f'Verba: valor_apurado atualizado em {len(verbas)} mês(es) (VerbaMensal, mecânica leve3).'
        ))
        if lojas_sem_cadastro:
            self.stdout.write(self.style.WARNING(
                f'Lojas sem cadastro (linhas ignoradas): {", ".join(sorted(lojas_sem_cadastro))}. '
                'Rode importar_lojas primeiro.'
            ))
        if produtos_sem_cadastro:
            self.stdout.write(self.style.WARNING(
                f'{len(produtos_sem_cadastro)} produto(s) fora do cadastro (apps.produtos) — '
                'fabricante caiu na heurística antiga, pode aparecer "Não identificado". '
                'Rode importar_produtos com um cadastro mais recente pra corrigir.'
            ))
