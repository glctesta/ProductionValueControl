# Daily Targets DB Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sostituire la costante `config.json["dailyValue"]` con una pianificazione giornaliera variabile su DB (`traceability_rs.dbo.DailyProductionTargets`), gestita via pagina admin in dashboard, con fallback al valore JSON per i giorni non pianificati.

**Architecture:** Nuovo `TargetService` dedicato (Approccio 1 dello spec) iniettato in `MetricsService` via DI. Tutte le scritture passano per nuove route `/api/targets/*`. Admin UI vanilla JS in `/admin/targets`. Il fallback al `config.json` e' interamente confinato nel `TargetService`.

**Tech Stack:** Python 3 + Flask, pyodbc su SQL Server (`traceability_rs`), Jinja2, vanilla JS, CSS coerente con la dashboard. Nessun test framework: verifica manuale via REPL, curl e browser.

**Reference spec:** [docs/superpowers/specs/2026-05-13-daily-targets-db-design.md](../specs/2026-05-13-daily-targets-db-design.md)

---

## File Structure

**Nuovi file:**
- `sql/create_daily_production_targets.sql` — script DDL idempotente
- `services/target_service.py` — letture/scritture target + fallback
- `templates/admin_targets.html` — pagina admin
- `static/css/admin_targets.css` — stile admin
- `static/js/admin_targets.js` — logica client admin

**File modificati:**
- `services/metrics_service.py` — costruttore prende `target_service`; sostituzioni puntuali per target variabile
- `app.py` — wiring `TargetService`, nuove route `/admin/targets` e `/api/targets/*`
- `templates/index.html` — link "Pianifica target" nell'header
- `README.md` — `dailyValue` documentato come fallback, sezione "Pianificazione target"

---

## Convenzioni di progetto da rispettare

- **DB**: pattern `conn = self.db.connect(); with conn.cursor() as cursor: cursor.execute(query, *params)`. `autocommit=True` ereditato da `DatabaseConnection`. Placeholder `?` (pyodbc).
- **Logging**: `logger = logging.getLogger(__name__)` a livello modulo. INFO per operazioni utente, ERROR per eccezioni gestite.
- **Tipi**: `from typing import Dict, List, Optional, Tuple`, `from datetime import date, datetime`. Docstring brevi in italiano (coerente con il resto).
- **Naming**: snake_case per Python, camelCase per JSON di API/output.
- **Niente test automatici**: la verifica e' manuale. Ogni task definisce comandi/azioni concrete.

---

## Task 1: Schema DB

**Files:**
- Create: `sql/create_daily_production_targets.sql`

- [ ] **Step 1: Crea la directory `sql/`**

```bash
mkdir sql
```

- [ ] **Step 2: Crea lo script DDL idempotente**

File: `sql/create_daily_production_targets.sql`

```sql
-- Tabella pianificazione target giornaliero di produzione.
-- Una riga per giorno lavorativo pianificato. I giorni senza riga
-- usano il fallback definito in config.json["dailyValue"].
IF NOT EXISTS (
    SELECT 1
    FROM sys.tables t
    INNER JOIN sys.schemas s ON t.schema_id = s.schema_id
    WHERE s.name = 'dbo' AND t.name = 'DailyProductionTargets'
)
BEGIN
    CREATE TABLE traceability_rs.dbo.DailyProductionTargets (
        PlanDate    DATE          NOT NULL,
        DailyValue  DECIMAL(12,2) NOT NULL,
        Notes       NVARCHAR(255) NULL,
        CreatedAt   DATETIME2(0)  NOT NULL CONSTRAINT DF_DPT_CreatedAt DEFAULT SYSUTCDATETIME(),
        UpdatedAt   DATETIME2(0)  NULL,
        CONSTRAINT PK_DailyProductionTargets PRIMARY KEY (PlanDate),
        CONSTRAINT CK_DPT_DailyValue_Positive CHECK (DailyValue > 0)
    );

    PRINT 'Tabella DailyProductionTargets creata.';
END
ELSE
BEGIN
    PRINT 'Tabella DailyProductionTargets gia' presente, nessuna azione.';
END
```

- [ ] **Step 3: Esegui lo script su `traceability_rs`**

Esegui via SQL Server Management Studio (o `sqlcmd`) sul DB `traceability_rs`.
Output atteso: `Tabella DailyProductionTargets creata.`

- [ ] **Step 4: Verifica lo schema della tabella**

Query di verifica:

```sql
SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COLUMN_DEFAULT
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_CATALOG = 'traceability_rs'
  AND TABLE_SCHEMA = 'dbo'
  AND TABLE_NAME = 'DailyProductionTargets'
ORDER BY ORDINAL_POSITION;
```

Output atteso: 5 colonne (`PlanDate DATE NOT NULL`, `DailyValue DECIMAL NOT NULL`, `Notes NVARCHAR NULL`, `CreatedAt DATETIME2 NOT NULL`, `UpdatedAt DATETIME2 NULL`).

- [ ] **Step 5: Commit**

```bash
git add sql/create_daily_production_targets.sql
git commit -m "feat(db): add DailyProductionTargets table DDL"
```

---

## Task 2: `TargetService` — letture e fallback

**Files:**
- Create: `services/target_service.py`

- [ ] **Step 1: Crea lo scheletro del modulo con le letture**

File: `services/target_service.py`

