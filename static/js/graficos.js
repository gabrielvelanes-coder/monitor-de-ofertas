// Configuração comum dos gráficos Chart.js do painel — cada tela só monta
// os `labels`/`datasets` e chama uma destas funções.
(function () {
  var PALETA = ['#5b8def', '#ef9f5b', '#4fc493', '#e8628f', '#b48cf0'];
  var DESTAQUES = ['#e8628f', '#f0c419', '#8e6fe8', '#3ad6c9', '#ff8a5c', '#6fd66f'];

  // Tema escuro: Chart.js desenha em <canvas>, não herda o CSS da página —
  // configura texto/linhas de grade claros globalmente, antes de qualquer
  // gráfico ser criado.
  if (window.Chart) {
    Chart.defaults.color = '#8b93a1';
    Chart.defaults.borderColor = 'rgba(255,255,255,0.08)';
    Chart.defaults.scale.grid.color = 'rgba(255,255,255,0.08)';
  }

  function corDaSerie(indice) {
    return PALETA[indice % PALETA.length];
  }

  // Chart.js desenha texto em <canvas> — o text-transform:uppercase do CSS
  // não alcança, então maiusculiza aqui pra bater com o resto da UI.
  function maiuscula(texto) {
    return String(texto).toUpperCase();
  }

  // Mesma regra pt-BR do filtro `numero`/`brl` do Django (separador de
  // milhar '.', decimal ',') — Chart.js desenha em <canvas>, não existe
  // filtro de template lá, então replica em JS.
  function formatarNumeroBR(valor, casas) {
    if (typeof casas === 'undefined') casas = 0;
    if (valor === null || typeof valor === 'undefined' || isNaN(valor)) return '';
    var negativo = valor < 0;
    valor = Math.abs(valor);
    var partes = valor.toFixed(casas).split('.');
    var inteiro = partes[0];
    var fracao = partes[1];
    var grupos = [];
    while (inteiro.length > 3) {
      grupos.unshift(inteiro.slice(-3));
      inteiro = inteiro.slice(0, -3);
    }
    grupos.unshift(inteiro);
    var texto = grupos.join('.');
    if (casas) texto += ',' + fracao;
    return (negativo ? '-' : '') + texto;
  }
  window.formatarNumeroBR = formatarNumeroBR;

  function formatarEixo(eixo, valor) {
    return eixo === 'unidades' ? formatarNumeroBR(valor, 0) : ('R$ ' + formatarNumeroBR(valor, 0));
  }

  function formatarTooltip(eixo, valor) {
    return eixo === 'unidades' ? formatarNumeroBR(valor, 0) : ('R$ ' + formatarNumeroBR(valor, 2));
  }

  // Monta as datasets + escalas (moeda à esquerda, unidades à direita,
  // sem grade pra não poluir) a partir de `series` no formato
  // {label, data, eixo}` — `eixo` vem do back-end (`grafico_mensal`),
  // 'moeda' quando omitido.
  function montarDatasetsEEscalas(series, tipoGrafico, destaqueIndices) {
    var usaEixoUnidades = series.some(function (s) { return s.eixo === 'unidades'; });
    var datasets = series.map(function (s, i) {
      var eixo = s.eixo || 'moeda';
      var base = {
        label: maiuscula(s.label),
        data: s.data,
        yAxisID: eixo === 'unidades' ? 'y1' : 'y',
        borderColor: corDaSerie(i),
        backgroundColor: corDaSerie(i),
      };
      if (tipoGrafico === 'line') {
        base.tension = 0.25;
        base.pointRadius = 3;
      } else if (tipoGrafico === 'bar' && destaqueIndices && series.length === 1) {
        base.backgroundColor = s.data.map(function (_, idx) {
          return destaqueIndices.indexOf(idx) !== -1 ? '#ef9f5b' : '#5b8def';
        });
      }
      return base;
    });

    var scales = {
      y: {
        beginAtZero: true,
        ticks: { callback: function (v) { return formatarEixo('moeda', v); } },
      },
    };
    if (usaEixoUnidades) {
      scales.y1 = {
        beginAtZero: true,
        position: 'right',
        grid: { drawOnChartArea: false },
        ticks: { callback: function (v) { return formatarEixo('unidades', v); } },
      };
    }
    return { datasets: datasets, scales: scales };
  }

  // Callback de tooltip precisa vir DENTRO da config passada a `new
  // Chart(...)` — Chart.js v4 resolve `options` (inclusive callbacks) num
  // objeto mesclado com os defaults na hora da construção; mutar
  // `chart.options...callbacks` depois não pega. Por isso fecha sobre um
  // array (`seriesInfo`) declarado ANTES do chart existir — o drill-down
  // grava nesse mesmo array por referência (`chart._seriesInfo`), então
  // series adicionadas depois também ficam formatadas certo.
  function callbackTooltip(seriesInfo) {
    return function (contexto) {
      var info = seriesInfo[contexto.datasetIndex] || {};
      return contexto.dataset.label + ': ' + formatarTooltip(info.eixo || 'moeda', contexto.parsed.y);
    };
  }

  window.graficoLinha = function (canvasId, labels, series) {
    var elemento = document.getElementById(canvasId);
    if (!elemento) return null;
    var montado = montarDatasetsEEscalas(series, 'line');
    var seriesInfo = series.slice();
    var chart = new Chart(elemento, {
      type: 'line',
      data: { labels: labels.map(maiuscula), datasets: montado.datasets },
      options: {
        responsive: true,
        plugins: {
          legend: { display: series.length > 1, position: 'bottom' },
          tooltip: { callbacks: { label: callbackTooltip(seriesInfo) } },
        },
        scales: montado.scales,
      },
    });
    chart._seriesInfo = seriesInfo;
    return chart;
  };

  // Drill-down: clicar numa linha da tabela (produto, fabricante...)
  // acrescenta/remove uma série extra destacada no gráfico com a série
  // mensal daquele item — várias linhas podem ficar marcadas ao mesmo
  // tempo (clicar de novo na mesma linha desmarca só ela). Devolve
  // true/false (ativou/desativou) pra tela colorir a linha da tabela.
  // `seriesPorItem` = {nome: [valores por mês]}.
  //
  // O destaque usa uma escala PRÓPRIA (`yDestaque`, escondida) em vez da
  // escala de moeda do gráfico de fundo: 1 produto/loja é uma fração
  // pequena do total (venda base/oferta somada), então na mesma escala a
  // linha destacada ficava achatada perto do zero — parecia que o clique
  // não fazia nada. Com escala própria, a forma/evolução da linha aparece
  // de verdade; o valor real (R$) continua certo no tooltip.
  // `ocultarBaseEnquantoAtivo`: telas com gráfico de fundo já cheio (4
  // séries, 2 escalas — ex. impacto por fabricante: venda base/oferta ×
  // itens base/oferta) ficam ilegíveis com a linha de destaque em cima
  // (achado real: Gabriel clicou numa campanha e "não consigo entender
  // nada" — a linha de destaque usa escala própria escondida, então
  // "sobe" até o topo do gráfico sem relação nenhuma com os números dos
  // 2 eixos visíveis). Quando `true`, esconde as séries que já existiam
  // no gráfico ANTES do 1º clique enquanto houver pelo menos 1 item
  // destacado — volta a mostrar quando desmarcar todos. Telas com
  // gráfico mais simples (Leve3: só Venda × Itens) não passam esse
  // parâmetro, mantém o comportamento de sempre.
  window.iniciarDrillDown = function (chart, seriesPorItem, rotuloMetrica, ocultarBaseEnquantoAtivo) {
    var ativos = {};
    var qtdSeriesBase = chart.data.datasets.length;

    function atualizarVisibilidadeBase() {
      if (!ocultarBaseEnquantoAtivo) return;
      // Lê o tamanho do array inteiro (não só `ativos` deste closure) --
      // produto e campanha usam `iniciarDrillDown` em separado no mesmo
      // `chart`; qualquer destaque de qualquer um dos dois soma nele, e a
      // base só pode voltar a aparecer quando NENHUM dos dois tiver nada
      // marcado.
      var algumAtivo = chart.data.datasets.length > qtdSeriesBase;
      for (var i = 0; i < qtdSeriesBase; i++) {
        chart.setDatasetVisibility(i, !algumAtivo);
      }
    }

    return function (nome) {
      var rotulo = maiuscula(rotuloMetrica ? nome + ' — ' + rotuloMetrica : nome);
      if (ativos[nome]) {
        var i = chart.data.datasets.indexOf(ativos[nome].dataset);
        if (i !== -1) chart.data.datasets.splice(i, 1);
        chart._seriesInfo.splice(i, 1);
        delete ativos[nome];
        chart.options.plugins.legend.display = chart.data.datasets.length > 1;
        atualizarVisibilidadeBase();
        chart.update();
        return false;
      }
      if (seriesPorItem[nome]) {
        if (!chart.options.scales.yDestaque) {
          chart.options.scales.yDestaque = { display: false, beginAtZero: true };
        }
        var cor = DESTAQUES[Object.keys(ativos).length % DESTAQUES.length];
        var dataset = {
          // `type: 'line'` explícito -- o gráfico de fundo virou barra
          // (22/09/26), sem isso o destaque nasceria como barra também
          // (Chart.js segue o tipo do gráfico quando o dataset não diz o
          // seu próprio), ficando confuso em cima de outras barras.
          type: 'line',
          label: rotulo, data: seriesPorItem[nome],
          borderColor: cor, backgroundColor: cor, yAxisID: 'yDestaque',
          borderWidth: 3, tension: 0.25, pointRadius: 4,
        };
        chart.data.datasets.push(dataset);
        chart._seriesInfo.push({ label: rotulo, eixo: 'moeda' });
        ativos[nome] = { dataset: dataset };
      }
      chart.options.plugins.legend.display = true;
      atualizarVisibilidadeBase();
      chart.update();
      return true;
    };
  };

  // Clicar num mês do gráfico de evolução mensal aplica o mesmo filtro
  // "Mês" da barra de topo (<select id="mes">, já existe em toda tela de
  // ação) sem precisar abrir o seletor — reenvia o mesmo form, que já
  // preserva bandeira/fabricante/busca via querystring_extra. `labelsOriginais`
  // são os valores AAAA-MM crus (`dados.labels`, antes do `.map(maiuscula)`
  // que só afeta o que aparece desenhado no eixo).
  window.ativarCliqueMes = function (chart, labelsOriginais) {
    var select = document.getElementById('mes');
    if (!select) return;
    chart.canvas.style.cursor = 'pointer';
    chart.options.onClick = function (evento) {
      var pontos = chart.getElementsAtEventForMode(evento, 'index', { intersect: false }, true);
      if (!pontos.length) return;
      var mes = labelsOriginais[pontos[0].index];
      if (!mes) return;
      select.value = mes;
      select.form.submit();
    };
  };

  window.graficoBarra = function (canvasId, labels, series, destaqueIndices) {
    var elemento = document.getElementById(canvasId);
    if (!elemento) return null;
    var montado = montarDatasetsEEscalas(series, 'bar', destaqueIndices);
    var seriesInfo = series.slice();
    var chart = new Chart(elemento, {
      type: 'bar',
      data: { labels: labels.map(maiuscula), datasets: montado.datasets },
      options: {
        responsive: true,
        plugins: {
          legend: { display: series.length > 1, position: 'bottom' },
          tooltip: { callbacks: { label: callbackTooltip(seriesInfo) } },
        },
        scales: montado.scales,
      },
    });
    chart._seriesInfo = seriesInfo;
    return chart;
  };

  // Venda por semana, semana(s) com oferta destacada + % de crescimento
  // escrito em cima da barra (pedido 22/09/26 -- "preciso VER no gráfico
  // o impacto, o realizado"; preview aprovado comparando com o gráfico de
  // linha mensal de sempre). `semanas` = lista de {inicio, fim, venda,
  // tem_oferta, crescimento_pct}, já vem pronta do back-end
  // (`serie_semanal`, services.py) -- aqui só desenha.
  var COR_NORMAL = '#5b8def', COR_DESTAQUE = '#e8628f';

  function rotuloSemana(semana) {
    var d = new Date(semana.inicio + 'T00:00:00');
    return (d.getDate() < 10 ? '0' : '') + d.getDate() + '/' + (d.getMonth() < 9 ? '0' : '') + (d.getMonth() + 1);
  }

  window.graficoBarraSemanal = function (canvasId, semanas) {
    var elemento = document.getElementById(canvasId);
    if (!elemento || !semanas.length) return null;

    var labels = semanas.map(function (s) { return rotuloSemana(s) + (s.parcial ? '*' : ''); });
    var dados = semanas.map(function (s) { return s.venda; });
    var cores = semanas.map(function (s) {
      if (s.parcial) return 'rgba(91,141,239,.35)'; // semana incompleta, ainda sem 7 dias de dado
      return s.tem_oferta ? COR_DESTAQUE : COR_NORMAL;
    });

    var rotuloImpacto = {
      id: 'rotuloImpacto',
      afterDatasetsDraw: function (chart) {
        var ctx = chart.ctx;
        var meta = chart.getDatasetMeta(0);
        ctx.save();
        ctx.font = '700 12px -apple-system, "Segoe UI", Roboto, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillStyle = COR_DESTAQUE;
        semanas.forEach(function (s, i) {
          if (s.crescimento_pct === null || s.crescimento_pct === undefined) return;
          var seta = s.crescimento_pct >= 0 ? '▲ +' : '▼ ';
          var texto = seta + Math.abs(s.crescimento_pct).toFixed(0) + '%';
          var elem = meta.data[i];
          ctx.fillText(texto, elem.x, elem.y - 10);
        });
        ctx.restore();
      },
    };

    return new Chart(elemento, {
      type: 'bar',
      data: { labels: labels, datasets: [{ label: 'Venda', data: dados, backgroundColor: cores, borderRadius: 4 }] },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        layout: { padding: { top: 24 } },
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              title: function (itens) {
                var s = semanas[itens[0].dataIndex];
                return s.inicio.split('-').reverse().join('/') + ' a ' + s.fim.split('-').reverse().join('/');
              },
              label: function (ctx) { return 'Venda: ' + formatarNumeroBR(ctx.parsed.y, 2).replace(/^/, 'R$ '); },
            },
          },
        },
        scales: {
          x: { grid: { display: false } },
          y: { beginAtZero: true, ticks: { callback: function (v) { return 'R$ ' + formatarNumeroBR(v, 0); } } },
        },
      },
      plugins: [rotuloImpacto],
    });
  };
})();
