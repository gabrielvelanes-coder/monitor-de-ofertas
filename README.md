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
python manage.py importar_leve3                  # genericos*.xls em dados/entrada/ (formato "Análise de Venda por Item", com Data — ver "Dado por dia" abaixo)
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
Ofertas Kimberly · Deu a Louca (Velanes) · Ultra Queimão (Ultra Popular) —
todas com importador + tela em `/`. Procter pode ter mais de 1 campanha
rodando no mesmo mês (ex.: promoção mensal + Semana do Cliente) — nesse
caso a tela de Procter ganha uma seção "Campanhas" separando
investimento/venda de cada uma (ver `Lancamento.tag_origem` +
`calcular_impacto_fabricante`, `apps/ofertas/services.py`).

**Dado por dia (22/09/26):** Kenvue/Principia/Botica/Procter/Kimberly/
Leve3 importam relatório bruto "Análise de Venda por Item" (com coluna
`Data`), 100% de cobertura — Leve3 ganhou o histórico completo (maio a
setembro) no mesmo dia, 2 arquivos (`genericos 2026 ate 3104.xls` = jan-
abr, sem nenhuma linha "LEVE 3" — a tag só existe a partir de maio;
`genericos 2026 -105 ate 2109.xls` = maio-setembro, 4.735 linhas, 25/05 a
20/09) substituindo os 4 arquivos antigos agregados por `Ano-mês`
(movidos pra `dados/entrada/_substituidos/`, fora do glob
`*genericos*.xls` do `importar_leve3` pra não serem reprocessados por
cima por engano). Deu a Louca/Ultra Queimão continuam com cobertura
parcial; Cestões e Itens do Marketing ainda são só agregado por
`Ano-mês`.

**Gráfico único Mês/Semana/Dia (22/09/26):** pedido do Gabriel — "prefiro
que tenhamos apenas 1 gráfico e eu tenha a opção de escolher olhar por
mês, por semana, ou por dia" — nas 4 telas com `data` (Kenvue/Principia/
Botica/Procter, Kimberly, Leve3, Deu a Louca/Ultra Queimão): 1 card só,
com abas "Mês / Semana / Dia" (mesmo padrão de abas de "Lojas: Por
bandeira/Loja a loja"). **Mês** continua o gráfico de sempre (virou
**barra** em vez de linha, mês é categoria discreta — em todo lugar,
inclusive Cestões/Itens do Marketing que não ganharam abas) com
drill-down por produto/campanha e clique-pra-filtrar — decisão
deliberada de NÃO trocar pelo formato de destaque único, pra não perder
essas 2 funcionalidades já validadas. **Semana** e **Dia** usam o
formato mais simples introduzido antes (venda com `grupo=oferta`
destacada + % de crescimento vs. a média dos períodos sem oferta, escrito
em cima da própria barra) — `serie_semanal`/`serie_diaria`
(`apps/ofertas/services.py`, `_periodos_com_destaque` compartilhado),
`graficoBarraDestaque` + `montarAbasGraficoPeriodo`
(`static/js/graficos.js`), partials `templates/ofertas/_abas_periodo.html`
+ `_paineis_periodo.html`. Aba só aparece se houver período pra mostrar
(mecânica com cobertura parcial de `data`, tipo Leve3 num mês/fabricante
sem dia importado, pode ficar só com "Mês"). Gráfico de Semana/Dia é
criado sob demanda no 1º clique na aba (canvas nasce dentro de painel
`hidden`, criar Chart.js de cara nele desenharia em branco — mesmo bug já
visto antes nesta tela). Semana/dia ainda incompleto ou o filtro de mês
cortando um período ao meio ficam marcados/tratados à parte, não entram
na comparação (2 bugs reais achados e corrigidos em 22/09/26, herdados do
gráfico semanal original).

