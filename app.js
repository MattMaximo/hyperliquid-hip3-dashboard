const state = {
  range: 90,
  fullFees: false,
  payload: null,
  charts: {},
  marketSort: {
    key: "uplift_est",
    direction: "desc",
  },
};

const money = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
});

const compactMoney = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  notation: "compact",
  maximumFractionDigits: 2,
});

const compactNumber = new Intl.NumberFormat("en-US", {
  notation: "compact",
  maximumFractionDigits: 2,
});

const dateFormatter = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  year: "numeric",
});

const fieldLabels = {
  regular_actual_fees: "Core Hyperliquid daily fees",
  hip3_actual_fees: "HIP3 daily fees",
  regular_actual_volume: "Core Hyperliquid daily volume",
  hip3_actual_volume: "HIP3 daily perp volume",
  regular_revenue_split: "Core share of estimated protocol revenue",
  hip3_revenue_split: "HIP3 share of estimated protocol revenue",
  regular_burn_split: "Core share of estimated Assistance Fund burn",
  hip3_burn_split: "HIP3 share of estimated Assistance Fund burn",
  hip3_full_fee_est: "HIP3 full-fee counterfactual",
};

function formatMoney(value) {
  return Math.abs(value) >= 1_000_000 ? compactMoney.format(value) : money.format(value);
}

function formatDate(value) {
  return dateFormatter.format(new Date(`${value}T00:00:00`));
}

function formatMaybeMoney(value, hasData = true) {
  return hasData ? formatMoney(value) : "No recent activity";
}

function latestDay() {
  return state.payload.days[state.payload.days.length - 1];
}

function filteredDays() {
  return state.payload.days.slice(-state.range);
}

function deriveDay(day) {
  const regularFees = day.regular_actual_fees;
  const hip3Fees = state.fullFees ? day.hip3_full_fee_est : day.hip3_actual_fees;
  const actualTotalFees = day.regular_actual_fees + day.hip3_actual_fees;
  const shownTotalFees = regularFees + hip3Fees;
  const revenueScale = actualTotalFees > 0 ? shownTotalFees / actualTotalFees : 1;
  const totalRevenue = day.total_revenue_actual * revenueScale;
  const totalBurn = day.total_burn_actual * revenueScale;
  const feeShareDenominator = shownTotalFees || 1;
  const regularShare = regularFees / feeShareDenominator;
  const hip3Share = hip3Fees / feeShareDenominator;

  return {
    ...day,
    shown_regular_fees: regularFees,
    shown_hip3_fees: hip3Fees,
    shown_total_fees: shownTotalFees,
    shown_regular_revenue: totalRevenue * regularShare,
    shown_hip3_revenue: totalRevenue * hip3Share,
    shown_total_revenue: totalRevenue,
    shown_regular_burn: totalBurn * regularShare,
    shown_hip3_burn: totalBurn * hip3Share,
    shown_total_burn: totalBurn,
    shown_hip3_uplift: hip3Fees - day.hip3_actual_fees,
  };
}

function buildKpis() {
  const latest = deriveDay(latestDay());
  const cards = [
    {
      label: "Core Hyperliquid Fees",
      value: formatMoney(latest.shown_regular_fees),
      subvalue: `Perps excluding HIP3 plus spot volume: ${formatMoney(latest.regular_actual_volume)}`,
    },
    {
      label: state.fullFees ? "HIP3 Fees at Full Fees" : "HIP3 Fees",
      value: formatMoney(latest.shown_hip3_fees),
      subvalue: state.fullFees
        ? `Actual ${formatMoney(latest.hip3_actual_fees)} / estimated uplift ${formatMoney(latest.shown_hip3_uplift)}`
        : `Allium HIP3 perp volume: ${formatMoney(latest.hip3_actual_volume)}`,
    },
    {
      label: "Estimated Protocol Revenue",
      value: formatMoney(latest.shown_total_revenue),
      subvalue: `Core ${formatMoney(latest.shown_regular_revenue)} / HIP3 ${formatMoney(latest.shown_hip3_revenue)}`,
    },
    {
      label: state.fullFees ? "Estimated Burn at Normal HIP3 Fees" : "Estimated Assistance Fund Burn",
      value: formatMoney(latest.shown_total_burn),
      subvalue: state.fullFees
        ? `Actual ${formatMoney(latest.total_burn_actual)} / est uplift ${formatMoney(latest.shown_total_burn - latest.total_burn_actual)}`
        : `${compactNumber.format(latest.total_burn_actual_hype)} HYPE on latest actual day`,
    },
  ];

  const kpis = document.getElementById("kpis");
  kpis.innerHTML = cards
    .map(
      (card) => `
        <article class="panel kpi">
          <span class="label">${card.label}</span>
          <strong class="value">${card.value}</strong>
          <p class="subvalue">${card.subvalue}</p>
        </article>
      `,
    )
    .join("");
}

