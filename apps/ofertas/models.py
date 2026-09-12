from django.db import models

from apps.lojas.models import Loja


class Lancamento(models.Model):
    """Uma linha de venda agregada (loja × produto × mês, ou × dia quando o
    relatório é diário), já classificada numa das 9 ações de oferta
    monitoradas.

    Sem pré-agregação: os cálculos por ação (ciclos, investimento,
    impacto, margem ajustada) são feitos em cima destas linhas no momento
    da consulta — granular o suficiente pra o filtro de bandeira funcionar
    em qualquer combinação (ver seção 9 do Painel_de_Ofertas_Documentacao).
    """

    LEVE3 = 'leve3'
    SUPRACORP = 'supracorp'
    KENVUE = 'kenvue'
    PRINCIPIA = 'principia'
    BOTICA = 'botica'
    PROCTER = 'procter'
    KIMBERLY = 'kimberly'
    CESTOES = 'cestoes'
    MARKETING = 'marketing'
    SELLOUT = 'sellout'
    MECANICA_CHOICES = [
        (LEVE3, 'Leve 3 Pague 2'),
        (SUPRACORP, 'Degustação Supra Corp Day'),
        (KENVUE, 'Ofertas Kenvue'),
        (PRINCIPIA, 'Ofertas Principia'),
        (BOTICA, 'Ofertas Botica'),
        (PROCTER, 'Ofertas Procter'),
        (KIMBERLY, 'Ofertas Kimberly'),
        (CESTOES, 'Cestões'),
        (MARKETING, 'Itens do Marketing'),
        (SELLOUT, 'Sellout Fabricante (referência)'),
    ]

    # dentro de uma oferta de fabricante (Kenvue/Principia/Botica/Procter),
    # a linha "base" é a venda sem desconto e a "oferta" é a venda com a tag
    # de promoção do fabricante — usado pra separar as duas séries.
    GRUPO_BASE = 'base'
    GRUPO_OFERTA = 'oferta'
    GRUPO_CHOICES = [
        (GRUPO_BASE, 'Base (sem desconto)'),
        (GRUPO_OFERTA, 'Oferta'),
    ]

    mecanica = models.CharField('ação', max_length=20, choices=MECANICA_CHOICES)
    loja = models.ForeignKey(Loja, on_delete=models.PROTECT, related_name='lancamentos')

    produto_descricao = models.CharField('produto', max_length=255)
    produto_codigo_barras = models.CharField(
        'código de barras', max_length=20, blank=True
    )
    fabricante = models.CharField('fabricante', max_length=120, blank=True)
    tag_origem = models.CharField(
        'tag de origem', max_length=255, blank=True,
        help_text='Texto bruto de "Cad. Oferta"/"Detalhe Desconto", pra auditoria.',
    )
    grupo = models.CharField(
        'grupo', max_length=10, choices=GRUPO_CHOICES, blank=True,
        help_text='Só usado nas ofertas de fabricante (base vs. oferta).',
    )

    ano_mes = models.CharField('ano-mês', max_length=7, help_text='formato AAAA-MM')
    data = models.DateField('data', null=True, blank=True, help_text='só em relatórios diários')

    itens = models.DecimalField('itens', max_digits=12, decimal_places=2)
    venda = models.DecimalField('venda', max_digits=14, decimal_places=2)
    desconto = models.DecimalField('desconto', max_digits=14, decimal_places=2, default=0)
    custo = models.DecimalField('custo', max_digits=14, decimal_places=2)
    lucro = models.DecimalField('lucro', max_digits=14, decimal_places=2)

    arquivo_origem = models.CharField('arquivo de origem', max_length=255, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'lançamento'
        verbose_name_plural = 'lançamentos'
        indexes = [
            models.Index(fields=['mecanica', 'ano_mes']),
            models.Index(fields=['mecanica', 'loja']),
        ]

    def __str__(self):
        return f'[{self.mecanica}] {self.loja_id} · {self.produto_descricao} · {self.ano_mes}'
