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