function chartOptions({ stacked = true, moneyMode = true }) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    interaction: {
      mode: "index",
      intersect: false,
    },
    plugins: {
      legend: {
        labels: {
          color: "#f8efe0",
          boxWidth: 12,
          usePointStyle: true,
          pointStyle: "circle",
        },
      },
      tooltip: {
        callbacks: {
          label(context) {
            const value = context.parsed.y ?? 0;
            return `${context.dataset.label}: ${moneyMode ? formatMoney(value) : compactNumber.format(value)}`;
          },
        },
      },
    },
    scales: {
      x: {
        stacked,
        ticks: { color: "#cab89a", maxTicksLimit: 8 },
        grid: { color: "rgba(255,255,255,0.06)" },
      },
      y: {
        stacked,
        ticks: {
          color: "#cab89a",
          callback(value) {
            return moneyMode ? compactMoney.format(value) : compactNumber.format(value);
          },
        },
        grid: { color: "rgba(255,255,255,0.06)" },
      },
    },
  };
}

function upsertChart(key, canvasId, config) {
  if (typeof Chart === "undefined") {
    return;
  }
  const existing = state.charts[key];
  if (existing) {
    existing.data = config.data;
    existing.options = config.options;
    existing.update();
    return;
  }
  const canvas = document.getElementById(canvasId);
  state.charts[key] = new Chart(canvas, config);
}

function renderCharts() {
  const rows = filteredDays().map(deriveDay);
  const labels = rows.map((row) => formatDate(row.date));

  upsertChart("fees", "fees-chart", {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          label: "Core Hyperliquid",
          data: rows.map((row) => row.shown_regular_fees),
          backgroundColor: "rgba(125, 211, 199, 0.75)",
          borderRadius: 6,
        },
        {
          label: state.fullFees ? "HIP3 at Full Fees" : "HIP3",
          data: rows.map((row) => row.shown_hip3_fees),
          backgroundColor: "rgba(255, 107, 44, 0.8)",
          borderRadius: 6,
        },
      ],
    },
    options: chartOptions({ stacked: true, moneyMode: true }),
  });

  upsertChart("revenue", "revenue-chart", {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          label: "Core Hyperliquid",
          data: rows.map((row) => row.shown_regular_revenue),
          backgroundColor: "rgba(125, 211, 199, 0.78)",
          borderRadius: 6,
        },
        {
          label: state.fullFees ? "HIP3 at Full Fees" : "HIP3",
          data: rows.map((row) => row.shown_hip3_revenue),
          backgroundColor: "rgba(255, 107, 44, 0.82)",
          borderRadius: 6,
        },
      ],
    },
    options: chartOptions({ stacked: true, moneyMode: true }),
  });

  upsertChart("burn", "burn-chart", {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          label: "Core Hyperliquid",
          data: rows.map((row) => row.shown_regular_burn),
          backgroundColor: "rgba(255, 193, 109, 0.8)",
          borderRadius: 6,
        },
        {
          label: state.fullFees ? "HIP3 at Full Fees" : "HIP3",
          data: rows.map((row) => row.shown_hip3_burn),
          backgroundColor: "rgba(255, 146, 139, 0.84)",
          borderRadius: 6,
        },
      ],
    },
    options: chartOptions({ stacked: true, moneyMode: true }),
  });

  upsertChart("uplift", "uplift-chart", {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          label: "HIP3 Fee Uplift from Full Fees",
          data: rows.map((row) => row.hip3_full_fee_est - row.hip3_actual_fees),
          backgroundColor: "rgba(255, 107, 44, 0.82)",
          borderRadius: 6,
        },
      ],
    },
    options: chartOptions({ stacked: false, moneyMode: true }),
  });
}

function buildCurrentMarkets() {
  const exactByToken = new Map(
    (state.payload.latest_market_rows || []).map((row) => [row.token, row]),
  );

  return (state.payload.growth_markets || [])
    .map((market) => {
      const exact = exactByToken.get(market.token);
      const actualFees = exact?.actual_fee_est ?? 0;
      const fullFees = exact?.full_fee_est ?? actualFees * (market.growth_enabled_now ? 10 : 1);
      return {
        token: market.token,
        display_name: market.display_name,
        dex: market.dex,
        growth_active: market.growth_enabled_now,
        volume: exact?.volume ?? 0,
        actual_fee_est: actualFees,
        full_fee_est: fullFees,
        uplift_est: fullFees - actualFees,
        has_latest_activity: Boolean(exact),
        activity_date: exact?.activity_date ?? null,
      };
    })
    .sort((a, b) => {
      if (a.growth_active !== b.growth_active) return Number(b.growth_active) - Number(a.growth_active);
      if (b.uplift_est !== a.uplift_est) return b.uplift_est - a.uplift_est;
      if (b.volume !== a.volume) return b.volume - a.volume;
      return a.display_name.localeCompare(b.display_name);
    });
}

