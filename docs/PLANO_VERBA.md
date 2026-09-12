# Plano: Módulo de Verba & Recebimento + CMV com/sem verba

> Planejado em 12/09/26, **ainda não implementado** — Gabriel pediu
> explicitamente pra só planejar e deixar isso registrado como pendência;
> a implementação começa quando ele confirmar. Este arquivo é a fonte de
> verdade do plano (complementa `../Painel_de_Ofertas_Documentacao.docx`,
> que documenta as regras do painel *antigo* usadas de referência aqui).

## Context

O painel-ofertas hoje mede performance (venda/unidades/margem/impacto) das
9 ações, mas não tem onde registrar quanto cada indústria efetivamente
reembolsa (verba) nem quando o pagamento é recebido. O painel antigo
(Artifact, docx seção 7.5/8) tinha uma aba "Verba & Recebimento" — 1 linha
por oferta+mês, com valor apurado, valor recebido, data e status
(Pendente/Parcial/Recebido) — que servia como um mini-contas-a-receber.

Gabriel pediu para formalizar esse módulo como 2ª etapa do projeto e que o
CMV do painel seja sempre analisado em duas versões: com verba e sem
verba. Hoje só Leve 3 tem fórmula de reembolso validada (margem contábil
→ ajustada, via `calcular_leve3`); as demais 8 ações ainda não têm
mecânica de verba definida — Gabriel confirmou que **todas as 9 devem
entrar eventualmente**, mas quer isso registrado como pendência a
finalizar depois, não especificado agora.

## Decisões já confirmadas com o Gabriel

1. **CMV "com verba" usa o valor APURADO** (teórico, calculado no mês da
   venda — mesma lógica que `margem_ajustada` do Leve 3 já usa hoje),
   não o valor efetivamente recebido (caixa). Uma única métrica "com
   verba" por ação, não duas.
2. **Entrada de dados: Django Admin.** Reusa o login que já existe
   (`velanes`/`velanes`) e o padrão já usado pra `Loja` — sem criar
   form/view nova, sem precisar adicionar autenticação às páginas do
   painel (que hoje são públicas, sem senha).
3. **Escopo final: as 9 ações** devem ter controle de verba (não só
   Leve3 + as 4 de fabricante). Como só Leve3 tem fórmula de apuração
   validada hoje, o modelo de dados **não deve restringir por mecânica**
   — fica pronto pra qualquer uma das 9, e a apuração automática (vs.
   manual) é decidida por ação, não em bloco. As outras 8 fórmulas ficam
   como pendência explícita a definir com o Gabriel, uma a uma.

## Desenho

### 1. Modelo de dados — app novo `apps/verba`

Não meter em `apps/ofertas`: `Lancamento` é dado importado (imutável via
fluxo de import), verba é dado editado manualmente por humano, com ciclo
de vida próprio (apurado → recebido). Separar evita acoplar "dado
importado" e "dado editorial" no mesmo `admin.py`/`models.py`.

```python
# apps/verba/models.py
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

    # reaproveita Lancamento.MECANICA_CHOICES (mesma fonte de verdade,
    # sem restringir por ação — as 9 podem ter verba eventualmente)
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
    valor_recebido = models.DecimalField('valor recebido', max_digits=14, decimal_places=2, null=True, blank=True)
    data_recebimento = models.DateField('data do recebimento', null=True, blank=True)
    status = models.CharField('status', max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDENTE)
    observacao = models.TextField('observação', blank=True)

    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'verba mensal'
        verbose_name_plural = 'verbas mensais'
        constraints = [models.UniqueConstraint(fields=['mecanica', 'ano_mes'], name='uniq_verba_mecanica_mes')]
        indexes = [models.Index(fields=['mecanica', 'ano_mes'])]

    def __str__(self):
        return f'[{self.mecanica}] {self.ano_mes}'
```

- `UniqueConstraint(mecanica, ano_mes)`: 1 linha por oferta+mês (nível
  agregado, igual ao painel antigo — não por loja/produto).
- `valor_apurado` nullable: fica `None` ("pendente de definição") pras
  ações sem fórmula ainda — nunca mostrar como R$ 0,00 silencioso.
- `apuracao_automatica`: flag explícita por linha, não `if mecanica ==
  'leve3'` espalhado pelo código — quando a fórmula de outra ação for
  validada, é só passar essa flag a `True` pra ela também.
- Sem FK pra `Lancamento`: verba é por mecânica+mês agregado, pode
  existir antes do import do mês ou mesmo sem nenhum `Lancamento` daquele
  mês ainda.

### 2. Camada de serviço — `apps/verba/services.py`

```python
def sincronizar_verba_leve3(ano_mes=None):
    """get_or_create + update de VerbaMensal(mecanica=LEVE3).valor_apurado
    a partir de calcular_leve3 — chamada no fim de importar_leve3 (ou via
    management command dedicado). Nunca toca valor_recebido/status."""

def cmv_sem_verba(venda, lucro):
    """100 - (lucro/venda*100) se venda else 0 — extrai o cálculo hoje
    inline em _resumo_executivo (apps/ofertas/views.py:76-77) pra reuso."""

def cmv_com_verba(venda, lucro, valor_apurado):
    """100 - ((lucro + valor_apurado)/venda*100) se venda e valor_apurado
    not None else None (nunca 0 silencioso quando a apuração não existe)."""

def verba_do_mes(mecanica, ano_mes='') -> VerbaMensal | None:
    """Busca a linha de VerbaMensal da mecânica pro mês (ou soma dos meses
    filtrados, se ano_mes vazio) — usada pelo dashboard e telas de ação."""
```

