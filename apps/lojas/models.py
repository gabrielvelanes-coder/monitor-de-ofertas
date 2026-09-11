from django.db import models


class Loja(models.Model):
    """Cadastro de lojas do Grupo Velanes.

    A bandeira é definida automaticamente pelo comando `importar_lojas`
    usando a heurística documentada no Painel de Ofertas (e-mail contém
    "ultrapopular", ou razão social é a da Drogacentro) — mas fica como
    campo explícito e editável no admin, para não depender da heurística
    pra sempre (ver seção 11.1 do documento).
    """

    VELANES = 'velanes'
    ULTRA_POPULAR = 'ultra_popular'
    BANDEIRA_CHOICES = [
        (VELANES, 'Velanes'),
        (ULTRA_POPULAR, 'Ultra Popular'),
    ]

    codigo = models.CharField('código', max_length=10, unique=True)
    razao_social = models.CharField('razão social', max_length=255)
    email = models.EmailField('e-mail', blank=True)
    cidade = models.CharField('cidade', max_length=120, blank=True)
    bandeira = models.CharField(
        'bandeira', max_length=20, choices=BANDEIRA_CHOICES, default=VELANES
    )

    class Meta:
        verbose_name = 'loja'
        verbose_name_plural = 'lojas'
        ordering = ['codigo']

    def __str__(self):
        return f'{self.codigo} — {self.razao_social}'

    @staticmethod
    def bandeira_por_heuristica(email: str, razao_social: str) -> str:
        """Heurística validada no docx do Painel de Ofertas (seção 4)."""
        email = (email or '').strip().lower()
        razao_social = (razao_social or '').strip().upper()
        if 'ultrapopular' in email:
            return Loja.ULTRA_POPULAR
        if razao_social == 'DROGACENTRO MEDICAMENTOS E PERFUMARIA LTDA':
            return Loja.ULTRA_POPULAR
        return Loja.VELANES
