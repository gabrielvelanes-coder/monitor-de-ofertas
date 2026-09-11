// Configuração comum dos gráficos Chart.js do painel — cada tela só monta
// os `labels`/`datasets` e chama uma destas funções.
(function () {
  var PALETA = ['#5b8def', '#ef9f5b', '#4fc493', '#e8628f', '#b48cf0'];

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

  window.graficoLinha = function (canvasId, labels, series) {
    var elemento = document.getElementById(canvasId);
    if (!elemento) return null;
    return new Chart(elemento, {
      type: 'line',
      data: {
        labels: labels.map(maiuscula),
        datasets: series.map(function (s, i) {
          return {
            label: maiuscula(s.label),
            data: s.data,
            borderColor: corDaSerie(i),
            backgroundColor: corDaSerie(i),
            tension: 0.25,
            pointRadius: 3,
          };
        }),
      },
      options: {
        responsive: true,
        plugins: { legend: { display: series.length > 1, position: 'bottom' } },
        scales: { y: { beginAtZero: true } },
      },
    });
  };

  // Drill-down: clicar numa linha da tabela (produto, fabricante...) troca
  // uma linha extra destacada no gráfico pela série mensal daquele item,
  // sem recarregar a página. `seriesPorItem` = {nome: [valores por mês]}.
  window.iniciarDrillDown = function (chart, seriesPorItem, rotuloMetrica) {
    var datasetExtra = null;
    return function (nome) {
      var rotulo = maiuscula(rotuloMetrica ? nome + ' — ' + rotuloMetrica : nome);
      if (datasetExtra) {
        var i = chart.data.datasets.indexOf(datasetExtra);
        if (i !== -1) chart.data.datasets.splice(i, 1);
        if (datasetExtra.label === rotulo) {
          datasetExtra = null;
          chart.options.plugins.legend.display = chart.data.datasets.length > 1;
          chart.update();
          return;
        }
      }
      if (seriesPorItem[nome]) {
        datasetExtra = {
          label: rotulo,
          data: seriesPorItem[nome],
          borderColor: '#e8628f', backgroundColor: '#e8628f',
          borderWidth: 3, tension: 0.25, pointRadius: 4,
        };
        chart.data.datasets.push(datasetExtra);
      }
      chart.options.plugins.legend.display = true;
      chart.update();
    };
  };

  window.graficoBarra = function (canvasId, labels, series, destaqueIndices) {
    var elemento = document.getElementById(canvasId);
    if (!elemento) return null;
    return new Chart(elemento, {
      type: 'bar',
      data: {
        labels: labels.map(maiuscula),
        datasets: series.map(function (s, i) {
          return {
            label: maiuscula(s.label),
            data: s.data,
            backgroundColor: (destaqueIndices && series.length === 1)
              ? labels.map(function (_, idx) {
                  return destaqueIndices.indexOf(idx) !== -1 ? '#ef9f5b' : '#5b8def';
                })
              : corDaSerie(i),
          };
        }),
      },
      options: {
        responsive: true,
        plugins: { legend: { display: series.length > 1, position: 'bottom' } },
        scales: { y: { beginAtZero: true } },
      },
    });
  };
})();
