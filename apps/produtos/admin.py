from django.contrib import admin

from .models import Produto


@admin.register(Produto)
class ProdutoAdmin(admin.ModelAdmin):
    list_display = ['descricao', 'fabricante', 'codigo_barras']
    list_filter = ['fabricante']
    search_fields = ['descricao', 'codigo_barras', 'fabricante']
