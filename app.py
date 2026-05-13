import atexit
import json
import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from flask import Flask, jsonify, render_template, send_file, send_from_directory

from config_manager import ConfigManager
from db_connection import DatabaseConnection
from services.calendar_service import CalendarService
from services.email_service import EmailService
from services.excel_service import ExcelService
from services.export_service import ExportService
from services.metrics_service import MetricsService
from services.report_service import ReportService
from services.sql_service import SqlService
from services.target_service import TargetService

BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / 'config.json'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger('ProductionValue')


def load_app_config() -> dict:
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


app = Flask(__name__, template_folder='templates', static_folder='static')

config = load_app_config()

config_mgr = ConfigManager(
    key_file=str(BASE_DIR / 'encryption_key.key'),
    config_file=str(BASE_DIR / 'db_config.enc'),
)
db = DatabaseConnection(config_mgr)

excel_svc = ExcelService(config['excelDir'], config['excelSheet'])
sql_svc = SqlService(
    db,
    phase_id=config.get('phaseId', 142),
    production_start=config.get('productionDayStart', '07:30'),
)
cal_svc = CalendarService(country=config.get('country', 'RO'))
target_svc = TargetService(
    db_connection=db,
    calendar_service=cal_svc,
    fallback_daily_value=config['dailyValue'],
)
metrics_svc = MetricsService(excel_svc, sql_svc, cal_svc, target_service=target_svc)
export_svc = ExportService(excel_svc, sql_svc, metrics_svc)
email_svc = EmailService(BASE_DIR)
report_svc = ReportService()

# Stato di notifica degli ordini mancanti: si invia una nuova email SOLO se
# rispetto alla precedente spedizione compaiono ordini NUOVI. Il set si resetta
# al cambio del giorno produttivo.
_missing_state: dict = {
    'production_day': None,
    'notified': set(),
}


def _fmt_eur(v) -> str:
    try:
        return "€ {:,.0f}".format(float(v)).replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "—"


def _build_missing_orders_email_html(result: dict, details_map: dict) -> str:
    """
    Corpo HTML dell'email di warning. Tono formale ma elegante. In italiano.
    """
    missing_list = sorted(result.get('missingOrders') or [])

    rows_html = []
    for order in missing_list:
        d = details_map.get(order, {})
        rows_html.append(
            "<tr>"
            f"<td style='padding:8px 12px;border:1px solid #d9d9d9;'>{order}</td>"
            f"<td style='padding:8px 12px;border:1px solid #d9d9d9;'>{d.get('productCode') or '&mdash;'}</td>"
            f"<td style='padding:8px 12px;border:1px solid #d9d9d9;'>{d.get('productName') or '&mdash;'}</td>"
            f"<td style='padding:8px 12px;border:1px solid #d9d9d9;text-align:right;'>{d.get('quantity', 0)}</td>"
            "</tr>"
        )
    table_body = "\n".join(rows_html) if rows_html else (
        "<tr><td colspan='4' style='padding:10px;border:1px solid #d9d9d9;text-align:center;'>&mdash;</td></tr>"
    )

    daily_target = _fmt_eur(result.get('dailyTarget'))
    monthly_target = _fmt_eur(result.get('monthlyTarget'))
    today_value = _fmt_eur(result.get('todayValue'))
    month_value = _fmt_eur(result.get('monthValue'))
    daily_gap = _fmt_eur(result.get('dailyGap'))
    monthly_gap = _fmt_eur(result.get('monthlyGap'))
    prod_day = result.get('productionDay') or ''
    excel_file = result.get('excelFile') or '(file non identificato)'

    return f"""
    <html>
    <body style="font-family:Arial,Helvetica,sans-serif;color:#2b2b2b;max-width:920px;margin:0 auto;">
        <h2 style="color:#366092;margin:0 0 12px 0;">
            Warning &ndash; Ordini in produzione non valorizzabili
        </h2>
        <p style="margin:0 0 10px 0;">Gentili Colleghi,</p>
        <p style="margin:0 0 14px 0;line-height:1.45;">
            in data <strong>{prod_day}</strong> il sistema di monitoraggio del valore della produzione
            ha rilevato che alcuni ordini attualmente in lavorazione <strong>non possono essere
            valorizzati</strong>: non sono presenti nel file Excel di riferimento
            (<em>"PR Master data From D365"</em>, per convenzione interna nella directory
            <code>T:\\D365 data</code>) e non sono reperibili neppure tramite la fonte di fallback
            (<code>resetservices</code>).
        </p>
        <p style="margin:0 0 14px 0;line-height:1.45;">
            Di conseguenza, il valore prodotto oggi indicato dalla dashboard <strong>potrebbe
            risultare sottostimato</strong> rispetto alla realta'.
        </p>

        <h3 style="color:#366092;margin:18px 0 8px 0;">Situazione produttiva al momento del warning</h3>
        <table style="border-collapse:collapse;font-size:14px;">
            <tr>
                <td style="padding:6px 12px;">Target giornaliero</td>
                <td style="padding:6px 12px;"><strong>{daily_target}</strong></td>
                <td style="padding:6px 12px;">Target mensile</td>
                <td style="padding:6px 12px;"><strong>{monthly_target}</strong></td>
            </tr>
            <tr>
                <td style="padding:6px 12px;">Valore prodotto oggi</td>
                <td style="padding:6px 12px;"><strong>{today_value}</strong></td>
                <td style="padding:6px 12px;">Valore prodotto mese</td>
                <td style="padding:6px 12px;"><strong>{month_value}</strong></td>
            </tr>
            <tr>
                <td style="padding:6px 12px;">Gap giornaliero</td>
                <td style="padding:6px 12px;"><strong>{daily_gap}</strong></td>
                <td style="padding:6px 12px;">Gap mensile</td>
                <td style="padding:6px 12px;"><strong>{monthly_gap}</strong></td>
            </tr>
        </table>

        <h3 style="color:#366092;margin:20px 0 8px 0;">
            Ordini non valorizzabili ({len(missing_list)})
        </h3>
        <table style="border-collapse:collapse;width:100%;font-size:13px;">
            <thead>
                <tr style="background:#366092;color:white;">
                    <th style="padding:9px 12px;border:1px solid #d9d9d9;text-align:left;">Order Number</th>
                    <th style="padding:9px 12px;border:1px solid #d9d9d9;text-align:left;">Product Code</th>
                    <th style="padding:9px 12px;border:1px solid #d9d9d9;text-align:left;">Product Name</th>
                    <th style="padding:9px 12px;border:1px solid #d9d9d9;text-align:right;">Quantita'</th>
                </tr>
            </thead>
            <tbody>
                {table_body}
            </tbody>
        </table>

        <p style="margin:18px 0 10px 0;line-height:1.45;">
            Si prega cortesemente di <strong>aggiungere le informazioni mancanti</strong> al file
            Excel (o di verificare la corretta anagrafica in D365), affinche' il dato di analisi
            della produzione risulti completo e corretto.
        </p>
        <p style="margin:0 0 16px 0;color:#666;font-size:12px;">
            File di riferimento al momento del controllo: <code>{excel_file}</code>.
        </p>
        <br/>
        <p style="margin:0;color:#666;">
            Cordiali saluti,<br/>
            <strong>Sistema di Monitoraggio Produzione</strong>
        </p>
    </body>
    </html>
    """


