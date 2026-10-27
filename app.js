(function () {
  "use strict";

  var APP_BASE_PATH = document.currentScript
    ? new URL(".", document.currentScript.src).pathname.replace(/\/$/, "")
    : "";
  var SETTINGS_KEY = "hk-leading-indicator-settings-v1";
  var FIELD_NAMES = ["M2", "PPI", "RETAIL", "CREDIT"];
  var FIELD_LABELS = ["港元 M2 同比", "内地 PPI 同比", "内地社零同比", "信用脉冲"];
  var seed = [];
  var rows = cloneRows(seed);
  var range = "ALL";
  var m2Range = "ALL";
  var showAllRows = false;
  var calculations = null;
  var saveQueue = Promise.resolve();
  var saveRevision = 0;

  function appPath(path) {
    return APP_BASE_PATH + path;
  }

  function cloneRows(value) {
    return value.map(function (row) {
      return {
        month: String(row.month || ""),
        values: Array.isArray(row.values) ? row.values.slice(0, 4).map(numberOrNull) : [null, null, null, null],
        hsi: numberOrNull(row.hsi),
        note: String(row.note || "")
      };
    });
  }

  function numberOrNull(value) {
    if (value === "" || value === null || value === undefined) return null;
    var result = Number(value);
    return Number.isFinite(result) ? result : null;
  }

  function setDataStatus(text, state) {
    var status = document.getElementById("data-status");
    if (!status) return;
    status.innerHTML = "<i></i> " + text;
    status.dataset.state = state || "";
  }

  function loadRowsFromCsv() {
    return fetch(appPath("/api/data"), { cache: "no-store" })
      .then(function (response) {
        if (!response.ok) throw new Error("CSV API returned " + response.status);
        return response.json();
      })
      .then(function (data) {
        if (!Array.isArray(data) || !data.length) throw new Error("CSV data is empty");
        rows = cloneRows(data);
        setDataStatus("已同步 CSV", "ready");
        renderAll();
        return true;
      })
      .catch(function (error) {
        setDataStatus("CSV 读取失败，数据未加载", "error");
        console.error("Unable to load CSV data.", error);
        renderAll();
        return false;
      });
  }

  function saveRows() {
    var revision = ++saveRevision;
    var payload = JSON.stringify(rows);
    setDataStatus("正在保存 CSV", "saving");
    saveQueue = saveQueue.catch(function () {}).then(function () {
      return fetch(appPath("/api/data"), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: payload
      });
    }).then(function (response) {
      if (!response.ok) throw new Error("CSV API returned " + response.status);
      if (revision === saveRevision) setDataStatus("已保存到 CSV", "ready");
    }).catch(function (error) {
      if (revision === saveRevision) setDataStatus("CSV 保存失败", "error");
      console.error("Unable to save CSV data.", error);
    });
    return saveQueue;
  }

  function setUpdateStatus(text, state) {
    var target = document.getElementById("update-status");
    target.textContent = text || "";
    target.className = "update-status" + (state ? " " + state : "");
  }

  function parseUpdateRange(value) {
    var match = String(value || "").trim().match(/^(\d{2}|\d{4})\s*[\/-]\s*(\d{1,2})\s*[-/]\s*(\d{2}|\d{4})\s*[\/-]\s*(\d{1,2})$/);
    if (!match) throw new Error("请输入类似 14/6-26/10 的月份范围");
    function month(year, month) {
      year = Number(year);
      month = Number(month);
      if (year < 100) year += year <= 79 ? 2000 : 1900;
      if (month < 1 || month > 12) throw new Error("月份必须在 1 至 12 之间");
      return String(year).padStart(4, "0") + "-" + String(month).padStart(2, "0");
    }
    var start = month(match[1], match[2]);
    var end = month(match[3], match[4]);
    if (start > end) throw new Error("起始月份不能晚于结束月份");
    return { start: start, end: end };
  }

  function updateData() {
    var button = document.getElementById("update-button");
    var rangeInput = document.getElementById("update-range");
    var rangeValue;
    try {
      rangeValue = parseUpdateRange(rangeInput.value);
    } catch (error) {
      setUpdateStatus(error.message, "error");
      rangeInput.focus();
      return Promise.resolve();
    }
    button.disabled = true;
    document.querySelectorAll(".data-input").forEach(function (input) { input.disabled = true; });
    document.getElementById("reset-button").disabled = true;
    setUpdateStatus("正在从 AkShare、人民银行、国家统计局和香港金管局抓取数据，请稍候…", "");
    return fetch(appPath("/api/update"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(rangeValue)
    }).then(function (response) {
      return response.json().then(function (payload) {
        if (!response.ok || !payload.ok) throw new Error(payload.error || "自动更新失败");
        return payload;
      });
    }).then(function (payload) {
      return loadRowsFromCsv().then(function (loaded) {
        if (!loaded) throw new Error("更新已写入，但页面重新读取 CSV 失败，请刷新页面");
        var status = "已更新 " + payload.written + " 个月（" + payload.start + " 至 " + payload.end + "），数据已写入 data/data.csv";
        if (payload.incomplete_months) status += "；" + payload.incomplete_months + " 个月有指标缺失，缺失值已留空";
        var sources = payload.sources || {};
        var financing = sources.social_financing || {};
        if (financing.pbc === "ok") status += "；社融采用人民银行官方表补齐近期数据";
        if (sources.gdp) status += "；GDP 来源：" + sources.gdp;
        setUpdateStatus(status, "success");
      });
    }).catch(function (error) {
      setUpdateStatus(error.message || "自动更新失败，CSV 未修改", "error");
    }).finally(function () {
      button.disabled = false;
      document.querySelectorAll(".data-input").forEach(function (input) { input.disabled = false; });
      document.getElementById("reset-button").disabled = false;
    });
  }

  function loadThreshold() {
    try {
      var settings = JSON.parse(localStorage.getItem(SETTINGS_KEY) || "{}");
      var value = Number(settings.threshold);
      return Number.isFinite(value) && value >= 0.1 && value <= 2 ? value : 0.5;
    } catch (error) {
      return 0.5;
    }
  }

  var threshold = loadThreshold();
  document.getElementById("threshold-input").value = threshold.toFixed(1);

  function saveThreshold() {
    try {
      localStorage.setItem(SETTINGS_KEY, JSON.stringify({ threshold: threshold }));
    } catch (error) {
      console.warn("Unable to save indicator settings.", error);
    }
  }

  function monthNumber(month) {
    var parts = month.split("-");
    return Number(parts[0]) * 12 + Number(parts[1]) - 1;
  }

  function monthLabel(month) {
    return month.replace("-", ".");
  }

  function average(values) {
    if (!values.length) return null;
    return values.reduce(function (total, value) { return total + value; }, 0) / values.length;
  }

  function sampleDeviation(values, mean) {
    if (values.length < 2) return null;
    var sum = values.reduce(function (total, value) {
      return total + Math.pow(value - mean, 2);
    }, 0);
    return Math.sqrt(sum / (values.length - 1));
  }

  function calculate() {
    var indexed = rows.map(function (row) {
      var complete = row.values.length === 4 && row.values.every(function (value) { return value !== null; });
      var indicator = complete ? average(row.values) : null;
      return Object.assign({}, row, { indicator: indicator, signal: null, z: null });
    });
    var values = indexed.map(function (row) { return row.indicator; }).filter(function (value) { return value !== null; });
    var mean = average(values);
    var deviation = mean === null ? null : sampleDeviation(values, mean);
    var upper = deviation === null ? null : mean + threshold * deviation;
    var lower = deviation === null ? null : mean - threshold * deviation;

    indexed.forEach(function (row) {
      if (row.indicator === null || deviation === null || deviation === 0) return;
      row.z = (row.indicator - mean) / deviation;
      if (row.indicator >= upper) row.signal = "top";
      else if (row.indicator <= lower) row.signal = "bottom";
      else row.signal = "neutral";
    });

    calculations = { rows: indexed, values: values, mean: mean, deviation: deviation, upper: upper, lower: lower };
    return calculations;
  }

  function format(value, digits) {
    if (value === null || value === undefined || !Number.isFinite(value)) return "—";
    return value.toLocaleString("zh-CN", {
      minimumFractionDigits: digits === undefined ? 2 : digits,
      maximumFractionDigits: digits === undefined ? 2 : digits
    });
  }

  function formatPrice(value) {
    return value === null ? "—" : value.toLocaleString("zh-CN", { maximumFractionDigits: 2, minimumFractionDigits: 2 });
  }

  function signalName(signal) {
    if (signal === "top") return "警惕顶部";
    if (signal === "bottom") return "关注底部";
    if (signal === "neutral") return "中性";
    return "待计算";
  }

  function signalDescription(signal) {
    if (signal === "top") return "高于均值 + " + format(threshold, 1) + " × 标准差";
    if (signal === "bottom") return "低于均值 − " + format(threshold, 1) + " × 标准差";
    return "位于上下信号阈值之间";
  }

  function setText(id, value) {
    document.getElementById(id).textContent = value;
  }

  function renderSummary(stats) {
    var completeRows = stats.rows.filter(function (row) { return row.indicator !== null; });
    var latest = completeRows[completeRows.length - 1];
    var hsiRows = stats.rows.filter(function (row) { return row.hsi !== null; });
    var latestHsi = hsiRows[hsiRows.length - 1];
    var datedRows = stats.rows.filter(function (row) {
      return row.values.some(function (value) { return value !== null; }) || row.hsi !== null;
    });

    setText("latest-indicator", latest ? format(latest.indicator) + "%" : "—");
    setText("latest-indicator-month", latest ? monthLabel(latest.month) + " · 最新完整月份" : "等待完整月度数据");
    setText("latest-hsi", latestHsi ? formatPrice(latestHsi.hsi) : "—");
    setText("latest-hsi-month", latestHsi ? monthLabel(latestHsi.month) + " · 月末收盘" : "暂无收盘数据");
    setText("sample-count", String(stats.values.length));
    setText("mean-value", stats.mean === null ? "—" : format(stats.mean) + "%");
    setText("std-value", stats.deviation === null ? "—" : format(stats.deviation) + "%");
    setText("lower-label", "下界 " + (stats.lower === null ? "—" : format(stats.lower) + "%"));
    setText("upper-label", "上界 " + (stats.upper === null ? "—" : format(stats.upper) + "%"));
    setText("latest-signal", latest ? signalName(latest.signal) : "待积累");
    setText("signal-explanation", latest ? signalDescription(latest.signal) : "至少需要两个月完整数据");
    setText("signal-badge", latest ? signalName(latest.signal) : "待积累");
    setText("coverage-label", datedRows.length ? monthLabel(datedRows[0].month) + " — " + monthLabel(datedRows[datedRows.length - 1].month) : "暂无数据");
    setText("updated-label", latestHsi ? "CSV 数据截至 " + monthLabel(latestHsi.month) : "暂无 CSV 数据");

    var signal = latest ? latest.signal : "";
    var badge = document.getElementById("signal-badge");
    var led = document.getElementById("signal-led");
    badge.className = "signal-badge" + (signal ? " " + signal : "");
    led.className = "status-led" + (signal ? " " + signal : "");

    renderSparkline(completeRows.slice(-18));
  }

  function renderSparkline(items) {
    var target = document.getElementById("sparkline");
    if (items.length < 2) {
      target.innerHTML = "";
      return;
    }
    var values = items.map(function (row) { return row.indicator; });
    var min = Math.min.apply(null, values);
    var max = Math.max.apply(null, values);
    var spread = max - min || 1;
    var points = values.map(function (value, index) {
      return { x: 2 + index * 4.5, y: 37 - ((value - min) / spread) * 29 };
    });
    var path = points.map(function (point, index) { return (index ? "L" : "M") + point.x + " " + point.y; }).join(" ");
    var area = path + " L" + points[points.length - 1].x + " 43 L" + points[0].x + " 43 Z";
    target.innerHTML = '<svg viewBox="0 0 82 45" preserveAspectRatio="none" aria-hidden="true"><path d="' + area + '" fill="rgba(80,125,222,.08)"/><path d="' + path + '" fill="none" stroke="#6388d7" stroke-width="1.5" vector-effect="non-scaling-stroke"/></svg>';
  }

  function svgText(x, y, text, anchor, className) {
    return '<text x="' + x + '" y="' + y + '" text-anchor="' + (anchor || "middle") + '" class="' + (className || "axis-label") + '">' + text + "</text>";
  }

  function linePath(points) {
    var path = "";
    points.forEach(function (point, index) {
      if (!Number.isFinite(point.x) || !Number.isFinite(point.y)) return;
      path += (path ? " L" : "M") + point.x.toFixed(1) + " " + point.y.toFixed(1);
    });
    return path;
  }

  function renderChart(stats) {
    var svg = document.getElementById("trend-chart");
    var tooltip = document.getElementById("chart-tooltip");
    var allDataRows = stats.rows.filter(function (row) { return row.indicator !== null || row.hsi !== null; });
    if (allDataRows.length < 2 || stats.deviation === null) {
      svg.innerHTML = '<text x="600" y="190" text-anchor="middle" fill="#95a1b2" font-size="13">录入至少两个月完整指标后显示趋势图</text>';
      setText("chart-range-label", "等待更多有效数据");
      tooltip.classList.remove("visible");
      return;
    }

    var latestMonth = monthNumber(allDataRows[allDataRows.length - 1].month);
    var minMonth = allDataRows[0].month;
    var rangeSpan = range === "1Y" ? 11 : range === "3Y" ? 35 : null;
    var visibleRows = allDataRows.filter(function (row) {
      return rangeSpan === null || monthNumber(row.month) >= latestMonth - rangeSpan;
    });
    var first = visibleRows[0];
    var last = visibleRows[visibleRows.length - 1];
    var xMin = monthNumber(first.month);
    var xMax = monthNumber(last.month);
    if (xMin === xMax) xMax += 1;
    var plot = { left: 67, right: 1135, top: 26, bottom: 327 };
    var plotWidth = plot.right - plot.left;
    var plotHeight = plot.bottom - plot.top;
    var zMin = -2.5;
    var zMax = 2.5;
    var priceValues = visibleRows.map(function (row) { return row.hsi; }).filter(function (value) { return value !== null; });
    var pMin = priceValues.length ? Math.min.apply(null, priceValues) : 0;
    var pMax = priceValues.length ? Math.max.apply(null, priceValues) : 1;
    var pStep = Math.max(1000, Math.ceil(((pMax - pMin) + 2200) / 5 / 1000) * 1000);
    var pLow = Math.floor((pMin - 600) / pStep) * pStep;
    var pHigh = Math.ceil((pMax + 600) / pStep) * pStep;
    if (pHigh === pLow) pHigh = pLow + pStep;

    function xScale(month) { return plot.left + ((monthNumber(month) - xMin) / (xMax - xMin)) * plotWidth; }
    function yZ(value) { return plot.bottom - ((value - zMin) / (zMax - zMin)) * plotHeight; }
    function yPrice(value) { return plot.bottom - ((value - pLow) / (pHigh - pLow)) * plotHeight; }

    var markup = [];
    var zTicks = [-2, -1, 0, 1, 2];
    zTicks.forEach(function (tick) {
      var y = yZ(tick);
      markup.push('<line x1="' + plot.left + '" y1="' + y + '" x2="' + plot.right + '" y2="' + y + '" class="' + (tick === 0 ? "chart-zero" : "chart-grid") + '"/>');
      markup.push(svgText(plot.left - 15, y + 3.5, tick > 0 ? "+" + tick : String(tick), "end"));
      var priceTick = pLow + ((pHigh - pLow) * (plot.bottom - y) / plotHeight);
      markup.push(svgText(plot.right + 14, y + 3.5, Math.round(priceTick / 1000) + "k", "start"));
    });

    if (stats.upper !== null && stats.deviation > 0) {
      var topY = yZ(threshold);
      var bottomY = yZ(-threshold);
      markup.push('<line x1="' + plot.left + '" y1="' + topY + '" x2="' + plot.right + '" y2="' + topY + '" class="chart-threshold" stroke="#d7835c"/>');
      markup.push('<line x1="' + plot.left + '" y1="' + bottomY + '" x2="' + plot.right + '" y2="' + bottomY + '" class="chart-threshold" stroke="#629db8"/>');
      markup.push(svgText(plot.right - 5, topY - 5, "顶部阈值", "end", "axis-caption"));
      markup.push(svgText(plot.right - 5, bottomY - 5, "底部阈值", "end", "axis-caption"));
    }

    var tickMonths = [];
    var tickYears = {};
    visibleRows.forEach(function (row) {
      var year = row.month.slice(0, 4);
      if ((row.month.slice(5) === "01" || row === first || row === last) && !tickYears[year]) {
        tickMonths.push(row);
        tickYears[year] = true;
      }
    });
    var seenTicks = {};
    tickMonths.forEach(function (row) {
      if (seenTicks[row.month]) return;
      seenTicks[row.month] = true;
      var x = xScale(row.month);
      markup.push('<line x1="' + x + '" y1="' + plot.top + '" x2="' + x + '" y2="' + plot.bottom + '" stroke="#f4f6f9" stroke-width="1"/>');
      var label = row.month.slice(0, 4);
      if ((row === first || row === last) && row.month.slice(5) !== "01") label += "." + row.month.slice(5);
      markup.push(svgText(x, plot.bottom + 23, label, "middle"));
    });
    markup.push(svgText(plot.left, 14, "标准分", "start", "axis-caption"));
    markup.push(svgText(plot.right, 14, "恒生指数", "end", "axis-caption"));

    var indicatorPoints = visibleRows.filter(function (row) { return row.indicator !== null && row.z !== null; }).map(function (row) {
      return { row: row, x: xScale(row.month), y: yZ(row.z) };
    });
    var hsiPoints = visibleRows.filter(function (row) { return row.hsi !== null; }).map(function (row) {
      return { row: row, x: xScale(row.month), y: yPrice(row.hsi) };
    });
    markup.push('<path d="' + linePath(hsiPoints) + '" class="hsi-path"/>');
    markup.push('<path d="' + linePath(indicatorPoints) + '" class="indicator-path"/>');

    indicatorPoints.forEach(function (point) {
      var row = point.row;
      if (row.signal === "top" || row.signal === "bottom") {
        markup.push('<circle cx="' + point.x + '" cy="' + point.y + '" r="5.2" class="signal-point ' + row.signal + '"/>');
      } else {
        markup.push('<circle cx="' + point.x + '" cy="' + point.y + '" r="2.5" class="point-core"/>');
      }
      markup.push('<circle cx="' + point.x + '" cy="' + point.y + '" r="9" class="hit-point" data-month="' + row.month + '"/>');
    });
    svg.innerHTML = markup.join("");

    setText("chart-range-label", monthLabel(first.month) + " — " + monthLabel(last.month));
    svg.onmousemove = function (event) {
      var target = event.target.closest ? event.target.closest(".hit-point") : null;
      if (!target) {
        tooltip.classList.remove("visible");
        return;
      }
      var row = stats.rows.find(function (entry) { return entry.month === target.getAttribute("data-month"); });
      if (!row) return;
      var statusColor = row.signal === "top" ? "#efaa87" : row.signal === "bottom" ? "#91c5dc" : "#c4d1e1";
      tooltip.innerHTML = '<div class="tooltip-title">' + monthLabel(row.month) + '</div>' +
        '<div class="tooltip-row"><span>领航指标</span><b>' + (row.indicator === null ? "—" : format(row.indicator) + "%") + '</b></div>' +
        '<div class="tooltip-row"><span>标准分</span><b>' + (row.z === null ? "—" : format(row.z)) + '</b></div>' +
        '<div class="tooltip-row"><span>信号</span><b style="color:' + statusColor + '">' + signalName(row.signal) + '</b></div>' +
        '<div class="tooltip-row"><span>恒生指数</span><b>' + formatPrice(row.hsi) + '</b></div>';
      tooltip.classList.add("visible");
      var box = document.querySelector(".chart-wrap").getBoundingClientRect();
      var x = event.clientX - box.left + 12;
      var y = event.clientY - box.top + 12;
      tooltip.style.left = Math.min(x, box.width - 170) + "px";
      tooltip.style.top = Math.min(y, box.height - 105) + "px";
    };
    svg.onmouseleave = function () { tooltip.classList.remove("visible"); };
  }

  function renderM2Chart(stats) {
    var svg = document.getElementById("m2-trend-chart");
    var tooltip = document.getElementById("m2-chart-tooltip");
    tooltip.classList.remove("visible");
    var data = stats.rows.filter(function (row) { return row.values[0] !== null || row.hsi !== null; });
    if (!data.length) {
      svg.innerHTML = '<text x="600" y="190" text-anchor="middle" fill="#95a1b2" font-size="13">录入港元 M2 同比或恒生指数后显示趋势图</text>';
      setText("m2-chart-range-label", "等待月度数据");
      return;
    }
    var latest = monthNumber(data[data.length - 1].month);
    var span = m2Range === "1Y" ? 11 : m2Range === "3Y" ? 35 : null;
    var visible = data.filter(function (row) { return span === null || monthNumber(row.month) >= latest - span; });
    var first = monthNumber(visible[0].month);
    var last = monthNumber(visible[visible.length - 1].month);
    var plot = { left: 67, right: 1135, top: 26, bottom: 327 };
    var height = plot.bottom - plot.top;
    function bounds(values) {
      if (!values.length) return { low: 0, high: 1 };
      var low = Math.min.apply(null, values);
      var high = Math.max.apply(null, values);
      var padding = Math.max((high - low) * 0.12, Math.abs(high) * 0.02, 0.5);
      return { low: low - padding, high: high + padding };
    }
    var m2Bounds = bounds(visible.map(function (row) { return row.values[0]; }).filter(function (value) { return value !== null; }));
    var priceBounds = bounds(visible.map(function (row) { return row.hsi; }).filter(function (value) { return value !== null; }));
    function x(month) { return first === last ? (plot.left + plot.right) / 2 : plot.left + (monthNumber(month) - first) / (last - first) * (plot.right - plot.left); }
    function y(value, scale) { return plot.bottom - (value - scale.low) / (scale.high - scale.low) * height; }
    var markup = [];
    for (var tick = 0; tick <= 5; tick++) {
      var ratio = tick / 5;
      var position = plot.bottom - ratio * height;
      markup.push('<line x1="' + plot.left + '" y1="' + position + '" x2="' + plot.right + '" y2="' + position + '" class="chart-grid"/>');
      markup.push(svgText(plot.left - 15, position + 3.5, format(m2Bounds.low + ratio * (m2Bounds.high - m2Bounds.low), 1) + "%", "end"));
      markup.push(svgText(plot.right + 14, position + 3.5, format(priceBounds.low + ratio * (priceBounds.high - priceBounds.low), 0), "start"));
    }
    if (m2Bounds.low < 0 && m2Bounds.high > 0) {
      markup.push('<line x1="' + plot.left + '" y1="' + y(0, m2Bounds) + '" x2="' + plot.right + '" y2="' + y(0, m2Bounds) + '" class="chart-zero"/>');
    }
    var step = Math.max(1, Math.ceil((last - first) / 8));
    visible.forEach(function (row, index) {
      var month = monthNumber(row.month);
      if ((month - first) % step !== 0 && index !== visible.length - 1) return;
      if (index === visible.length - 1 && last !== first && (last - first) % step < step / 2) return;
      markup.push('<line x1="' + x(row.month) + '" y1="' + plot.top + '" x2="' + x(row.month) + '" y2="' + plot.bottom + '" stroke="#f4f6f9"/>');
      markup.push(svgText(x(row.month), plot.bottom + 23, monthLabel(row.month), "middle"));
    });
    markup.push(svgText(plot.left, 14, "港元 M2 同比（%）", "start", "axis-caption"));
    markup.push(svgText(plot.right, 14, "恒生指数（点）", "end", "axis-caption"));

    function seriesPath(valueOf, scale) {
      var path = "";
      var previous = null;
      visible.forEach(function (row) {
        var value = valueOf(row);
        if (value === null) { previous = null; return; }
        var month = monthNumber(row.month);
        path += (previous !== null && month === previous + 1 ? " L" : " M") + x(row.month).toFixed(1) + " " + y(value, scale).toFixed(1);
        previous = month;
      });
      return path;
    }
    markup.push('<path d="' + seriesPath(function (row) { return row.hsi; }, priceBounds) + '" class="hsi-path"/>');
    markup.push('<path d="' + seriesPath(function (row) { return row.values[0]; }, m2Bounds) + '" class="indicator-path"/>');
    visible.forEach(function (row) {
      if (row.values[0] !== null) markup.push('<circle cx="' + x(row.month) + '" cy="' + y(row.values[0], m2Bounds) + '" r="2.5" class="point-core"/>');
      if (row.hsi !== null) markup.push('<circle cx="' + x(row.month) + '" cy="' + y(row.hsi, priceBounds) + '" r="2" fill="#b69259"/>');
      var stripWidth = Math.min(40, (plot.right - plot.left) / Math.max(1, last - first));
      markup.push('<rect x="' + (x(row.month) - stripWidth / 2) + '" y="' + plot.top + '" width="' + stripWidth + '" height="' + height + '" class="hit-point" data-month="' + row.month + '"/>');
    });
    svg.innerHTML = markup.join("");
    setText("m2-chart-range-label", monthLabel(visible[0].month) + " — " + monthLabel(visible[visible.length - 1].month));
    function showTooltip(event) {
      var target = event.target.closest ? event.target.closest(".hit-point") : null;
      if (!target) { tooltip.classList.remove("visible"); return; }
      var row = visible.find(function (item) { return item.month === target.getAttribute("data-month"); });
      if (!row) return;
      tooltip.innerHTML = '<div class="tooltip-title">' + monthLabel(row.month) + '</div>' +
        '<div class="tooltip-row"><span>港元 M2 同比</span><b>' + (row.values[0] === null ? "—" : format(row.values[0]) + "%") + '</b></div>' +
        '<div class="tooltip-row"><span>恒生指数</span><b>' + formatPrice(row.hsi) + '</b></div>';
      tooltip.classList.add("visible");
      var box = document.getElementById("m2-chart-wrap").getBoundingClientRect();
      tooltip.style.left = Math.max(0, Math.min(event.clientX - box.left + 12, box.width - tooltip.offsetWidth)) + "px";
      tooltip.style.top = Math.max(0, Math.min(event.clientY - box.top + 12, box.height - tooltip.offsetHeight)) + "px";
    }
    svg.onpointermove = showTooltip;
    svg.onpointerdown = showTooltip;
    svg.onpointerleave = function () { tooltip.classList.remove("visible"); };
  }

  function renderSignals(stats) {
    var signals = stats.rows.filter(function (row) { return row.signal === "top" || row.signal === "bottom"; }).slice(-5).reverse();
    var target = document.getElementById("recent-signals");
    if (!signals.length) {
      target.innerHTML = '<div class="empty-signals">目前没有触发顶底阈值的月份</div>';
      return;
    }
    target.innerHTML = signals.map(function (row) {
      var kind = row.signal === "top" ? "top" : "bottom";
      var hint = kind === "top" ? "高于上界" : "低于下界";
      return '<div class="signal-row">' +
        '<span class="signal-date">' + monthLabel(row.month) + '</span>' +
        '<span class="signal-description">' + hint + ' · ' + format(row.indicator) + '%</span>' +
        '<span class="signal-tag ' + kind + '"><i></i>' + signalName(row.signal) + '</span>' +
      '</div>';
    }).join("");
  }

  function hasData(row) {
    return row.values.some(function (value) { return value !== null; }) || row.hsi !== null;
  }

  function inputCell(row, field, value, extraClass) {
    return '<input class="data-input ' + (extraClass || "") + '" type="number" step="any" value="' + (value === null ? "" : value) + '" placeholder="—" aria-label="' + monthLabel(row.month) + " " + field + '" data-month="' + row.month + '" data-field="' + field + '">';
  }

  function renderTable(stats) {
    var all = stats.rows.slice();
    var populated = all.filter(hasData).sort(function (a, b) { return monthNumber(b.month) - monthNumber(a.month); });
    var blanks = all.filter(function (row) { return !hasData(row); }).sort(function (a, b) { return monthNumber(a.month) - monthNumber(b.month); });
    var search = document.getElementById("month-search").value.trim();
    var onlySignals = document.getElementById("signal-filter").checked;
    var visible;
    if (showAllRows || search || onlySignals) {
      visible = populated.concat(blanks);
    } else {
      visible = populated.slice(0, 12);
    }
    if (search) visible = visible.filter(function (row) { return row.month.indexOf(search) >= 0; });
    if (onlySignals) visible = visible.filter(function (row) { return row.signal === "top" || row.signal === "bottom"; });

    document.getElementById("show-all-button").textContent = showAllRows ? "仅看最近 12 个月" : "查看全部月份";
    setText("table-count", "显示 " + visible.length + " / " + stats.rows.length + " 个月");
    var body = document.getElementById("data-body");
    if (!visible.length) {
      body.innerHTML = '<tr><td colspan="8" class="empty-signals">没有符合条件的月份</td></tr>';
      return;
    }
    body.innerHTML = visible.map(function (row) {
      var signal = row.signal;
      var signalClass = signal || "empty";
      var cells = row.values.map(function (value, index) {
        return "<td>" + inputCell(row, FIELD_NAMES[index], value) + "</td>";
      }).join("");
      return "<tr>" +
        '<td>' + monthLabel(row.month) + '</td>' +
        cells +
        '<td class="computed-column"><span class="computed-value">' + (row.indicator === null ? "—" : format(row.indicator)) + '</span></td>' +
        '<td><span class="table-signal ' + signalClass + '">' + (signal ? signalName(signal) : "—") + '</span></td>' +
        '<td>' + inputCell(row, "HSI", row.hsi, "hsi-input") + '</td>' +
      "</tr>";
    }).join("");
  }

  function renderAll() {
    var stats = calculate();
    renderSummary(stats);
    renderChart(stats);
    renderM2Chart(stats);
    renderSignals(stats);
    renderTable(stats);
  }

  function appendMarkdownInline(parent, source) {
    var pattern = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\))/g;
    var lastIndex = 0;
    var match;
    while ((match = pattern.exec(source))) {
      if (match.index > lastIndex) parent.appendChild(document.createTextNode(source.slice(lastIndex, match.index)));
      var token = match[0];
      if (token.slice(0, 2) === "**") {
        var strong = document.createElement("strong");
        strong.textContent = token.slice(2, -2);
        parent.appendChild(strong);
      } else if (token.charAt(0) === "`") {
        var code = document.createElement("code");
        code.textContent = token.slice(1, -1);
        parent.appendChild(code);
      } else {
        var linkMatch = token.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
        var linkUrl;
        try { linkUrl = new URL(linkMatch[2], window.location.href); } catch (error) { linkUrl = null; }
        if (linkUrl && (linkUrl.protocol === "https:" || linkUrl.protocol === "http:")) {
          var anchor = document.createElement("a");
          anchor.textContent = linkMatch[1];
          anchor.href = linkUrl.href;
          anchor.target = "_blank";
          anchor.rel = "noopener noreferrer";
          parent.appendChild(anchor);
        } else {
          parent.appendChild(document.createTextNode(linkMatch[1]));
        }
      }
      lastIndex = pattern.lastIndex;
    }
    if (lastIndex < source.length) parent.appendChild(document.createTextNode(source.slice(lastIndex)));
  }

  function renderSourceMarkdown(markdown) {
    var root = document.getElementById("source-doc-content");
    root.textContent = "";
    var lines = String(markdown).replace(/\r\n?/g, "\n").split("\n");
    var lists = [];
    var paragraph = [];
    var paragraphParent = root;
    var baseHeading = 6;
    lines.forEach(function (line) {
      var match = line.trim().match(/^(#{1,6})\s+/);
      if (match) baseHeading = Math.min(baseHeading, match[1].length);
    });

    function flushParagraph() {
      if (!paragraph.length) return;
      var node = document.createElement("p");
      appendMarkdownInline(node, paragraph.join(" "));
      paragraphParent.appendChild(node);
      paragraph = [];
    }

    lines.forEach(function (rawLine) {
      var line = rawLine.trim();
      var indent = rawLine.match(/^\s*/)[0].replace(/\t/g, "    ").length;
      if (!line) { flushParagraph(); return; }
      var heading = line.match(/^(#{1,6})\s+(.+)$/);
      if (heading) {
        flushParagraph();
        lists = [];
        var headingNode = document.createElement("h" + Math.min(6, 2 + heading[1].length - baseHeading));
        appendMarkdownInline(headingNode, heading[2]);
        root.appendChild(headingNode);
        return;
      }
      var bullet = line.match(/^[-*]\s+(.+)$/);
      var numbered = line.match(/^(\d+)[.)]\s+(.+)$/);
      if (bullet || numbered) {
        flushParagraph();
        var nextType = bullet ? "ul" : "ol";
        while (lists.length && (indent < lists[lists.length - 1].indent ||
            (indent === lists[lists.length - 1].indent && nextType !== lists[lists.length - 1].type))) lists.pop();
        if (!lists.length || indent > lists[lists.length - 1].indent) {
          var parent = lists.length ? lists[lists.length - 1].node.lastElementChild : root;
          var list = document.createElement(nextType);
          if (numbered) list.start = Number(numbered[1]);
          parent.appendChild(list);
          lists.push({ node: list, indent: indent, type: nextType });
        }
        var item = document.createElement("li");
        if (numbered) item.value = Number(numbered[1]);
        appendMarkdownInline(item, bullet ? bullet[1] : numbered[2]);
        lists[lists.length - 1].node.appendChild(item);
        return;
      }
      var target = root;
      if (lists.length && indent > lists[lists.length - 1].indent) target = lists[lists.length - 1].node.lastElementChild;
      else lists = [];
      if (target !== paragraphParent) flushParagraph();
      paragraphParent = target;
      paragraph.push(line);
    });
    flushParagraph();
  }

  var sourceDocumentLoading = false;

  function loadSourceDocument() {
    if (sourceDocumentLoading) return;
    sourceDocumentLoading = true;
    var status = document.getElementById("source-doc-status");
    status.classList.remove("error");
    status.textContent = "正在加载来源文档…";
    fetch(appPath("/docs/数据获取来源.md"), { cache: "no-store" })
      .then(function (response) {
        if (!response.ok) throw new Error("文档读取失败（HTTP " + response.status + "）");
        return response.text();
      })
      .then(function (markdown) {
        renderSourceMarkdown(markdown);
        status.textContent = "内容来自工程目录 docs/数据获取来源.md";
      })
      .catch(function (error) {
        status.textContent = error.message || "来源文档加载失败，请稍后重试。";
        status.classList.add("error");
      })
      .finally(function () { sourceDocumentLoading = false; });
  }

  var viewTabs = [
    { button: document.getElementById("dashboard-tab"), panel: document.getElementById("dashboard-tab-panel"), name: "dashboard" },
    { button: document.getElementById("sources-tab"), panel: document.getElementById("sources-tab-panel"), name: "sources" }
  ];

  function activateViewTab(name, focusButton) {
    var activeName = name === "sources" ? "sources" : "dashboard";
    viewTabs.forEach(function (tab) {
      var selected = tab.name === activeName;
      tab.button.classList.toggle("selected", selected);
      tab.button.setAttribute("aria-selected", selected ? "true" : "false");
      tab.button.tabIndex = selected ? 0 : -1;
      tab.panel.hidden = !selected;
      if (selected && focusButton) tab.button.focus();
    });
    if (activeName === "sources") loadSourceDocument();
  }

  viewTabs.forEach(function (tab, index) {
    tab.button.addEventListener("click", function () { activateViewTab(tab.name, false); });
    tab.button.addEventListener("keydown", function (event) {
      var nextIndex = null;
      if (event.key === "ArrowRight" || event.key === "ArrowDown") nextIndex = (index + 1) % viewTabs.length;
      else if (event.key === "ArrowLeft" || event.key === "ArrowUp") nextIndex = (index + viewTabs.length - 1) % viewTabs.length;
      else if (event.key === "Home") nextIndex = 0;
      else if (event.key === "End") nextIndex = viewTabs.length - 1;
      if (nextIndex !== null) {
        event.preventDefault();
        activateViewTab(viewTabs[nextIndex].name, true);
      }
    });
  });

  document.querySelectorAll(".brand, [data-dashboard-link]").forEach(function (link) {
    link.addEventListener("click", function () { activateViewTab("dashboard", false); });
  });

  function exportCsv() {
    var header = ["月份"].concat(FIELD_LABELS).concat(["领航指标(%)", "顶底信号", "恒生指数(月末收盘)", "备注"]);
    var stats = calculations || calculate();
    var lines = [header];
    stats.rows.forEach(function (row) {
      lines.push([row.month].concat(row.values).concat([
        row.indicator,
        row.signal ? signalName(row.signal) : "",
        row.hsi,
        row.note
      ]));
    });
    var csv = "\ufeff" + lines.map(function (line) {
      return line.map(function (value) {
        if (value === null || value === undefined) return "";
        var text = String(value);
        return /[",\r\n]/.test(text) ? '"' + text.replace(/"/g, '""') + '"' : text;
      }).join(",");
    }).join("\r\n");
    var link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    link.download = "港股领航指标月度数据.csv";
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(link.href);
  }

  document.getElementById("data-body").addEventListener("change", function (event) {
    var input = event.target.closest(".data-input");
    if (!input) return;
    var row = rows.find(function (entry) { return entry.month === input.getAttribute("data-month"); });
    if (!row) return;
    var field = input.getAttribute("data-field");
    if (field === "HSI") row.hsi = numberOrNull(input.value);
    else {
      var index = FIELD_NAMES.indexOf(field);
      if (index >= 0) row.values[index] = numberOrNull(input.value);
    }
    renderAll();
    saveRows();
  });

  document.getElementById("threshold-input").addEventListener("change", function (event) {
    var value = Number(event.target.value);
    if (!Number.isFinite(value)) value = 0.5;
    threshold = Math.max(0.1, Math.min(2, Math.round(value * 10) / 10));
    event.target.value = threshold.toFixed(1);
    saveThreshold();
    renderAll();
  });

  document.querySelectorAll("[data-range]").forEach(function (button) {
    button.addEventListener("click", function () {
      range = button.getAttribute("data-range");
      document.querySelectorAll("[data-range]").forEach(function (item) { item.classList.toggle("selected", item === button); });
      renderChart(calculations || calculate());
    });
  });

  document.querySelectorAll("[data-m2-range]").forEach(function (button) {
    button.addEventListener("click", function () {
      m2Range = button.getAttribute("data-m2-range");
      document.querySelectorAll("[data-m2-range]").forEach(function (item) {
        item.classList.toggle("selected", item === button);
        item.setAttribute("aria-pressed", item === button ? "true" : "false");
      });
      renderM2Chart(calculations || calculate());
    });
  });

  document.getElementById("month-search").addEventListener("input", function () {
    renderTable(calculations || calculate());
  });
  document.getElementById("signal-filter").addEventListener("change", function () {
    renderTable(calculations || calculate());
  });
  document.getElementById("show-all-button").addEventListener("click", function () {
    showAllRows = !showAllRows;
    renderTable(calculations || calculate());
  });
  document.getElementById("export-button").addEventListener("click", exportCsv);
  document.getElementById("reset-button").addEventListener("click", function () {
    if (!window.confirm("从工程目录 data/data.csv 重新读取数据？未保存的编辑会被当前 CSV 内容覆盖。")) return;
    showAllRows = false;
    document.getElementById("month-search").value = "";
    document.getElementById("signal-filter").checked = false;
    loadRowsFromCsv();
  });
  document.getElementById("update-form").addEventListener("submit", function (event) {
    event.preventDefault();
    updateData();
  });

  renderAll();
  loadRowsFromCsv();
})();
