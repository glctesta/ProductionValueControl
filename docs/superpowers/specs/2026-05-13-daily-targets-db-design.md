# Spec — Target Giornalieri Pianificati su DB

**Data:** 2026-05-13
**Autore:** brainstorming session
**Stato:** approvato dall'utente, pronto per writing-plans

## Obiettivo

Sostituire l'attuale singolo valore costante `dailyValue` (letto da `config.json`) con una **pianificazione giornaliera variabile**, memorizzata in una nuova tabella di `traceability_rs`. Quando un giorno lavorativo non e' pianificato in tabella, l'app ripiega sul valore di `config.json["dailyValue"]` (che diventa quindi un **fallback** e non piu' "il" target).

L'utente puo' pianificare i target tramite una nuova pagina di amministrazione `/admin/targets` integrata nella dashboard, con vista mensile editabile.

## Decisioni di prodotto (chiarite con l'utente)

| ID | Tema | Decisione |
|---|---|---|
| D1 | Granularita' tabella | Una riga per **data piena** (`PlanDate DATE PRIMARY KEY`). Storicizza naturalmente, query immediate. |
| D2 | Inserimento dati | **Pagina admin nella dashboard** (`/admin/targets`), non solo SQL diretto. |
| D3 | Giorni non lavorativi | La tabella e l'UI accettano **solo giorni lavorativi** del mese (lun-ven minus festivi RO via `CalendarService`). Coerente con la semantica attuale (target = solo working days). |
| D4 | Ambito del fallback | Fallback applicato a **qualunque giorno lavorativo senza riga** in tabella (passato, presente, futuro). Valore del fallback resta in `config.json["dailyValue"]`. |
| D5 | Livello UI | **Medio**: oltre a edit per giorno, supporta "applica a tutti i vuoti" e "copia dal mese precedente". Distinzione visuale passato/oggi/futuro. Validazione lato server. Nessun audit trail (out of scope). |
| D6 | Architettura | Nuovo `services/target_service.py` come modulo dedicato (Approccio 1). `MetricsService` riceve `target_service` per dependency injection, non parla direttamente con DB. |
| D7 | Autenticazione admin | Nessuna. Coerente con il resto della dashboard (tool interno, accesso di rete controllato a monte). |

## File modificati / creati

**Nuovi**:
- `services/target_service.py`
- `sql/create_daily_production_targets.sql`
- `templates/admin_targets.html`
- `static/css/admin_targets.css`
- `static/js/admin_targets.js`

**Modificati**:
- `app.py` — wiring del `TargetService`, nuove route `/admin/targets` e `/api/targets/*`.
- `services/metrics_service.py` — costruttore riceve `target_service`; sostituzioni puntuali per target variabile.
- `templates/index.html` — link "Pianifica target" nell'header.
- `README.md` — `dailyValue` ora documentato come fallback; nuova sezione "Pianificazione target".

Nessuna modifica a `sql_service.py`, `excel_service.py`, `calendar_service.py`, `report_service.py`, `export_service.py`, `email_service.py`.

## Schema DB

Tabella: `traceability_rs.dbo.DailyProductionTargets`

```sql
CREATE TABLE traceability_rs.dbo.DailyProductionTargets (
    PlanDate    DATE          NOT NULL PRIMARY KEY,
    DailyValue  DECIMAL(12,2) NOT NULL,
    Notes       NVARCHAR(255) NULL,
    CreatedAt   DATETIME2(0)  NOT NULL CONSTRAINT DF_DPT_CreatedAt DEFAULT SYSUTCDATETIME(),
    UpdatedAt   DATETIME2(0)  NULL,
    CONSTRAINT CK_DPT_DailyValue_Positive CHECK (DailyValue > 0)
);
```

- PK su `PlanDate` → un solo target per giorno.
- `DECIMAL(12,2)` → fino a ~10 miliardi con due decimali.
- `Notes` (opzionale) per annotazioni operative (es. "turno ridotto vigilia").
- CHECK > 0 evita valori non sensati.
- Script SQL idempotente con `IF NOT EXISTS`, eseguito una tantum.

## Backend — `services/target_service.py`

Interfaccia pubblica:

```python
class TargetService:
    def __init__(self, db_connection, calendar_service, fallback_daily_value: float):
        ...

    def get_target_for_day(self, day: date) -> float:
        """Target del singolo giorno. Se manca riga in tabella -> fallback JSON."""

    def get_targets_for_month(self, year: int, month: int) -> Dict[date, float]:
        """
        {working_day: target} per OGNI giorno lavorativo del mese, fallback gia' risolto.
        MetricsService riceve sempre un dict completo.
        """

    def get_raw_targets_for_month(self, year: int, month: int) -> Dict[date, Dict]:
        """
        Per l'admin UI: ritorna SOLO le righe esistenti in tabella per il mese
        (con valore e note). Niente fallback. Permette di distinguere
        'pianificato' da 'default' nella griglia di modifica.
        """

    def upsert_targets(self, rows: List[Dict]) -> int:
        """
        Batch upsert (MERGE) di righe {planDate, dailyValue, notes}.
        Aggiorna UpdatedAt. Ritorna numero di righe interessate.
        """

    def delete_target(self, day: date) -> bool:
        """Rimuove la pianificazione di un giorno -> il giorno torna al fallback."""

    def copy_from_previous_month(self, year: int, month: int) -> int:
        """
        Copia i target del mese precedente sui giorni lavorativi del mese target,
        mappando per giorno-del-mese (5 maggio -> 5 giugno se entrambi lavorativi).
        Non sovrascrive righe gia' esistenti del mese target. Copia anche le note.
        """
```

