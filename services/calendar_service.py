import logging
from datetime import date, timedelta
from typing import Dict, List, Set

import holidays

logger = logging.getLogger(__name__)


class CalendarService:
    """
    Determina giorni lavorativi e festivi secondo il calendario rumeno (che include
    le principali festivita' ortodosse pubbliche: Paste, Lunedi di Paste, Pentecoste,
    ecc.). La libreria 'holidays' contiene queste date gia' calcolate.
    """

    def __init__(self, country: str = 'RO'):
        self.country = country
        self._holidays_cache: Dict[int, Set[date]] = {}

    def _holidays_for_year(self, year: int) -> Set[date]:
        if year not in self._holidays_cache:
            try:
                h = holidays.country_holidays(self.country, years=year)
            except Exception as e:
                logger.warning(f"Impossibile caricare festivita' {self.country} {year}: {e}")
                h = {}
            self._holidays_cache[year] = set(h.keys())
        return self._holidays_cache[year]

    def is_working_day(self, d: date) -> bool:
        if d.weekday() >= 5:  # 5 = sabato, 6 = domenica
            return False
        if d in self._holidays_for_year(d.year):
            return False
        return True

    def all_days_in_month(self, year: int, month: int) -> List[date]:
        first = date(year, month, 1)
        last = (date(year + 1, 1, 1) - timedelta(days=1)) if month == 12 \
            else (date(year, month + 1, 1) - timedelta(days=1))
        days: List[date] = []
        cur = first
        while cur <= last:
            days.append(cur)
            cur += timedelta(days=1)
        return days

    def working_days_in_month(self, year: int, month: int) -> List[date]:
        return [d for d in self.all_days_in_month(year, month) if self.is_working_day(d)]

    def carry_forward_map(self, year: int, month: int) -> Dict[date, date]:
        """
        Per ogni giorno di calendario del mese, indica il giorno lavorativo sul
        quale deve essere riversata la produzione.

        Regole:
          - giorno lavorativo         -> se stesso
          - SABATO (non lavorativo)   -> VENERDI' precedente (primo giorno lavorativo all'indietro)
          - domenica / festivita'     -> primo giorno lavorativo successivo (avanti)

        Se il target uscirebbe dal mese corrente (es. sabato sul giorno 1), si
        ricade sull'altra direzione per non perdere il dato.
        """
        wd_in_month = set(self.working_days_in_month(year, month))
        result: Dict[date, date] = {}

        def find_back(start: date) -> date:
            cur = start - timedelta(days=1)
            for _ in range(60):
                if cur in wd_in_month:
                    return cur
                cur -= timedelta(days=1)
            return None  # type: ignore[return-value]

        def find_forward(start: date) -> date:
            cur = start
            for _ in range(60):
                if cur in wd_in_month:
                    return cur
                cur += timedelta(days=1)
            return None  # type: ignore[return-value]

        for d in self.all_days_in_month(year, month):
            if d in wd_in_month:
                result[d] = d
                continue

            if d.weekday() == 5:  # sabato -> indietro a venerdi'
                target = find_back(d) or find_forward(d)
            else:  # domenica / festivita' infrasettimanale -> avanti
                target = find_forward(d) or find_back(d)

            if target is not None:
                result[d] = target
        return result
