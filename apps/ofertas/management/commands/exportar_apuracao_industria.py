from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.ofertas.apuracao import gerar_dataframe_apuracao
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

        if mecanica != Lancamento.LEVE3 and not campanha:
            raise CommandError('--campanha é obrigatório pra essa mecânica (só o Leve3 dispensa).')

        df, dados = gerar_dataframe_apuracao(mecanica, campanha=campanha, ano_mes=options['mes'])

        if df.empty:
            raise CommandError(
                f'Nenhum lançamento encontrado pra [{mecanica}'
                f'{"/" + campanha if campanha else ""}] -- confira mecânica/campanha/mês.'
            )

        identificador = (
            f'{mecanica}{"_" + options["mes"] if options["mes"] else ""}' if mecanica == Lancamento.LEVE3
            else f'{mecanica}_{campanha.lower().replace(" ", "_")}'
        )
        saida = Path(options['saida']) if options['saida'] else Path(f'dados/saida/apuracao_{identificador}.xlsx')
        saida.parent.mkdir(parents=True, exist_ok=True)
        df.to_excel(saida, index=False, sheet_name='Apuração')

        self.stdout.write(self.style.SUCCESS(
            f"Apuração [{mecanica}{'/' + campanha if campanha else ''}]: {len(df)} linhas, "
            f"investimento total R$ {dados['total_investimento']:.2f}, "
            f"salvo em {saida}."
        ))
        if dados.get('produtos_sem_rebaixa'):
            self.stdout.write(self.style.WARNING(
                f"{len(dados['produtos_sem_rebaixa'])} produto(s) sem rebaixa encontrada "
                f"(investimento R$0,00 nessas linhas): "
                f"{', '.join(dados['produtos_sem_rebaixa'])}."
            ))