def maybe_send_missing_email(result: dict) -> None:
    """
    Invia l'email di warning SOLO se nel set di ordini non valorizzabili di oggi
    compaiono ordini nuovi rispetto a quelli gia' notificati. Il set di notifica
    si resetta a ogni cambio di giorno produttivo.
    """
    prod_day = result.get('productionDay')
    current_missing = set(result.get('missingOrders') or [])

    if _missing_state.get('production_day') != prod_day:
        _missing_state['production_day'] = prod_day
        _missing_state['notified'] = set()

    if not current_missing:
        return

    new_orders = current_missing - _missing_state['notified']
    if not new_orders:
        logger.info(
            f"Missing orders invariati ({len(current_missing)}): email non inviata."
        )
        return

    try:
        recipients = sql_svc.get_missing_order_recipients()
    except Exception as e:
        logger.error(f"Errore nel recupero destinatari 'sys_value_missing_Order': {e}")
        return

    if not recipients:
        logger.warning("Alert ordini mancanti: nessun destinatario configurato in settings.")
        return

    # Dettagli ordini (per il corpo email) su tutti i missing correnti.
    details_map = {}
    for order in sorted(current_missing):
        try:
            details_map[order] = sql_svc.get_order_details(order)
        except Exception as e:
            logger.error(f"Dettagli ordine {order} non recuperati: {e}")

    html_body = _build_missing_orders_email_html(result, details_map)
    subject = (
        f"[Production Monitor] Ordini non valorizzabili del {prod_day} "
        f"({len(current_missing)} totali, {len(new_orders)} nuovi)"
    )

    ok = email_svc.send(recipients=recipients, subject=subject, html_body=html_body)
    if ok:
        _missing_state['notified'] |= current_missing
        logger.info(
            f"Email warning inviata a {recipients}. "
            f"Ordini non valorizzabili: {sorted(current_missing)}. "
            f"Nuovi rispetto alla precedente: {sorted(new_orders)}."
        )


