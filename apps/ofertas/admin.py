from django.contrib import admin

from .models import Lancamento


@admin.register(Lancamento)
class LancamentoAdmin(admin.ModelAdmin):
    list_display = [
        'mecanica', 'loja', 'ano_mes', 'produto_descricao', 'fabricante',
        'grupo', 'itens', 'venda', 'lucro',
    ]
    list_filter = ['mecanica', 'ano_mes', 'fabricante', 'grupo', 'loja__bandeira']
    search_fields = ['produto_descricao', 'produto_codigo_barras', 'tag_origem']
    list_select_related = ['loja']
