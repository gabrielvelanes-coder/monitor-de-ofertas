from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.ofertas.apuracao import (
    fabricantes_leve3, gerar_dataframe_apuracao, nome_arquivo_apuracao,
)
from apps.ofertas.models import Lancamento


class Command(BaseCommand):
    help = (
        'Gera o arquivo de apuração pra enviar à indústria: base = vendas por item '
        '(linha a linha) + investimento que o fabricante deve pagar. Leve 3 Pague 2 '
        'usa fórmula própria (ciclos × custo, não precisa de --campanha nem de '
        'tabela de rebaixa) e sai 1 arquivo POR FABRICANTE (--fabricante EMS, ou '
        '--todos-fabricantes pra gerar todos de uma vez). As outras (Kenvue/'
        'Principia/Botica/Procter) precisam da tabela de rebaixa já importada '
        '(importar_rebaixas) pra --mecanica/--campanha.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--mecanica', required=True, help='Ex.: procter, leve3')
        parser.add_argument(
            '--campanha', default=None,
            help='Ex.: "OFERTAS PROCTER SEMANA DO CLIENTE" -- não usado pro Leve3.',
        )
        parser.add_argument('--mes', default=None, help='"AAAA-MM". Omitido = todos os meses.')
        parser.add_argument('--fabricante', default=None, help='Só pro Leve3, ex.: EMS.')
        parser.add_argument(
            '--todos-fabricantes', action='store_true',
            help='Só pro Leve3 -- gera 1 arquivo pra cada fabricante com lançamento no mês (ou em todos os meses).',
        )
        parser.add_argument('--saida-dir', default='dados/saida', help='Pasta de saída (default: dados/saida).')

    def handle(self, *args, **options):
        mecanica = options['mecanica']
        campanha = options['campanha']
        mes = options['mes']
        saida_dir = Path(options['saida_dir'])

        if mecanica != Lancamento.LEVE3 and not campanha:
            raise CommandError('--campanha é obrigatório pra essa mecânica (só o Leve3 dispensa).')

        if mecanica == Lancamento.LEVE3 and options['todos_fabricantes']:
            fabricantes = fabricantes_leve3(ano_mes=mes)
            if not fabricantes:
                raise CommandError(f'Nenhum fabricante com lançamento{" em " + mes if mes else ""}.')
            for fabricante in fabricantes:
                self._gerar_1_arquivo(mecanica, saida_dir, campanha=None, ano_mes=mes, fabricante=fabricante)
            return

        self._gerar_1_arquivo(mecanica, saida_dir, campanha=campanha, ano_mes=mes, fabricante=options['fabricante'])

    def _gerar_1_arquivo(self, mecanica, saida_dir, *, campanha, ano_mes, fabricante):
        df, dados = gerar_dataframe_apuracao(mecanica, campanha=campanha, ano_mes=ano_mes, fabricante=fabricante)

        if df.empty:
            rotulo = fabricante or campanha or mecanica
            self.stdout.write(self.style.WARNING(f'Nenhum lançamento pra [{rotulo}{" em " + ano_mes if ano_mes else ""}] -- pulando.'))
            return

        nome_oferta = fabricante if mecanica == Lancamento.LEVE3 else campanha
        saida_dir.mkdir(parents=True, exist_ok=True)
        saida = saida_dir / nome_arquivo_apuracao(nome_oferta, ano_mes)
        df.to_excel(saida, index=False, sheet_name='Apuração')

        self.stdout.write(self.style.SUCCESS(
            f"Apuração [{nome_oferta}{' - ' + ano_mes if ano_mes else ''}]: {len(df)} linhas, "
            f"investimento total R$ {dados['total_investimento']:.2f}, salvo em {saida}."
        ))
        if dados.get('produtos_sem_rebaixa'):
            self.stdout.write(self.style.WARNING(
                f"{len(dados['produtos_sem_rebaixa'])} produto(s) sem rebaixa encontrada "
                f"(investimento R$0,00 nessas linhas): "
                f"{', '.join(dados['produtos_sem_rebaixa'])}."
            ))
