# Spec — KPI "Valore Prodotto Ieri" e "Massimo Giornaliero del Mese"

**Data:** 2026-05-08
**Autore:** brainstorming session
**Stato:** approvato dall'utente, pronto per writing-plans

## Obiettivo

Aggiungere alla dashboard `ProductionValue` due nuovi KPI nell'header:

1. **Valore Prodotto Ieri** — il valore della produzione effettivamente realizzato nel giorno produttivo precedente (finestra 07:30 → 07:30).
2. **Massimo Giornaliero del Mese** — il valore di calendario più alto raggiunto in un singolo giorno produttivo all'interno del mese corrente, con accanto la data in cui è stato raggiunto (formato `gg/mm`).

I nuovi KPI devono essere mostrati assieme agli altri 9 KPI esistenti, mantenendo (per quanto possibile) un layout su singola riga su monitor 1080p+.

## Decisioni di prodotto (chiarite con l'utente)

| ID | Tema | Decisione |
|---|---|---|
| D1 | Semantica "ieri" | **Valore di calendario** del giorno produttivo precedente (finestra 07:30→07:30 di ieri), **senza** carry-forward. Ragione utente: si lavora anche di sabato e quel valore non deve essere riversato. |
| D2 | Semantica "max del mese" | Massimo del valore di calendario tra i giorni del mese corrente **già conclusi** (escluso il giorno produttivo corrente, perche' in corso). Mostra anche la **data** del giorno in cui e' stato raggiunto. |
| D3 | Posizione UI | Subito dopo "Valore Prodotto Mese", per raggruppare i KPI di valore reale: Oggi → Mese → Ieri → Max Mese. |
| D4 | Formato max | Tutto in linea: `€ 78.450 (15/05)`. |
| D5 | Riduzione font | Rimpicciolimento dei font dei KPI per consentire 11 box su una riga su 1080p+; sotto i ~1500px di larghezza il layout va a capo dolcemente (CSS `auto-fit`). |
| D6 | Edge case "ieri = mese precedente" (1° del mese) | Mostra comunque il valore di ieri, anche se appartiene al mese precedente. Richiede una mini-query DB aggiuntiva solo in questa giornata. |
| D7 | Edge case "max = nessun giorno concluso" | Mostra `—` (placeholder coerente con gli altri KPI). |
| D8 | Email / Excel export | Fuori scope per questo task. Si interverra' in seguito se richiesto. |

## File modificati

- `services/metrics_service.py` — calcolo dei due nuovi valori, aggiunti al dict di ritorno di `compute()`.
- `templates/index.html` — due nuovi blocchi `.kpi` dopo `kpi-month-value`.
- `static/js/app.js` — due setter (uno custom per concatenare la data al valore max).
- `static/css/style.css` — riduzione font dei KPI e ricalibratura grid.

Nessun nuovo file. Nessuna modifica a `app.py`, `sql_service.py`, `excel_service.py`, `calendar_service.py`.

## Backend — `services/metrics_service.py`

Dentro `MetricsService.compute()`, **dopo** il calcolo di `value_per_cal_day` e prima del `return`:

### previousDayValue / previousDayDate

```python
prev_day = prod_day - timedelta(days=1)

if prev_day.month == prod_day.month and prev_day.year == prod_day.year:
    # Giorno precedente nello stesso mese: dato gia' disponibile.
    previous_day_value = value_per_cal_day.get(prev_day, 0.0)
else:
    # Caso 1° del mese: ieri appartiene al mese precedente, mini-query mirata.
    prev_start, prev_end = self.production_window(prev_day)
    prev_rows = self.sql.get_month_production(prev_start, prev_end)
    # Risolve i prezzi anche per ordini eventualmente non in price_map / sql_price_map.
    extra_orders = {o for o, _, _ in prev_rows} - set(price_map) - set(sql_price_map)
    for order in extra_orders:
        fb = self.sql.get_price_from_resetservices(order)
        if fb is not None:
            sql_price_map[order] = fb
    previous_day_value = sum(qty * resolve_price(o) for o, _, qty in prev_rows)
```

### monthMaxValue / monthMaxDate

```python
concluded_days = {
    d: v for d, v in value_per_cal_day.items()
    if d < prod_day and d.year == year and d.month == month
}
if concluded_days:
    month_max_date = max(concluded_days, key=concluded_days.get)
    month_max_value = concluded_days[month_max_date]
else:
    month_max_date = None
    month_max_value = None
```

### Aggiunte al dict di ritorno

```python
'previousDayValue': round(previous_day_value, 2),
'previousDayDate': prev_day.isoformat(),
'monthMaxValue': round(month_max_value, 2) if month_max_value is not None else None,
'monthMaxDate': month_max_date.isoformat() if month_max_date else None,
```

## Frontend — `templates/index.html`

Inserire dopo il blocco `kpi-month-value` (linea ~29):

```html
<div class="kpi">
    <span class="kpi-label">Valore Prodotto Ieri</span>
    <span class="kpi-value" id="kpi-previous-day-value">&mdash;</span>
</div>
<div class="kpi">
    <span class="kpi-label">Massimo Giornaliero del Mese</span>
    <span class="kpi-value" id="kpi-month-max">&mdash;</span>
</div>
```

## Frontend — `static/js/app.js`

In `loadMetrics()`, dopo `setKpi('kpi-month-value', data.monthValue);`:

```js
setKpi('kpi-previous-day-value', data.previousDayValue);

const maxEl = document.getElementById('kpi-month-max');
if (maxEl) {
    if (data.monthMaxValue == null) {
        maxEl.textContent = '—';
    } else {
        const d = new Date(data.monthMaxDate);
        const suffix = ' (' + pad(d.getDate()) + '/' + pad(d.getMonth() + 1) + ')';
        maxEl.textContent = formatEUR(data.monthMaxValue) + suffix;
    }
}
```

Nessun `kind` di colorazione: dati informativi, non gap/forecast.

## CSS — `static/css/style.css`

```css
#kpis {
    grid-template-columns: repeat(auto-fit, minmax(10rem, 1fr));  /* da 12rem */
    gap: 0.5rem;  /* da 0.6rem */
}
.kpi {
    padding: 8px 12px;  /* da 10px 14px */
}
.kpi-value {
    font-size: 1.2rem;  /* da 1.45rem */
}
.kpi-label {
    font-size: 0.65rem;  /* da 0.7rem */
    min-height: 2.1em;  /* da 2.3em, lieve compattazione verticale */
}
```

## Test e verifica

Verifica manuale via browser su `http://localhost:5065`:

1. **Caso normale (giorno feriale a meta' mese):**
   - "Valore Prodotto Ieri" mostra l'importo del giorno produttivo precedente, coerente con il valore di calendario di quel giorno (NON con il valore della curva Rolling, che include il carry-forward).
   - "Massimo Giornaliero del Mese" mostra l'importo del giorno di calendario migliore del mese (escluso oggi) + data tra parentesi.
2. **Caso 1° del mese:**
   - "Valore Prodotto Ieri" mostra il valore dell'ultimo giorno del mese precedente (E1).
   - "Massimo Giornaliero del Mese" mostra `—` (nessun giorno concluso del mese corrente).
3. **Caso domenica/festivita' senza produzione il giorno prima:**
   - "Valore Prodotto Ieri" mostra `€ 0`.
4. **Caso sabato lavorato:**
   - Se ieri era sabato e si e' lavorato, "Valore Prodotto Ieri" mostra il valore di sabato (NON 0 e NON riversato a lunedi').
5. **Layout:**
   - Su monitor 1920x1080: 11 KPI su una sola riga.
   - Su monitor 1366x768 o finestre piu' strette: i KPI vanno su 2 righe senza overflow.
   - Su 4K (3840x2160): font scalato proporzionalmente via `clamp()` (gia' presente).

## Fuori scope

- Aggiunta dei due valori al corpo email del report giornaliero (`_build_daily_report_html` in `app.py`).
- Aggiunta al file Excel di export (`services/export_service.py`).
- Modifiche al grafico (es. evidenziare il giorno di max).

Da affrontare in spec separate se richieste.
