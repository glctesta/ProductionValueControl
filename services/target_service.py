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
