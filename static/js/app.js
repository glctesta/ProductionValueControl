(function () {
    const REFRESH_MINUTES = parseInt(document.body.dataset.refreshMinutes || '60', 10);
    let chartInstance = null;
    let wipMonthlyChartInstance = null;
    let wipDailyChartInstance = null;
    let countdownSeconds = REFRESH_MINUTES * 60;
    let countdownInterval = null;
    
    // View state
    let currentView = 'production'; // 'production' o 'wip'
    const ROTATION_SECONDS = parseInt(document.body.dataset.rotationSeconds || '20', 10);
    let secondsSinceRotation = 0;

    // Pause auto-rotation state
    let rotationPaused = false;
    let pauseSecondsRemaining = 0;
    const PAUSE_MINUTES = parseInt(document.body.dataset.rotationPauseMinutes || '30', 10);

    const eurFmt = new Intl.NumberFormat('it-IT', {
        style: 'currency',
        currency: 'EUR',
        maximumFractionDigits: 0,
    });

    function formatEUR(n) {
        if (n === null || n === undefined || Number.isNaN(n)) return '—';
        return eurFmt.format(n);
    }

    function pad(n) { return String(n).padStart(2, '0'); }

    function updateClock() {
        const now = new Date();
        document.getElementById('clock-time').textContent =
            pad(now.getHours()) + ':' + pad(now.getMinutes()) + ':' + pad(now.getSeconds());
        document.getElementById('clock-date').textContent =
            pad(now.getDate()) + '/' + pad(now.getMonth() + 1) + '/' + now.getFullYear();
    }

    function updateCountdown() {
        const mins = Math.max(0, Math.ceil(countdownSeconds / 60));
        document.getElementById('countdown').textContent = mins;
    }

    function startCountdown() {
        if (countdownInterval) clearInterval(countdownInterval);
        countdownInterval = setInterval(() => {
            // 1. Gestione Refresh Decimale (60 minuti)
            countdownSeconds--;
            updateCountdown();
            if (countdownSeconds <= 0) {
                refreshAllData();
            }

            // 2. Gestione Rotazione Automatica (20 secondi)
            if (rotationPaused) {
                if (pauseSecondsRemaining > 0) {
                    pauseSecondsRemaining--;
                    updatePauseButton();
                    if (pauseSecondsRemaining <= 0) {
                        rotationPaused = false;
                        secondsSinceRotation = 0;
                        updatePauseButton();
                    }
                }
            } else {
                secondsSinceRotation++;
                if (secondsSinceRotation >= ROTATION_SECONDS) {
                    secondsSinceRotation = 0;
                    toggleView();
                }
            }
        }, 1000);
    }

    function refreshAllData() {
        loadMetrics();
        if (currentView === 'wip' || document.getElementById('panel-wip').classList.contains('hidden') === false) {
            loadWipMetrics();
        }
    }

    function setKpi(id, value, kind) {
        const el = document.getElementById(id);
        if (!el) return;
        el.textContent = formatEUR(value);
        el.classList.remove('positive', 'negative', 'warning');
        if (kind === 'gap') {
            if (value <= 0) el.classList.add('positive');
            else el.classList.add('negative');
        } else if (kind === 'forecastDay' || kind === 'forecastMonth') {
            if (value >= (kind === 'forecastDay' ? window._dailyTarget : window._monthlyTarget)) {
                el.classList.add('positive');
            } else {
                el.classList.add('warning');
            }
        } else if (kind === 'required') {
            if (value <= (window._dailyTarget || Infinity)) {
                el.classList.add('positive');
            } else {
                el.classList.add('warning');
            }
        }
    }

    function rootFontPx() {
        return parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
    }

    function renderChart(data) {
        const ctx = document.getElementById('chart').getContext('2d');
        const baseFont = rootFontPx();
        const tickFont = Math.round(baseFont * 0.8);   // ~12px su 16px root
        const titleFont = Math.round(baseFont * 0.85);
        const tooltipBody = Math.round(baseFont * 0.85);
        const datasets = [
            {
                label: 'Target',
                data: data.chart.target,
                dailyData: data.chart.targetDaily || [],
                borderColor: '#4fc3f7',
                backgroundColor: 'transparent',
                borderWidth: 3,
                borderDash: [10, 5],
                tension: 0.15,
                pointRadius: 0,
                pointHoverRadius: 4,
            },
            {
                label: 'Media (giorni lavorativi)',
                data: data.chart.average,
                dailyData: data.chart.averageDaily || [],
                borderColor: '#ffb74d',
                backgroundColor: 'transparent',
                borderWidth: 3,
                tension: 0.2,
                pointRadius: 2,
                pointHoverRadius: 5,
            },
            {
                label: 'Rolling Mese',
                data: data.chart.rollingMonth,
                dailyData: data.chart.rollingDaily || [],
                borderColor: '#81c784',
                backgroundColor: 'rgba(129,199,132,0.15)',
                borderWidth: 4,
                tension: 0.25,
                fill: true,
                pointRadius: 4,
                pointHoverRadius: 7,
                pointBackgroundColor: '#81c784',
                pointBorderColor: '#0b111c',
                pointBorderWidth: 2,
                spanGaps: false,
            },
        ];

        if (chartInstance) {
            chartInstance.data.labels = data.chart.labels;
            chartInstance.data.datasets.forEach((ds, i) => {
                ds.data = datasets[i].data;
                ds.dailyData = datasets[i].dailyData;
            });
            chartInstance.$qtyDaily = data.chart.qtyDaily || [];
            chartInstance.$rollingDaily = data.chart.rollingDaily || [];
            chartInstance.update('none');
            return;
        }

        chartInstance = new Chart(ctx, {
            type: 'line',
            data: { labels: data.chart.labels, datasets },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: 'index', intersect: false },
                plugins: {
                    legend: {
                        display: false,
                    },
                    tooltip: {
                        backgroundColor: 'rgba(20,32,46,0.95)',
                        titleColor: '#f2f6fb',
                        bodyColor: '#e8ecf2',
                        footerColor: '#81c784',
                        borderColor: '#4fc3f7',
                        borderWidth: 1,
                        padding: Math.round(baseFont * 0.75),
                        titleFont: { size: tooltipBody + 1, weight: '600' },
                        bodyFont: { size: tooltipBody },
                        footerFont: { size: tooltipBody, weight: '600' },
                        callbacks: {
                            title: (items) => 'Giorno lavorativo ' + (items[0] ? items[0].label : ''),
                            label: (c) => {
                                const cum = c.parsed.y;
                                const daily = (c.dataset.dailyData || [])[c.dataIndex];
                                const parts = [c.dataset.label + ': ' + formatEUR(cum) + ' (cumulato)'];
                                if (daily !== null && daily !== undefined) {
                                    parts.push('    \u2192 giorno: ' + formatEUR(daily));
                                }
                                return parts;
                            },
                            footer: (items) => {
                                if (!items || !items.length) return '';
                                const idx = items[0].dataIndex;
                                const qty = (chartInstance && chartInstance.$qtyDaily) ? chartInstance.$qtyDaily[idx] : null;
                                const val = (chartInstance && chartInstance.$rollingDaily) ? chartInstance.$rollingDaily[idx] : null;
                                const lines = [];
                                if (val !== null && val !== undefined) {
                                    lines.push('Valore prodotto: ' + formatEUR(val));
                                }
                                if (qty !== null && qty !== undefined) {
                                    lines.push('Pezzi prodotti: ' + new Intl.NumberFormat('it-IT').format(qty));
                                }
                                return lines;
                            },
                        },
                    },
                },
                scales: {
                    x: {
                        ticks: { color: '#8fa3bf', font: { size: tickFont } },
                        grid: { color: 'rgba(255,255,255,0.04)' },
                        title: {
                            display: true,
                            text: 'Giorno lavorativo del mese',
                            color: '#8fa3bf',
                            font: { size: titleFont, weight: '600' },
                        },
                    },
                    y: {
                        ticks: {
                            color: '#8fa3bf',
                            font: { size: 12 },
                            callback: (v) => formatEUR(v),
                        },
                        grid: { color: 'rgba(255,255,255,0.04)' },
                        title: {
                            display: true,
                            text: 'Valore cumulato',
                            color: '#8fa3bf',
                            font: { size: titleFont, weight: '600' },
                        },
                    },
                },
            },
        });
        chartInstance.$qtyDaily = data.chart.qtyDaily || [];
        chartInstance.$rollingDaily = data.chart.rollingDaily || [];
    }

    async function loadMetrics() {
        const btn = document.getElementById('refresh-btn');
        btn.disabled = true;
        btn.textContent = '…';
        try {
            const resp = await fetch('/api/metrics', { cache: 'no-store' });
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            const data = await resp.json();
            if (data.error) throw new Error(data.error);

            window._dailyTarget = data.dailyTarget;
            window._monthlyTarget = data.monthlyTarget;

            setKpi('kpi-daily-target', data.dailyTarget);
            setKpi('kpi-monthly-target', data.monthlyTarget);
            setKpi('kpi-today-value', data.todayValue);
            setKpi('kpi-month-value', data.monthValue);
            setKpi('kpi-daily-gap', data.dailyGap, 'gap');
            setKpi('kpi-monthly-gap', data.monthlyGap, 'gap');
            setKpi('kpi-forecast-day', data.forecastDay, 'forecastDay');
            setKpi('kpi-forecast-month', data.forecastMonth, 'forecastMonth');
            setKpi('kpi-required', data.requiredDailyAdjustment, 'required');

            const star = document.getElementById('warning-star');
            if (data.missingOrdersCount > 0) {
                star.classList.remove('hidden');
                star.title =
                    data.missingOrdersCount + ' ordini mancanti nel file Excel: ' +
                    (data.missingOrders || []).join(', ');
            } else {
                star.classList.add('hidden');
            }

            const src = document.getElementById('source-info');
            if (src) {
                const parts = [];
                if (data.excelFile) parts.push('Excel: ' + data.excelFile);
                if (data.workingDaysInMonth) {
                    parts.push(
                        'Giorni lav. mese: ' + data.workingDaysInMonth +
                        ' (residui: ' + data.remainingWorkingDays + ')'
                    );
                }
                if (data.productionDay) parts.push('Giorno prod.: ' + data.productionDay);
                src.textContent = parts.join(' • ');
            }

            renderChart(data);

            const refreshMins = data.refreshMinutes || REFRESH_MINUTES;
            countdownSeconds = refreshMins * 60;
            updateCountdown();
        } catch (e) {
            console.error('Errore caricamento metriche:', e);
            const src = document.getElementById('source-info');
            if (src) src.textContent = 'Errore: ' + e.message;
        } finally {
            btn.disabled = false;
            btn.textContent = 'Refresh';
        }
    }

    // ------------------------------------------------------------- WIP View Functions
    async function loadWipMetrics() {
        const tbody = document.getElementById('wip-table-body');
        const src = document.getElementById('wip-source-info');
        
        try {
            const resp = await fetch('/api/wip', { cache: 'no-store' });
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            const data = await resp.json();
            if (data.error) throw new Error(data.error);

            // Popola KPI WIP
            document.getElementById('kpi-wip-total-val').textContent = formatEUR(data.wipTotalVal);
            document.getElementById('kpi-wip-ok-val').textContent = formatEUR(data.wipTotalValOk);
            document.getElementById('kpi-wip-fail-val').textContent = formatEUR(data.wipTotalValFail);
            document.getElementById('kpi-wip-total-qty').textContent = new Intl.NumberFormat('it-IT').format(data.wipTotalQty) + ' pz (OK: ' + data.wipTotalQtyOk + ' / FAIL: ' + data.wipTotalQtyFail + ')';
            document.getElementById('kpi-wip-orders-count').textContent = data.wipOrdersCount;

            // Rende tabella giornaliera
            tbody.innerHTML = '';
            if (!data.wipByDay || data.wipByDay.length === 0) {
                tbody.innerHTML = '<tr><td colspan="8" style="text-align: center; color: #8fa3bf; padding: 20px;">Nessun ordine in WIP attivo nel 2026.</td></tr>';
            } else {
                data.wipByDay.forEach(dayData => {
                    const dayStr = dayData.ProductionDay;
                    const dParts = dayStr.split('-');
                    const dateFmt = `${dParts[2]}/${dParts[1]}/${dParts[0]}`;
                    
                    const rowId = `wip-row-${dayStr}`;
                    const detailId = `wip-detail-${dayStr}`;
                    
                    const totalQty = dayData.QtyOK + dayData.QtyFAIL;
                    const totalVal = dayData.ValueOK + dayData.ValueFAIL;

                    const tr = document.createElement('tr');
                    tr.id = rowId;
                    tr.className = 'wip-day-header-row';
                    tr.innerHTML = `
                        <td style="text-align: center; color: #4fc3f7;" class="wip-caret">&#9654;</td>
                        <td style="font-weight: bold; color: #f2f6fb;">${dateFmt}</td>
                        <td style="text-align: right; color: #81c784;">${new Intl.NumberFormat('it-IT').format(dayData.QtyOK)}</td>
                        <td style="text-align: right; color: #ff5252;">${new Intl.NumberFormat('it-IT').format(dayData.QtyFAIL)}</td>
                        <td style="text-align: right; font-weight: bold;">${new Intl.NumberFormat('it-IT').format(totalQty)}</td>
                        <td style="text-align: right; color: #81c784;">${formatEUR(dayData.ValueOK)}</td>
                        <td style="text-align: right; color: #ff5252;">${formatEUR(dayData.ValueFAIL)}</td>
                        <td style="text-align: right; font-weight: bold; color: #4fc3f7;">${formatEUR(totalVal)}</td>
                    `;
                    tbody.appendChild(tr);

                    const trDetail = document.createElement('tr');
                    trDetail.id = detailId;
                    trDetail.className = 'wip-detail-row hidden';
                    
                    let ordersHtml = `
                        <div class="nested-wip-table-container">
                            <table class="nested-wip-table">
                                <thead>
                                    <tr>
                                        <th>Order Number</th>
                                        <th>Product Code</th>
                                        <th>Product Name</th>
                                        <th style="text-align: right;">Qty OK</th>
                                        <th style="text-align: right;">Qty FAIL</th>
                                        <th style="text-align: right;">Prezzo Unit.</th>
                                        <th style="text-align: right;">Valore Totale</th>
                                    </tr>
                                </thead>
                                <tbody>
                    `;
                    
                    dayData.Orders.forEach(o => {
                        ordersHtml += `
                            <tr>
                                <td style="text-align: center; font-weight: bold; color: #4fc3f7;">${o.OrderNumber}</td>
                                <td style="text-align: center; color: #f2f6fb;">${o.ProductCode}</td>
                                <td>${o.ProductName}</td>
                                <td style="text-align: right; color: #81c784;">${new Intl.NumberFormat('it-IT').format(o.QtyOK)}</td>
                                <td style="text-align: right; color: #ff5252;">${new Intl.NumberFormat('it-IT').format(o.QtyFAIL)}</td>
                                <td style="text-align: right;">${formatEUR(o.UnitPrice)}</td>
                                <td style="text-align: right; font-weight: bold; color: #4fc3f7;">${formatEUR(o.TotalValue)}</td>
                            </tr>
                        `;
                    });

                    ordersHtml += `
                                </tbody>
                            </table>
                        </div>
                    `;

                    trDetail.innerHTML = `<td colspan="8" style="padding: 10px 15px; background: rgba(30,46,68,0.4);">${ordersHtml}</td>`;
                    tbody.appendChild(trDetail);

                    // Click handler per espandere/collassare la tabella degli ordini
                    tr.addEventListener('click', () => {
                        const isHidden = trDetail.classList.contains('hidden');
                        const caret = tr.querySelector('.wip-caret');
                        if (isHidden) {
                            trDetail.classList.remove('hidden');
                            caret.innerHTML = '&#9660;';
                        } else {
                            trDetail.classList.add('hidden');
                            caret.innerHTML = '&#9654;';
                        }
                    });
                });
            }

            if (src) {
                src.textContent = `Aggiornato alle: ${new Date().toLocaleTimeString('it-IT')}`;
            }

            renderWipChart(data);

        } catch (e) {
            console.error('Errore caricamento WIP:', e);
            if (src) src.textContent = 'Errore: ' + e.message;
        }
    }

    function renderWipChart(data) {
        const baseFont = rootFontPx();
        const tickFont = Math.round(baseFont * 0.8);
        const titleFont = Math.round(baseFont * 0.85);
        const tooltipBody = Math.round(baseFont * 0.85);

        // 1. Monthly Chart (Stacked Bar)
        const monthlyCtx = document.getElementById('chart-wip-monthly').getContext('2d');
        const monthlyDatasets = [
            {
                label: 'WIP OK',
                data: data.chartMonthly.valOk,
                backgroundColor: '#81c784',
                borderColor: '#81c784',
                borderWidth: 1,
                stack: 'combined'
            },
            {
                label: 'WIP FAIL',
                data: data.chartMonthly.valFail,
                backgroundColor: '#ff5252',
                borderColor: '#ff5252',
                borderWidth: 1,
                stack: 'combined'
            }
        ];

        if (wipMonthlyChartInstance) {
            wipMonthlyChartInstance.data.labels = data.chartMonthly.labels;
            wipMonthlyChartInstance.data.datasets[0].data = data.chartMonthly.valOk;
            wipMonthlyChartInstance.data.datasets[1].data = data.chartMonthly.valFail;
            wipMonthlyChartInstance.update('none');
        } else {
            wipMonthlyChartInstance = new Chart(monthlyCtx, {
                type: 'bar',
                data: {
                    labels: data.chartMonthly.labels,
                    datasets: monthlyDatasets
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    interaction: { mode: 'index', intersect: false },
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            backgroundColor: 'rgba(20,32,46,0.95)',
                            titleColor: '#f2f6fb',
                            bodyColor: '#e8ecf2',
                            borderColor: '#4fc3f7',
                            borderWidth: 1,
                            padding: Math.round(baseFont * 0.75),
                            titleFont: { size: tooltipBody + 1, weight: '600' },
                            bodyFont: { size: tooltipBody },
                            callbacks: {
                                label: (c) => {
                                    return c.dataset.label + ': ' + formatEUR(c.parsed.y);
                                },
                                footer: (items) => {
                                    let sum = 0;
                                    items.forEach(item => { sum += item.parsed.y; });
                                    return 'WIP Totale: ' + formatEUR(sum);
                                }
                            }
                        }
                    },
                    scales: {
                        x: {
                            stacked: true,
                            ticks: { color: '#8fa3bf', font: { size: tickFont } },
                            grid: { color: 'rgba(255,255,255,0.04)' }
                        },
                        y: {
                            stacked: true,
                            ticks: {
                                color: '#8fa3bf',
                                font: { size: 12 },
                                callback: (v) => formatEUR(v)
                            },
                            grid: { color: 'rgba(255,255,255,0.04)' },
                            title: {
                                display: true,
                                text: 'Valore (€)',
                                color: '#8fa3bf',
                                font: { size: titleFont, weight: '600' }
                            }
                        }
                    }
                }
            });
        }

        // 2. Daily Chart (Stacked Area)
        const dailyCtx = document.getElementById('chart-wip-daily').getContext('2d');
        const dailyDatasets = [
            {
                label: 'WIP OK',
                data: data.chartDaily.valOk,
                borderColor: '#81c784',
                backgroundColor: 'rgba(129,199,132,0.3)',
                borderWidth: 2,
                fill: true,
                tension: 0.25,
                pointRadius: 1,
                pointHoverRadius: 4,
            },
            {
                label: 'WIP FAIL',
                data: data.chartDaily.valFail,
                borderColor: '#ff5252',
                backgroundColor: 'rgba(255,82,82,0.3)',
                borderWidth: 2,
                fill: true,
                tension: 0.25,
                pointRadius: 1,
                pointHoverRadius: 4,
            }
        ];

        if (wipDailyChartInstance) {
            wipDailyChartInstance.data.labels = data.chartDaily.labels;
            wipDailyChartInstance.data.datasets[0].data = data.chartDaily.valOk;
            wipDailyChartInstance.data.datasets[1].data = data.chartDaily.valFail;
            wipDailyChartInstance.update('none');
        } else {
            wipDailyChartInstance = new Chart(dailyCtx, {
                type: 'line',
                data: {
                    labels: data.chartDaily.labels,
                    datasets: dailyDatasets
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    interaction: { mode: 'index', intersect: false },
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            backgroundColor: 'rgba(20,32,46,0.95)',
                            titleColor: '#f2f6fb',
                            bodyColor: '#e8ecf2',
                            borderColor: '#4fc3f7',
                            borderWidth: 1,
                            padding: Math.round(baseFont * 0.75),
                            titleFont: { size: tooltipBody + 1, weight: '600' },
                            bodyFont: { size: tooltipBody },
                            callbacks: {
                                label: (c) => {
                                    return c.dataset.label + ': ' + formatEUR(c.parsed.y);
                                },
                                footer: (items) => {
                                    let sum = 0;
                                    items.forEach(item => { sum += item.parsed.y; });
                                    return 'WIP Totale: ' + formatEUR(sum);
                                }
                            }
                        }
                    },
                    scales: {
                        x: {
                            ticks: { color: '#8fa3bf', font: { size: tickFont } },
                            grid: { color: 'rgba(255,255,255,0.04)' }
                        },
                        y: {
                            stacked: true,
                            ticks: {
                                color: '#8fa3bf',
                                font: { size: 12 },
                                callback: (v) => formatEUR(v)
                            },
                            grid: { color: 'rgba(255,255,255,0.04)' },
                            title: {
                                display: true,
                                text: 'Valore (€)',
                                color: '#8fa3bf',
                                font: { size: titleFont, weight: '600' }
                            }
                        }
                    }
                }
            });
        }
    }

    // Toggle view logic
    function toggleView(forceView) {
        const nextView = forceView || (currentView === 'production' ? 'wip' : 'production');
        if (nextView === currentView) return;

        currentView = nextView;
        secondsSinceRotation = 0; // resetta contatore rotazione

        const btn = document.getElementById('toggle-view-btn');
        const prodKpis = document.getElementById('kpis-production');
        const wipKpis = document.getElementById('kpis-wip');
        const prodPanel = document.getElementById('panel-production');
        const wipPanel = document.getElementById('panel-wip');
        const exportBtn = document.getElementById('export-btn');
        const exportWipBtn = document.getElementById('export-wip-btn');

        if (currentView === 'production') {
            btn.textContent = 'Vai a WIP';
            wipKpis.classList.add('hidden');
            prodKpis.classList.remove('hidden');
            wipPanel.classList.add('hidden');
            prodPanel.classList.remove('hidden');
            exportWipBtn.classList.add('hidden');
            exportBtn.classList.remove('hidden');

            if (chartInstance) {
                chartInstance.resize();
                chartInstance.update();
            }
        } else {
            btn.textContent = 'Vai a Produzione';
            prodKpis.classList.add('hidden');
            wipKpis.classList.remove('hidden');
            prodPanel.classList.add('hidden');
            wipPanel.classList.remove('hidden');
            exportBtn.classList.add('hidden');
            exportWipBtn.classList.remove('hidden');

            loadWipMetrics();
        }
    }

    function updatePauseButton() {
        const pauseBtn = document.getElementById('pause-rotation-btn');
        if (!pauseBtn) return;
        
        if (rotationPaused) {
            pauseBtn.className = 'btn-rotate-paused';
            const mins = Math.floor(pauseSecondsRemaining / 60);
            const secs = pauseSecondsRemaining % 60;
            pauseBtn.textContent = `Auto-swap: Pausa (${pad(mins)}:${pad(secs)})`;
        } else {
            pauseBtn.className = 'btn-rotate-active';
            pauseBtn.textContent = 'Auto-swap: Attivo';
        }
    }

    function togglePauseRotation() {
        rotationPaused = !rotationPaused;
        if (rotationPaused) {
            pauseSecondsRemaining = PAUSE_MINUTES * 60;
        } else {
            pauseSecondsRemaining = 0;
            secondsSinceRotation = 0;
        }
        updatePauseButton();
    }

    // Initialize pause button state
    updatePauseButton();

    const pauseBtn = document.getElementById('pause-rotation-btn');
    if (pauseBtn) {
        pauseBtn.addEventListener('click', togglePauseRotation);
    }

    // Wiring up view toggling
    document.getElementById('toggle-view-btn').addEventListener('click', () => {
        toggleView();
    });

    // Refresh action
    document.getElementById('refresh-btn').addEventListener('click', () => {
        refreshAllData();
    });

    // Export Excel Production
    const exportBtn = document.getElementById('export-btn');
    if (exportBtn) {
        exportBtn.addEventListener('click', async () => {
            exportBtn.disabled = true;
            const original = exportBtn.textContent;
            exportBtn.textContent = 'Generazione…';
            try {
                const resp = await fetch('/api/export/month-excel', { cache: 'no-store' });
                if (!resp.ok) {
                    let msg = 'HTTP ' + resp.status;
                    try {
                        const j = await resp.json();
                        if (j && j.error) msg = j.error;
                    } catch (_) { }
                    throw new Error(msg);
                }
                const disp = resp.headers.get('Content-Disposition') || '';
                const m = /filename="?([^";]+)"?/i.exec(disp);
                const filename = m ? m[1] : 'ProductionValue.xlsx';

                const blob = await resp.blob();
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = filename;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                setTimeout(() => URL.revokeObjectURL(url), 1500);
            } catch (e) {
                console.error('Errore export Excel:', e);
                alert('Errore nella generazione del file Excel: ' + e.message);
            } finally {
                exportBtn.disabled = false;
                exportBtn.textContent = original;
            }
        });
    }

    // Export Excel WIP
    const exportWipBtn = document.getElementById('export-wip-btn');
    if (exportWipBtn) {
        exportWipBtn.addEventListener('click', async () => {
            exportWipBtn.disabled = true;
            const original = exportWipBtn.textContent;
            exportWipBtn.textContent = 'Generazione…';
            try {
                const resp = await fetch('/api/export/wip-excel', { cache: 'no-store' });
                if (!resp.ok) {
                    let msg = 'HTTP ' + resp.status;
                    try {
                        const j = await resp.json();
                        if (j && j.error) msg = j.error;
                    } catch (_) { }
                    throw new Error(msg);
                }
                const disp = resp.headers.get('Content-Disposition') || '';
                const m = /filename="?([^";]+)"?/i.exec(disp);
                const filename = m ? m[1] : 'WIP_Report.xlsx';

                const blob = await resp.blob();
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = filename;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                setTimeout(() => URL.revokeObjectURL(url), 1500);
            } catch (e) {
                console.error('Errore export WIP Excel:', e);
                alert('Errore nella generazione del file Excel WIP: ' + e.message);
            } finally {
                exportWipBtn.disabled = false;
                exportWipBtn.textContent = original;
            }
        });
    }

    updateClock();
    setInterval(updateClock, 1000);
    updateCountdown();
    startCountdown();
    loadMetrics();

    // Resize handlers
    let resizeTimer = null;
    window.addEventListener('resize', () => {
        if (resizeTimer) clearTimeout(resizeTimer);
        resizeTimer = setTimeout(() => {
            if (chartInstance) {
                chartInstance.destroy();
                chartInstance = null;
            }
            if (wipMonthlyChartInstance) {
                wipMonthlyChartInstance.destroy();
                wipMonthlyChartInstance = null;
            }
            if (wipDailyChartInstance) {
                wipDailyChartInstance.destroy();
                wipDailyChartInstance = null;
            }
            loadMetrics();
            if (currentView === 'wip') {
                loadWipMetrics();
            }
        }, 250);
    });
})();
