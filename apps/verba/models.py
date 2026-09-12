"""Verba/recebimento das indústrias — dado editorial (humano), separado de
`apps.ofertas.Lancamento` (dado importado, imutável via fluxo de import).

1 linha por mecânica+mês, nível agregado (igual à aba "Verba & Recebimento"
do painel antigo, docx seção 7.5/8) — não por loja/produto. Plano completo
em `docs/PLANO_VERBA.md`.
"""
from django.db import models

from apps.ofertas.models import Lancamento


class VerbaMensal(models.Model):
    STATUS_PENDENTE = 'pendente'
    STATUS_PARCIAL = 'parcial'
    STATUS_RECEBIDO = 'recebido'
    STATUS_CHOICES = [
        (STATUS_PENDENTE, 'Pendente'),
        (STATUS_PARCIAL, 'Parcial'),
        (STATUS_RECEBIDO, 'Recebido'),
    ]

    # reaproveita Lancamento.MECANICA_CHOICES (mesma fonte de verdade, sem
    # restringir por ação — as 9 ações podem ganhar verba eventualmente,
    # ver "Fora de escopo agora" em docs/PLANO_VERBA.md)
    mecanica = models.CharField('mecânica', max_length=20, choices=Lancamento.MECANICA_CHOICES)
    ano_mes = models.CharField('ano-mês', max_length=7, help_text='formato AAAA-MM')

    valor_apurado = models.DecimalField(
        'valor apurado', max_digits=14, decimal_places=2, null=True, blank=True,
        help_text='Leve 3: calculado automaticamente. Demais ações: manual, até a fórmula ser definida.',
    )
    apuracao_automatica = models.BooleanField(
        'apuração automática', default=False,
        help_text='True só onde já existe fórmula validada (Leve 3, por ora) — valor_apurado deixa de ser editável no admin.',
    )
    valor_recebido = models.DecimalField(
        'valor recebido', max_digits=14, decimal_places=2, null=True, blank=True,
    )
    data_recebimento = models.DateField('data do recebimento', null=True, blank=True)
    status = models.CharField('status', max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDENTE)
    observacao = models.TextField('observação', blank=True)

    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'verba mensal'
        verbose_name_plural = 'verbas mensais'
        constraints = [
            models.UniqueConstraint(fields=['mecanica', 'ano_mes'], name='uniq_verba_mecanica_mes'),
        ]
        indexes = [models.Index(fields=['mecanica', 'ano_mes'])]

    def __str__(self):
        return f'[{self.mecanica}] {self.ano_mes}'