function compareMarketRows(a, b) {
  const { key, direction } = state.marketSort;
  const multiplier = direction === "asc" ? 1 : -1;
  const aValue = a[key];
  const bValue = b[key];

  if (key === "activity_date") {
    const aTime = aValue ? new Date(`${aValue}T00:00:00`).getTime() : -Infinity;
    const bTime = bValue ? new Date(`${bValue}T00:00:00`).getTime() : -Infinity;
    if (aTime !== bTime) return (aTime - bTime) * multiplier;
  } else if (typeof aValue === "number" || typeof bValue === "number" || typeof aValue === "boolean" || typeof bValue === "boolean") {
    const aNum = Number(aValue ?? -Infinity);
    const bNum = Number(bValue ?? -Infinity);
    if (aNum !== bNum) return (aNum - bNum) * multiplier;
  } else {
    const compared = String(aValue ?? "").localeCompare(String(bValue ?? ""));
    if (compared !== 0) return compared * multiplier;
  }

  if (b.uplift_est !== a.uplift_est) return b.uplift_est - a.uplift_est;
  if (b.volume !== a.volume) return b.volume - a.volume;
  return a.display_name.localeCompare(b.display_name);
}

function syncSortButtons() {
  document.querySelectorAll(".sort-button").forEach((button) => {
    const isActive = button.dataset.sortKey === state.marketSort.key;
    button.classList.toggle("is-active", isActive);
    button.classList.toggle("is-asc", isActive && state.marketSort.direction === "asc");
    button.classList.toggle("is-desc", isActive && state.marketSort.direction === "desc");
  });
}

function renderMarkets() {
  const rows = buildCurrentMarkets().sort(compareMarketRows);
  const growthCount = rows.filter((row) => row.growth_active).length;
  const fullFeeCount = rows.length - growthCount;
  document.getElementById("market-note").textContent =
    `${rows.length} current HIP3 markets. ${growthCount} in growth mode, ${fullFeeCount} already at full fees.`;

  const tbody = document.getElementById("market-table");
  tbody.innerHTML = rows
    .map(
      (row) => `
        <tr>
          <td><strong>${row.display_name}</strong></td>
          <td>${row.dex}</td>
          <td><span class="pill ${row.growth_active ? "is-on" : "is-off"}">${row.growth_active ? "growth" : "full"}</span></td>
          <td>${row.activity_date ? formatDate(row.activity_date) : "No recent trade"}</td>
          <td>${formatMaybeMoney(row.volume, row.has_latest_activity)}</td>
          <td>${formatMaybeMoney(row.actual_fee_est, row.has_latest_activity)}</td>
          <td>${formatMaybeMoney(row.full_fee_est, row.has_latest_activity)}</td>
          <td>${formatMaybeMoney(row.uplift_est, row.has_latest_activity)}</td>
        </tr>
      `,
    )
    .join("");
  syncSortButtons();
}

function renderMethodology() {
  const { methodology } = state.payload;
  const exactList = document.getElementById("exact-list");
  const estimatedList = document.getElementById("estimated-list");
  const notesList = document.getElementById("notes-list");

  exactList.innerHTML = methodology.exact_fields
    .map((item) => `<li>${fieldLabels[item] || item}</li>`)
    .join("");
  estimatedList.innerHTML = methodology.estimated_fields
    .map((item) => `<li>${fieldLabels[item] || item}</li>`)
    .join("");
  notesList.innerHTML = methodology.notes.map((item) => `<li>${item}</li>`).join("");
}

function render() {
  document.getElementById("latest-date").textContent = formatDate(state.payload.latest_date);
  document.getElementById("toggle-full-fees").classList.toggle("is-on", state.fullFees);
  document.getElementById("toggle-full-fees").setAttribute("aria-pressed", String(state.fullFees));
  document.getElementById("burn-note").textContent = state.fullFees
    ? "Estimated daily burn if all HIP3 markets charged normal fees"
    : "Uses Artemis buyback burn series";
  buildKpis();
  renderMarkets();
  renderMethodology();
  renderCharts();
}

async function init() {
  const embedded = document.getElementById("dashboard-data");
  if (embedded?.textContent?.trim()) {
    state.payload = JSON.parse(embedded.textContent);
  } else {
    const response = await fetch("./data/dashboard-data.json");
    state.payload = await response.json();
  }

  document.getElementById("toggle-full-fees").addEventListener("click", () => {
    state.fullFees = !state.fullFees;
    render();
  });

  document.getElementById("range-picker").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-range]");
    if (!button) return;
    state.range = Number(button.dataset.range);
    document
      .querySelectorAll("#range-picker button")
      .forEach((node) => node.classList.toggle("is-active", node === button));
    render();
  });

  document.querySelector("thead").addEventListener("click", (event) => {
    const button = event.target.closest(".sort-button");
    if (!button) return;
    const key = button.dataset.sortKey;
    if (state.marketSort.key === key) {
      state.marketSort.direction = state.marketSort.direction === "asc" ? "desc" : "asc";
    } else {
      state.marketSort.key = key;
      state.marketSort.direction = key === "display_name" || key === "dex" || key === "activity_date" ? "asc" : "desc";
    }
    renderMarkets();
  });

  render();
}

init();