```python
import logging
from datetime import date
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class TargetService:
    """
    Gestisce il target giornaliero variabile letto dalla tabella
    `traceability_rs.dbo.DailyProductionTargets`.

    Fallback: per qualunque giorno lavorativo senza riga in tabella
    viene restituito il valore di default passato al costruttore
    (tipicamente `config.json["dailyValue"]`).
    """

    def __init__(self, db_connection, calendar_service, fallback_daily_value: float):
        self.db = db_connection
        self.cal = calendar_service
        self.fallback = float(fallback_daily_value)

    def get_target_for_day(self, day: date) -> float:
        """Target del singolo giorno. Se manca riga in tabella -> fallback."""
        query = """
        SELECT DailyValue
        FROM traceability_rs.dbo.DailyProductionTargets
        WHERE PlanDate = ?
        """
        try:
            conn = self.db.connect()
            with conn.cursor() as cursor:
                cursor.execute(query, day)
                row = cursor.fetchone()
        except Exception as e:
            logger.error(f"Errore lettura target per {day}: {e}")
            return self.fallback

        if not row or row[0] is None:
            return self.fallback
        try:
            return float(row[0])
        except (TypeError, ValueError):
            return self.fallback

    def get_targets_for_month(self, year: int, month: int) -> Dict[date, float]:
        """
        Ritorna {working_day: target} per OGNI giorno lavorativo del mese,
        con fallback gia' applicato (mai chiavi mancanti per giorni lavorativi).
        """
        working_days = self.cal.working_days_in_month(year, month)
        raw = self._fetch_rows_for_month(year, month)
        result: Dict[date, float] = {}
        for wd in working_days:
            row = raw.get(wd)
            if row is not None and row.get('value') is not None:
                result[wd] = float(row['value'])
            else:
                result[wd] = self.fallback
        return result

    def get_raw_targets_for_month(self, year: int, month: int) -> Dict[date, Dict]:
        """
        Per l'admin UI: ritorna SOLO le righe esistenti in tabella per il mese,
        con valore e note. Niente fallback.
        """
        return self._fetch_rows_for_month(year, month)

    def _fetch_rows_for_month(self, year: int, month: int) -> Dict[date, Dict]:
        query = """
        SELECT PlanDate, DailyValue, Notes
        FROM traceability_rs.dbo.DailyProductionTargets
        WHERE YEAR(PlanDate) = ? AND MONTH(PlanDate) = ?
        """
        result: Dict[date, Dict] = {}
        try:
            conn = self.db.connect()
            with conn.cursor() as cursor:
                cursor.execute(query, year, month)
                rows = cursor.fetchall()
        except Exception as e:
            logger.error(f"Errore lettura target per {year}-{month:02d}: {e}")
            return result

        for r in rows:
            plan_date = r[0]
            if hasattr(plan_date, 'date'):
                plan_date = plan_date.date()
            result[plan_date] = {
                'value': float(r[1]) if r[1] is not None else None,
                'notes': str(r[2]) if r[2] is not None else None,
            }
        return result
```

- [ ] **Step 2: Verifica le letture via REPL**

Avvia un REPL nella directory del progetto:

```bash
python -c "
from datetime import date
from config_manager import ConfigManager
from db_connection import DatabaseConnection
from services.calendar_service import CalendarService
from services.target_service import TargetService
import json

with open('config.json') as f:
    cfg = json.load(f)
cm = ConfigManager()
db = DatabaseConnection(cm)
cal = CalendarService(country=cfg.get('country','RO'))
ts = TargetService(db, cal, cfg['dailyValue'])
print('get_target_for_day(today):', ts.get_target_for_day(date.today()))
print('get_targets_for_month(2026,5) length:', len(ts.get_targets_for_month(2026,5)))
print('get_raw_targets_for_month(2026,5):', ts.get_raw_targets_for_month(2026,5))
"
```

Output atteso (con tabella vuota): valore fallback (es. `50000.0`) per oggi, dict con ~21 entry tutte uguali al fallback, raw dict vuoto `{}`.

- [ ] **Step 3: Commit**

```bash
git add services/target_service.py
git commit -m "feat(targets): add TargetService read methods with JSON fallback"
```

---

## Task 3: `TargetService` — scritture (upsert / delete / copy)

**Files:**
- Modify: `services/target_service.py`

- [ ] **Step 1: Aggiungi `upsert_targets`**

Aggiungi in coda alla classe `TargetService`, dopo `_fetch_rows_for_month`:

```python
    def upsert_targets(self, rows: List[Dict]) -> int:
        """
        Batch upsert via MERGE. `rows` = [{planDate: date, dailyValue: float, notes: str|None}].
        Ritorna il numero totale di righe interessate.
        """
        if not rows:
            return 0

        merge_sql = """
        MERGE traceability_rs.dbo.DailyProductionTargets AS target
        USING (SELECT ? AS PlanDate, ? AS DailyValue, ? AS Notes) AS source
        ON target.PlanDate = source.PlanDate
        WHEN MATCHED THEN
            UPDATE SET
                DailyValue = source.DailyValue,
                Notes = source.Notes,
                UpdatedAt = SYSUTCDATETIME()
        WHEN NOT MATCHED THEN
            INSERT (PlanDate, DailyValue, Notes)
            VALUES (source.PlanDate, source.DailyValue, source.Notes);
        """

        affected = 0
        conn = self.db.connect()
        with conn.cursor() as cursor:
            for r in rows:
                plan_date = r['planDate']
                if hasattr(plan_date, 'date'):
                    plan_date = plan_date.date()
                value = float(r['dailyValue'])
                notes = r.get('notes')
                if notes is not None:
                    notes = str(notes)[:255]
                try:
                    cursor.execute(merge_sql, plan_date, value, notes)
                    affected += 1
                    logger.info(
                        f"Upsert target {plan_date}: {value:.2f} "
                        f"(notes='{notes or ''}')"
                    )
                except Exception as e:
                    logger.error(f"Errore upsert target {plan_date}: {e}")
        return affected
```

