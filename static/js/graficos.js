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
        // 'none' -- sem isso a animação as vezes trava no frame inicial
        // (linha nasce em y=0, a animação pra subir até o valor real
        // nunca termina de rodar) e a linha de destaque fica achatada
        // no fundo do gráfico pra sempre (achado real 22/09/26, Gabriel:
        // "quando eu seleciono um item, a linha fica a cima das barras" --
        // na real ela ficava ACHATADA embaixo, escondida atrás/em cima
        // das barras baixas, não subia pro valor certo). Sem animação
        // nesse update, a posição final aplica na hora, sem depender de
        // requestAnimationFrame terminar.
        chart.update('none');
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
      chart.update('none'); // ver comentário acima -- sem isso a linha nova às vezes fica travada em y=0
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

  // Venda do mês EMPILHADA por bandeira (Velanes + Ultra Popular) --
  // só o Leve3 usa isso (pedido 22/09/26, depois de levar a cor por
  // bandeira pro Semana/Dia: "no mes, nao foi implantado as cores das
  // bandeiras?"). 1ª versão pintava a barra inteira pela bandeira
  // "dominante" do mês -- saía sempre laranja/Velanes em TODO mês
  // (Velanes vende mais que a Ultra Popular o ano inteiro, mesmo cada
  // uma rodando sua própria semana), ficava monótono e sem informação
  // (achado do Gabriel comparando com o Kenvue, rico em cores: "vamos
  // arrumar isso"). Empilhada mostra a proporção REAL de cada bandeira
  // por mês. Itens fica numa 3ª barra à parte, cor neutra (cinza) --
  // não splitada por bandeira, orange bateria com a cor da Velanes e
  // confundiria (achado do teste anterior, na versão "cor sólida").
  // `grafico` = `{labels, venda_velanes, venda_ultra_popular, itens}`.
  window.graficoBarraMensalBandeira = function (canvasId, grafico) {
    var elemento = document.getElementById(canvasId);
    if (!elemento) return null;

    // Cores translúcidas (mesma família de Velanes/Ultra Popular, tom mais
    // claro) pras unidades -- pedido 23/09/26: "separar as unidades
    // tambem, por bandeira" (antes era 1 série cinza só, agnóstica de
    // bandeira). Tom mais claro em vez da cor sólida (já usada na Venda)
    // pra não confundir as 2 pilhas ao olhar rápido pro gráfico.
    var CORES_BANDEIRA_ITENS = {
      velanes: 'rgba(239,159,91,.45)', ultra_popular: 'rgba(229,72,77,.45)',
    };

    var datasets = [
      {
        label: maiuscula('Venda Velanes'), stack: 'venda', yAxisID: 'y',
        data: grafico.venda_velanes, backgroundColor: CORES_BANDEIRA.velanes,
      },
      {
        label: maiuscula('Venda Ultra Popular'), stack: 'venda', yAxisID: 'y',
        data: grafico.venda_ultra_popular, backgroundColor: CORES_BANDEIRA.ultra_popular,
      },
      {
        label: maiuscula('Itens Velanes'), stack: 'itens', yAxisID: 'y1',
        data: grafico.itens_velanes, backgroundColor: CORES_BANDEIRA_ITENS.velanes,
      },
      {
        label: maiuscula('Itens Ultra Popular'), stack: 'itens', yAxisID: 'y1',
        data: grafico.itens_ultra_popular, backgroundColor: CORES_BANDEIRA_ITENS.ultra_popular,
      },
    ];
    var seriesInfo = [
      { label: 'Venda Velanes', eixo: 'moeda' },
      { label: 'Venda Ultra Popular', eixo: 'moeda' },
      { label: 'Itens Velanes', eixo: 'unidades' },
      { label: 'Itens Ultra Popular', eixo: 'unidades' },
    ];

    // Total geral (Velanes + Ultra Popular) escrito em cima de cada pilha
    // -- venda em R$ acima da pilha de venda, unidades acima da pilha de
    // itens (pedido 23/09/26: "me mostre o valor geral tanto em vendas
    // quanto em unidades").
    var totalVenda = grafico.labels.map(function (_, i) {
      return (grafico.venda_velanes[i] || 0) + (grafico.venda_ultra_popular[i] || 0);
    });
    var totalItens = grafico.labels.map(function (_, i) {
      return (grafico.itens_velanes[i] || 0) + (grafico.itens_ultra_popular[i] || 0);
    });
    var rotuloTotal = {
      id: 'rotuloTotal',
      afterDatasetsDraw: function (chart) {
        var ctx = chart.ctx;
        ctx.save();
        ctx.font = '700 11px -apple-system, "Segoe UI", Roboto, sans-serif';
        ctx.textAlign = 'center';
        function escrever(datasetIndex, valores, eixo, cor) {
          var meta = chart.getDatasetMeta(datasetIndex);
          ctx.fillStyle = cor;
          valores.forEach(function (valor, i) {
            var elem = meta.data[i];
            if (!elem) return;
            ctx.fillText(formatarEixo(eixo, valor), elem.x, elem.y - 8);
          });
        }
        escrever(1, totalVenda, 'moeda', '#c7cdd6');
        escrever(3, totalItens, 'unidades', '#c7cdd6');
        ctx.restore();
      },
    };

    var chart = new Chart(elemento, {
      type: 'bar',
      data: { labels: grafico.labels.map(maiuscula), datasets: datasets },
      options: {
        responsive: true,
        layout: { padding: { top: 20 } },
        plugins: {
          legend: { display: true, position: 'bottom' },
          tooltip: { callbacks: { label: callbackTooltip(seriesInfo) } },
        },
        scales: {
          x: { stacked: true },
          y: { stacked: true, beginAtZero: true, ticks: { callback: function (v) { return formatarEixo('moeda', v); } } },
          y1: {
            stacked: true, beginAtZero: true, position: 'right',
            grid: { drawOnChartArea: false },
            ticks: { callback: function (v) { return formatarEixo('unidades', v); } },
          },
        },
      },
      plugins: [rotuloTotal],
    });
    chart._seriesInfo = seriesInfo;
    return chart;
  };

  // Venda por semana/dia, período(s) com oferta destacado + % de
  // crescimento escrito em cima da barra (pedido 22/09/26 -- "preciso VER
  // no gráfico o impacto, o realizado"). `periodos` = lista de {rotulo,
  // tooltip, venda, tem_oferta, parcial, crescimento_pct}, já vem pronta
  // do back-end (`serie_semanal`/`serie_diaria`, services.py) -- aqui só
  // desenha. Mesmo formato pras 2 granularidades, 1 função só desenha as
  // 2 (usada nas abas Semana/Dia do gráfico único -- a aba Mês continua
  // no `graficoBarra` de sempre, com drill-down por produto e clique
  // pra filtrar mês, que esse formato mais simples não tem).
  var COR_NORMAL = '#5b8def', COR_DESTAQUE = '#e8628f';
  // Leve3 roda 1 semana por mês, POR bandeira, em semanas diferentes
  // entre Velanes/Ultra Popular -- "destaque por oferta" não diz nada
  // (toda semana com dado já é oferta, ver `_periodos_com_destaque`),
  // então lá a cor mostra de QUEM foi a semana em vez de SE teve oferta
  // (pedido 22/09/26: "semana de ultra barra vermelha, semana de
  // velanes, laranja"). `graficoBarraDestaque(..., {modo:'bandeira'})`.
  var CORES_BANDEIRA = { velanes: '#ef9f5b', ultra_popular: '#e5484d' };

  window.graficoBarraDestaque = function (canvasId, periodos, opcoes) {
    var elemento = document.getElementById(canvasId);
    if (!elemento || !periodos.length) return null;
    var porBandeira = opcoes && opcoes.modo === 'bandeira';

    var labels = periodos.map(function (p) { return p.rotulo + (p.parcial ? '*' : ''); });
    var dados = periodos.map(function (p) { return p.venda; });
    var cores = periodos.map(function (p) {
      if (p.parcial) return 'rgba(91,141,239,.35)'; // período incompleto, ainda sem todos os dias de dado
      if (porBandeira) return CORES_BANDEIRA[p.bandeira_dominante] || COR_NORMAL;
      return p.tem_oferta ? COR_DESTAQUE : COR_NORMAL;
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
        periodos.forEach(function (p, i) {
          if (porBandeira || p.crescimento_pct === null || p.crescimento_pct === undefined) return;
          var seta = p.crescimento_pct >= 0 ? '▲ +' : '▼ ';
          var texto = seta + Math.abs(p.crescimento_pct).toFixed(0) + '%';
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
              title: function (itens) { return periodos[itens[0].dataIndex].tooltip; },
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

  // Barra empilhada por bandeira (Velanes + Ultra Popular), pedido
  // 22/09/26 logo depois do modo "1 cor só" do Leve3 -- "faze isso
  // tambem, para os outros, talvez dividido nas barras". Diferente do
  // Leve3 (que roda 1 semana por bandeira, "de quem foi a semana" é a
  // pergunta certa), essas mecânicas rodam nas 2 bandeiras ao MESMO
  // TEMPO -- o sinal que importa continua sendo oferta/não-oferta (o
  // "impacto" que motivou o gráfico), a bandeira aqui é só a proporção
  // DENTRO da barra. Por isso cada segmento usa a MESMA família de cor
  // do destaque por oferta (rosa/azul), só numa tonalidade própria pra
  // dar pra distinguir Velanes de Ultra Popular dentro da pilha.
  var CORES_OFERTA_BANDEIRA = {
    velanes: { normal: COR_NORMAL, destaque: COR_DESTAQUE },
    ultra_popular: { normal: '#3f6bc4', destaque: '#c94c72' },
  };

  window.graficoBarraEmpilhadaBandeira = function (canvasId, periodos) {
    var elemento = document.getElementById(canvasId);
    if (!elemento || !periodos.length) return null;

    var labels = periodos.map(function (p) { return p.rotulo + (p.parcial ? '*' : ''); });

    function corSegmento(p, bandeira) {
      if (p.parcial) return 'rgba(91,141,239,.35)';
      var cores = CORES_OFERTA_BANDEIRA[bandeira];
      return p.tem_oferta ? cores.destaque : cores.normal;
    }

    var datasets = [
      {
        label: 'Velanes', stack: 'venda', borderRadius: 4,
        data: periodos.map(function (p) { return p.venda_velanes; }),
        backgroundColor: periodos.map(function (p) { return corSegmento(p, 'velanes'); }),
      },
      {
        label: 'Ultra Popular', stack: 'venda', borderRadius: 4,
        data: periodos.map(function (p) { return p.venda_ultra_popular; }),
        backgroundColor: periodos.map(function (p) { return corSegmento(p, 'ultra_popular'); }),
      },
    ];

    var rotuloImpacto = {
      id: 'rotuloImpacto',
      afterDatasetsDraw: function (chart) {
        var ctx = chart.ctx;
        // Topo da pilha = topo do ÚLTIMO dataset desenhado (Ultra
        // Popular, empilhado por cima do Velanes) -- rótulo tem que ficar
        // acima da barra inteira, não só do pedaço de cima.
        var metaTopo = chart.getDatasetMeta(datasets.length - 1);
        ctx.save();
        ctx.font = '700 12px -apple-system, "Segoe UI", Roboto, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillStyle = COR_DESTAQUE;
        periodos.forEach(function (p, i) {
          if (p.crescimento_pct === null || p.crescimento_pct === undefined) return;
          var seta = p.crescimento_pct >= 0 ? '▲ +' : '▼ ';
          var texto = seta + Math.abs(p.crescimento_pct).toFixed(0) + '%';
          var elem = metaTopo.data[i];
          ctx.fillText(texto, elem.x, elem.y - 10);
        });
        ctx.restore();
      },
    };

    return new Chart(elemento, {
      type: 'bar',
      data: { labels: labels, datasets: datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        layout: { padding: { top: 24 } },
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              title: function (itens) { return periodos[itens[0].dataIndex].tooltip; },
              label: function (ctx) { return ctx.dataset.label + ': ' + formatarNumeroBR(ctx.parsed.y, 2).replace(/^/, 'R$ '); },
            },
          },
        },
        scales: {
          x: { stacked: true, grid: { display: false } },
          y: { stacked: true, beginAtZero: true, ticks: { callback: function (v) { return 'R$ ' + formatarNumeroBR(v, 0); } } },
        },
      },
      plugins: [rotuloImpacto],
    });
  };

  // Gráfico único "Mês / Semana / Dia" (pedido 22/09/26 -- "prefiro que
  // tenhamos apenas 1 gráfico"): a aba Mês já é montada por fora (mesmo
  // `graficoBarra` de sempre, com drill-down/clique-pra-filtrar) -- essa
  // função só cuida de criar Semana/Dia SOB DEMANDA, no 1º clique na aba
  // (não de cara: o canvas nasce dentro de um painel `hidden`, e criar um
  // Chart.js num canvas de altura 0 desenha em branco -- já foi bug real
  // nesta tela, "graficoBarraSemanal is not defined"/canvas vazio).
  // `idBase` é o mesmo passado nos 3 `data-grupo="periodo-<idBase>"` do
  // template; `dadosPeriodo` = `{semana: [...], dia: [...]}`.
  window.montarAbasGraficoPeriodo = function (idBase, dadosPeriodo, opcoes) {
    var grupo = 'periodo-' + idBase;
    var criados = {};
    document.querySelectorAll('[data-grupo="' + grupo + '"]').forEach(function (aba) {
      var valor = aba.dataset.valor;
      if (valor === 'mes' || !dadosPeriodo[valor] || !dadosPeriodo[valor].length) return;
      aba.addEventListener('click', function () {
        if (criados[valor]) return;
        criados[valor] = true;
        var canvasId = 'grafico-' + valor + '-' + idBase;
        if (opcoes && opcoes.modo === 'bandeira-empilhada') {
          graficoBarraEmpilhadaBandeira(canvasId, dadosPeriodo[valor]);
        } else {
          graficoBarraDestaque(canvasId, dadosPeriodo[valor], opcoes);
        }
      });
    });
  };
})();
