from pathlib import Path

import pandas as pd
from django.core.management.base import BaseCommand, CommandError

from apps.ofertas.erp import coluna, normalizar
from apps.produtos.models import RebaixaProduto


class Command(BaseCommand):
    help = (
        'Importa a tabela de rebaixa (EAN/Produto/Rebaixa) que o fabricante manda '
        '-- valor fixo em R$ por unidade vendida que ele reembolsa, usado no arquivo '
        'de apuração pra indústria. Precisa de --mecanica e --campanha (mesmo texto '
        'de Lancamento.mecanica / tag_origem sem o prefixo "Cad. Oferta:").'
    )

    def add_arguments(self, parser):
        parser.add_argument('--arquivo', required=True, help='Caminho do .xlsx.')
        parser.add_argument('--mecanica', required=True, help='Ex.: procter')
        parser.add_argument('--campanha', required=True, help='Ex.: "OFERTAS PROCTER SEMANA DO CLIENTE"')

    def handle(self, *args, **options):
        caminho = Path(options['arquivo'])
        mecanica = options['mecanica']
        campanha = options['campanha']

        df = pd.read_excel(caminho, sheet_name=0)
        df.columns = [normalizar(c) for c in df.columns]

        col_ean = coluna(df, 'Ean', 'EAN')
        col_produto = coluna(df, 'Produto')
        col_rebaixa = coluna(df, 'Rebaixa')
        faltando = [
            nome for nome, col in {'ean': col_ean, 'produto': col_produto, 'rebaixa': col_rebaixa}.items()
            if col is None
        ]
        if faltando:
            raise CommandError(f'{caminho.name}: colunas não encontradas: {", ".join(faltando)}.')

        rebaixas = []
        for _, linha in df.iterrows():
            if pd.isna(linha[col_ean]):
                continue
            try:
                ean = str(int(linha[col_ean]))
            except (TypeError, ValueError):
                ean = str(linha[col_ean]).strip()
            rebaixas.append(RebaixaProduto(
                mecanica=mecanica,
                campanha=campanha,
                ean=ean,
                produto_descricao=str(linha[col_produto]).strip(),
                valor_rebaixa=linha[col_rebaixa],
                arquivo_origem=caminho.name,
            ))

        RebaixaProduto.objects.filter(mecanica=mecanica, campanha=campanha).delete()
        RebaixaProduto.objects.bulk_create(rebaixas, batch_size=500)

        self.stdout.write(self.style.SUCCESS(
            f'Rebaixas: {len(rebaixas)} produtos importados pra [{mecanica}/{campanha}], '
            f'fonte {caminho.name}.'
        ))
