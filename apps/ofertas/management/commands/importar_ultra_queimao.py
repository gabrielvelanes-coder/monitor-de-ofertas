from pathlib import Path

from django.core.management.base import BaseCommand

from apps.lojas.models import Loja
from apps.ofertas.importadores import PADRAO_LOUCA_QUEIMAO, importar_promocao_bandeira
from apps.ofertas.models import Lancamento


class Command(BaseCommand):
    help = (
        'Importa a promoção "Ultra Queimão" (só lojas Ultra Popular) a '
        'partir de um relatório "Análise de Venda por Item" — ainda não tem '
        'um relatório dedicado do ERP. Reconhece a tag "ULTRA QUEIMAO '
        '<mês>" (nome de cadastro fixo, não muda com o mês real) e também '
        '"DEU A LOUCA <mês>" caso apareça linha cruzada. Aditivo por '
        'arquivo: repita o import conforme o mês avança, sem apagar o que '
        'já foi importado de outro arquivo.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--arquivo', required=True, help='Caminho do .xls.')

    def handle(self, *args, **options):
        caminho = Path(options['arquivo'])
        resultado = importar_promocao_bandeira(
            caminho, Lancamento.ULTRA_QUEIMAO, PADRAO_LOUCA_QUEIMAO, Loja.ULTRA_POPULAR,
        )
        self.stdout.write(self.style.SUCCESS(
            f"Ultra Queimão: {resultado['importados']} lançamentos importados "
            f"({resultado['apagados']} substituídos), fonte {caminho.name}."
        ))
        if resultado['lojas_sem_cadastro']:
            self.stdout.write(self.style.WARNING(
                f"Lojas sem cadastro (linhas ignoradas): "
                f"{', '.join(sorted(resultado['lojas_sem_cadastro']))}."
            ))
