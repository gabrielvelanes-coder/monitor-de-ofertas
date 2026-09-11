# Painel de Ofertas — Grupo Velanes

Ferramenta de monitoramento de ofertas promocionais (venda, unidades, margem
e impacto) financiadas por indústrias parceiras. Projeto novo e independente
do Artifact "Painel de Ofertas" (que continua publicado e não é tocado por
este projeto) e do app "AÇÕES DE MARKETING - CAMPANHAS".

Mecânicas cobertas: Leve 3 Pague 2 · Degustação Supra Corp Day · Ofertas
Kenvue · Ofertas Principia · Ofertas Botica · Ofertas Procter · Ofertas
Kimberly · Cestões · Itens do Marketing. Sem módulo de verba/recebimento
nesta primeira versão — só performance.

As regras de negócio (fórmulas, tags de "Cad. Oferta" por mecânica,
heurística de bandeira) vêm de `../Painel_de_Ofertas_Documentacao.docx`.

## Rodando localmente

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Login do admin (`/admin/`): `velanes` / `velanes` (criado via
`DJANGO_SUPERUSER_*` + `createsuperuser --noinput`).

## Importando dados

Copie o(s) `.xls`/`.xlsx` de origem para `dados/entrada/` (pasta gitignored)
e rode o comando correspondente:

```
python manage.py importar_lojas          # cadastro de lojas + bandeira
```

Os demais comandos (`importar_leve3`, `importar_cestoes`,
`importar_supracorp`, `importar_kenvue`/`principia`/`botica`/`procter`,
`importar_marketing`, `importar_kimberly`) chegam nas próximas etapas — ver
`apps/ofertas/models.py::Lancamento.MECANICA_CHOICES`.

Todo importador é idempotente: rodar de novo com o mesmo arquivo não
duplica lançamento.
