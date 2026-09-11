from pathlib import Path

import pandas as pd
from django.core.management.base import BaseCommand

from apps.lojas.models import Loja
from apps.ofertas.erp import encontrar_arquivo, normalizar


class Command(BaseCommand):
    help = (
        'Importa o cadastro de lojas (DADOS GRUPO VELANES ATUALIZADO.xlsx) e '
        'classifica a bandeira (Velanes / Ultra Popular) pela heurística de '
        'e-mail/razão social documentada no Painel de Ofertas.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--arquivo', default=None,
            help='Caminho do .xlsx. Se omitido, procura em dados/entrada/.',
        )

    def handle(self, *args, **options):
        caminho = Path(options['arquivo']) if options['arquivo'] else encontrar_arquivo(
            '*dados*grupo*velanes*'
        )
        df = pd.read_excel(caminho, sheet_name=0)
        df.columns = [normalizar(c) for c in df.columns]

        criadas, atualizadas = 0, 0
        for _, linha in df.iterrows():
            codigo = str(linha.get('loja', '')).strip()
            if not codigo or codigo.lower() == 'nan':
                continue
            razao_social = str(linha.get('razao_social', '') or '').strip()
            email = str(linha.get('e_mail', '') or '').strip()
            cidade = str(linha.get('cidade', '') or '').strip()
            if email.lower() == 'nan':
                email = ''
            if cidade.lower() == 'nan':
                cidade = ''

            bandeira = Loja.bandeira_por_heuristica(email, razao_social)
            _, criada = Loja.objects.update_or_create(
                codigo=codigo,
                defaults={
                    'razao_social': razao_social,
                    'email': email,
                    'cidade': cidade,
                    'bandeira': bandeira,
                },
            )
            criadas += int(criada)
            atualizadas += int(not criada)

        self.stdout.write(self.style.SUCCESS(
            f'Lojas: {criadas} criadas, {atualizadas} atualizadas (fonte: {caminho.name}).'
        ))