`calcular_leve3` e `calcular_impacto_fabricante` (`apps/ofertas/services.py`)
continuam exatamente como estão — a nova camada só lê o resultado deles e
cruza com `VerbaMensal`, sem mudar assinatura nem comportamento.

**Conexão com o dashboard:** `_resumo_executivo` (`apps/ofertas/views.py:27-85`)
hoje calcula só `cmv_pct` cru (linha 76-77). Passa a calcular
`cmv_pct_sem_verba` (mesma fórmula, renomeada) e `cmv_pct_com_verba`
(usando `verba_do_mes` quando existir apuração; senão `None` — template
mostra "—" com uma explicação de "sem fórmula de verba definida").

### 3. UI — só leitura, sem forms/views novas

- **Dashboard (`templates/ofertas/home.html`):** a coluna única de CMV
  na tabela de ações vira 2 colunas — "CMV sem verba" / "CMV com verba".
  `tabela.js` não precisa mudar (ordenação/busca é agnóstica ao nº de
  colunas).
- **Leve3 (`templates/ofertas/leve3.html`):** já tem 3 cards lado a lado
  (Investimento / Margem contábil / Margem ajustada, linhas ~31-37) —
  acrescentar 2 cards no mesmo `.cards`: "CMV sem verba" / "CMV com
  verba". Mesmo padrão visual, zero CSS novo.
- **Telas de fabricante (`templates/ofertas/impacto_fabricante.html`,
  reusada por Kenvue/Principia/Botica/Procter):** mesmos 2 cards, com
  estado explícito de "verba pendente de definição" (reusar `.aviso` já
  existente) quando `valor_apurado` for `None` — nunca virar R$0 mudo.
- **Cestões/Supracorp/Marketing/Kimberly:** por ora sem cards de verba
  (nenhuma linha de `VerbaMensal` é criada pra elas ainda) — ficam
  cobertas pelo modelo, mas sem apuração até a fórmula de cada uma ser
  definida (pendência explícita, ver abaixo).
- **Django Admin (`apps/verba/admin.py`):**
  ```python
  @admin.register(VerbaMensal)
  class VerbaMensalAdmin(admin.ModelAdmin):
      list_display = ['mecanica', 'ano_mes', 'valor_apurado', 'valor_recebido', 'data_recebimento', 'status']
      list_editable = ['valor_recebido', 'data_recebimento', 'status']
      list_filter = ['mecanica', 'status']
  ```
  `get_readonly_fields` condicional deixa `valor_apurado` bloqueado
  quando `apuracao_automatica=True` (só Leve3, por ora).

### 4. Migração

`apps/verba/migrations/0001_initial.py` (app novo, primeira migration) +
registrar `apps.verba` em `INSTALLED_APPS` (`config/settings.py`).

## Sequenciamento sugerido (cada etapa commitável, regra "commitar sempre")

1. App `apps/verba` — `models.py::VerbaMensal`, `admin.py`, migration
   `0001_initial`, `INSTALLED_APPS`. Só schema + admin, nada calcula
   ainda. **Commit isolado.**
2. `sincronizar_verba_leve3` + management command (ou hook no fim de
   `importar_leve3.py`) pra popular `valor_apurado` automaticamente do
   Leve3. Testável via admin. **Commit isolado.**
3. `cmv_sem_verba`/`cmv_com_verba`/`verba_do_mes` + ajuste em
   `_resumo_executivo`. **Commit isolado.**
4. `home.html`: 2 colunas de CMV na tabela do dashboard. **Commit
   isolado, visual.**
5. `leve3.html`: 2 cards novos de CMV. **Commit isolado.**
6. `impacto_fabricante.html`: 2 cards novos + estado "pendente".
   **Commit isolado.**

## Fora de escopo agora (pendências explícitas)

- **Fórmula de apuração das outras 8 ações** (Kenvue, Principia, Botica,
  Procter, Cestões, Marketing, Kimberly, Supracorp) — o modelo já
  suporta qualquer uma via `mecanica`/`apuracao_automatica`, mas nenhuma
  fórmula deve ser inventada; Gabriel confirmou que quer isso registrado
  como pendência e finalizado numa rodada futura, ação por ação.
- Autenticação nas páginas web do painel (hoje públicas) — só entraria
  em jogo se, no futuro, Gabriel preferir editar verba direto no painel
  em vez do Admin.
- Anexo de comprovante/nota fiscal e histórico de alterações (docx,
  seção 11.3) — feature de fase posterior, não pedida ainda.

## Verificação (quando for implementar)

- `python manage.py migrate` cria `VerbaMensal` sem erro; `python
  manage.py createsuperuser` já existe (`velanes`/`velanes`) — confirmar
  que a nova aba aparece em `/admin/`.
- Rodar `importar_leve3` de novo após o passo 2 e confirmar no admin que
  `VerbaMensal(mecanica='leve3', ano_mes='2026-08').valor_apurado` bate
  com o valor já validado (R$ 12.277,83 — memória do projeto).
- Cadastrar manualmente 1 linha de `valor_recebido`/`status` no admin e
  confirmar que o dashboard e a tela do Leve3 mostram "CMV com verba"
  diferente de "CMV sem verba" só depois que `valor_apurado` existe;
  confirmar que Kenvue/Principia/Botica/Procter mostram o aviso de
  "pendente" em vez de R$ 0,00.
