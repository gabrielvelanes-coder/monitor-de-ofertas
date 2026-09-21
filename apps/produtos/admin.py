from django.contrib import admin

from .models import Produto, RebaixaProduto


@admin.register(Produto)
class ProdutoAdmin(admin.ModelAdmin):
    list_display = ['descricao', 'fabricante', 'codigo_barras']
    list_filter = ['fabricante']
    search_fields = ['descricao', 'codigo_barras', 'fabricante']


@admin.register(RebaixaProduto)
class RebaixaProdutoAdmin(admin.ModelAdmin):
    list_display = ['ean', 'produto_descricao', 'mecanica', 'campanha', 'valor_rebaixa']
    list_filter = ['mecanica', 'campanha']
    search_fields = ['ean', 'produto_descricao']
