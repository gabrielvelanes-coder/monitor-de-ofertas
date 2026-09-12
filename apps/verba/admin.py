from django.contrib import admin

from .models import VerbaMensal


@admin.register(VerbaMensal)
class VerbaMensalAdmin(admin.ModelAdmin):
    list_display = [
        'mecanica', 'ano_mes', 'valor_apurado', 'apuracao_automatica',
        'valor_recebido', 'data_recebimento', 'status',
    ]
    list_editable = ['valor_recebido', 'data_recebimento', 'status']
    list_filter = ['mecanica', 'status']
    ordering = ['-ano_mes', 'mecanica']

    def get_readonly_fields(self, request, obj=None):
        # valor_apurado só é editável à mão nas ações sem fórmula
        # automática ainda (hoje, todas exceto Leve 3) — em Leve 3 quem
        # calcula é sincronizar_verba_leve3(), pra não divergir do painel.
        if obj is not None and obj.apuracao_automatica:
            return ['valor_apurado']
        return []
