// Configuração comum dos gráficos Chart.js do painel — cada tela só monta
// os `labels`/`datasets` e chama uma destas funções.
(function () {
  var PALETA = ['#2f6feb', '#e8763a', '#2fa876', '#c93f6f', '#9b6fe8'];

  function corDaSerie(indice) {
    return PALETA[indice % PALETA.length];
  }

  window.graficoLinha = function (canvasId, labels, series) {
    var elemento = document.getElementById(canvasId);
    if (!elemento) return null;
    return new Chart(elemento, {
      type: 'line',
      data: {
        labels: labels,
        datasets: series.map(function (s, i) {
          return {
            label: s.label,
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

  window.graficoBarra = function (canvasId, labels, series, destaqueIndices) {
    var elemento = document.getElementById(canvasId);
    if (!elemento) return null;
    return new Chart(elemento, {
      type: 'bar',
      data: {
        labels: labels,
        datasets: series.map(function (s, i) {
          return {
            label: s.label,
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
