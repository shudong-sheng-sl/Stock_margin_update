const statusText = document.getElementById("status-text");
const totalStocks = document.getElementById("total-stocks");
const latestDate = document.getElementById("latest-date");
const dataProvider = document.getElementById("data-provider");
const sourceNote = document.getElementById("source-note");
const summaryTableBody = document.getElementById("summary-table-body");
const stockCards = document.getElementById("stock-cards");
const refreshButton = document.getElementById("refresh-button");
const clearCacheButton = document.getElementById("clear-cache-button");

function formatCurrency(value) {
  if (value === null || value === undefined) {
    return "--";
  }
  return new Intl.NumberFormat("zh-CN", {
    maximumFractionDigits: 0,
  }).format(value);
}

function formatPercent(value) {
  if (value === null || value === undefined) {
    return "--";
  }
  const num = Number(value);
  const prefix = num > 0 ? "+" : "";
  return `${prefix}${num.toFixed(2)}%`;
}

function calculateWindowFinancingChangePercent(records) {
  if (!records || records.length < 2) {
    return null;
  }

  const first = Number(records[0].financing_balance);
  const last = Number(records[records.length - 1].financing_balance);

  if (!Number.isFinite(first) || !Number.isFinite(last) || first === 0) {
    return null;
  }

  return ((last - first) / first) * 100;
}

function calculateWindowPriceChangePercent(records) {
  if (!records || records.length < 2) {
    return null;
  }

  const first = Number(records[0].close_price);
  const last = Number(records[records.length - 1].close_price);

  if (!Number.isFinite(first) || !Number.isFinite(last) || first === 0) {
    return null;
  }

  return ((last - first) / first) * 100;
}

function formatPrice(value) {
  if (value === null || value === undefined) {
    return "--";
  }
  return Number(value).toFixed(2);
}

function changeClass(value) {
  if (value === null || value === undefined) {
    return "change-flat";
  }
  if (value > 0) {
    return "change-positive";
  }
  if (value < 0) {
    return "change-negative";
  }
  return "change-flat";
}

function buildRow(record) {
  return `
    <tr>
      <td>${record.trading_date}</td>
      <td>${formatPrice(record.close_price)}</td>
      <td class="${changeClass(record.price_change_percent)}">${formatPercent(record.price_change_percent)}</td>
      <td>${formatCurrency(record.financing_balance)}</td>
      <td class="${changeClass(record.financing_change_percent)}">${formatPercent(record.financing_change_percent)}</td>
    </tr>
  `;
}

function renderStocks(payload) {
  summaryTableBody.innerHTML = "";
  stockCards.innerHTML = "";

  payload.stocks.forEach((stock) => {
    const card = document.createElement("article");
    card.className = "stock-card";
    const windowPriceChangePercent = calculateWindowPriceChangePercent(stock.records);
    const windowChangePercent = calculateWindowFinancingChangePercent(stock.records);
    const summaryRow = document.createElement("tr");
    summaryRow.innerHTML = `
      <td>${stock.name}</td>
      <td class="${changeClass(windowPriceChangePercent)}">${formatPercent(windowPriceChangePercent)}</td>
      <td class="${changeClass(windowChangePercent)}">${formatPercent(windowChangePercent)}</td>
    `;
    summaryTableBody.appendChild(summaryRow);

    card.innerHTML = `
      <div class="stock-card-header">
        <div>
          <h3>${stock.name}</h3>
          <p>${stock.symbol} · ${stock.market}</p>
          <p class="scope-note">展示当日收盘价、当日涨跌幅、融资余额，以及相对上一交易日的融资变化百分比</p>
        </div>
        <div class="summary-chip ${changeClass(windowChangePercent)}">
          <span>近10日融资变化</span>
          <strong>${formatPercent(windowChangePercent)}</strong>
        </div>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>交易日</th>
              <th>收盘价</th>
              <th>涨跌幅</th>
              <th>融资余额</th>
              <th>融资变化</th>
            </tr>
          </thead>
          <tbody>
            ${stock.records.map((record) => buildRow(record)).join("")}
          </tbody>
        </table>
      </div>
    `;

    stockCards.appendChild(card);
  });

  totalStocks.textContent = String(payload.stocks.length);
  latestDate.textContent = payload.latest_trading_date || "-";
  dataProvider.textContent = payload.provider;
  sourceNote.textContent = `来源: ${payload.sources.join(" / ")}。当前页面展示收盘价、涨跌幅、融资余额，以及融资相对上一交易日的变化百分比；若个别行情字段暂缺，则显示为 --。`;
}

async function loadStocks() {
  statusText.textContent = "正在加载数据...";
  refreshButton.disabled = true;
  clearCacheButton.disabled = true;

  try {
    const response = await fetch("/api/margin-dashboard");

    if (!response.ok) {
      let detail = `Request failed with status ${response.status}`;
      try {
        const errorPayload = await response.json();
        if (errorPayload && errorPayload.detail) {
          detail = errorPayload.detail;
        }
      } catch (parseError) {
        // Keep the HTTP status fallback message.
      }
      throw new Error(detail);
    }

    const payload = await response.json();
    renderStocks(payload);
    statusText.textContent = `更新于 ${new Date().toLocaleTimeString("zh-CN")}`;
  } catch (error) {
    statusText.textContent = "Live 数据加载失败";
    summaryTableBody.innerHTML = "";
    stockCards.innerHTML = `
      <article class="stock-card stock-card-empty">
        <p>未能加载 Live 数据。</p>
        <p>${error.message}</p>
      </article>
    `;
  } finally {
    refreshButton.disabled = false;
    clearCacheButton.disabled = false;
  }
}

refreshButton.addEventListener("click", () => {
  loadStocks();
});

clearCacheButton.addEventListener("click", async () => {
  statusText.textContent = "正在清理缓存并刷新...";
  refreshButton.disabled = true;
  clearCacheButton.disabled = true;

  try {
    const response = await fetch("/api/margin-dashboard/clear-cache", {
      method: "POST",
    });

    if (!response.ok) {
      throw new Error(`Request failed with status ${response.status}`);
    }

    await loadStocks();
  } catch (error) {
    statusText.textContent = "清缓存失败";
    refreshButton.disabled = false;
    clearCacheButton.disabled = false;
  }
});

loadStocks();
