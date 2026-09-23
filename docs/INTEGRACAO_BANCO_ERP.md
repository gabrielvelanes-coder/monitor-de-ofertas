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
| Leve 3, Kimberly, Cestões, Marketing, Supra Corp, Deu a Louca/Ultra Queimão, Sellout | não configuradas ainda | ❌ |

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

Backup do painel antes da 1ª gravação: `db.sqlite3.bak-antes-banco`
(para voltar: fechar o painel e copiar esse arquivo por cima de `db.sqlite3`).

## Próximos passos

1. **Conferir o painel** (telas Kenvue, Principia, Botica e Procter, já gravadas do banco).
2. ~~Botica~~ — resolvido, ver nota acima (grupo Botica+Siage+Vult, gravado).
3. ~~Procter~~ — resolvido, ver nota acima (2 campanhas numa consulta só via
   `tag_alvo` em lista, `PROCTER FARMA` fica de fora, gravado).
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
6. Demais mecânicas (Leve 3, Kimberly, Cestões, Marketing, etc.), uma a
   uma, sempre com `--comparar` antes de gravar. Cadernos de oferta,
   produtos e itens de caderno também estão no banco
   (`cadernooferta`, `itemcadernooferta`, `unidadenegocioparticipantecadernooferta`)
   — dá pra substituir planilhas de cadastro no futuro.
