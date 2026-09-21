from pathlib import Path

from django.core.management.base import BaseCommand

from apps.ofertas.erp import encontrar_arquivo
from apps.ofertas.importadores import importar_relatorio_fabricante
from apps.ofertas.models import Lancamento


class Command(BaseCommand):
    help = (
        'Importa Procter Semana do Cliente (ação pontual, tag própria — '
        'diferente da promoção mensal "PROMOÇÃO PROCTER"): compara a tag '
        '"OFERTAS PROCTER SEMANA DO CLIENTE" (oferta) com todo o resto das '
        'vendas Procter (base).'
    )

    def add_arguments(self, parser):
        parser.add_argument('--arquivo', default=None, help='Caminho do .xls.')

    def handle(self, *args, **options):
        caminho = Path(options['arquivo']) if options['arquivo'] else encontrar_arquivo(
            '*procter*semana*cliente*.xls'
        )
        resultado = importar_relatorio_fabricante(
            caminho, Lancamento.PROCTER_SEMANA, 'OFERTAS PROCTER SEMANA DO CLIENTE',
            fabricante='Procter & Gamble',
        )
        self.stdout.write(self.style.SUCCESS(
            f"Procter Semana do Cliente: {resultado['importados']} lançamentos importados "
            f"({resultado['apagados']} substituídos), fonte {caminho.name}."
        ))
        if resultado['lojas_sem_cadastro']:
            self.stdout.write(self.style.WARNING(
                f"Lojas sem cadastro (linhas ignoradas): {', '.join(sorted(resultado['lojas_sem_cadastro']))}."
            ))
