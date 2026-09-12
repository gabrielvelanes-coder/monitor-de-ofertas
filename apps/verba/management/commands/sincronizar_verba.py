from django.core.management.base import BaseCommand

from apps.verba.services import sincronizar_verba_leve3


class Command(BaseCommand):
    help = (
        'Recalcula VerbaMensal.valor_apurado das ações com fórmula automática '
        '(hoje só Leve 3). importar_leve3 já chama isso sozinho a cada import — '
        'este comando serve pra backfill (meses importados antes do módulo de '
        'verba existir) ou pra resincronizar sem reimportar nada.'
    )

    def handle(self, *args, **options):
        verbas = sincronizar_verba_leve3()
        if not verbas:
            self.stdout.write(self.style.WARNING(
                'Nenhum lançamento de Leve 3 encontrado — rode importar_leve3 primeiro.'
            ))
            return
        for verba in verbas:
            self.stdout.write(f'  {verba.ano_mes}: R$ {verba.valor_apurado}')
        self.stdout.write(self.style.SUCCESS(
            f'Verba (Leve 3): valor_apurado atualizado em {len(verbas)} mês(es).'
        ))