def _build_daily_report_html(metrics: dict, prod_day: date) -> str:
    """Corpo HTML del report giornaliero inviato alle 07:35."""
    dt = _fmt_eur(metrics.get('dailyTarget'))
    tv = _fmt_eur(metrics.get('todayValue'))
    dg = _fmt_eur(metrics.get('dailyGap'))
    mt = _fmt_eur(metrics.get('monthlyTarget'))
    mv = _fmt_eur(metrics.get('monthValue'))
    mg = _fmt_eur(metrics.get('monthlyGap'))
    fd = _fmt_eur(metrics.get('forecastDay'))
    fm = _fmt_eur(metrics.get('forecastMonth'))
    rq = _fmt_eur(metrics.get('requiredDailyAdjustment'))
    wd = metrics.get('workingDaysInMonth', 0)
    rs = metrics.get('remainingWorkingDays', 0)

    return f"""
    <html>
    <body style="font-family:Arial,Helvetica,sans-serif;color:#2b2b2b;max-width:920px;margin:0 auto;">
        <h2 style="color:#1F4E78;margin:0 0 8px 0;">
            Production Value &mdash; Report Giornaliero
        </h2>
        <p style="margin:0 0 16px 0;color:#555;">
            Riepilogo della giornata produttiva del
            <strong>{prod_day.strftime('%d/%m/%Y')}</strong>
            (periodo 07:30 &rarr; 07:30) e stato del mese in corso.
        </p>

        <h3 style="color:#1F4E78;margin:18px 0 8px 0;">Giorno precedente vs target</h3>
        <table style="border-collapse:collapse;font-size:14px;">
            <tr>
                <td style="padding:6px 12px;">Target giornaliero</td>
                <td style="padding:6px 12px;"><strong>{dt}</strong></td>
                <td style="padding:6px 12px;">Valore prodotto</td>
                <td style="padding:6px 12px;"><strong>{tv}</strong></td>
                <td style="padding:6px 12px;">Gap</td>
                <td style="padding:6px 12px;"><strong>{dg}</strong></td>
            </tr>
            <tr>
                <td style="padding:6px 12px;">Previsione fine giorno</td>
                <td style="padding:6px 12px;" colspan="5"><strong>{fd}</strong></td>
            </tr>
        </table>

        <h3 style="color:#1F4E78;margin:18px 0 8px 0;">Situazione mese</h3>
        <table style="border-collapse:collapse;font-size:14px;">
            <tr>
                <td style="padding:6px 12px;">Target mensile</td>
                <td style="padding:6px 12px;"><strong>{mt}</strong></td>
                <td style="padding:6px 12px;">Valore prodotto mese</td>
                <td style="padding:6px 12px;"><strong>{mv}</strong></td>
                <td style="padding:6px 12px;">Gap mese</td>
                <td style="padding:6px 12px;"><strong>{mg}</strong></td>
            </tr>
            <tr>
                <td style="padding:6px 12px;">Previsione fine mese</td>
                <td style="padding:6px 12px;"><strong>{fm}</strong></td>
                <td style="padding:6px 12px;">Aggiustamento richiesto/giorno</td>
                <td style="padding:6px 12px;"><strong>{rq}</strong></td>
                <td style="padding:6px 12px;">Giorni lav. mese</td>
                <td style="padding:6px 12px;"><strong>{wd} (res: {rs})</strong></td>
            </tr>
        </table>

        <h3 style="color:#1F4E78;margin:22px 0 8px 0;">Snapshot dashboard</h3>
        <div style="text-align:center;">
            <img src="cid:dashboard_snapshot" alt="Dashboard"
                 style="max-width:100%;border:1px solid #ccc;border-radius:6px;"/>
        </div>

        <p style="margin:22px 0 6px 0;line-height:1.45;">
            In allegato il file Excel con il dettaglio completo della produzione
            del mese corrente: KPI, raggruppamento per settimana / giorno e
            tab &ldquo;Semilavorati&rdquo; con i valori di sola manodopera.
        </p>

        <br/>
        <p style="margin:0;color:#666;">
            Cordiali saluti,<br/>
            <strong>Sistema di Monitoraggio Produzione</strong>
        </p>
    </body>
    </html>
    """


