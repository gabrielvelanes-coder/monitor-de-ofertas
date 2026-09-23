from pathlib import Path

from django.core.management.base import BaseCommand

from apps.ofertas.erp import encontrar_arquivo
from apps.ofertas.importadores import importar_relatorio_fabricante
from apps.ofertas.models import Lancamento

# Confirmado com o Gabriel (22/09/26): as 3 são oferta de verdade -- a
# "Nacional" só tinha uma mecânica de PAGAMENTO/verba diferente por trás,
# não deixava de ser oferta. Ficam unificadas aqui (a tela de Botica separa
# por campanha automaticamente quando há mais de 1 tag, mesmo padrão já
# usado na Procter).
TAGS_BOTICA = ['OFERTA BOTICA NACIONAL', 'OFERTAS BOTICA', 'OFERTAS BOTICA KIT AG']


class Command(BaseCommand):
    help = (
        'Importa Ofertas Botica (baseline_botica_2026.xls): compara as tags '
        f'{TAGS_BOTICA} (oferta, unificadas) com todo o resto das vendas do '
        'fabricante, incluindo "Sem Desconto" (base) (docx, seção 5.3).'
    )

    def add_arguments(self, parser):
        parser.add_argument('--arquivo', default=None, help='Caminho do .xls.')

    def handle(self, *args, **options):
        caminho = Path(options['arquivo']) if options['arquivo'] else encontrar_arquivo(
            '*baseline*botica*.xls'
        )
        resultado = importar_relatorio_fabricante(
            caminho, Lancamento.BOTICA, TAGS_BOTICA, fabricante='Botica',
        )
        self.stdout.write(self.style.SUCCESS(
            f"Botica: {resultado['importados']} lançamentos importados "
            f"({resultado['apagados']} substituídos), fonte {caminho.name}."
        ))
        if resultado['lojas_sem_cadastro']:
            self.stdout.write(self.style.WARNING(
                f"Lojas sem cadastro (linhas ignoradas): {', '.join(sorted(resultado['lojas_sem_cadastro']))}."
            ))