Note implementative:
- Il fallback e' **interamente confinato** in `TargetService`. `MetricsService` non legge `config.json` per il target.
- Le query usano `db.connect()` con `?` placeholder, coerenti con `SqlService`.
- Tutte le scritture loggate INFO (giorno, valore, esito).

## Backend — `services/metrics_service.py`

Cambio del costruttore:

```python
class MetricsService:
    def __init__(self, excel_service, sql_service, calendar_service, target_service):
        self.excel = excel_service
        self.sql = sql_service
        self.cal = calendar_service
        self.targets = target_service
```

Dentro `compute(now)`, dopo `working_days = self.cal.working_days_in_month(year, month)`:

```python
target_per_wd = self.targets.get_targets_for_month(year, month)
# dict completo per ogni giorno lavorativo (con fallback gia' applicato)

daily_target_today = target_per_wd.get(
    prod_day,
    self.targets.get_target_for_day(prod_day)
)
# Se oggi e' lavorativo, dal dict; se non e' lavorativo (es. sabato),
# restituiamo comunque il fallback per coerenza del KPI mostrato.
```

Sostituzioni puntuali:

| Vecchio | Nuovo |
|---|---|
| `target_line = [round(self.daily_target * (i + 1), 2) for i in range(len(working_days))]` | somma cumulata: `cum = 0; for wd in working_days: cum += target_per_wd[wd]; target_line.append(round(cum, 2))` |
| `monthly_target = round(self.daily_target * len(working_days), 2)` | `monthly_target = round(sum(target_per_wd.values()), 2)` |
| `target_daily = [round(self.daily_target, 2)] * len(working_days)` | `target_daily = [round(target_per_wd[wd], 2) for wd in working_days]` |
| `daily_gap = self.daily_target - today_value` | `daily_gap = daily_target_today - today_value` |
| Output `'dailyTarget': round(self.daily_target, 2)` | `'dailyTarget': round(daily_target_today, 2)` |