def run_daily_report() -> bool:
    """
    Compone e invia il report giornaliero. Il giorno di riferimento e' il
    giorno produttivo APPENA CONCLUSO (quello di 'ieri', visto che il job
    parte alle 07:35 subito dopo la chiusura della finestra 07:30 -> 07:30).
    """
    try:
        now = datetime.now()
        # Spostiamo logicamente 'now' un minuto prima del cambio giorno produttivo
        # cosi' le metriche sono quelle del giorno appena concluso.
        report_now = now.replace(hour=7, minute=29, second=59, microsecond=0)

        metrics = metrics_svc.compute(report_now)
        prod_day = MetricsService.current_production_date(report_now)

        recipients = sql_svc.get_daily_report_recipients()
        if not recipients:
            logger.warning(
                "Daily report: nessun destinatario configurato "
                "(attribute 'Sys_email_production_intern')."
            )
            return False

        try:
            png_buf = report_svc.generate_dashboard_png(metrics, prod_day)
            png_bytes = png_buf.getvalue()
        except Exception as e:
            logger.exception(f"Daily report: errore generazione PNG: {e}")
            png_bytes = b''

        try:
            xlsx_buf = export_svc.build_current_month_workbook(report_now)
            xlsx_bytes = xlsx_buf.getvalue()
            xlsx_filename = (
                f"ProductionValue_{prod_day.strftime('%Y-%m')}_"
                f"{prod_day.strftime('%Y%m%d')}.xlsx"
            )
        except Exception as e:
            logger.exception(f"Daily report: errore generazione Excel: {e}")
            xlsx_bytes = b''
            xlsx_filename = ''

        subject = f"Production Value \u2014 Report {prod_day.strftime('%d/%m/%Y')}"
        html_body = _build_daily_report_html(metrics, prod_day)

        inline_images = {'dashboard_snapshot': png_bytes} if png_bytes else None
        attachments = []
        if xlsx_bytes:
            attachments.append((
                xlsx_filename,
                xlsx_bytes,
                'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            ))

        ok = email_svc.send(
            recipients=recipients,
            subject=subject,
            html_body=html_body,
            inline_images=inline_images,
            attachments=attachments,
        )
        if ok:
            logger.info(
                f"Daily report inviato a {len(recipients)} destinatari per il "
                f"giorno produttivo {prod_day} ({recipients})."
            )
        return ok
    except Exception as e:
        logger.exception(f"Daily report: errore non gestito: {e}")
        return False


def _start_scheduler() -> BackgroundScheduler:
    sched = BackgroundScheduler()
    sched.add_job(
        run_daily_report,
        CronTrigger(hour=7, minute=35),
        id='daily_report_0735',
        name='Daily production report (07:35)',
        replace_existing=True,
        misfire_grace_time=60 * 60,  # esegue entro 1h se la macchina era spenta
        coalesce=True,
    )
    sched.start()
    logger.info("Scheduler avviato: job 'daily_report_0735' alle 07:35 ora locale.")
    return sched


scheduler = _start_scheduler()
atexit.register(lambda: scheduler.shutdown(wait=False))


@app.route('/')
def index():
    return render_template('index.html', refresh_minutes=config['refreshMinutes'])


@app.route('/api/metrics')
def api_metrics():
    try:
        now = datetime.now()
        result = metrics_svc.compute(now)
        result['now'] = now.isoformat(timespec='seconds')
        result['refreshMinutes'] = config['refreshMinutes']

        maybe_send_missing_email(result)

        return jsonify(result)
    except Exception as e:
        logger.exception("Errore nel calcolo delle metriche")
        return jsonify({'error': str(e)}), 500


@app.route('/api/export/month-excel')
def api_export_month_excel():
    try:
        now = datetime.now()
        buf = export_svc.build_current_month_workbook(now)
        filename = f"ProductionValue_{now.strftime('%Y-%m')}_{now.strftime('%Y%m%d-%H%M')}.xlsx"
        return send_file(
            buf,
            as_attachment=True,
            download_name=filename,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
    except Exception as e:
        logger.exception("Errore export Excel")
        return jsonify({'error': str(e)}), 500


@app.route('/api/daily-report/test', methods=['POST', 'GET'])
def api_daily_report_test():
    """
    Trigger manuale del report giornaliero, utile per testare senza aspettare le 07:35.
    Usa lo stesso flusso dello scheduler.
    """
    ok = run_daily_report()
    if ok:
        return jsonify({'ok': True, 'message': 'Report inviato.'})
    return jsonify({'ok': False, 'message': 'Report non inviato (vedi log per dettagli).'}), 500


@app.route('/api/daily-report/preview.png')
def api_daily_report_preview():
    """
    Restituisce il PNG del report giornaliero senza inviarlo, per ispezione veloce.
    """
    try:
        now = datetime.now()
        report_now = now.replace(hour=7, minute=29, second=59, microsecond=0)
        metrics = metrics_svc.compute(report_now)
        prod_day = MetricsService.current_production_date(report_now)
        buf = report_svc.generate_dashboard_png(metrics, prod_day)
        return send_file(buf, mimetype='image/png')
    except Exception as e:
        logger.exception("Errore preview report PNG")
        return jsonify({'error': str(e)}), 500


@app.route('/logo.png')
def logo():
    return send_from_directory(str(BASE_DIR), 'Logo.png')


@app.route('/healthz')
def healthz():
    return jsonify({'ok': True, 'now': datetime.now().isoformat(timespec='seconds')})


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


if __name__ == '__main__':
    # werkzeug reloader tenuto spento per evitare doppia inizializzazione della cache
    app.run(host='0.0.0.0', port=5065, debug=False, use_reloader=False)
