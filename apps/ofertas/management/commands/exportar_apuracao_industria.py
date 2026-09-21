from pathlib import Path

import pandas as pd
from django.core.management.base import BaseCommand, CommandError

from apps.ofertas.apuracao import montar_apuracao_industria


class Command(BaseCommand):
    help = (
        'Gera o arquivo de apuração pra enviar à indústria: base = vendas por item '
        'da campanha (linha a linha) + valor da rebaixa (R$/un.) + investimento '
        '(itens × rebaixa). Precisa da tabela de rebaixa já importada '
        '(importar_rebaixas) pra --mecanica/--campanha.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--mecanica', required=True, help='Ex.: procter')
        parser.add_argument('--campanha', required=True, help='Ex.: "OFERTAS PROCTER SEMANA DO CLIENTE"')
        parser.add_argument('--saida', default=None, help='Caminho do .xlsx de saída.')

    def handle(self, *args, **options):
        mecanica = options['mecanica']
        campanha = options['campanha']
        dados = montar_apuracao_industria(mecanica, campanha)

        if not dados['linhas']:
            raise CommandError(
                f'Nenhum lançamento encontrado pra [{mecanica}/{campanha}] -- '
                'confira o texto exato da campanha (bate com tag_origem sem "Cad. Oferta:").'
            )

        df = pd.DataFrame(dados['linhas'])
        df = df.rename(columns={
            'loja': 'Loja', 'bandeira': 'Bandeira', 'data': 'Data', 'ean': 'EAN',
            'produto': 'Produto', 'itens': 'Itens', 'venda': 'Venda',
            'desconto': 'Desconto', 'custo': 'Custo', 'lucro': 'Lucro',
            'valor_rebaixa_unitario': 'Valor da Rebaixa (R$/un.)',
            'investimento': 'Investimento (R$)',
        })

        saida = Path(options['saida']) if options['saida'] else Path(
            f'dados/saida/apuracao_{mecanica}_{campanha.lower().replace(" ", "_")}.xlsx'
        )
        saida.parent.mkdir(parents=True, exist_ok=True)
        df.to_excel(saida, index=False, sheet_name='Apuração')

        self.stdout.write(self.style.SUCCESS(
            f"Apuração [{mecanica}/{campanha}]: {len(dados['linhas'])} linhas, "
            f"investimento total R$ {dados['total_investimento']:.2f}, "
            f"salvo em {saida}."
        ))
        if dados['produtos_sem_rebaixa']:
            self.stdout.write(self.style.WARNING(
                f"{len(dados['produtos_sem_rebaixa'])} produto(s) sem rebaixa encontrada "
                f"(investimento R$0,00 nessas linhas): "
                f"{', '.join(dados['produtos_sem_rebaixa'])}."
            ))