- [ ] **Step 2: Aggiungi `delete_target`**

```python
    def delete_target(self, day: date) -> bool:
        """Rimuove la pianificazione di un giorno. Ritorna True se la riga esisteva."""
        query = "DELETE FROM traceability_rs.dbo.DailyProductionTargets WHERE PlanDate = ?"
        try:
            conn = self.db.connect()
            with conn.cursor() as cursor:
                cursor.execute(query, day)
                rowcount = cursor.rowcount
        except Exception as e:
            logger.error(f"Errore delete target {day}: {e}")
            return False

        if rowcount and rowcount > 0:
            logger.info(f"Delete target {day}: riga rimossa.")
            return True
        return False
```

- [ ] **Step 3: Aggiungi `copy_from_previous_month`**

```python
    def copy_from_previous_month(self, year: int, month: int) -> int:
        """
        Copia i target del mese precedente sui giorni lavorativi del mese target,
        mappando per giorno-del-mese (5 maggio -> 5 giugno SE entrambi lavorativi).
        Non sovrascrive righe gia' esistenti nel mese target. Copia anche le note.
        """
        if month == 1:
            prev_year, prev_month = year - 1, 12
        else:
            prev_year, prev_month = year, month - 1

        prev_raw = self._fetch_rows_for_month(prev_year, prev_month)
        existing_raw = self._fetch_rows_for_month(year, month)
        working_days = set(self.cal.working_days_in_month(year, month))

        to_insert: List[Dict] = []
        for prev_date, payload in prev_raw.items():
            try:
                candidate = date(year, month, prev_date.day)
            except ValueError:
                # giorno del mese inesistente (es. 31 in un mese di 30)
                continue
            if candidate not in working_days:
                continue
            if candidate in existing_raw:
                continue
            to_insert.append({
                'planDate': candidate,
                'dailyValue': payload['value'],
                'notes': payload.get('notes'),
            })

        if not to_insert:
            logger.info(
                f"Copy from previous month {prev_year}-{prev_month:02d} -> "
                f"{year}-{month:02d}: nulla da copiare."
            )
            return 0

        copied = self.upsert_targets(to_insert)
        logger.info(
            f"Copy from previous month {prev_year}-{prev_month:02d} -> "
            f"{year}-{month:02d}: {copied} giorni copiati."
        )
        return copied
```

- [ ] **Step 4: Verifica le scritture via REPL**

```bash
python -c "
from datetime import date
from config_manager import ConfigManager
from db_connection import DatabaseConnection
from services.calendar_service import CalendarService
from services.target_service import TargetService
import json

with open('config.json') as f:
    cfg = json.load(f)
ts = TargetService(DatabaseConnection(ConfigManager()),
                   CalendarService(country=cfg.get('country','RO')),
                   cfg['dailyValue'])
# inserisci una riga di prova
n = ts.upsert_targets([{'planDate': date(2026,5,15), 'dailyValue': 77777, 'notes': 'prova'}])
print('inserted:', n)
print('get_target_for_day(2026-05-15):', ts.get_target_for_day(date(2026,5,15)))
# delete
print('delete:', ts.delete_target(date(2026,5,15)))
print('after delete:', ts.get_target_for_day(date(2026,5,15)))
"
```

Output atteso: `inserted: 1`, `get_target_for_day: 77777.0`, `delete: True`, `after delete: <fallback>`.

- [ ] **Step 5: Commit**

```bash
git add services/target_service.py
git commit -m "feat(targets): add upsert/delete/copy on TargetService"
```

---

## Task 4: Integrazione `TargetService` in `MetricsService`

**Files:**
- Modify: `services/metrics_service.py`
- Modify: `app.py`

- [ ] **Step 1: Modifica il costruttore di `MetricsService`**

File: `services/metrics_service.py`

Sostituisci il costruttore esistente:

```python
    def __init__(self, excel_service, sql_service, calendar_service, target_service):
        self.excel = excel_service
        self.sql = sql_service
        self.cal = calendar_service
        self.targets = target_service
```

