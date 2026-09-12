"""Cadastro de produtos (árvore de produtos do ERP) — fonte de verdade de
produto -> fabricante, pra substituir `erp.fabricante_generico()` (que só
reconhecia a sigla do laboratório genérico no fim do nome do produto e
deixava ~2,7% como "Não identificado", além de ter mapeado errado pelo
menos 2 produtos — ver `apps/produtos/services.py`).

Cruza com `Lancamento.produto_descricao` pelo texto (o ERP não exporta
código de barras nos relatórios de venda usados pelos importadores, só
no cadastro) — por isso `descricao` é a chave, não `codigo_barras`.
"""
from django.db import models


class Produto(models.Model):
    descricao = models.CharField(
        'descrição', max_length=255, unique=True,
        help_text='Mesmo texto de "Produto"/"Embalagem" nos relatórios do ERP — chave de cruzamento.',
    )
    codigo_barras = models.CharField('código de barras', max_length=20, blank=True)
    fabricante = models.CharField('fabricante', max_length=120)

    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'produto'
        verbose_name_plural = 'produtos (cadastro)'
        indexes = [models.Index(fields=['descricao'])]

    def __str__(self):
        return f'{self.descricao} ({self.fabricante})'