**Destaque em mecânica sem base/oferta (22/09/26):** Leve3 não separa
`grupo` (base/oferta) — toda linha importada já É a própria oferta. Isso
fazia `tem_oferta` ficar sempre `False` (comparava contra
`grupo=oferta`, que o Leve3 nunca usa) e o gráfico de Semana/Dia nunca
destacava nada, mesmo só tendo semana de oferta pra mostrar (achado
real: Gabriel reportou "o gráfico não está destacado as semanas que
foram da oferta"). `_periodos_com_destaque` (`apps/ofertas/services.py`)
ganhou um fallback: se NENHUM período da série tem `tem_oferta=True`,
marca todos como destaque (sem % — não tem baseline "sem oferta" pra
comparar). Mecânicas com separação base/oferta de verdade (Kenvue etc.)
não são afetadas, continuam com a mistura real de semanas com/sem
oferta.

**Mês também (22/09/26, mesmo dia):** o destaque acima só tinha ido pro
Semana/Dia — Gabriel perguntou "no mes, nao foi implantado as cores das
bandeiras?". `calcular_leve3` (services.py) agora também soma venda por
`loja__bandeira` por mês e calcula `bandeira_dominante` (reaproveitando
`_campos_bandeira`); a view expõe isso em `grafico['bandeiras']`.
`graficoBarraMensalBandeira` (graficos.js, nova) pinta a barra "Venda"
pela bandeira do mês; a barra "Itens" usa a MESMA cor só translúcida
(`hexParaRgba`) -- sem isso ela ficaria com a cor de "Velanes" por
coincidência de paleta (2ª cor padrão já é laranja) e confundiria as 2
séries. Drill-down/clique-pra-filtrar continuam funcionando (a função
só reusa `montarDatasetsEEscalas`, mesma estrutura de chart de sempre).
**Achado ao testar:** os 5 meses saíram todos laranja/Velanes — não é
bug, é real: Velanes vende mais que a Ultra Popular em TODO mês do
Leve3 (conferido com `Sum('venda')` por mês+bandeira), mesmo cada uma
rodando sua própria semana. No nível de mês essa diferença fica
"escondida" pela soma; só aparece de verdade no Semana/Dia (onde cada
período já é só de 1 bandeira).

**Correção (mesmo dia, logo depois):** Gabriel comparou o "Mês" do
Leve3 (tudo laranja) com o do Kenvue (rico em cores, 4 séries) e pediu
pra "dar um 360" e arrumar — a versão "cor dominante" ficava monótona
demais (sempre a mesma cor, zero informação por mês, exatamente o
problema que o achado acima já antecipava). Trocado por **barra
empilhada de verdade**: Venda vira 2 séries empilhadas
(`venda_velanes`/`venda_ultra_popular`, já calculadas por
`calcular_leve3` via `_campos_bandeira`) mostrando a proporção real de
cada bandeira por mês (varia mês a mês, ao contrário da versão
anterior). Itens virou uma 3ª barra à parte, cor cinza neutra (não
dividida por bandeira — laranja bateria com a cor da Velanes de novo).
View do Leve3 monta `grafico` na mão (não usa mais `grafico_mensal`
genérico) com `{labels, venda_velanes, venda_ultra_popular, itens}`.
`graficoBarraMensalBandeira` (graficos.js) reescrita: 3 datasets Chart.js
(`stack:'venda'` nos 2 primeiros, escala `y`/`y1` dual como sempre).
Drill-down/clique-pra-filtrar continuam funcionando (testado: clique
num produto ainda adiciona o dataset de destaque, 3→4 datasets).

**Cor por bandeira no Leve3 (22/09/26, mesmo dia):** Gabriel corrigiu o
pedido acima — não queria destaque por oferta (que não diz nada aqui,
como visto acima), queria saber DE QUEM foi cada semana/dia: "semana de
ultra barra vermelha, semana de velanes, laranja". `serie_semanal`/
`serie_diaria` (`apps/ofertas/services.py`) agora também somam venda por
`loja__bandeira` e calculam `bandeira_dominante` por período (a bandeira
que mais vendeu nele). `graficoBarraDestaque` (`static/js/graficos.js`)
ganhou `opcoes.modo: 'bandeira'` — nesse modo pinta cada barra pela
bandeira dominante (`#ef9f5b` Velanes / `#e5484d` Ultra Popular) em vez
de oferta/normal, e não desenha % (não faz sentido nesse modo). Usado só
no Leve3 (`leve3.html` passa `{modo:'bandeira'}` e legendas customizadas
via `_paineis_periodo.html`, que agora aceita `legenda_semana`/
`legenda_dia` opcionais) — as outras mecânicas continuam com o
destaque por oferta de sempre, sem mudança nenhuma no comportamento
delas. **Pendência em aberto:** Gabriel perguntou se dá pra levar
"bandeira" pras outras mecânicas também, sugerindo dividir a barra em
vez de pintar ela inteira — avaliado, não implementado ainda (ver seção
"Pendências").

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
    planejar o módulo). **Procter Semana do Cliente — resolvido
    (21/09/26):** `rebaixas_produtos procter.xlsx` (EAN/Produto/Rebaixa,
    valor fixo em R$ por UNIDADE vendida). Modelo `RebaixaProduto`
    (`apps/produtos`, escopado por mecânica+campanha), `manage.py
    importar_rebaixas`. **Kenvue — fórmula decodificada mas BLOQUEADA
    (22/09/26):** Gabriel manda um "calendário" bem mais rico (planilha
    com aba RESUMO/RELATÓRIO PADRÃO/Produtos/vendas) — fórmula é
    `Investimento = Menor Preço × % Desconto × Qtd Vendida (na janela
    Início-Fim)`, diferente da Procter (que não tem "preço de
    referência"). Conferida na mão com o exemplo de julho (já
    preenchido), bate exato. **Bloqueado:** o calendário do mês
    corrente vem com Qtd Vendida/Investimento zerados — só preenche
    quando o Gabriel cola a aba "vendas" manual no final da campanha.
    Ideia levantada, não decidida: calcular a Qtd Vendida sozinho
    batendo EAN+janela de datas contra a venda que a Kenvue já tem
    importada (100% com dia desde 22/09) em vez de depender da cola
    manual — **aguardando o Gabriel confirmar.** Principia/Botica
    ainda sem regra nenhuma.
  - **Cestões / Itens do Marketing / Kimberly:** ainda não confirmado se
    essas 3 ações têm verba/reembolso da indústria ou se são só de
    exposição/giro sem repasse financeiro — pergunta feita ao Gabriel,
    resposta pendente.
  - **Supra Corp Day:** nem chegou a ser perguntado ainda — evento
    pontual de degustação, pode ser patrocínio de valor fixo em vez de
    fórmula sobre venda (a decidir quando entrar na fila).
