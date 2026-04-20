(function () {
    const REFRESH_MINUTES = parseInt(document.body.dataset.refreshMinutes || '60', 10);
    let chartInstance = null;
    let countdownSeconds = REFRESH_MINUTES * 60;
    let countdownInterval = null;

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
            countdownSeconds--;
            updateCountdown();
            if (countdownSeconds <= 0) {
                loadMetrics();
            }
        }, 1000);
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
        // Dimensione del font root in px, usata per scalare il font di Chart.js
        // insieme al resto dell'interfaccia (vedi css html { font-size: clamp(...) }).
        return parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
    }

    function renderChart(data) {
        const ctx = document.getElementById('chart').getContext('2d');
        const baseFont = rootFontPx();
        const tickFont = Math.round(baseFont * 0.8);   // ~12px su 16px root, scala su 4K
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

    document.getElementById('refresh-btn').addEventListener('click', loadMetrics);

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
                    } catch (_) { /* non-json */ }
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

    updateClock();
    setInterval(updateClock, 1000);
    updateCountdown();
    startCountdown();
    loadMetrics();

    // Ridisegna il chart (per ricalcolare font in base al nuovo root font-size)
    // quando la finestra del browser viene ridimensionata / spostata su altro monitor.
    let resizeTimer = null;
    window.addEventListener('resize', () => {
        if (resizeTimer) clearTimeout(resizeTimer);
        resizeTimer = setTimeout(() => {
            if (chartInstance) {
                chartInstance.destroy();
                chartInstance = null;
                loadMetrics();
            }
        }, 250);
    });
})();
