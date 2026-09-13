# Painel de Ofertas — Grupo Velanes

Ferramenta de monitoramento de ofertas promocionais (venda, unidades, margem
e impacto) financiadas por indústrias parceiras. Projeto novo e independente
do Artifact "Painel de Ofertas" (que continua publicado e não é tocado por
este projeto) e do app "AÇÕES DE MARKETING - CAMPANHAS".

Mecânicas cobertas: Leve 3 Pague 2 · Degustação Supra Corp Day · Ofertas
Kenvue · Ofertas Principia · Ofertas Botica · Ofertas Procter · Ofertas
Kimberly · Cestões · Itens do Marketing — todas com importador, tela,
menu lateral, dashboard executivo e gráficos (Chart.js local, sem CDN).
Mais uma referência sem tela própria no menu — Sellout (EMS/Eurofarma/
Germed/Prati, giro completo do fabricante) — usada só pra medir o
impacto do Leve 3 sobre o fabricante. Módulo de verba/recebimento
(`apps/verba`) cobre CMV com/sem verba nas 9 ações, mas só Leve 3 tem
apuração automática validada — ver "Pendências" abaixo.

As regras de negócio (fórmulas, tags de "Cad. Oferta" por mecânica,
heurística de bandeira) vêm de `../Painel_de_Ofertas_Documentacao.docx`.

**Correção (12/09/26) — Impacto por Fabricante (Kenvue/Principia/Botica/
Procter):** a comparação "base vs. oferta" era feita entre a tag literal
"Sem Desconto" (preço cheio) e a tag exata da promoção, descartando toda
venda com qualquer outra tag (Todo Dia, Cestão, Marketing, outras
campanhas do fabricante) — isso subestimava a base e, em vários meses,
fazia a venda "sem oferta" parecer menor que a venda "com oferta"
(inconsistência notada pelo Gabriel). Corrigido: oferta = só a tag exata
do fabricante; base = todo o resto das vendas dele, "Sem Desconto"
incluído. Os 4 fabricantes foram reimportados; base agora é sempre maior
que oferta, em todo mês.

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
python manage.py importar_produtos               # cadastro arvore nova com ean.xlsx (produto -> fabricante)
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

`importar_produtos` roda antes de `importar_leve3` (mas pode rodar
depois também): `importar_leve3` só lê o cadastro no momento em que roda,
não fica "escutando" atualização — depois de atualizar o cadastro,
rodar `importar_leve3` de novo pra refletir nos lançamentos já
importados.

## Mecânicas cobertas

Leve 3 Pague 2 · Cestões · Degustação Supra Corp Day · Ofertas Kenvue ·
Ofertas Principia · Ofertas Botica · Ofertas Procter · Itens do Marketing ·
Ofertas Kimberly — todas com importador + tela em `/`.

## Pendências

- **Controle de verba/recebimento + CMV com/sem verba — implementado
  (12/09/26)**, plano em [`docs/PLANO_VERBA.md`](docs/PLANO_VERBA.md).
  App `apps/verba` (modelo `VerbaMensal`, 1 linha por mecânica+mês,
  entrada só via Django Admin em `/admin/`). Dashboard e todas as telas
  de ação (cards + toda tabela de loja/produto/fabricante) mostram CMV
  sem verba e com verba lado a lado. **Só Leve 3 tem apuração
  automática** (`sincronizar_verba_leve3`, chamada a cada
  `importar_leve3` ou via `manage.py sincronizar_verba`) — as outras 8
  ações mostram "CMV com verba: —" até alguém cadastrar `valor_apurado`
  manualmente no admin ou uma fórmula ser definida e validada.
- **Fórmula de verba das outras 8 ações — pendência aberta (13/09/26),
  aguardando o Gabriel mandar os dados de cada uma.** Pra cada
  ação/fabricante abaixo falta saber: **base de cálculo** (venda na
  oferta? desconto dado item a item, como o Leve3? valor fixo por
  período?), **percentual/valor** e **periodicidade** (mensal? por
  ciclo/evento?).
  - **Kenvue / Principia / Botica / Procter:** confirmado com o Gabriel
    que **cada indústria tem sua própria regra e formato** (não dá pra
    usar 1 fórmula genérica pras 4, diferente do que se assumiu ao
    planejar o módulo) — ele vai mandar os dados de cada fabricante.
  - **Cestões / Itens do Marketing / Kimberly:** ainda não confirmado se
    essas 3 ações têm verba/reembolso da indústria ou se são só de
    exposição/giro sem repasse financeiro — pergunta feita ao Gabriel,
    resposta pendente.
  - **Supra Corp Day:** nem chegou a ser perguntado ainda — evento
    pontual de degustação, pode ser patrocínio de valor fixo em vez de
    fórmula sobre venda (a decidir quando entrar na fila).
- Kimberly: importador aceita curadoria manual (`--produto`/
  `--venda-max`/`--data-inicio`/`--data-fim`), mas a fórmula ainda
  precisa da validação do Gabriel.
- **Fabricante do Leve 3 — resolvido (12/09/26)** com o cadastro que o
  Gabriel mandou (`apps/produtos`, `importar_produtos`). 100% dos 150
  produtos distintos do Leve 3 bateram com o cadastro — zero "não
  identificado". `erp.fabricante_generico()` (a heurística antiga) virou
  só fallback pra produto novo fora do cadastro. **Achado ao comparar:**
  a heurística mapeava errado produtos com sufixo "QUIM" como "Neo
  Química" — o cadastro mostra que são "U Química" e "Nova Química",
  fabricantes diferentes; os rótulos EMS/Eurofarma/Germed/Prati foram
  mantidos iguais de propósito, pra não quebrar o cruzamento com os
  dados de Sellout já importados (`importar_sellout`, que usa esses
  mesmos nomes). O segundo arquivo que ele mandou (`cadastro arvore nova
  com classificacao.xlsx`) não foi usado ainda — tem Classificação por
  produto, pode servir pra alguma análise futura.