- **Cor por bandeira no gráfico Semana/Dia das outras mecânicas —
  implementado (22/09/26).** Gabriel confirmou o caminho avaliado
  (empilhar em vez de trocar a cor inteira, "sim, pode fazer assim").
  `serie_semanal`/`serie_diaria` (`apps/ofertas/services.py`) agora
  também expõem `venda_velanes`/`venda_ultra_popular` por período
  (helper `_campos_bandeira`, compartilhado com o `bandeira_dominante`
  do modo do Leve3). `graficoBarraEmpilhadaBandeira`
  (`static/js/graficos.js`) desenha 2 datasets empilhados (Velanes +
  Ultra Popular), cada um na MESMA família de cor do destaque por
  oferta (tons de rosa se o período teve oferta, tons de azul se não
  teve) — preserva o sinal principal (impacto) e mostra a proporção por
  bandeira dentro da barra. `montarAbasGraficoPeriodo` despacha pra essa
  função quando `opcoes.modo === 'bandeira-empilhada'` (usado só em
  `impacto_fabricante.html` — Kenvue/Principia/Botica/Procter — e
  `kimberly.html`, com legenda customizada via
  `legenda_semana`/`legenda_dia`). `impacto_promocao.html` (Deu a
  Louca/Ultra Queimão) e `leve3.html` (já tem seu próprio modo
  `'bandeira'`, cor única) não mudaram. Testado ao vivo: Kenvue e
  Kimberly, os 2 segmentos aparecem distinguíveis dentro de cada barra,
  tons certos conforme teve ou não oferta.
