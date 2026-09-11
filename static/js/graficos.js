// Configuração comum dos gráficos Chart.js do painel — cada tela só monta
// os `labels`/`datasets` e chama uma destas funções.
(function () {
  var PALETA = ['#2f6feb', '#e8763a', '#2fa876', '#c93f6f', '#9b6fe8'];

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
          borderColor: '#c93f6f', backgroundColor: '#c93f6f',
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
                  return destaqueIndices.indexOf(idx) !== -1 ? '#e8763a' : '#2f6feb';
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
