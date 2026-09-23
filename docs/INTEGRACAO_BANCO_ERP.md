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
| Botica | ⚠️ +0,22% (jan-jul; ago-set e oferta batem 100%) | ❌ Não |
| Procter | não configurada ainda | ❌ |
| Leve 3, Kimberly, Cestões, Marketing, Supra Corp, Deu a Louca/Ultra Queimão, Sellout | não configuradas ainda | ❌ |

Backup do painel antes da 1ª gravação: `db.sqlite3.bak-antes-banco`
(para voltar: fechar o painel e copiar esse arquivo por cima de `db.sqlite3`).

## Próximos passos

1. **Conferir o painel** (telas Kenvue e Principia, ambas já gravadas do banco).
2. **Botica**: o banco achou 2 fabricantes, `BOTICA` e `BOTICA LA PIEL`.
   Suspeita: a planilha foi exportada só com `BOTICA`. Rodar no DBeaver a
   venda mensal por fabricante (`pf.nome ILIKE '%BOTICA%'`) e ver se
   `BOTICA LA PIEL` jan/26 = R$ 191,62. Depois o Gabriel decide: só
   `BOTICA` (igual planilha) ou incluir La Piel. Ajuste é trocar o filtro
   em `MECANICAS['botica']` (ou aceitar lista de fabricantes).
3. **Procter**: 2 campanhas no mesmo fabricante (mensal
   `PROMOÇÃO PROCTER` + `OFERTAS PROCTER SEMANA DO CLIENTE`), hoje
   importadas de arquivos separados com `escopo_delete='arquivo'`.
   Precisa tratamento próprio (1 consulta, 2 tags).
4. **Botão "Atualizar agora"** no painel (roda o incremental das
   mecânicas liberadas).
5. **Atualização automática 1x por dia** (decidido com o Gabriel: todo
   dia de manhã, ex. 6h) via Agendador de Tarefas do Windows:
   `.venv\Scripts\python manage.py importar_do_banco todas --dias 7`.
   O computador precisa estar ligado no horário.
6. Demais mecânicas (Leve 3, Kimberly, Cestões, Marketing, etc.), uma a
   uma, sempre com `--comparar` antes de gravar. Cadernos de oferta,
   produtos e itens de caderno também estão no banco
   (`cadernooferta`, `itemcadernooferta`, `unidadenegocioparticipantecadernooferta`)
   — dá pra substituir planilhas de cadastro no futuro.
