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
python manage.py importar_lojas                 # DADOS GRUPO VELANES ATUALIZADO*.xlsx
python manage.py importar_leve3                  # genericos_<bimestre>_2026.xls (todos em dados/entrada/)
python manage.py importar_cestoes                # CESTOES*.xls
python manage.py importar_supracorp              # supracorp day.xls
python manage.py importar_kenvue                 # baseline kenvue*.xls
python manage.py importar_principia              # baseline principia*.xls
python manage.py importar_botica                 # baseline botica*.xls
python manage.py importar_procter                # baseline procter*.xls
python manage.py importar_marketing --arquivo "dados/entrada/<arquivo>.xls"
python manage.py importar_kimberly --arquivo "dados/entrada/<arquivo>.xls"
```

Todo importador é idempotente: rodar de novo com o mesmo arquivo não
duplica lançamento. `importar_marketing` e `importar_kimberly` pedem
`--arquivo` explícito porque a tag/arquivo de origem não é única (ver
`--help` de cada um pra mais opções, especialmente `importar_kimberly`,
que precisa de curadoria manual — não existe tag limpa pra promoção
Hipzinha nos relatórios).

## Mecânicas cobertas

Leve 3 Pague 2 · Cestões · Degustação Supra Corp Day · Ofertas Kenvue ·
Ofertas Principia · Ofertas Botica · Ofertas Procter · Itens do Marketing ·
Ofertas Kimberly — todas com importador + tela em `/`.

## Não incluído nesta versão

- Controle de verba/recebimento (contas a receber por indústria) — decisão
  explícita, fica pra uma 2ª etapa.
- Gráficos (as telas usam tabelas por ora).
- Mecânica de verba pra Kenvue/Principia/Botica/Procter — pendente de
  definição (docx, seção 5.3), as telas mostram só performance.
