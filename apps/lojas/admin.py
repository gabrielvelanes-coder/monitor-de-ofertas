from django.contrib import admin

from .models import Loja


@admin.register(Loja)
class LojaAdmin(admin.ModelAdmin):
    list_display = ['codigo', 'razao_social', 'bandeira', 'cidade', 'email']
    list_filter = ['bandeira']
    search_fields = ['codigo', 'razao_social', 'email', 'cidade']
