from pathlib import Path

from django.core.management.base import BaseCommand

from apps.lojas.models import Loja
from apps.ofertas.importadores import PADRAO_LOUCA_QUEIMAO, importar_promocao_bandeira
from apps.ofertas.models import Lancamento


class Command(BaseCommand):
    help = (
        'Importa a promoção "Deu a Louca" (só lojas Velanes) a partir de um '
        'relatório "Análise de Venda por Item" — ainda não tem um relatório '
        'dedicado do ERP. Reconhece tanto a tag "DEU A LOUCA <mês>" (a '
        'partir de set/2026) quanto a tag antiga "ULTRA QUEIMAO <mês>" '
        '(até ago/2026 as duas bandeiras usavam o mesmo cadastro). Aditivo '
        'por arquivo: repita o import conforme o mês avança, sem apagar o '
        'que já foi importado de outro arquivo.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--arquivo', required=True, help='Caminho do .xls.')

    def handle(self, *args, **options):
        caminho = Path(options['arquivo'])
        resultado = importar_promocao_bandeira(
            caminho, Lancamento.DEU_A_LOUCA, PADRAO_LOUCA_QUEIMAO, Loja.VELANES,
        )
        self.stdout.write(self.style.SUCCESS(
            f"Deu a Louca: {resultado['importados']} lançamentos importados "
            f"({resultado['apagados']} substituídos), fonte {caminho.name}."
        ))
        if resultado['lojas_sem_cadastro']:
            self.stdout.write(self.style.WARNING(
                f"Lojas sem cadastro (linhas ignoradas): "
                f"{', '.join(sorted(resultado['lojas_sem_cadastro']))}."
            ))
