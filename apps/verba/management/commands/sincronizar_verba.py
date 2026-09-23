from django.core.management.base import BaseCommand

from apps.ofertas.models import Lancamento
from apps.verba.services import (
    sincronizar_verba_leve3, sincronizar_verba_percentual_custo,
)


class Command(BaseCommand):
    help = (
        'Recalcula VerbaMensal.valor_apurado das ações com fórmula automática '
        '(Leve 3 e, hoje, Principia). importar_leve3/importar_principia já chamam '
        'isso sozinhos a cada import — este comando serve pra backfill (meses '
        'importados antes da fórmula existir) ou pra resincronizar sem reimportar nada.'
    )

    def handle(self, *args, **options):
        total = 0

        verbas = sincronizar_verba_leve3()
        for verba in verbas:
            self.stdout.write(f'  Leve 3 {verba.ano_mes}: R$ {verba.valor_apurado}')
        total += len(verbas)

        verbas = sincronizar_verba_percentual_custo(Lancamento.PRINCIPIA)
        for verba in verbas:
            self.stdout.write(f'  Principia {verba.ano_mes}: R$ {verba.valor_apurado}')
        total += len(verbas)

        if not total:
            self.stdout.write(self.style.WARNING(
                'Nenhum lançamento encontrado — rode os importadores primeiro.'
            ))
            return
        self.stdout.write(self.style.SUCCESS(f'Verba: valor_apurado atualizado em {total} mês(es) no total.'))
