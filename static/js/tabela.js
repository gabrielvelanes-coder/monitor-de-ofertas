// Tabelas interativas: ordenar clicando no cabeçalho + filtro instantâneo,
// sem round-trip pro servidor. Aplica em qualquer <table class="tabela-interativa">.
(function () {
  function valorNumerico(texto) {
    // "R$ 1.234,56" / "1.234" / "12,3%" / "5,14×" -> número, ou null se não for número.
    var limpo = texto.replace(/[^0-9,.\-]/g, '').trim();
    if (!limpo) return null;
    limpo = limpo.replace(/\./g, '').replace(',', '.');
    var n = parseFloat(limpo);
    return isNaN(n) ? null : n;
  }

  function ordenarTabela(tabela, indiceColuna, asc) {
    var tbody = tabela.tBodies[0];
    var linhas = Array.prototype.slice.call(tbody.rows);
    var numerica = linhas.every(function (linha) {
      var celula = linha.cells[indiceColuna];
      return !celula || celula.textContent.trim() === '' || valorNumerico(celula.textContent) !== null;
    });

    linhas.sort(function (a, b) {
      var ta = a.cells[indiceColuna] ? a.cells[indiceColuna].textContent.trim() : '';
      var tb = b.cells[indiceColuna] ? b.cells[indiceColuna].textContent.trim() : '';
      var va = numerica ? (valorNumerico(ta) || 0) : ta.toLowerCase();
      var vb = numerica ? (valorNumerico(tb) || 0) : tb.toLowerCase();
      if (va < vb) return asc ? -1 : 1;
      if (va > vb) return asc ? 1 : -1;
      return 0;
    });

    linhas.forEach(function (linha) { tbody.appendChild(linha); });
  }

  function iniciarOrdenacao() {
    document.querySelectorAll('table.tabela-interativa').forEach(function (tabela) {
      var cabecalhos = tabela.tHead ? tabela.tHead.rows[0].cells : [];
      Array.prototype.forEach.call(cabecalhos, function (th, indice) {
        th.style.cursor = 'pointer';
        th.dataset.ordemAsc = 'true';
        th.addEventListener('click', function () {
          var asc = th.dataset.ordemAsc === 'true';
          Array.prototype.forEach.call(cabecalhos, function (outro) {
            outro.classList.remove('ordenado-asc', 'ordenado-desc');
          });
          th.classList.add(asc ? 'ordenado-asc' : 'ordenado-desc');
          ordenarTabela(tabela, indice, asc);
          th.dataset.ordemAsc = asc ? 'false' : 'true';
        });
      });
    });
  }

  function iniciarFiltro() {
    document.querySelectorAll('[data-filtro-tabela]').forEach(function (input) {
      var tabela = document.getElementById(input.dataset.filtroTabela);
      if (!tabela) return;
      input.addEventListener('input', function () {
        var termo = input.value.trim().toLowerCase();
        Array.prototype.forEach.call(tabela.tBodies[0].rows, function (linha) {
          linha.hidden = termo !== '' && linha.textContent.toLowerCase().indexOf(termo) === -1;
        });
      });
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    iniciarOrdenacao();
    iniciarFiltro();
  });

  // Alterna entre painéis (ex.: "por bandeira" vs. "loja a loja") sem
  // round-trip pro servidor: <a data-grupo="g" data-valor="x" onclick="alternarPainel(this)">
  // mostra só os elementos com data-painel="g" data-valor="x" dentro do mesmo <body>.
  window.alternarPainel = function (botao) {
    var grupo = botao.dataset.grupo, valor = botao.dataset.valor;
    document.querySelectorAll('[data-grupo="' + grupo + '"]').forEach(function (b) {
      b.classList.remove('ativa');
    });
    botao.classList.add('ativa');
    document.querySelectorAll('[data-painel="' + grupo + '"]').forEach(function (painel) {
      painel.hidden = painel.dataset.valor !== valor;
    });
  };
})();
