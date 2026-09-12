from pathlib import Path

from django.core.management.base import BaseCommand

from apps.ofertas.erp import encontrar_arquivo
from apps.ofertas.importadores import importar_relatorio_fabricante
from apps.ofertas.models import Lancamento


class Command(BaseCommand):
    help = (
        'Importa Ofertas Botica (baseline_botica_2026.xls): compara a tag '
        '"OFERTA BOTICA NACIONAL" (oferta) — não "OFERTAS BOTICA" nem '
        '"OFERTAS BOTICA KIT AG" — com todo o resto das vendas do '
        'fabricante, incluindo "Sem Desconto" (base) (docx, seção 5.3).'
    )

    def add_arguments(self, parser):
        parser.add_argument('--arquivo', default=None, help='Caminho do .xls.')

    def handle(self, *args, **options):
        caminho = Path(options['arquivo']) if options['arquivo'] else encontrar_arquivo(
            '*baseline*botica*.xls'
        )
        resultado = importar_relatorio_fabricante(
            caminho, Lancamento.BOTICA, 'OFERTA BOTICA NACIONAL', fabricante='Botica Nacional',
        )
        self.stdout.write(self.style.SUCCESS(
            f"Botica: {resultado['importados']} lançamentos importados "
            f"({resultado['apagados']} substituídos), fonte {caminho.name}."
        ))
        if resultado['lojas_sem_cadastro']:
            self.stdout.write(self.style.WARNING(
                f"Lojas sem cadastro (linhas ignoradas): {', '.join(sorted(resultado['lojas_sem_cadastro']))}."
            ))