- **Arquivo de apuração pra enviar à indústria — implementado pra Leve3
  e Procter Semana do Cliente (21-22/09/26).** `apps/ofertas/apuracao.py`:
  `montar_apuracao_industria` (fabricantes, via `RebaixaProduto`) e
  `montar_apuracao_leve3` (fórmula própria, ciclos × custo, não
  depende de rebaixa cadastrada — sai **1 arquivo por fabricante
  genérico**, EMS/Eurofarma/Germed/etc., não 1 só misturado).
  `manage.py exportar_apuracao_industria --mecanica --campanha|--mes
  [--fabricante|--todos-fabricantes]` e **botão "Baixar apuração" nas
  telas de Leve3 e Procter** (view `exportar_apuracao`, rota
  `/apuracao/<mecanica>/` — só aparece pra campanha que já tem regra
  cadastrada). Nome do arquivo padronizado: `apuracao_<oferta>_<mês>.xlsx`.
  Testado com dado real (Leve3: 3.286 linhas, R$ 50.646,84 — bate exato
  com o painel depois de corrigir um bug de arredondamento linha a
  linha; Procter: 189 linhas, R$ 650,00, 100% resolvido). Coluna "Data"
  linha a linha confirmada funcionando (pedido do Gabriel 22/09, "igual
  tem no relatório de vendas por item") — já vinha incluída desde a
  1ª versão (`_COLUNAS_FABRICANTE`/`_COLUNAS_LEVE3` em `apuracao.py`),
  só ficava em branco nos meses do Leve3 sem dado por dia ainda; depois
  do Leve3 ganhar maio-set por dia (mesmo dia), passou a sair 100%
  preenchida também (ex.: EMS, 2.460 linhas, 0 sem data). **Cabeçalho do
  arquivo (22/09/26):** Gabriel mandou foto do relatório "Análise de
  Venda por Item" do ERP e pediu o mesmo cabeçalho no arquivo de
  apuração — título + "Período: dd/mm/aaaa hh:mm:ss a dd/mm/aaaa
  hh:mm:ss" antes da tabela. `escrever_excel_apuracao`/`periodo_texto`
  (`apps/ofertas/apuracao.py`, usado tanto pelo botão quanto pelo
  management command) escreve linha 1 = "Apuração <oferta>", linha 2 =
  "Período: dd/mm/aaaa a dd/mm/aaaa", linha 3 = cabeçalho das colunas.
  **Correção (mesmo dia):** a 1ª versão usava o mês-calendário inteiro
  (dia 1 ao último dia) quando veio `?mes=` — Gabriel corrigiu: "o
  cabeçalho tem que ser a data da ação", a promoção roda só numa janela
  dentro do mês (ex. Procter Semana do Cliente: 15 a 20/09, não o mês
  inteiro). `periodo_texto` agora ignora o filtro de mês pro cabeçalho e
  usa sempre a data mín/máx REAL das linhas exportadas.
  **Revisão do modelo (22/09/26, mesmo dia):** Gabriel perguntou se
  aquele modelo era mesmo o melhor pra mandar pra indústria. Achado
  real ao reler o arquivo: as colunas Custo/Lucro/Desconto iam junto
  sem necessidade nenhuma (a fórmula do Procter é só `Itens × Valor da
  Rebaixa`, não usa Custo/Lucro pra nada) — **isso vazava a margem da
  Velanes pro fabricante**, sem servir de justificativa pro valor
  cobrado. Removidas as 3 colunas dos 2 modelos (`_COLUNAS_FABRICANTE`/
  `_COLUNAS_LEVE3`, `montar_apuracao_industria`/`montar_apuracao_leve3`)
  — Leve3 manteve só "Custo Unitário (R$)" (esse sim é a base da fórmula
  ciclos × custo). Também faltava total nenhum no arquivo (2 mil linhas,
  quem recebe teria que somar na mão) — `escrever_excel_apuracao` ganhou
  uma linha "TOTAL" no rodapé (Itens/Venda/Ciclos/Investimento, com
  borda no topo). **Achado ao testar a linha de TOTAL:** somar a coluna
  Investimento (R$) já arredondada linha a linha deu R$7.698,42 em vez
  de R$7.698,48 — mesmo bug de precisão já corrigido antes (arredondar
  cada linha e DEPOIS somar ≠ somar em precisão cheia e arredondar só no
  fim); corrigido usando `dados['total_investimento']` (já vem em
  precisão cheia) só nessa célula, em vez de somar a coluna do
  DataFrame. Testado ao vivo pelo botão real do painel — cabeçalho,
  colunas e total todos batendo.
- **Coluna "Loja" removida (22/09/26, mesmo dia).** Gabriel: "para enviar
  pra indústria, não preciso da loja" — o código da loja é só um número
  interno (ex. "2"), não significa nada fora da Velanes. Removida dos 2
  modelos, mantida só "Bandeira" (Velanes/Ultra Popular, essa sim pode
  interessar à indústria).
- **Seção redesenhada no painel (22/09/26, mesmo dia).** Gabriel achou os
  botões antigos (linkzinhos soltos empilhados no topo da página) feios
  e confusos. 2 rodadas de prévia (Artifact) até chegar no formato: card
  grande no topo → rejeitado ("mostrar grande assim, logo no início está
  muito feio") → virou **seção retrátil no FIM da página**
  (`<details id="apuracao-industria">`, depois de tudo — tabelas de
  produtos/impacto incluídas), com um linkzinho `↓ Apuração para a
  indústria` pertinho do título, no topo, que rola a página até lá
  (`<a href="#apuracao-industria">`) — visível mas discreto, sem
  precisar caçar. Virou TABELA (reaproveita `.tabela-interativa`/
  `tfoot .linha-total` já existentes, não CSS novo): 1 linha por
  fabricante/campanha com nome, período, nº de linhas, **investimento já
  calculado** (sem abrir o Excel) e o botão de baixar. `apps/ofertas/
  apuracao.py`: `resumo_apuracao_leve3`/`resumo_apuracao_industria`
  (reaproveitam `montar_apuracao_leve3`/`montar_apuracao_industria` +
  `periodo_texto`, 1 chamada por fabricante/campanha — aceitável, são
  poucos). Partial `templates/ofertas/_apuracao_industria.html`
  compartilhado entre `leve3.html` e `impacto_fabricante.html`. Só
  aparece (link + seção) quando há algo pra mostrar — Kenvue/Principia/
  Botica (sem fórmula ainda) não têm nem o link.
- **Bug real: linha de destaque (drill-down) travava achatada — corrigido
  (22/09/26).** Gabriel notou: "quando eu seleciono um item, a linha fica
  a cima das barras" — na prática a linha ficava ACHATADA no fundo do
  gráfico (valor 0) em vez de subir pro valor real do produto. Causa:
  `iniciarDrillDown` (`static/js/graficos.js`) chamava `chart.update()`
  com animação (padrão do Chart.js) depois de empurrar o novo dataset —
  a animação que devia levar a linha de y=0 até o valor certo às vezes
  não chegava a rodar/terminar (`requestAnimationFrame` não dispara
  igual em toda aba/contexto), deixando a linha travada no frame
  inicial pra sempre. Não era bug novo desta sessão nem específico do
  Leve3 — reproduzido também no Kenvue (gráfico antigo, nunca mexido).
  Corrigido trocando pra `chart.update('none')` (aplica a posição final
  na hora, sem depender de animação nenhuma) nos 2 pontos de
  `iniciarDrillDown` (ativar e desativar destaque). Testado ao vivo:
  Kenvue e Leve3, linha sobe/desce de verdade agora, desmarcar também
  funciona.
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
- **Backup de código + dado — resolvido (16/09/26).** Repositório não
  tinha remoto (só commits locais); criado
  https://github.com/gabrielvelanes-coder/monitor-de-ofertas e enviado
  todo o histórico. Novo `backup_tudo.py` (`python backup_tudo.py`,
  roda manual, sem Tarefa Agendada) copia `db.sqlite3` (via backup API
  do SQLite, seguro com o banco em uso) e tudo em `dados/entrada/`
  (nunca vão pro Git) pra `OneDrive\Área de Trabalho\BACKUPS DB\
  painel-ofertas\` — mantém os 10 bancos e as 5 rodadas de dado mais
  recentes. Mesmo processo já aplicado no Monitor de Preço de Mercado e
  no Monitor de Perdas no mesmo dia.