Rimuovi tutti i riferimenti a `self.daily_target` (parametro `daily_target` non esiste piu').

- [ ] **Step 2: Inserisci la lookup dei target dentro `compute()`**

Subito dopo la riga:

```python
working_days = self.cal.working_days_in_month(year, month)
```

aggiungi:

```python
        target_per_wd = self.targets.get_targets_for_month(year, month)
        daily_target_today = target_per_wd.get(
            prod_day,
            self.targets.get_target_for_day(prod_day),
        )
```

- [ ] **Step 3: Sostituisci il calcolo di `target_line`**

Trova:

```python
        # Target line cumulativo (lineare)
        target_line = [round(self.daily_target * (i + 1), 2) for i in range(len(working_days))]
        monthly_target = round(self.daily_target * len(working_days), 2)
```

Sostituisci con:

```python
        # Target line cumulativo: somma dei target pianificati (o fallback) per i giorni lavorativi
        target_line: List[float] = []
        cum_target = 0.0
        for wd in working_days:
            cum_target += target_per_wd[wd]
            target_line.append(round(cum_target, 2))
        monthly_target = round(sum(target_per_wd.values()), 2)
```

- [ ] **Step 4: Sostituisci `daily_gap`**

Trova:

```python
        daily_gap = self.daily_target - today_value
```

Sostituisci con:

```python
        daily_gap = daily_target_today - today_value
```

- [ ] **Step 5: Sostituisci `target_daily` (array per tooltip grafico)**

Trova:

```python
        target_daily = [round(self.daily_target, 2)] * len(working_days)
```

Sostituisci con:

```python
        target_daily = [round(target_per_wd[wd], 2) for wd in working_days]
```

- [ ] **Step 6: Sostituisci `'dailyTarget'` nel dict di ritorno**

Trova:

```python
            'dailyTarget': round(self.daily_target, 2),
```

Sostituisci con:

```python
            'dailyTarget': round(daily_target_today, 2),
```

- [ ] **Step 7: Aggiorna il wiring in `app.py`**

File: `app.py`

Sostituisci la riga dell'import (se necessario aggiungi):

```python
from services.target_service import TargetService
```

Sostituisci il blocco di inizializzazione esistente:

```python
metrics_svc = MetricsService(excel_svc, sql_svc, cal_svc, daily_target=config['dailyValue'])
```

con:

```python
target_svc = TargetService(
    db_connection=db,
    calendar_service=cal_svc,
    fallback_daily_value=config['dailyValue'],
)
metrics_svc = MetricsService(excel_svc, sql_svc, cal_svc, target_service=target_svc)
```

- [ ] **Step 8: Avvia l'app e verifica comportamento identico al passato**

Con la tabella `DailyProductionTargets` **vuota**, avvia l'app:

```bash
python app.py
```

Apri `http://localhost:5065/api/metrics` (o la dashboard) e verifica:

- `dailyTarget` = `config.json["dailyValue"]` (es. `50000`)
- `monthlyTarget` = `dailyValue × workingDaysInMonth`
- `chart.target` = serie cumulativa lineare (incrementi costanti)
- `chart.targetDaily` = array di valori tutti uguali al fallback

Confronta numericamente con i valori che vedevi prima della modifica. Devono essere identici.

- [ ] **Step 9: Verifica comportamento con almeno una riga in tabella**

Inserisci manualmente una riga di prova in DB:

```sql
INSERT INTO traceability_rs.dbo.DailyProductionTargets (PlanDate, DailyValue, Notes)
VALUES (CAST(GETDATE() AS DATE), 80000.00, 'test variabile');
```

Ricarica `http://localhost:5065/api/metrics`. Output atteso:
- `dailyTarget` = `80000` (target di oggi, dal DB)
- `monthlyTarget` = somma 80000 + fallback × (workingDays - 1)
- `chart.target` = curva non piu' lineare nel giorno odierno
- `chart.targetDaily[i]` corrispondente a oggi = `80000`, gli altri = fallback

Pulisci la riga:

```sql
DELETE FROM traceability_rs.dbo.DailyProductionTargets WHERE PlanDate = CAST(GETDATE() AS DATE);
```

- [ ] **Step 10: Commit**

```bash
git add services/metrics_service.py app.py
git commit -m "feat(metrics): use TargetService for per-day target lookup"
```

---

## Task 5: Route `GET /api/targets`

**Files:**
- Modify: `app.py`

- [ ] **Step 1: Aggiungi la route**

File: `app.py`

Aggiungi dopo l'ultima `@app.route` esistente (prima di `if __name__ == '__main__':`):

```python
@app.route('/api/targets')
def api_targets_get():
    """
    Ritorna i target pianificati per il mese richiesto + fallback.
    Query params: ?year=YYYY&month=MM (default: mese corrente).
    """
    from flask import request
    try:
        now = datetime.now()
        year = int(request.args.get('year', now.year))
        month = int(request.args.get('month', now.month))
        if not (2020 <= year <= 2100) or not (1 <= month <= 12):
            return jsonify({'error': 'year/month fuori range'}), 400

        working_days = cal_svc.working_days_in_month(year, month)
        raw = target_svc.get_raw_targets_for_month(year, month)

        targets_out = {}
        for wd in working_days:
            iso = wd.isoformat()
            if wd in raw:
                targets_out[iso] = {
                    'value': raw[wd]['value'],
                    'notes': raw[wd].get('notes'),
                    'planned': True,
                }
            else:
                targets_out[iso] = {
                    'value': config['dailyValue'],
                    'notes': None,
                    'planned': False,
                }

        return jsonify({
            'year': year,
            'month': month,
            'workingDays': [wd.isoformat() for wd in working_days],
            'targets': targets_out,
            'fallback': config['dailyValue'],
        })
    except Exception as e:
        logger.exception("Errore GET /api/targets")
        return jsonify({'error': str(e)}), 500
```

- [ ] **Step 2: Verifica la route**

Avvia l'app. Con `curl` (o browser):

```bash
curl "http://localhost:5065/api/targets?year=2026&month=5"
```

Output atteso (JSON):
- `workingDays`: lista di date in formato `YYYY-MM-DD` (giorni lavorativi di maggio 2026 RO)
- `targets`: dict con una entry per ogni working day, `planned: false` se tabella vuota
- `fallback`: 50000 (o valore corrente di `dailyValue`)

Test errori:

```bash
curl "http://localhost:5065/api/targets?year=1999&month=5"
# atteso: 400 con messaggio "year/month fuori range"
```

- [ ] **Step 3: Commit**

```bash
git add app.py
git commit -m "feat(api): add GET /api/targets endpoint"
```

---

## Task 6: Route `POST /api/targets` e `DELETE /api/targets/<date>`

**Files:**
- Modify: `app.py`

- [ ] **Step 1: Aggiungi la route POST**

File: `app.py`

Aggiungi sotto `api_targets_get`:

```python
@app.route('/api/targets', methods=['POST'])
def api_targets_post():
    """
    Upsert batch di target. Body JSON:
      { "year": 2026, "month": 5,
        "rows": [{"planDate": "2026-05-04", "dailyValue": 55000, "notes": "..."}] }
    """
    from flask import request
    try:
        payload = request.get_json(force=True, silent=False) or {}
        year = int(payload.get('year', 0))
        month = int(payload.get('month', 0))
        rows = payload.get('rows', [])

        if not (2020 <= year <= 2100) or not (1 <= month <= 12):
            return jsonify({'error': 'year/month fuori range'}), 400
        if not isinstance(rows, list):
            return jsonify({'error': 'rows deve essere una lista'}), 400

        working_days = set(cal_svc.working_days_in_month(year, month))
        cleaned = []
        for r in rows:
            try:
                d = date.fromisoformat(str(r['planDate']))
            except (KeyError, ValueError, TypeError):
                return jsonify({'error': f"planDate non valido: {r}"}), 400
            if d.year != year or d.month != month:
                return jsonify({'error': f"planDate {d} fuori dal mese richiesto"}), 400
            if d not in working_days:
                return jsonify({'error': f"planDate {d} non e' un giorno lavorativo"}), 400
            try:
                value = float(r['dailyValue'])
            except (KeyError, ValueError, TypeError):
                return jsonify({'error': f"dailyValue non valido per {d}"}), 400
            if not (0 < value <= 1_000_000):
                return jsonify({'error': f"dailyValue {value} fuori range (0, 1.000.000]"}), 400
            notes = r.get('notes')
            if notes is not None:
                notes = str(notes)[:255]
            cleaned.append({'planDate': d, 'dailyValue': value, 'notes': notes})

        affected = target_svc.upsert_targets(cleaned)
        return jsonify({'ok': True, 'affected': affected})
    except Exception as e:
        logger.exception("Errore POST /api/targets")
        return jsonify({'error': str(e)}), 500
```

- [ ] **Step 2: Aggiungi la route DELETE**

```python
@app.route('/api/targets/<date_iso>', methods=['DELETE'])
def api_targets_delete(date_iso: str):
    """Rimuove la pianificazione di un singolo giorno."""
    try:
        d = date.fromisoformat(date_iso)
    except ValueError:
        return jsonify({'error': 'date non valida (atteso YYYY-MM-DD)'}), 400

    try:
        removed = target_svc.delete_target(d)
        return jsonify({'ok': True, 'removed': removed})
    except Exception as e:
        logger.exception(f"Errore DELETE /api/targets/{date_iso}")
        return jsonify({'error': str(e)}), 500
```

- [ ] **Step 3: Verifica POST e DELETE**

Con l'app in esecuzione:

```bash
# Upsert
curl -X POST "http://localhost:5065/api/targets" \
     -H "Content-Type: application/json" \
     -d '{"year":2026,"month":5,"rows":[{"planDate":"2026-05-04","dailyValue":55000,"notes":"test"}]}'
```

Output atteso: `{"ok": true, "affected": 1}`. Verifica in DB la presenza della riga.

```bash
# Errore: giorno non lavorativo
curl -X POST "http://localhost:5065/api/targets" \
     -H "Content-Type: application/json" \
     -d '{"year":2026,"month":5,"rows":[{"planDate":"2026-05-03","dailyValue":55000}]}'
```

Output atteso: 400 (3 maggio 2026 e' domenica).

```bash
# Errore: valore fuori range
curl -X POST "http://localhost:5065/api/targets" \
     -H "Content-Type: application/json" \
     -d '{"year":2026,"month":5,"rows":[{"planDate":"2026-05-04","dailyValue":0}]}'
```

Output atteso: 400.

```bash
# Delete
curl -X DELETE "http://localhost:5065/api/targets/2026-05-04"
```

Output atteso: `{"ok": true, "removed": true}`. Verifica in DB l'assenza.

- [ ] **Step 4: Commit**

```bash
git add app.py
git commit -m "feat(api): add POST/DELETE /api/targets endpoints"
```

---

## Task 7: Route `POST /api/targets/copy-previous-month`

**Files:**
- Modify: `app.py`

- [ ] **Step 1: Aggiungi la route**

File: `app.py`

Aggiungi sotto `api_targets_delete`:

```python
@app.route('/api/targets/copy-previous-month', methods=['POST'])
def api_targets_copy_previous_month():
    """
    Copia la pianificazione del mese precedente sui giorni lavorativi del mese target.
    Body JSON: { "year": 2026, "month": 6 }
    """
    from flask import request
    try:
        payload = request.get_json(force=True, silent=False) or {}
        year = int(payload.get('year', 0))
        month = int(payload.get('month', 0))
        if not (2020 <= year <= 2100) or not (1 <= month <= 12):
            return jsonify({'error': 'year/month fuori range'}), 400

        copied = target_svc.copy_from_previous_month(year, month)
        return jsonify({'ok': True, 'copied': copied})
    except Exception as e:
        logger.exception("Errore POST /api/targets/copy-previous-month")
        return jsonify({'error': str(e)}), 500
```

- [ ] **Step 2: Verifica la route**

Prepara dati nel mese precedente (es. maggio 2026):

```sql
INSERT INTO traceability_rs.dbo.DailyProductionTargets (PlanDate, DailyValue, Notes)
VALUES ('2026-05-04', 60000, 'lunedi tipo'),
       ('2026-05-05', 60000, 'martedi tipo');
```

Esegui la copia su giugno 2026:

```bash
curl -X POST "http://localhost:5065/api/targets/copy-previous-month" \
     -H "Content-Type: application/json" \
     -d '{"year":2026,"month":6}'
```

Output atteso: `{"ok": true, "copied": 2}`. Verifica in DB:

```sql
SELECT * FROM traceability_rs.dbo.DailyProductionTargets
WHERE PlanDate IN ('2026-06-04', '2026-06-05');
```

Devono esistere entrambe le righe (4 e 5 giugno sono lavorativi).

Test idempotenza: riesegui la copia. Output atteso: `{"ok": true, "copied": 0}` (righe gia' esistenti non sovrascritte).

Pulizia:

```sql
DELETE FROM traceability_rs.dbo.DailyProductionTargets
WHERE PlanDate IN ('2026-05-04','2026-05-05','2026-06-04','2026-06-05');
```

- [ ] **Step 3: Commit**

```bash
git add app.py
git commit -m "feat(api): add POST /api/targets/copy-previous-month endpoint"
```

---

## Task 8: Pagina admin — route HTML e template

**Files:**
- Create: `templates/admin_targets.html`
- Modify: `app.py`

- [ ] **Step 1: Aggiungi la route Flask**

File: `app.py`

Aggiungi sotto `api_targets_copy_previous_month`:

```python
@app.route('/admin/targets')
def admin_targets():
    return render_template('admin_targets.html')
```

- [ ] **Step 2: Crea il template HTML**

File: `templates/admin_targets.html`

```html
<!doctype html>
<html lang="it">
<head>
    <meta charset="utf-8" />
    <title>ProductionValue — Pianificazione Target</title>
    <link rel="stylesheet" href="{{ url_for('static', filename='css/admin_targets.css') }}" />
</head>
<body>
    <header class="admin-header">
        <a class="back-link" href="/">&larr; Dashboard</a>
        <h1>Pianificazione Target Giornalieri</h1>
    </header>

    <section class="controls">
        <label>Mese:
            <select id="month-select"></select>
        </label>
        <label>Anno:
            <select id="year-select"></select>
        </label>
        <button id="btn-load" type="button">Carica</button>
        <span class="fallback-info">
            Valore di default: <strong id="fallback-value">—</strong>
        </span>
    </section>

    <section class="bulk-tools">
        <label>Applica a tutti i vuoti:
            <input id="bulk-value" type="number" min="1" max="1000000" step="1" />
        </label>
        <button id="btn-bulk" type="button">Applica</button>
        <button id="btn-copy-prev" type="button">Copia dal mese precedente</button>
    </section>

    <section class="grid-wrap">
        <table class="targets-grid">
            <thead>
                <tr>
                    <th>Data</th>
                    <th>Giorno</th>
                    <th>Target (€)</th>
                    <th>Note</th>
                </tr>
            </thead>
            <tbody id="targets-body">
                <tr><td colspan="4" class="placeholder">Carica un mese per iniziare.</td></tr>
            </tbody>
        </table>
    </section>

    <section class="totals">
        Totale mensile pianificato: <strong id="month-total">—</strong>
    </section>

    <section class="actions">
        <button id="btn-save" type="button" class="primary">Salva mese</button>
        <button id="btn-cancel" type="button">Annulla</button>
    </section>

    <div id="toast" class="toast hidden"></div>

    <script src="{{ url_for('static', filename='js/admin_targets.js') }}"></script>
</body>
</html>
```

- [ ] **Step 3: Verifica che la pagina si carichi**

Avvia l'app e apri `http://localhost:5065/admin/targets`. La pagina deve renderizzare lo scheletro statico (controlli, tabella vuota, bottoni). Sara' priva di stile e logica fino ai prossimi step.

- [ ] **Step 4: Commit**

```bash
git add templates/admin_targets.html app.py
git commit -m "feat(admin): add /admin/targets HTML skeleton"
```

---

## Task 9: Pagina admin — CSS

**Files:**
- Create: `static/css/admin_targets.css`

- [ ] **Step 1: Crea il foglio di stile**

File: `static/css/admin_targets.css`

```css
:root {
    --color-bg: #f5f6fa;
    --color-card: #ffffff;
    --color-border: #d9dce5;
    --color-text: #2b2b2b;
    --color-muted: #777;
    --color-accent: #1F4E78;
    --color-accent-soft: #e8f0f9;
    --color-past: #f2f2f2;
    --color-today: #fff8d8;
    --color-danger: #b03030;
    --color-success: #2b7a3d;
    --radius: 6px;
    --font: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
}

* { box-sizing: border-box; }

body {
    margin: 0;
    font-family: var(--font);
    background: var(--color-bg);
    color: var(--color-text);
}

.admin-header {
    background: var(--color-accent);
    color: white;
    padding: 14px 24px;
    display: flex;
    align-items: center;
    gap: 24px;
}
.admin-header h1 { margin: 0; font-size: 18px; font-weight: 600; }
.back-link {
    color: white;
    text-decoration: none;
    font-size: 14px;
    border: 1px solid rgba(255,255,255,0.4);
    padding: 4px 10px;
    border-radius: var(--radius);
}
.back-link:hover { background: rgba(255,255,255,0.1); }

section { padding: 16px 24px; }
.controls, .bulk-tools, .actions {
    background: var(--color-card);
    border-bottom: 1px solid var(--color-border);
    display: flex;
    gap: 16px;
    align-items: center;
    flex-wrap: wrap;
}
.controls label, .bulk-tools label { display: flex; gap: 8px; align-items: center; font-size: 14px; }
.controls select, .bulk-tools input, .targets-grid input {
    border: 1px solid var(--color-border);
    border-radius: var(--radius);
    padding: 6px 8px;
    font-size: 14px;
    font-family: inherit;
}
button {
    border: 1px solid var(--color-border);
    background: var(--color-card);
    border-radius: var(--radius);
    padding: 6px 14px;
    font-size: 14px;
    cursor: pointer;
}
button:hover { background: var(--color-accent-soft); }
button.primary { background: var(--color-accent); color: white; border-color: var(--color-accent); }
button.primary:hover { filter: brightness(1.1); }

.fallback-info { margin-left: auto; color: var(--color-muted); font-size: 13px; }

.grid-wrap { padding: 0 24px; }
.targets-grid {
    width: 100%;
    border-collapse: collapse;
    background: var(--color-card);
    border: 1px solid var(--color-border);
    border-radius: var(--radius);
    overflow: hidden;
    font-size: 14px;
}
.targets-grid th, .targets-grid td {
    padding: 8px 12px;
    border-bottom: 1px solid var(--color-border);
    text-align: left;
}
.targets-grid th { background: #fafbfc; font-weight: 600; }
.targets-grid tr.past td { background: var(--color-past); }
.targets-grid tr.today td { background: var(--color-today); border-left: 3px solid var(--color-accent); }
.targets-grid td.badge { color: var(--color-accent); font-weight: 600; font-size: 12px; }
.targets-grid input.value { width: 140px; text-align: right; }
.targets-grid input.notes { width: 260px; }
.targets-grid td.placeholder { text-align: center; color: var(--color-muted); padding: 24px; }

.totals { background: var(--color-card); border-bottom: 1px solid var(--color-border); font-size: 15px; }
.totals strong { color: var(--color-accent); font-size: 18px; }

.toast {
    position: fixed; bottom: 24px; right: 24px;
    padding: 12px 18px; border-radius: var(--radius);
    color: white; font-size: 14px; box-shadow: 0 4px 12px rgba(0,0,0,0.15);
    transition: opacity 0.3s;
}
.toast.success { background: var(--color-success); }
.toast.error { background: var(--color-danger); }
.toast.hidden { opacity: 0; pointer-events: none; }
```

- [ ] **Step 2: Verifica nel browser**

Ricarica `http://localhost:5065/admin/targets`. La pagina deve ora avere header blu, controlli organizzati su righe, tabella pulita. Niente dati ancora.

- [ ] **Step 3: Commit**

```bash
git add static/css/admin_targets.css
git commit -m "feat(admin): add CSS for /admin/targets"
```

---

## Task 10: Pagina admin — JS logica

**Files:**
- Create: `static/js/admin_targets.js`

- [ ] **Step 1: Crea lo script JS**

File: `static/js/admin_targets.js`

```javascript
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
```

- [ ] **Step 2: Verifica il flusso completo nel browser**

Apri `http://localhost:5065/admin/targets`. Verifica:

1. La griglia si popola con tutti i giorni lavorativi del mese corrente.
2. I placeholder mostrano il valore di fallback.
3. Il giorno odierno ha sfondo giallo e badge "oggi", i passati hanno sfondo grigio.
4. Cambiando mese/anno e cliccando "Carica" la griglia si aggiorna.
5. Inserendo valori in alcune righe, il totale mensile si aggiorna in tempo reale.
6. "Applica a tutti i vuoti" con valore `45000` popola solo gli input ancora vuoti.
7. "Salva mese": toast verde "Salvataggio OK: N aggiornati"; ricaricando la pagina i valori persistono.
8. Svuotando un input e ri-salvando, quel giorno torna al fallback (toast indica `rimossi: 1`).
9. "Copia dal mese precedente": chiede conferma, poi mostra il numero di giorni copiati.
10. Provando valore negativo o > 1.000.000: silenziosamente ignorato lato client; provando comunque a forzare via curl il server respinge.

- [ ] **Step 3: Commit**

```bash
git add static/js/admin_targets.js
git commit -m "feat(admin): add JS logic for /admin/targets"
```

---

## Task 11: Link "Pianifica target" in dashboard

**Files:**
- Modify: `templates/index.html`

- [ ] **Step 1: Trova l'header della dashboard**

File: `templates/index.html`

Leggi il file e identifica l'header della dashboard (probabile blocco `<header>` o il titolo principale).

- [ ] **Step 2: Aggiungi il link**

Dentro l'header della dashboard, aggiungi accanto al titolo (o in una zona "actions" se esiste) il link:

```html
<a href="/admin/targets" class="admin-link" title="Pianifica i target giornalieri">
    Pianifica target
</a>
```

Se l'header non ha un selettore CSS adatto, definisci uno stile minimo nello stesso file o nel CSS della dashboard:

```html
<style>
    .admin-link {
        margin-left: 12px;
        font-size: 13px;
        color: #1F4E78;
        text-decoration: none;
        border: 1px solid #d9dce5;
        padding: 4px 10px;
        border-radius: 6px;
        background: #fff;
    }
    .admin-link:hover { background: #e8f0f9; }
</style>
```

- [ ] **Step 3: Verifica nel browser**

Apri `http://localhost:5065/`. Verifica che il link "Pianifica target" compaia accanto al titolo, sia leggibile e cliccabile, e che porti a `/admin/targets`. Il link "← Dashboard" della pagina admin deve riportare alla dashboard.

- [ ] **Step 4: Commit**

```bash
git add templates/index.html
git commit -m "feat(dashboard): add link to /admin/targets"
```

---

## Task 12: Aggiornamento README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Aggiorna la descrizione di `dailyValue`**

File: `README.md`

Trova la riga nella tabella dei parametri:

```
| `dailyValue` | 50000 | Target giornaliero in € |
```

Sostituisci con:

```
| `dailyValue` | 50000 | Target giornaliero **di fallback** in €. Usato per i giorni lavorativi senza pianificazione nella tabella `DailyProductionTargets`. |
```

E nella sezione "Target mensile = ..." sostituisci:

```
- Target mensile = `dailyValue × giorni_lavorativi_mese`.
```

con:

```
- Target mensile = somma dei target pianificati in `DailyProductionTargets` per i giorni lavorativi del mese; per i giorni privi di pianificazione si usa il fallback `dailyValue`.
```

- [ ] **Step 2: Aggiungi una nuova sezione "Pianificazione target"**

In fondo al README (o dopo la sezione "Configurazione"):

```markdown
## Pianificazione target giornalieri

I target di produzione giornalieri sono memorizzati in
`traceability_rs.dbo.DailyProductionTargets`. Per popolarli usa la pagina
admin integrata alla dashboard:

- URL: `/admin/targets`
- Funzioni: vista mensile dei giorni lavorativi, modifica per giorno, applica
  bulk a tutti i vuoti, copia pianificazione dal mese precedente.
- Persistenza: i valori sono salvati su DB al click di "Salva mese".
- Fallback: ogni giorno lavorativo senza riga in tabella usa
  `config.json["dailyValue"]` come valore di default.

### Inizializzazione tabella

Esegui una sola volta lo script `sql/create_daily_production_targets.sql`
su `traceability_rs`. Lo script e' idempotente (controlla l'esistenza
prima di creare).
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: update README for DB-backed daily targets"
```

---

## Verifica end-to-end finale

- [ ] **Step 1: Esegui i 9 scenari della checklist dello spec**

Lavora dallo spec [docs/superpowers/specs/2026-05-13-daily-targets-db-design.md](../specs/2026-05-13-daily-targets-db-design.md), sezione "Verifica manuale post-implementazione". Per ciascuno scenario (1-9) prepara dati, esegui l'azione descritta, verifica il risultato atteso e annota eventuali discrepanze.

- [ ] **Step 2: Pulizia dati di test**

```sql
-- Mantieni solo i target reali del mese corrente
DELETE FROM traceability_rs.dbo.DailyProductionTargets
WHERE Notes LIKE 'test%' OR Notes LIKE 'prova%';
```

- [ ] **Step 3: Squash review (opzionale)**

Se l'utente preferisce uno storico pulito, fai squash dei commit di task in commit semantici. Altrimenti i commit dei singoli task vanno bene per code review.

---

## Note operative

- **Hot reload**: Flask con `use_reloader=False` non ricarica automaticamente. Riavvia `python app.py` dopo modifiche al backend.
- **Encoding pyodbc**: `DECIMAL` viene letto come `decimal.Decimal`. Convertiamo sempre con `float(...)` prima di usare in JSON o calcoli.
- **MERGE con autocommit**: `DatabaseConnection.connect()` imposta `autocommit=True`. Il `MERGE` viene committato per ogni esecuzione (no transazione esplicita). Se in futuro si vuole atomicita' del batch, va aggiunto `conn.autocommit=False` + `conn.commit()` esplicito attorno al loop di upsert.
- **Calendario festivi**: `CalendarService` legge `country='RO'` e usa la libreria `holidays`. Eventuali modifiche al calendario (es. cambio paese) richiedono pulizia di righe orfane nella tabella (giorni che non sono piu' lavorativi).
