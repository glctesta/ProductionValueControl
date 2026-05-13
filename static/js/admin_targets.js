(function () {
    'use strict';

    const MONTHS_IT = [
        'Gennaio', 'Febbraio', 'Marzo', 'Aprile', 'Maggio', 'Giugno',
        'Luglio', 'Agosto', 'Settembre', 'Ottobre', 'Novembre', 'Dicembre',
    ];
    const DAYS_IT = ['Dom', 'Lun', 'Mar', 'Mer', 'Gio', 'Ven', 'Sab'];

    const monthSelect = document.getElementById('month-select');
    const yearSelect = document.getElementById('year-select');
    const btnLoad = document.getElementById('btn-load');
    const fallbackEl = document.getElementById('fallback-value');
    const tbody = document.getElementById('targets-body');
    const bulkInput = document.getElementById('bulk-value');
    const btnBulk = document.getElementById('btn-bulk');
    const btnCopyPrev = document.getElementById('btn-copy-prev');
    const btnSave = document.getElementById('btn-save');
    const btnCancel = document.getElementById('btn-cancel');
    const totalEl = document.getElementById('month-total');
    const toast = document.getElementById('toast');

    let currentFallback = 0;
    let originalServerData = {}; // {iso: {value, notes, planned}}
    let isoTodayStr = new Date().toISOString().slice(0, 10);

    function fmtEUR(v) {
        if (v === null || v === undefined || isNaN(v)) return '—';
        return '€ ' + Number(v).toLocaleString('it-IT', { maximumFractionDigits: 0 });
    }

    function showToast(msg, kind) {
        toast.textContent = msg;
        toast.className = 'toast ' + (kind === 'error' ? 'error' : 'success');
        setTimeout(() => { toast.className = 'toast hidden'; }, 3500);
    }

    function populateMonthYear() {
        const now = new Date();
        MONTHS_IT.forEach((m, idx) => {
            const opt = document.createElement('option');
            opt.value = String(idx + 1);
            opt.textContent = m;
            if (idx + 1 === now.getMonth() + 1) opt.selected = true;
            monthSelect.appendChild(opt);
        });
        for (let y = now.getFullYear() - 1; y <= now.getFullYear() + 2; y++) {
            const opt = document.createElement('option');
            opt.value = String(y);
            opt.textContent = String(y);
            if (y === now.getFullYear()) opt.selected = true;
            yearSelect.appendChild(opt);
        }
    }

    function classifyDay(iso) {
        if (iso < isoTodayStr) return 'past';
        if (iso === isoTodayStr) return 'today';
        return 'future';
    }

    function renderGrid(data) {
        currentFallback = data.fallback;
        fallbackEl.textContent = fmtEUR(currentFallback);
        originalServerData = data.targets;
        tbody.innerHTML = '';

        if (!data.workingDays.length) {
            tbody.innerHTML = '<tr><td colspan="4" class="placeholder">Nessun giorno lavorativo nel mese.</td></tr>';
            updateTotal();
            return;
        }

        data.workingDays.forEach(iso => {
            const entry = data.targets[iso] || {};
            const dt = new Date(iso + 'T00:00:00');
            const cls = classifyDay(iso);

            const tr = document.createElement('tr');
            tr.className = cls;
            tr.dataset.iso = iso;

            const tdDate = document.createElement('td');
            tdDate.textContent = `${DAYS_IT[dt.getDay()]} ${dt.toLocaleDateString('it-IT')}`;
            tr.appendChild(tdDate);

            const tdBadge = document.createElement('td');
            tdBadge.className = 'badge';
            tdBadge.textContent = cls === 'today' ? 'oggi' : (cls === 'past' ? 'passato' : '');
            tr.appendChild(tdBadge);

            const tdValue = document.createElement('td');
            const inpValue = document.createElement('input');
            inpValue.type = 'number';
            inpValue.className = 'value';
            inpValue.min = '1';
            inpValue.max = '1000000';
            inpValue.step = '1';
            inpValue.placeholder = String(currentFallback);
            if (entry.planned) inpValue.value = entry.value;
            inpValue.addEventListener('input', updateTotal);
            tdValue.appendChild(inpValue);
            tr.appendChild(tdValue);

            const tdNotes = document.createElement('td');
            const inpNotes = document.createElement('input');
            inpNotes.type = 'text';
            inpNotes.className = 'notes';
            inpNotes.maxLength = 255;
            if (entry.planned && entry.notes) inpNotes.value = entry.notes;
            tdNotes.appendChild(inpNotes);
            tr.appendChild(tdNotes);

            tbody.appendChild(tr);
        });

        updateTotal();
    }

    function updateTotal() {
        let total = 0;
        tbody.querySelectorAll('tr').forEach(tr => {
            const inp = tr.querySelector('input.value');
            if (!inp) return;
            const v = parseFloat(inp.value);
            total += isNaN(v) ? currentFallback : v;
        });
        totalEl.textContent = fmtEUR(total);
    }

    async function loadMonth() {
        const y = yearSelect.value, m = monthSelect.value;
        try {
            const res = await fetch(`/api/targets?year=${y}&month=${m}`);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            renderGrid(data);
        } catch (e) {
            showToast('Errore caricamento: ' + e.message, 'error');
        }
    }

    function applyBulk() {
        const v = parseFloat(bulkInput.value);
        if (isNaN(v) || v <= 0) {
            showToast('Inserisci un valore valido per il bulk.', 'error');
            return;
        }
        let count = 0;
        tbody.querySelectorAll('tr input.value').forEach(inp => {
            if (inp.value === '' || inp.value === null) {
                inp.value = v;
                count++;
            }
        });
        updateTotal();
        showToast(`${count} giorni vuoti aggiornati.`, 'success');
    }

    async function copyPrev() {
        const y = parseInt(yearSelect.value, 10), m = parseInt(monthSelect.value, 10);
        if (!confirm(`Copiare la pianificazione di ${MONTHS_IT[(m+10)%12]} ${m === 1 ? y-1 : y} su questo mese?`)) return;
        try {
            const res = await fetch('/api/targets/copy-previous-month', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({year: y, month: m}),
            });
            const data = await res.json();
            if (!res.ok || !data.ok) throw new Error(data.error || `HTTP ${res.status}`);
            showToast(`${data.copied} giorni copiati.`, 'success');
            await loadMonth();
        } catch (e) {
            showToast('Errore copia: ' + e.message, 'error');
        }
    }

    async function saveMonth() {
        const y = parseInt(yearSelect.value, 10), m = parseInt(monthSelect.value, 10);
        const rowsToUpsert = [];
        const isosToDelete = [];

        tbody.querySelectorAll('tr').forEach(tr => {
            const iso = tr.dataset.iso;
            const inpV = tr.querySelector('input.value');
            const inpN = tr.querySelector('input.notes');
            if (!inpV) return;
            const raw = inpV.value.trim();
            const wasPlanned = originalServerData[iso] && originalServerData[iso].planned;

            if (raw === '') {
                // utente ha svuotato un valore precedentemente pianificato
                if (wasPlanned) isosToDelete.push(iso);
            } else {
                const v = parseFloat(raw);
                if (isNaN(v) || v <= 0 || v > 1_000_000) return; // validazione lato client; server ricontrolla
                rowsToUpsert.push({
                    planDate: iso,
                    dailyValue: v,
                    notes: inpN.value.trim() || null,
                });
            }
        });

        try {
            let affected = 0, removed = 0;
            if (rowsToUpsert.length) {
                const res = await fetch('/api/targets', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({year: y, month: m, rows: rowsToUpsert}),
                });
                const data = await res.json();
                if (!res.ok || !data.ok) throw new Error(data.error || `HTTP ${res.status}`);
                affected = data.affected;
            }
            for (const iso of isosToDelete) {
                const res = await fetch('/api/targets/' + iso, { method: 'DELETE' });
                const data = await res.json();
                if (res.ok && data.ok && data.removed) removed++;
            }
            showToast(`Salvataggio OK: ${affected} aggiornati, ${removed} rimossi.`, 'success');
            await loadMonth();
        } catch (e) {
            showToast('Errore salvataggio: ' + e.message, 'error');
        }
    }

    btnLoad.addEventListener('click', loadMonth);
    btnBulk.addEventListener('click', applyBulk);
    btnCopyPrev.addEventListener('click', copyPrev);
    btnSave.addEventListener('click', saveMonth);
    btnCancel.addEventListener('click', loadMonth);

    populateMonthYear();
    loadMonth();
})();
