const dashboardCharts = {
  mom: null,
  pie: null,
  cities: null,
};

function switchTab(tabId) {
  document.querySelectorAll('.tab-content').forEach((element) => element.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach((element) => element.classList.remove('active'));
  document.getElementById(`tab-${tabId}`).classList.add('active');

  if (window.event && window.event.target) {
    const button = window.event.target.closest('.tab-btn');
    if (button) {
      button.classList.add('active');
    }
  }
}

function openModal(id) {
  document.getElementById(id).classList.add('open');
}

function closeModal(id) {
  document.getElementById(id).classList.remove('open');
}

function initializeCharts(backendData = null) {
  console.log('InitializeCharts called with:', backendData);
  if (typeof Chart === 'undefined') {
    console.error('Chart.js is not loaded!');
    return;
  }

  const chartFont = { family: 'Inter', size: 11 };
  const gridColor = '#d7e0ea';
  const momChartElement = document.getElementById('momChart');
  const pieChartElement = document.getElementById('pieChart');
  const citiesChartElement = document.getElementById('citiesChart');

  Object.keys(dashboardCharts).forEach((chartKey) => {
    if (dashboardCharts[chartKey]) {
      dashboardCharts[chartKey].destroy();
      dashboardCharts[chartKey] = null;
    }
  });

  if (momChartElement && backendData?.mom) {
    dashboardCharts.mom = new Chart(momChartElement, {
      type: 'line',
      data: {
        labels: backendData.mom.map(d => d.label),
        datasets: [{
          label: 'New Agents',
          data: backendData.mom.map(d => d.total),
          borderColor: '#2258a5',
          backgroundColor: 'rgba(34,88,165,0.12)',
          fill: true,
          tension: 0.4,
          borderWidth: 2,
          pointRadius: 3
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { grid: { display: false }, ticks: { font: chartFont } },
          y: { grid: { color: gridColor }, ticks: { font: chartFont, stepSize: 1 } }
        }
      }
    });
  }

  if (pieChartElement && backendData?.plans) {
    const plans = backendData.plans;
    dashboardCharts.pie = new Chart(pieChartElement, {
      type: 'doughnut',
      data: {
        labels: Object.keys(plans),
        datasets: [{
          data: Object.values(plans),
          backgroundColor: ['#2258a5', '#1d7d5d', '#f59e0b'],
          borderWidth: 0,
          spacing: 4
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: '60%',
        plugins: { legend: { position: 'bottom', labels: { font: chartFont, usePointStyle: true } } }
      }
    });
  }

  if (citiesChartElement && backendData?.cities) {
    dashboardCharts.cities = new Chart(citiesChartElement, {
      type: 'bar',
      data: {
        labels: backendData.cities.map(d => d.label),
        datasets: [{
          label: 'Agents',
          data: backendData.cities.map(d => d.total),
          backgroundColor: '#2258a5',
          borderRadius: 4,
          barThickness: 20
        }]
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { grid: { color: gridColor }, ticks: { font: chartFont, stepSize: 1 } },
          y: { grid: { display: false }, ticks: { font: chartFont } }
        }
      }
    });
  }
}

function initializeDashboardRefresh() {
  const refreshButton = document.getElementById('dashboardRefreshBtn');
  if (!refreshButton) {
    return;
  }

  const defaultLabel = refreshButton.textContent;
  refreshButton.addEventListener('click', () => {
    refreshButton.disabled = true;
    refreshButton.textContent = 'Refreshing...';

    window.setTimeout(() => {
      window.location.reload();
    }, 300);
  });
}

function initializeLovableBadge() {
  if (window.self !== window.top || navigator.userAgent.includes('puppeteer')) {
    const badge = document.getElementById('lovable-badge');
    if (badge) {
      badge.style.display = 'none';
    }
  }

  const closeButton = document.getElementById('lovable-badge-close');
  if (!closeButton) {
    return;
  }

  closeButton.addEventListener('click', (event) => {
    event.preventDefault();
    event.stopPropagation();

    const badge = document.getElementById('lovable-badge');
    if (!badge) {
      return;
    }

    badge.classList.add('closing');
    window.setTimeout(() => {
      badge.style.display = 'none';
    }, 240);
  });
}

function initializeAgentsSearch() {
  const searchInput = document.getElementById('agents-search-input');
  const cityInput = document.getElementById('agents-city-filter');
  const planFilter = document.getElementById('agents-plan-filter');
  const statusFilter = document.getElementById('agents-status-filter');
  const searchButton = document.getElementById('agents-search-button');
  const tableBody = document.getElementById('agents-table-body');
  if (!searchInput || !cityInput || !planFilter || !statusFilter || !searchButton || !tableBody) {
    return;
  }

  // Search logic: filter the agents table rows as the user types.
  const rows = Array.from(tableBody.querySelectorAll('tr[data-agent-row]'));
  const noResultsRow = document.getElementById('agents-no-results');
  const resultsSummary = document.getElementById('agents-results-summary');
  const totalAgents = rows.length;

  // Cache lowercased row text once to keep input filtering fast.
  rows.forEach((row) => {
    // Combine text from all columns for "search all types"
    row.dataset.searchText = row.innerText.toLowerCase().replace(/\s+/g, ' ');
  });

  function applySearch() {
    const term = searchInput.value.trim().toLowerCase();
    const cityTerm = cityInput.value.trim().toLowerCase();
    const selectedPlan = planFilter.value.toLowerCase();
    const selectedStatus = statusFilter.value.toLowerCase();
    let visibleCount = 0;

    rows.forEach((row) => {
      const rowPlan = row.dataset.plan || '';
      const rowStatus = row.dataset.status || '';
      const rowCity = row.dataset.city || '';

      const matchesText = term === '' || row.dataset.searchText.includes(term);
      const matchesCity = cityTerm === '' || rowCity.includes(cityTerm);
      const matchesPlan = selectedPlan === 'all plans' || rowPlan === selectedPlan;
      const matchesStatus = selectedStatus === 'all status' || rowStatus === selectedStatus;

      const isVisible = matchesText && matchesCity && matchesPlan && matchesStatus;
      row.style.display = isVisible ? '' : 'none';
      if (isVisible) {
        visibleCount += 1;
      }
    });

    if (noResultsRow) {
      noResultsRow.style.display = visibleCount === 0 ? '' : 'none';
    }

    if (resultsSummary) {
      resultsSummary.textContent = `Showing ${visibleCount} of ${totalAgents} agents`;
    }
  }

  searchInput.addEventListener('input', applySearch);
  cityInput.addEventListener('input', applySearch);
  planFilter.addEventListener('change', applySearch);
  statusFilter.addEventListener('change', applySearch);
  searchButton.addEventListener('click', applySearch);
  applySearch();
}

function initializeDashboardExportCsv() {
  const exportButton = document.getElementById('exportCsvBtn');
  if (!exportButton) {
    return;
  }

  const periodSelect = document.getElementById('dashboardPeriodFilter');

  function escapeCsvValue(value) {
    const stringValue = String(value ?? '');
    if (/[",\n]/.test(stringValue)) {
      return `"${stringValue.replace(/"/g, '""')}"`;
    }
    return stringValue;
  }

  function buildCsvText() {
    const kpiRows = Array.from(document.querySelectorAll('.kpi-card')).map((card) => {
      const label = card.querySelector('.kpi-label')?.textContent?.trim() || 'Unknown Metric';
      const value = card.querySelector('.kpi-value')?.textContent?.trim().replace(/[^0-9.%+]/g, '') || '';
      return [label, value];
    });

    const monthlyRows = [
      ['Apr 25', 2], ['May 25', 3], ['Jun 25', 4], ['Jul 25', 3],
      ['Aug 25', 5], ['Sep 25', 6], ['Oct 25', 4], ['Nov 25', 5],
      ['Dec 25', 7], ['Jan 26', 6], ['Feb 26', 8], ['Mar 26', 8],
    ];
    const planRows = [['Starter', 31], ['Professional', 17]];
    const cityRows = [
      ['Mumbai', 12], ['Delhi', 9], ['Bangalore', 7], ['Pune', 5],
      ['Jaipur', 4], ['Chennai', 4], ['Hyderabad', 3], ['Kolkata', 2],
    ];

    const lines = [
      ['Dashboard Export'],
      ['Generated At', new Date().toISOString()],
      ['Period', periodSelect?.value || 'Last 12 Months'],
      [],
      ['Section', 'Metric', 'Value'],
      ...kpiRows.map(([metric, value]) => ['KPI', metric, value]),
      ...monthlyRows.map(([month, total]) => ['MoM Registrations', month, total]),
      ...planRows.map(([plan, total]) => ['Plan Distribution', plan, total]),
      ...cityRows.map(([city, total]) => ['Top Cities', city, total]),
    ];

    return lines.map((row) => row.map(escapeCsvValue).join(',')).join('\n');
  }

  function downloadCsv(csvText) {
    const blob = new Blob([`\uFEFF${csvText}`], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    const safePeriod = (periodSelect?.value || 'last-12-months')
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/(^-|-$)/g, '');

    link.href = url;
    link.download = `dashboard-report-${safePeriod}.csv`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  exportButton.addEventListener('click', () => {
    const csvText = buildCsvText();
    downloadCsv(csvText);
  });
}

document.addEventListener('DOMContentLoaded', () => {
  initializeLovableBadge();
  initializeAgentsSearch();
  initializeDashboardRefresh();
  initializeDashboardExportCsv();
});