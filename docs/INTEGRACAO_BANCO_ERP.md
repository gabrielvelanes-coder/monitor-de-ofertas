# Integração direta com o banco do ERP (em andamento)

Objetivo: o painel parar de depender de .xls exportados à mão ("Análise de
Venda por Item") e buscar os dados direto do banco do ERP. Iniciado em
23/09/26 com o Gabriel.

## Banco

- PostgreSQL. Host `cli-1807.ddns.a7cloud.net.br`, porta `5432`, banco
  `drogariavelanes_esc`, usuário `leitura_velanes` (**somente leitura**,
  criado pelo TI).
- Senha fica só no arquivo `.env` na raiz do projeto (fora do Git, ver
  `.env.exemplo`). É a mesma senha usada no DBeaver.
- A conexão do painel é aberta com `default_transaction_read_only=on`
  (segunda trava: o PostgreSQL recusa qualquer gravação) e
  `statement_timeout` de 10 min.
- Ferramenta para explorar o banco: **DBeaver** (SSMS não serve, é só
  SQL Server).

## Mapeamento relatório .xls -> banco (validado)

| Coluna do relatório | Banco |
|---|---|
| Cód. Un. Neg. | `itemvenda.unidadenegocioid` -> `unidadenegocio.codigo` |
| Data | `itemvenda.datahora::date` |
| Embalagem | `itemvenda.embalagemid` -> `embalagem.descricao` |
| Código de barras | `embalagem.codigobarras` |
| Detalhe Desconto / Cad. Oferta | `itemvenda.cadernoofertaid` -> `'Cad. Oferta: ' \|\| cadernooferta.nome`; sem caderno = `'Sem Desconto'` |
| Itens / Venda / Desconto | `itemvenda.quantidade` / `valortotal` / `desconto` |
| Custo | `itemvenda.quantidade * movimentacaoestoque.custo` (via `itemvenda.movimentacaoestoqueid`) |
| Lucro | Venda - Custo |
| Fabricante | `embalagem.produtoid` -> `produto.fabricanteid` -> `fabricante.pessoaid` -> `pessoa.nome` |
| Loja (nome) | `unidadenegocio.nomefantasia` (ou `nome`) |

**Filtros obrigatórios** (iguais ao relatório do ERP):

- `venda.status = 'F'` — venda finalizada. Outros status vistos: `C`
  (cancelada), `G` e `D` (significado a confirmar com o TI/suporte).
- `itemvenda.status = 'F'` — item finalizado. `C`/`D` = item cancelado/
  devolvido dentro de venda finalizada. **Sem esse filtro o banco dá
  +0,3% a mais** (Kenvue jan/26: C+D = R$ 707,25, exatamente a diferença).

Consulta completa em `apps/ofertas/erp_banco.py` (`CONSULTA_VENDA_POR_ITEM`).

## O que foi implementado

- `apps/ofertas/erp_banco.py` (novo): conexão somente leitura +
  `consultar_venda_por_item(inicio, fim, fabricante_like)`, devolve
  DataFrame com as mesmas colunas normalizadas de `erp.ler_relatorio_erp`.
- `apps/ofertas/management/commands/importar_do_banco.py` (novo):
  - `importar_do_banco <mecanica> --comparar` — compara banco x painel
    mês a mês (venda/custo/itens/oferta). **Não grava nada.**
  - `importar_do_banco <mecanica>` — carga completa desde 01/01/2026 até
    ontem, substitui os lançamentos da mecânica (`arquivo_origem='banco'`).
  - `importar_do_banco <mecanica> --dias N` — incremental: refaz só os
    últimos N dias (apaga/recria `data >= hoje-N`), mantém o histórico.
  - `importar_do_banco todas ...` — todas as mecânicas liberadas.
  - Mecânicas configuradas: `kenvue`, `principia`, `botica`.
- `apps/ofertas/importadores.py`: `importar_relatorio_fabricante` aceita
  `df=`, `origem=` e `desde=` (dados do banco / incremental). O fluxo por
  .xls continua funcionando igual.
- `requirements.txt`: `psycopg[binary]>=3.2`. `.gitignore`: `.env`.

Como rodar (PowerShell, na pasta `painel-ofertas`, sem precisar ativar o venv):

```
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python manage.py importar_do_banco kenvue --comparar
```

## Status (23/09/26)

| Mecânica | Comparação banco x planilha | Gravado do banco? |
|---|---|---|
| Kenvue | ✅ 0,00% em todos os meses (R$ 1.438.523,71) | ✅ Sim — 44.036 lançamentos, dados até 22/09 |
| Principia | ✅ 0,00% em todos os meses (R$ 350.294,05) | ✅ Sim — 6.386 lançamentos (fabricante PRINCIPIA SKINCARE), dados até 22/09 |
| Botica | Grupo redefinido — ver nota abaixo | ✅ Sim — 20.056 lançamentos, dados até 22/09 |
| Procter | ✅ 0,00% em todos os meses (R$ 1.726.074,65), oferta 0,00% | ✅ Sim — 60.647 lançamentos, dados até 22/09 |
| Marketing | ✅ 0,00% em agosto (único mês que a planilha tinha) | ✅ Sim — 80.494 lançamentos, jan-set/26 inteiro (planilha só tinha agosto) |
| Cestões | ~10% (1 produto novo no banco) — ver nota abaixo | ✅ Sim — 62.187 lançamentos, dados até 22/09 |
| Leve 3 | ✅ 0,00% em maio/junho/agosto, diferenças pequenas nos meses de borda | ✅ Sim — 4.743 lançamentos, dados até 22/09 |
| Kimberly | ✅ 0,00% em jan-ago, filtro manual Hipzinha validado (35 linhas/R$2.095,50) | ✅ Sim — 11.691 lançamentos, dados até 22/09 |
| Supra Corp | ✅ 0,00% em agosto | ✅ Sim — 998 lançamentos, jan-set/26 (planilha só tinha ago/set) |
| Sellout (EMS/Eurofarma/Germed/Prati) | Germed/Prati 0,00%; EMS/Eurofarma maiores no banco (planilha truncada, ver nota) | ✅ Sim — 69.019+65.451+32.293+61.169 lançamentos, dados até 22/09 |
| Deu a Louca/Ultra Queimão | ⚠️ oferta 0,00%, base 5-12x maior — **BLOQUEADO**, ver nota abaixo | ❌ Não (aguardando o Gabriel) |

**Botica — achado e decisão (23/09/26):** o banco tem 4 fabricantes que batem
`%BOTICA%`/relacionados: `BOTICA`, `BOTICA LA PIEL`, `SIAGE EUDORA`, `VULT`.
A planilha histórica só cobria `BOTICA` sozinho (validado: bank-só-BOTICA de
jan/26 = R$45.221,97 = exatamente o valor da planilha). Perguntado ao
Gabriel, ele confirmou: o grupo certo é **Botica + Siage + Vult** — `BOTICA
LA PIEL` (R$191,62 em jan/26) fica de fora, é outro fabricante. Conferido
que Siage e Vult carregam de fato a mesma tag `OFERTAS BOTICA` (ex. Siage
R$14.425,90 em oferta em março/26) — não é erro de dado, é campanha nacional
cobrindo as 3 marcas. `MECANICAS['botica']` em `importar_do_banco.py` usa
lista de nomes exatos (`pf.nome = ANY(...)`) em vez do padrão ILIKE único —
`consultar_venda_por_item` (`erp_banco.py`) aceita os dois formatos agora.
Rótulo no painel mudou de "Botica Nacional" pra "Botica" (o "Nacional" era
só o nome de 1 das 3 tags, ficou confuso agora que a tela cobre os 3
fabricantes). Carga completa gravada (20.056 lançamentos, substituindo os
3.598 da planilha antiga).

**Procter — achado e decisão (23/09/26):** o banco tem `PROCTER & GAMBLE`
e `PROCTER FARMA` separados. Diferente do Botica/Siage/Vult, `PROCTER
FARMA` (R$42mil em jan/26 sozinho, valor real, não desprezível) **não
carrega nenhuma das 2 tags de oferta em nenhum mês** (jan-set/26
conferido) — não participa da promoção, então fica de fora sem precisar
perguntar ao Gabriel (a própria ausência de tag já responde). As 2
campanhas (`PROMOÇÃO PROCTER` mensal + `OFERTAS PROCTER SEMANA DO
CLIENTE`) saem da MESMA consulta agora — `tag_alvo` como lista (mesmo
mecanismo do Botica) separa automaticamente por `tag_origem` na tela,
substitui o fluxo antigo de 2 arquivos/2 comandos com
`escopo_delete='arquivo'`. Validado: apuração da Semana do Cliente
continua batendo 189 linhas/R$650,00 de investimento (RebaixaProduto),
idêntico a antes do import do banco.

**Marketing — achado e decisão (23/09/26):** mecânica diferente das 4
anteriores — não é de 1 fabricante, filtra pelo nome do caderno de oferta
("PRODUTOS MARKETING <mês>"). `importar_do_banco` generalizado com um
"tipo" (`'fabricante'` vs `'tag'`) — tipo `'tag'` usa `consultar_venda_por_tag`
(filtro `co.nome ILIKE`, qualquer fabricante) e `importar_relatorio_fabricante`
com `fabricante=None` (usa o fabricante por linha do banco, já que a
mecânica espalha por ~65 fabricantes diferentes). Validado: agosto bate
0,00% com a planilha antiga (único mês que ela tinha). **Achado bom:** o
banco já tem jan-set/26 inteiro (80.494 linhas) — resolve de graça a
pendência registrada em 17/09/26 ("Marketing só tem 1 mês, preciso o
Gabriel mandar mais"), sem precisar pedir nada a ele.

**Cestões — achado e decisão (23/09/26):** 3º tipo de mecânica, nenhum
fabricante fixo, produto identificado pela tag em vez do fabricante —
1ª passada acha os produtos (Embalagem) que já tiveram a tag "OFERTAS
CESTAO" (histórico COMPLETO, não só a janela pedida), 2ª passada traz o
histórico inteiro desses produtos exatos, com ou sem a tag, qualquer
fabricante (`consultar_venda_por_produtos`, `importar_do_banco` tipo
`'produtos_com_tag'`). **Achado real:** filtro com wildcard (`%CESTAO%`)
também pegava "CESTAO PREÇO UNICO LOJA NN" — caderno de OUTRO projeto do
Grupo Velanes ("Cestão Preço Único", ferramenta separada, nada a ver com
esta mecânica), inflava de 24 pra 1.843 produtos e a venda de R$2,4M pra
R$6,9M. Corrigido pra ILIKE exato ("OFERTAS CESTAO", sem `%`). Validado:
banco achou 24 produtos vs 23 do painel antigo — 1 a mais (TOALHA UMED
SUPRABABY 140UNID) que entrou em cestão depois da última exportação da
planilha, explica a diferença de ~10% no histórico (o produto novo soma
em TODOS os meses porque a mecânica sempre traz o histórico inteiro de
quem está em cestão hoje). Gravado: 62.187 lançamentos.

**Leve 3 — achado e decisão (23/09/26):** 4º tipo de mecânica, parecido
com o `'tag'` do Marketing (filtra pelo padrão do caderno de oferta,
"LEVE 3", só 2 variações no banco — sem risco de decoy tipo Cestões).
**Achado real:** o fabricante que o banco traz (razão social, ex. "EMS
GENERICO S/A") não serve — o resto do painel (Sellout, `calcular_
impacto_leve3_fabricante`) espera o rótulo curto do cadastro
`apps.produtos` ("EMS"). `importar_do_banco` remapeia a coluna
`fabricante` do df via `mapa_fabricantes()` (com a heurística antiga
como fallback) antes de importar. `sincronizar_verba_leve3()` chamado no
fim, igual o importador antigo fazia. Validado: 0,00% em maio/junho/
agosto, diferenças pequenas nos meses de borda (jul +0,28%, set -3,54%,
explicado pelo corte do `--comparar`). Testado ao vivo: tela, seção de
apuração e download por fabricante funcionando. Gravado: 4.743
lançamentos, verba resincronizada em 5 meses.

**Kimberly — achado e decisão (23/09/26):** 5º tipo, 1 fabricante só
(como Kenvue/Principia), mas SEM tag limpa de oferta no ERP pra
"Hipzinha" (achado antigo, não documentado no docx) — "oferta" é um
filtro manual (produto contém "HIPZINHA", venda da linha ≤ R$60, janela
27/07-02/08/2026), não uma tag. `importar_relatorio_fabricante` ganhou
`classificar_grupo` (função opcional `linha -> grupo` que substitui a
classificação por tag quando passada) — só o Kimberly usa. **Achado
real:** o banco tem 3 fabricantes candidatos (`KIMBERLY CLARK KENKO`,
`KLABIN KIMBERLY S/A`, `KLABIN KIMBERLY SA`), mas só o 1º tem venda no
ano inteiro — nome exato já resolve, sem precisar de lista. Validado: o
filtro manual bate exato com o backfill de 22/09/26 (35 linhas,
R$2.095,50); venda total 0,00% em jan-ago. Gravado: 11.691 lançamentos.

**Supra Corp Day — achado e decisão (23/09/26):** 6º tipo, nem
fabricante nem tag. **Achado real:** "Supra Corp" é o nome comercial de
TODA a linha de suplementos/vitaminas da `CATARINENSE` no ERP (68
produtos distintos), mas a mecânica (degustação) só rastreia 5 SKUs
específicos (whey/creatina) — lista fixa, sem tag nenhuma pra descobrir
sozinho (diferente do Cestões). `consultar_venda_por_produtos` com os 5
nomes exatos hardcoded, sem passada de descoberta antes. Validado:
agosto bate 0,00% exato. O banco traz o ano inteiro (esses produtos
vendem fora de evento também, sem problema — `JANELAS_SUPRACORP` só
define janela pros meses com evento, cálculo de impacto é por mês).
Gravado: 998 lançamentos.

**Sellout — achado e decisão (23/09/26):** 8º tipo, variante de
`'fabricante'` sem split oferta/base (é referência de giro pro impacto do
Leve3, `tags: []`). **Achado real:** cada marca tem várias variações de
fabricante no ERP (ex. `EMS`, `EMS GENERICO S/A`, `EMS SIGMA`) —
resolvido batendo os produtos já canônicos do cadastro `apps.produtos`
(usados no Leve3) contra o fabricante real deles no banco: todos caem em
`EMS GENERICO S/A` (idem Eurofarma → `EUROFARMA GENERICO`; Germed/Prati
sem variação, nome exato mesmo). `escopo_delete='mecanica_fabricante'`
novo em `importar_relatorio_fabricante` — 1 mecânica (`SELLOUT`), 4
fabricantes coexistindo, reimportar 1 não apaga os outros 3. Validado:
Germed/Prati batem 0,00% quase todo mês; EMS/Eurofarma ficam 10-36%
MAIORES no banco — confirma o achado já documentado (22/09/26: a
planilha antiga batia no teto de 65.536 linhas do Excel, dado truncado;
o banco corrige isso de graça). Gravado: 69.019 (EMS) + 65.451
(Eurofarma) + 32.293 (Germed) + 61.169 (Prati) lançamentos.

**Deu a Louca/Ultra Queimão — investigado, BLOQUEADO PRA GRAVAÇÃO
(23/09/26):** tentativa de tipo `'promocao_bandeira'` (como Cestões, mas
restrito a 1 bandeira via código de loja — `consultar_venda_por_
produtos_e_lojas` nova). `--comparar` mostra "oferta" batendo 0,00%
exato (a identificação da tag está certa — achado à parte, cuidado:
histórico do ERP tem cadernos "QUEIMA DE ESTOQUE"/"QUEIMÃO INAUGURAÇÃO
DERMO JAGUAQUARA" de 2024/2025, evento de loja diferente, que bateriam
num padrão `%QUEIM%` largo demais — confirmado que nenhum tem venda em
2026, sem risco na prática). Mas "base" fica 5-12x maior que a planilha
em todo mês. Investigado a fundo: os arquivos que o Gabriel mandou pra
jun-ago (`deu a louca ano - com loja.xls`) vieram JÁ FILTRADOS só com
linhas de oferta (100% grupo=oferta nesses 3 meses, achado documentado
em 17/09/26 — não tinham base nenhuma pra comparar); o único mês com
base real (set/26, arquivo "detalhe") tem só 105 produtos, MENOS que os
194 que a própria tag já revela no histórico completo — ou seja, nem
"produtos que já tiveram a tag" (mesma lógica do Cestões) bate com o
recorte real que ele historicamente comparou. `importar_promocao_
bandeira` (código antigo) documenta "base = todo o resto do portfólio
da bandeira", mas isso nunca foi exportado de verdade — o catálogo
INTEIRO de 1 bandeira seria centenas de milhares de linhas/mês.
**Não implementado — falta perguntar ao Gabriel** o que define o recorte
de "base" que ele quer pra essas 2 mecânicas antes de gravar qualquer
coisa. Código novo (`consultar_venda_por_produtos_e_lojas`, tipo
`'promocao_bandeira'` em `importar_do_banco.py`) já existe e funciona
pra descoberta/comparação, só falta decidir o escopo certo.

Backup do painel antes da 1ª gravação: `db.sqlite3.bak-antes-banco`
(para voltar: fechar o painel e copiar esse arquivo por cima de `db.sqlite3`).

## Próximos passos

1. **Conferir o painel** (telas Kenvue, Principia, Botica, Procter,
   Marketing, Cestões, Leve 3, Kimberly, Supra Corp e Sellout, já
   gravadas do banco).
2. ~~Botica~~ — resolvido, ver nota acima (grupo Botica+Siage+Vult, gravado).
3. ~~Procter~~ — resolvido, ver nota acima (2 campanhas numa consulta só via
   `tag_alvo` em lista, `PROCTER FARMA` fica de fora, gravado).
3b. ~~Marketing~~ — resolvido, ver nota acima (tipo `'tag'` novo,
   `fabricante=None`, jan-set/26 inteiro gravado).
3c. ~~Cestões~~ — resolvido, ver nota acima (tipo `'produtos_com_tag'`
   novo, achou 1 produto novo, gravado).
3d. ~~Leve 3~~ — resolvido, ver nota acima (tipo `'leve3'` novo, remapeia
   fabricante pro cadastro, verba resincronizada, gravado).
3e. ~~Kimberly~~ — resolvido, ver nota acima (tipo `'kimberly'` novo,
   `classificar_grupo` pro filtro manual da Hipzinha, gravado).
3f. ~~Supra Corp~~ — resolvido, ver nota acima (tipo `'produtos'` novo,
   lista fixa de 5 SKUs, gravado).
3g. ~~Sellout~~ — resolvido, ver nota acima (tipo `'fabricante'` sem
   oferta/base, `escopo_delete='mecanica_fabricante'` novo, 4 fabricantes
   gravados, EMS/Eurofarma corrigem o truncamento do Excel antigo).
3h. **Deu a Louca/Ultra Queimão — BLOQUEADO, ver nota acima.** Pergunta
   pro Gabriel: o que define quais produtos/lojas entram na comparação
   "base" dessas 2 mecânicas? (a) todo o catálogo da bandeira (centenas
   de milhares de linhas/mês — viável só via banco, nunca foi exportado
   assim); (b) só os ~200 produtos que já apareceram na tag alguma vez
   (testado, dá 5-12x mais venda que a planilha); (c) outro recorte
   específico que ele aplica na hora de exportar do ERP (categoria,
   departamento?) que não dá pra inferir só pelos dados.
4. ~~Botão "Atualizar agora"~~ — resolvido (23/09/26): botão no menu
   "Sistema" do painel, `views.atualizar_agora` roda `importar_do_banco
   todas --dias 7` na hora e mostra mensagem de sucesso/erro.
5. **Atualização automática 1x por dia** (decidido com o Gabriel: todo
   dia de manhã, 6h) via Agendador de Tarefas do Windows —
   `atualizar_diario.bat` (raiz do projeto) já criado e testado, roda
   `importar_do_banco todas --dias 7` e loga em `atualizacao_diaria.log`.
   **Falta só registrar a tarefa** (`Register-ScheduledTask` foi bloqueado
   pelo modo automático do Claude Code por mudar o sistema — ver instrução
   deixada pro Gabriel rodar com `!` ou pelo Agendador de Tarefas na UI).
   O computador precisa estar ligado no horário.
6. **Todas as 9 ações + Sellout já passaram pelo banco** (8 gravadas, 1
   bloqueada aguardando o Gabriel — item 3h). Cadernos de oferta,
   produtos e itens de caderno também estão no banco
   (`cadernooferta`, `itemcadernooferta`,
   `unidadenegocioparticipantecadernooferta`) — dá pra substituir
   planilhas de cadastro no futuro.
7. **Nota pra depois (não pedida ainda):** Marketing, Cestões e Leve 3
   nunca tiveram dado diário (`data`) antes do banco (só `ano_mes`) — agora
   têm, já que a consulta do banco sempre traz `data` por linha. As telas
   `marketing.html`/`cestoes.html` ainda não têm as abas Mês/Semana/Dia
   (`_abas_periodo.html`) que as outras já têm — dá pra ligar se o Gabriel
   quiser, é trabalho de UI, não de dado (Leve3 já tinha as abas desde
   22/09, usando o arquivo bruto por dia que ele mandou à parte).