Conseguenze sul comportamento:
- Curva target a **pendenza variabile** (non piu' lineare). Termina sul `monthlyTarget`.
- Tooltip del grafico (`targetDaily`) mostra il target pianificato del giorno specifico.
- `monthlyTarget` = somma dei target pianificati + fallback per i giorni senza pianificazione (non piu' `daily × giorni`).
- `requiredDailyAdjustment` e `forecastMonth` restano invariati nella formula.

Nessuna modifica a `report_service.py`, `export_service.py`, `email_service.py`: leggono gia' da `metrics['dailyTarget']` / `metrics['monthlyTarget']` che restano nello stesso formato.

## Backend — `app.py`

Wiring:

```python
from services.target_service import TargetService

target_svc = TargetService(
    db_connection=db,
    calendar_service=cal_svc,
    fallback_daily_value=config['dailyValue'],
)

metrics_svc = MetricsService(
    excel_svc, sql_svc, cal_svc, target_service=target_svc
)
```

`config['dailyValue']` resta in `config.json` con significato cambiato: **fallback** per giorni non pianificati.

Nuove route API (`/api/targets/*`):

| Metodo | Route | Scopo |
|---|---|---|
| `GET` | `/api/targets?year=YYYY&month=MM` | `{ workingDays: [...], targets: {date: {value, notes, planned: bool}}, fallback: <number> }`. `planned: false` → fallback. |
| `POST` | `/api/targets` | Body: `{year, month, rows: [{planDate, dailyValue, notes?}]}`. Upsert batch. Ritorna `{ok, affected}`. |
| `DELETE` | `/api/targets/<YYYY-MM-DD>` | Cancella la pianificazione di un giorno (torna al fallback). |
| `POST` | `/api/targets/copy-previous-month` | Body: `{year, month}`. Esegue copia. Ritorna `{ok, copied}`. |

Nuova route HTML:

| Metodo | Route | Scopo |
|---|---|---|
| `GET` | `/admin/targets` | Render di `templates/admin_targets.html`. |

Validazioni server-side (centralizzate nelle route):
- `year` 2020-2100, `month` 1-12.
- `planDate` deve essere un giorno lavorativo del mese richiesto (via `cal_svc`).
- `dailyValue` numero, `> 0`, `<= 1_000_000`.
- `notes` se presente troncata a 255 caratteri.

Logging INFO per ogni upsert/delete/copy.

## Frontend — `templates/admin_targets.html` + assets

Layout pagina:

```
┌──────────────────────────────────────────────────────────────────┐
│  ProductionValue — Pianificazione Target Giornalieri              │
│  [← Dashboard]                                                    │
├──────────────────────────────────────────────────────────────────┤
│  Mese: [Maggio ▼]  Anno: [2026 ▼]   [Carica]                     │
│                                                                   │
│  Valore di default (fallback config.json): € 50.000               │
│                                                                   │
│  [Applica a tutti i vuoti: 50000 ] [Applica]                      │
│  [Copia dal mese precedente]                                      │
├──────────────────────────────────────────────────────────────────┤
│  Data            │ Giorno  │ Target (€)         │ Note            │
│  Lun 04/05/2026  │ ●       │ [    55000      ]  │ [           ]   │
│  Mar 05/05/2026  │ oggi    │ [    50000      ]  │ [           ]   │
│  Mer 06/05/2026  │ futuro  │ [             ]    │ [           ]   │
│  ...                                                              │
├──────────────────────────────────────────────────────────────────┤
│  Totale mensile pianificato: € 1.100.000                          │
│  [Salva mese]      [Annulla]                                      │
└──────────────────────────────────────────────────────────────────┘
```

Comportamento:
- Selettore mese/anno → default mese/anno correnti. Cambiando ricarica via `GET /api/targets`.
- Griglia: solo giorni lavorativi del mese, ordinati cronologicamente.
- Distinzione visuale: passato (sfondo grigio chiaro, editabile), oggi (bordo blu + badge "oggi"), futuro (neutro).
- Placeholder input: valore di fallback in grigio quando il giorno non e' pianificato.
- Note: campo testo a destra, max 255 char.
- "Applica a tutti i vuoti": popola solo gli input vuoti, lato client (no scrittura DB finche' non si salva).
- "Copia dal mese precedente": chiamata `POST /api/targets/copy-previous-month` → ricarica.
- "Salva mese": `POST /api/targets` con righe compilate; per righe svuotate dall'utente esegue `DELETE`. Validazione lato client (>0, <=1.000.000) + ricontrollo server.
- Totale mensile calcolato in tempo reale via JS (somma input compilati + fallback per i vuoti).
- Toast verde/rosso a fine operazione.

File:
- `templates/admin_targets.html`
- `static/css/admin_targets.css` (riusa token CSS della dashboard)
- `static/js/admin_targets.js` (vanilla JS, niente framework)
- `templates/index.html`: link discreto "Pianifica target" nell'header.

## Migrazione e rollout

Migrazione DB: una sola operazione, eseguire `sql/create_daily_production_targets.sql` su `traceability_rs`. Nessun seed: tabella vuota → tutto al fallback.

Rollout in 5 step (l'app resta funzionante e identica al passato dopo lo step 3):

1. Crea tabella DB.
2. Aggiungi `services/target_service.py` (solo lettura/scrittura, no integrazione).
3. Cambia il costruttore di `MetricsService` per accettare `target_service`; aggiorna `app.py`. **A questo punto comportamento identico al passato** (tabella vuota → tutti i giorni usano il fallback).
4. Aggiungi le route `/api/targets/*` e i template/asset admin.
5. Aggiungi il link "Pianifica target" nell'header della dashboard.

## Verifica manuale post-implementazione

| # | Scenario | Risultato atteso |
|---|---|---|
| 1 | Tabella vuota, dashboard | KPI e curva target identici al comportamento attuale (tutto al valore JSON × giorni lavorativi). |
| 2 | Inserisco target diversi su 3 giorni del mese | Curva target a pendenza variabile; `monthlyTarget` = somma dei 3 valori + fallback × giorni lavorativi rimanenti. |
| 3 | Cancello una riga via DELETE | Il giorno torna al fallback senza riavvio. |
| 4 | "Copia dal mese precedente" su mese vuoto | Tutti i giorni lavorativi del mese ricevono il target del corrispondente giorno-del-mese precedente. Giorni del mese precedente non lavorativi → ignorati. |
| 5 | "Copia dal mese precedente" su mese parzialmente pianificato | Solo i giorni ancora vuoti vengono popolati. |
| 6 | Tento di inserire `dailyValue = 0` | Server respinge con 400; UI mostra errore. |
| 7 | Modifico un giorno passato | KPI ricalcolati al refresh successivo: `target_line` storica cambia, `monthlyGap` e `requiredDailyAdjustment` si aggiornano. |
| 8 | Primo del mese, giorno precedente in mese diverso | Il KPI "Valore Prodotto Ieri" continua a funzionare (logica esistente immutata); "Target Giornaliero" e' quello pianificato di oggi (o fallback). |
| 9 | Modifico `config.json["dailyValue"]` mentre l'app gira | Valore vecchio in memoria fino a riavvio (comportamento attuale). |

## Out of scope (dichiarato esplicitamente)

- Autenticazione/autorizzazione sull'admin page.
- Audit trail (chi/quando modifica).
- Notifiche email su modifiche al piano.
- Multi-tenant / multi-plant.
- Validazione di coerenza tra piano e capacita' produttiva.
- Esposizione esplicita del piano nel Daily Report email / Excel export (il report mostra gia' `dailyTarget`/`monthlyTarget` aggiornati automaticamente).
