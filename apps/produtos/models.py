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


class RebaixaProduto(models.Model):
    """Regra de verba de 1 fabricante/campanha: valor fixo (R$) por UNIDADE
    vendida que a indústria reembolsa — vem de uma planilha que o próprio
    fabricante manda (ex. "rebaixas_produtos procter.xlsx", 1ª regra real
    recebida, pra Procter Semana do Cliente). Diferente do Leve3
    (`ciclos × custo`, calculado) — aqui o valor já vem pronto por EAN.

    Escopado por `mecanica` + `campanha` (não só `mecanica`) porque uma
    mecânica pode ter mais de 1 campanha rodando (ver
    `Lancamento`/`calcular_impacto_fabricante` "por campanha") e cada uma
    pode ter sua própria tabela de rebaixa."""

    mecanica = models.CharField('mecânica', max_length=20)
    campanha = models.CharField(
        'campanha', max_length=255,
        help_text='Mesmo texto de Lancamento.tag_origem (sem o prefixo "Cad. Oferta:") pra casar.',
    )
    ean = models.CharField('EAN', max_length=20)
    produto_descricao = models.CharField(
        'descrição (da planilha do fabricante)', max_length=255, blank=True,
        help_text='Guardado pra auditoria e como 2º critério de cruzamento quando o EAN não resolve.',
    )
    valor_rebaixa = models.DecimalField('valor da rebaixa (R$/un.)', max_digits=10, decimal_places=4)

    arquivo_origem = models.CharField('arquivo de origem', max_length=255, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'rebaixa de produto'
        verbose_name_plural = 'rebaixas de produto'
        constraints = [
            models.UniqueConstraint(fields=['mecanica', 'campanha', 'ean'], name='rebaixa_unica_por_campanha_ean')
        ]

    def __str__(self):
        return f'[{self.mecanica}/{self.campanha}] {self.ean} — R$ {self.valor_rebaixa}'


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
