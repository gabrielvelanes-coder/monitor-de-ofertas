from pathlib import Path

import pandas as pd
from django.core.management.base import BaseCommand, CommandError

from apps.ofertas.apuracao import montar_apuracao_industria, montar_apuracao_leve3
from apps.ofertas.models import Lancamento


class Command(BaseCommand):
    help = (
        'Gera o arquivo de apuração pra enviar à indústria: base = vendas por item '
        '(linha a linha) + investimento que o fabricante deve pagar. Leve 3 Pague 2 '
        'usa fórmula própria (ciclos × custo, não precisa de --campanha nem de '
        'tabela de rebaixa). As outras (Kenvue/Principia/Botica/Procter) precisam '
        'da tabela de rebaixa já importada (importar_rebaixas) pra --mecanica/--campanha.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--mecanica', required=True, help='Ex.: procter, leve3')
        parser.add_argument(
            '--campanha', default=None,
            help='Ex.: "OFERTAS PROCTER SEMANA DO CLIENTE" -- não usado pro Leve3.',
        )
        parser.add_argument('--mes', default=None, help='"AAAA-MM" -- só pro Leve3, filtra 1 mês. Omitido = todos.')
        parser.add_argument('--saida', default=None, help='Caminho do .xlsx de saída.')

    def handle(self, *args, **options):
        mecanica = options['mecanica']
        campanha = options['campanha']

        if mecanica == Lancamento.LEVE3:
            dados = montar_apuracao_leve3(ano_mes=options['mes'])
            colunas = {
                'loja': 'Loja', 'bandeira': 'Bandeira', 'data': 'Data', 'ano_mes': 'Ano-mês',
                'produto': 'Produto', 'itens': 'Itens', 'venda': 'Venda', 'custo': 'Custo',
                'lucro': 'Lucro', 'ciclos': 'Ciclos', 'custo_unitario': 'Custo Unitário (R$)',
                'investimento': 'Investimento (R$)',
            }
            identificador = mecanica + (f'_{options["mes"]}' if options['mes'] else '')
        else:
            if not campanha:
                raise CommandError('--campanha é obrigatório pra essa mecânica (só o Leve3 dispensa).')
            dados = montar_apuracao_industria(mecanica, campanha)
            colunas = {
                'loja': 'Loja', 'bandeira': 'Bandeira', 'data': 'Data', 'ean': 'EAN',
                'produto': 'Produto', 'itens': 'Itens', 'venda': 'Venda',
                'desconto': 'Desconto', 'custo': 'Custo', 'lucro': 'Lucro',
                'valor_rebaixa_unitario': 'Valor da Rebaixa (R$/un.)',
                'investimento': 'Investimento (R$)',
            }
            identificador = f'{mecanica}_{campanha.lower().replace(" ", "_")}'

        if not dados['linhas']:
            raise CommandError(
                f'Nenhum lançamento encontrado pra [{mecanica}'
                f'{"/" + campanha if campanha else ""}] -- confira mecânica/campanha/mês.'
            )

        df = pd.DataFrame(dados['linhas'])
        # Arredonda só aqui, pra exibir -- `total_investimento` (mensagem
        # abaixo) já foi somado em precisão cheia antes disso, pra bater
        # com o painel (ver comentário em apuracao.py sobre a diferença de
        # 7 centavos achada com o Leve3).
        df['investimento'] = df['investimento'].astype(float).round(2)
        df = df.rename(columns=colunas)

        saida = Path(options['saida']) if options['saida'] else Path(f'dados/saida/apuracao_{identificador}.xlsx')
        saida.parent.mkdir(parents=True, exist_ok=True)
        df.to_excel(saida, index=False, sheet_name='Apuração')

        self.stdout.write(self.style.SUCCESS(
            f"Apuração [{mecanica}{'/' + campanha if campanha else ''}]: {len(dados['linhas'])} linhas, "
            f"investimento total R$ {dados['total_investimento']:.2f}, "
            f"salvo em {saida}."
        ))
        if dados.get('produtos_sem_rebaixa'):
            self.stdout.write(self.style.WARNING(
                f"{len(dados['produtos_sem_rebaixa'])} produto(s) sem rebaixa encontrada "
                f"(investimento R$0,00 nessas linhas): "
                f"{', '.join(dados['produtos_sem_rebaixa'])}."
            ))
