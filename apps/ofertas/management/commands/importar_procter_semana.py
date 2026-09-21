from pathlib import Path

from django.core.management.base import BaseCommand

from apps.ofertas.erp import encontrar_arquivo
from apps.ofertas.importadores import importar_relatorio_fabricante
from apps.ofertas.models import Lancamento


class Command(BaseCommand):
    help = (
        'Importa Procter Semana do Cliente (ação pontual, tag própria '
        '"OFERTAS PROCTER SEMANA DO CLIENTE" -- diferente de "PROMOÇÃO '
        'PROCTER", a promoção mensal) DENTRO da mesma tela/mecânica '
        'Procter, não uma ação separada -- as duas coexistem (Gabriel '
        'quer ver as 2 juntas, com investimento próprio de cada uma; ver '
        '"por campanha" na tela). escopo_delete="arquivo": reimportar só '
        'substitui as linhas desta campanha, não mexe na promoção normal.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--arquivo', default=None, help='Caminho do .xls.')

    def handle(self, *args, **options):
        caminho = Path(options['arquivo']) if options['arquivo'] else encontrar_arquivo(
            '*procter*semana*cliente*.xls'
        )
        resultado = importar_relatorio_fabricante(
            caminho, Lancamento.PROCTER, 'OFERTAS PROCTER SEMANA DO CLIENTE',
            fabricante='Procter & Gamble', escopo_delete='arquivo',
        )
        self.stdout.write(self.style.SUCCESS(
            f"Procter Semana do Cliente: {resultado['importados']} lançamentos importados "
            f"({resultado['apagados']} substituídos), fonte {caminho.name}."
        ))
        if resultado['lojas_sem_cadastro']:
            self.stdout.write(self.style.WARNING(
                f"Lojas sem cadastro (linhas ignoradas): {', '.join(sorted(resultado['lojas_sem_cadastro']))}."
            ))
