# ProductionValue

Dashboard intranet per il valore economico della produzione, porta **5065**.

## Struttura
```
ProductionValue/
├─ app.py                    # Flask server
├─ config.json               # dailyValue, refreshMinutes, paths, ecc.
├─ config_manager.py         # (esistente) credenziali DB cifrate (Fernet)
├─ db_connection.py          # (esistente) connessione pyodbc
├─ db_config.enc              (esistente)
├─ encryption_key.key         (esistente)
├─ email_connector.py        # (esistente - usato quando attiveremo le email)
├─ utils.py                  # (esistente - helpers email)
├─ Logo.png                  # mostrato in alto a destra
├─ services/
│  ├─ excel_service.py       # legge T:\D365 data, foglio PR Master data From D365
│  ├─ sql_service.py         # produzione, check ordini, destinatari alert
│  ├─ calendar_service.py    # giorni lavorativi RO (festivita' ortodosse via holidays)
│  └─ metrics_service.py     # KPI, curve Target/Media/Rolling, carry-forward
├─ templates/index.html
└─ static/{css,js}/
```

## Avvio rapido
```bat
run.bat
```
Apri poi `http://localhost:5065` (o l'IP della macchina dall'intranet).

## Config (`config.json`)
| Campo | Default | Descrizione |
|---|---|---|
| `dailyValue` | 50000 | Target giornaliero in € |
| `refreshMinutes` | 60 | Intervallo refresh automatico |
| `excelDir` | `T:\D365 data` | Directory con il file prezzi (si usa il piu' recente) |
| `excelSheet` | `PR Master data From D365` | Nome foglio |
| `phaseId` | 142 | IDPhase filtrato nelle query |
| `productionDayStart` | `07:30` | Orario inizio giorno produttivo |
| `country` | `RO` | Paese per il calendario festivita' |

## Logica
- Giorno produttivo: 07:30 → 07:30 del giorno successivo.
- Il valore e' `qty(ordine) * unitPrice(Excel)` sommato su tutti gli ordini PR.
- Target mensile = `dailyValue × giorni_lavorativi_mese`.
- Grafico 3 curve sull'asse dei soli giorni lavorativi; la produzione dei giorni non
  lavorativi (sabato, domenica, festivita' ortodosse RO) viene **riversata sul primo
  giorno lavorativo successivo** (carry-forward).
- Stella gialla in header se alcuni ordini prodotti oggi non sono presenti
  nell'Excel (valore mostrato potenzialmente sottostimato).

## Email ordini mancanti
L'invio email ai destinatari di `traceability_rs.dbo.settings` (attributo
`sys_value_missing_Order`) e' **disabilitato** per ora: l'app logga solo cosa
invierebbe. Si attivera' riusando `email_connector.py` / `utils.py` in uno step
successivo.

Rate-limit: al massimo una mail per ciclo di refresh.

## API
- `GET /` → dashboard HTML
- `GET /api/metrics` → JSON con tutti i KPI e i dati del grafico
- `GET /logo.png` → logo aziendale
- `GET /healthz` → healthcheck
