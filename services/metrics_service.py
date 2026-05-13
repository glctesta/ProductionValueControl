import logging
from datetime import date, datetime, timedelta
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)


class MetricsService:
    """
    Orchestratore del calcolo KPI e delle curve del grafico.

    Regole chiave (dalla specifica):
      - Giorno produttivo = 07:30 -> 07:30 del giorno successivo.
      - Target mensile = dailyValue * num_giorni_lavorativi_mese (RO ortodosso).
      - Valori reali mensili includono TUTTI i giorni (anche weekend/festivi).
      - Curve Target / Media / Rolling: ascissa solo giorni lavorativi; la
        produzione dei non lavorativi e' riversata (carry-forward) sul primo
        giorno lavorativo successivo.
    """

    def __init__(self, excel_service, sql_service, calendar_service, target_service):
        self.excel = excel_service
        self.sql = sql_service
        self.cal = calendar_service
        self.targets = target_service

    @staticmethod
    def current_production_date(now: datetime) -> date:
        """
        Se sono prima delle 07:30, il giorno produttivo in corso e' quello di ieri.
        """
        threshold = now.replace(hour=7, minute=30, second=0, microsecond=0)
        if now < threshold:
            return (now - timedelta(days=1)).date()
        return now.date()

    @staticmethod
    def production_window(d: date) -> Tuple[datetime, datetime]:
        start = datetime(d.year, d.month, d.day, 7, 30, 0)
        return start, start + timedelta(days=1)

    def compute(self, now: datetime) -> Dict:
        prod_day = self.current_production_date(now)
        year, month = prod_day.year, prod_day.month

        today_start, today_end = self.production_window(prod_day)
        month_start_dt = datetime(year, month, 1, 7, 30, 0)
        cutoff_dt = today_end  # estende il range fino alla fine del giorno produttivo corrente

        month_rows = self.sql.get_month_production(month_start_dt, cutoff_dt)
        price_map = self.excel.load_price_map()

        today_orders = self.sql.get_today_produced_orders(today_start, today_end)

        # Fallback prezzo su resetservices per gli ordini non presenti in Excel
        # (tipicamente ordini del passato). Interrogo solo gli ordini realmente
        # coinvolti nel mese corrente, limitando il carico sul DB.
        orders_in_month = {o for o, _, _ in month_rows}
        orders_in_month.update(today_orders)
        orders_missing_from_excel = {o for o in orders_in_month if o not in price_map}

        sql_price_map: Dict[str, float] = {}
        unresolved: set = set()
        for order in orders_missing_from_excel:
            fb = self.sql.get_price_from_resetservices(order)
            if fb is not None:
                sql_price_map[order] = fb
            else:
                unresolved.add(order)

        def resolve_price(order: str) -> float:
            if order in price_map:
                return price_map[order]
            if order in sql_price_map:
                return sql_price_map[order]
            return 0.0

        # "Missing" = ordine prodotto oggi non reperibile ne' in Excel ne' in SQL fallback
        missing_orders = sorted({o for o in today_orders if o in unresolved})
        missing_detected = len(missing_orders) > 0

        # Aggrega valore e pezzi prodotti per giorno di calendario usando il price resolver combinato
        value_per_cal_day: Dict[date, float] = {}
        qty_per_cal_day: Dict[date, int] = {}
        for order_number, production_day, qty in month_rows:
            price = resolve_price(order_number)
            value_per_cal_day[production_day] = value_per_cal_day.get(production_day, 0.0) + qty * price
            qty_per_cal_day[production_day] = qty_per_cal_day.get(production_day, 0) + qty

        working_days = self.cal.working_days_in_month(year, month)
        target_per_wd = self.targets.get_targets_for_month(year, month)
        daily_target_today = target_per_wd.get(
            prod_day,
            self.targets.get_target_for_day(prod_day),
        )
        working_days_set = set(working_days)
        cf_map = self.cal.carry_forward_map(year, month)

        # Attribuisci il valore di ciascun giorno di calendario al giorno lavorativo target
        value_per_wd: Dict[date, float] = {d: 0.0 for d in working_days}
        qty_per_wd: Dict[date, int] = {d: 0 for d in working_days}
        for cal_day, value in value_per_cal_day.items():
            target = cf_map.get(cal_day, cal_day)
            if target in value_per_wd:
                value_per_wd[target] += value
            elif working_days:
                # il carry-forward finirebbe nel mese successivo -> lo appoggio all'ultimo lavorativo del mese
                value_per_wd[working_days[-1]] += value
        for cal_day, q in qty_per_cal_day.items():
            target = cf_map.get(cal_day, cal_day)
            if target in qty_per_wd:
                qty_per_wd[target] += q
            elif working_days:
                qty_per_wd[working_days[-1]] += q

        # Rolling cumulativo: mostrato solo fino al giorno produttivo corrente (None dopo)
        rolling: List = []
        cum = 0.0
        for wd in working_days:
            if wd <= prod_day:
                cum += value_per_wd[wd]
                rolling.append(round(cum, 2))
            else:
                rolling.append(None)

        # Target line cumulativo: somma dei target pianificati (o fallback) per i giorni lavorativi
        target_line: List[float] = []
        cum_target = 0.0
        for wd in working_days:
            cum_target += target_per_wd[wd]
            target_line.append(round(cum_target, 2))
        monthly_target = round(sum(target_per_wd.values()), 2)

        # Totali
        # today_value: valore attribuito al giorno produttivo corrente, coerente
        # con il tooltip del grafico (include il carry-forward dei giorni non
        # lavorativi precedenti, se oggi e' un giorno lavorativo).
        # Se il giorno corrente non e' lavorativo, cade sul valore di calendario.
        today_value_cal = value_per_cal_day.get(prod_day, 0.0)
        if prod_day in value_per_wd:
            today_value = value_per_wd[prod_day]
        else:
            today_value = today_value_cal
        month_value = sum(value_per_cal_day.values())

        # Media giornaliera sui soli giorni lavorativi gia' conclusi (< oggi)
        past_wd = [wd for wd in working_days if wd < prod_day]
        past_wd_values = [value_per_wd[wd] for wd in past_wd]
        if past_wd_values:
            avg_daily = sum(past_wd_values) / len(past_wd_values)
        elif prod_day in working_days_set and today_value > 0:
            avg_daily = today_value
        else:
            avg_daily = 0.0

        # Curva Media: progressione cumulata basata sulla media dei giorni lavorativi
        average_line = [round(avg_daily * (i + 1), 2) for i in range(len(working_days))]

        # Gap
        daily_gap = daily_target_today - today_value
        monthly_gap = monthly_target - month_value

        # Forecast fine giornata sulla base dei minuti trascorsi nella finestra produttiva
        total_minutes_day = 24 * 60
        if now >= today_start:
            elapsed = int((now - today_start).total_seconds() / 60)
        else:
            elapsed = 0
        elapsed = max(1, min(elapsed, total_minutes_day))
        # Forecast basato sulla sola produzione odierna di calendario (non include
        # il carry-forward, che rappresenta produzione passata non velocita' attuale).
        forecast_day = today_value_cal / elapsed * total_minutes_day if elapsed > 0 else today_value_cal

        # Giorni lavorativi residui (futuri). Se oggi e' lavorativo, lo contiamo come 1.
        future_wd = [wd for wd in working_days if wd > prod_day]
        today_is_working = prod_day in working_days_set
        effective_remaining = len(future_wd) + (1 if today_is_working else 0)

        # Forecast fine mese: cumulato reale + resto odierno (se oggi e' lavorativo)
        # + media * giorni lavorativi futuri
        today_remainder = (forecast_day - today_value_cal) if today_is_working else 0.0
        forecast_month = month_value + today_remainder + avg_daily * len(future_wd)

        # Aggiustamento richiesto per recuperare il gap mensile sui giorni residui
        if monthly_gap <= 0:
            required_adjustment = 0.0
        elif effective_remaining > 0:
            required_adjustment = monthly_gap / effective_remaining
        else:
            required_adjustment = 0.0

        labels = [wd.strftime('%d') for wd in working_days]

        # Valori puntuali (non cumulati) per ciascun giorno lavorativo,
        # usati dal tooltip del grafico per mostrare "di quanto cresce oggi".
        rolling_daily = []
        qty_daily = []
        for wd in working_days:
            if wd <= prod_day:
                rolling_daily.append(round(value_per_wd[wd], 2))
                qty_daily.append(int(qty_per_wd[wd]))
            else:
                rolling_daily.append(None)
                qty_daily.append(None)
        target_daily = [round(target_per_wd[wd], 2) for wd in working_days]
        average_daily = [round(avg_daily, 2)] * len(working_days)

        return {
            'dailyTarget': round(daily_target_today, 2),
            'monthlyTarget': monthly_target,
            'todayValue': round(today_value, 2),
            'monthValue': round(month_value, 2),
            'dailyGap': round(daily_gap, 2),
            'monthlyGap': round(monthly_gap, 2),
            'forecastDay': round(forecast_day, 2),
            'forecastMonth': round(forecast_month, 2),
            'requiredDailyAdjustment': round(required_adjustment, 2),
            'workingDaysInMonth': len(working_days),
            'remainingWorkingDays': effective_remaining,
            'productionDay': prod_day.isoformat(),
            'todayIsWorkingDay': today_is_working,
            'missingOrders': missing_orders,
            'missingOrdersCount': len(missing_orders),
            'missingDetected': missing_detected,
            'todayProducedOrders': sorted(set(today_orders)),
            'excelFile': self.excel.source_file_name(),
            'chart': {
                'labels': labels,
                'target': target_line,
                'average': average_line,
                'rollingMonth': rolling,
                'targetDaily': target_daily,
                'averageDaily': average_daily,
                'rollingDaily': rolling_daily,
                'qtyDaily': qty_daily,
            }
        }
