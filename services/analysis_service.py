import logging
from datetime import datetime, date, timedelta
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)

ALIASES = {
    "FINAL ASSEMBLY":    "ASSEMBLY",
    "CONFORMAL COATING": "COATING",
    "PTHM SELECTIVE":    "PTHSEL",
    "SUDURA SELECTIVA":  "PTHSEL",
    "PROGRAMARE":        "PROGRAMING",
    "AOI":               "SMT"
}

def canonicalize(phase_name: str) -> str:
    if not phase_name:
        return ""
    name_upper = phase_name.strip().upper()
    # Check exact match or check if name starts with any alias key
    for k, v in ALIASES.items():
        if k in name_upper:
            return v
    return name_upper

class AnalysisService:
    """
    Service to run local statistical analysis on production:
      - Bottleneck detection: compares actual hourly rate with cycle time capacity.
      - Daily projection: predicts end of day production value based on hourly rate.
    """
    
    def __init__(self, completion_phase_id: int = 142):
        self.completion_phase_id = completion_phase_id

    def analyze_hourly_production(
        self,
        hourly_rows: List[Tuple[datetime, str, str, int, str, int]],
        cycle_times: Dict[Tuple[str, str], float],
        price_map: Dict[str, float],
        daily_target: float,
        production_start_hour: datetime
    ) -> Dict:
        """
        Runs the local analysis.
        hourly_rows: list of (ScanHour, OrderNumber, ProductCode, IDPhase, PhaseName, Qty)
        cycle_times: {(ProductCode, PhaseName): CycleTimeMinutes}
        price_map: {OrderNumber: Price}
        daily_target: float (budget of the day)
        production_start_hour: datetime (e.g. today at 07:30)
        """
        warnings = []
        
        # 1. Group actual completed production by hour to build the budget comparison data
        # Standard work shift is 16 hours (07:30 -> 23:30)
        # Budget is distributed across these 16 hours: hourly_budget = daily_target / 16.
        hourly_target_rate = daily_target / 16.0
        
        # We want to represent 24 hours starting from 07:30
        hourly_intervals = []
        for h in range(24):
            interval_start = production_start_hour + timedelta(hours=h)
            hourly_intervals.append(interval_start)
            
        actual_by_hour = {t: 0.0 for t in hourly_intervals}
        qty_by_hour = {t: 0 for t in hourly_intervals}
        
        # Fill actual completed value by hour
        for scan_hour, order, p_code, phase_id, phase_name, qty in hourly_rows:
            if phase_id == self.completion_phase_id:
                diff_hours = int((scan_hour - production_start_hour).total_seconds() // 3600)
                if 0 <= diff_hours < 24:
                    slot = hourly_intervals[diff_hours]
                    price = price_map.get(order, 0.0)
                    actual_by_hour[slot] += qty * price
                    qty_by_hour[slot] += qty

        # 2. Cumulative calculations
        budget_cumulative = []
        actual_cumulative = []
        labels = []
        
        cum_budget = 0.0
        cum_actual = 0.0
        
        current_time = datetime.now()
        
        for idx, slot in enumerate(hourly_intervals):
            # Budget increases only during standard production hours (first 16 hours: 07:30 to 23:30)
            if idx < 16:
                cum_budget += hourly_target_rate
            else:
                # Night shift, budget cumulative stays at daily target
                pass
                
            cum_actual += actual_by_hour[slot]
            
            # Format labels as "07:30", "08:30", etc.
            label_str = slot.strftime("%H:%M")
            labels.append(label_str)
            
            budget_cumulative.append(round(cum_budget, 2))
            
            # Show actual cumulative only for slots that have started (or contain scans)
            if slot <= current_time or actual_by_hour[slot] > 0:
                actual_cumulative.append(round(cum_actual, 2))
            else:
                actual_cumulative.append(None)

        # 3. Budget Projection Alert
        # Find how many active hours have passed in the standard shift (07:30 to 23:30)
        hours_passed = 0
        for idx, slot in enumerate(hourly_intervals[:16]):
            if slot <= current_time:
                hours_passed = idx + 1
        
        # If we are within standard shift
        if 0 < hours_passed <= 16:
            current_completed = sum(actual_by_hour[slot] for slot in hourly_intervals[:hours_passed])
            expected_at_this_hour = hours_passed * hourly_target_rate
            
            # Project to 16 hours
            average_hourly_rate = current_completed / hours_passed
            projected_value = average_hourly_rate * 16.0
            
            gap = daily_target - current_completed
            remaining_hours = 16 - hours_passed
            
            if projected_value < daily_target:
                # Target is at risk
                required_rate = gap / remaining_hours if remaining_hours > 0 else 0
                pct = (projected_value / daily_target) * 100 if daily_target > 0 else 0
                warnings.append({
                    "category": "BUDGET_RISK",
                    "title": "Daily Target at Risk",
                    "severity": "high" if pct < 85 else "medium",
                    "message": f"End-of-day projection is {pct:.1f}% of target ({current_completed:,.0f} € produced vs. {expected_at_this_hour:,.0f} € expected).",
                    "detail": f"Current hourly rate: {average_hourly_rate:,.0f} €/hour. Required rate in the remaining {remaining_hours} hours to reach budget: {required_rate:,.0f} €/hour."
                })
            else:
                warnings.append({
                    "category": "BUDGET_STATUS",
                    "title": "Daily Target On Track",
                    "severity": "info",
                    "message": f"Current production meets the budget trend. End-of-day projection: {projected_value:,.0f} € (Target: {daily_target:,.0f} €).",
                    "detail": f"Current hourly rate: {average_hourly_rate:,.0f} €/hour (Required hourly budget: {hourly_target_rate:,.0f} €/hour)."
                })

        # 4. Bottleneck Detection based on Cycle Times
        # We look at active scans in the last 2 hours to detect active bottleneck issues.
        phase_groups = {} # {(PhaseCanon, ProductCode): {"qty": int, "orders": set}}
        
        cutoff_2h = current_time - timedelta(hours=2)
        active_rows = [r for r in hourly_rows if r[0] >= cutoff_2h]
        
        for scan_hour, order, p_code, phase_id, phase_name, qty in active_rows:
            # Skip completion phase in bottleneck analysis to focus on process phases
            if phase_id == self.completion_phase_id:
                continue
                
            phase_canon = canonicalize(phase_name)
            key = (phase_canon, p_code)
            if key not in phase_groups:
                phase_groups[key] = {"qty": 0, "orders": set()}
            phase_groups[key]["qty"] += qty
            phase_groups[key]["orders"].add(order)
            
        # Analyze each phase-product group
        for (phase_canon, p_code), data in phase_groups.items():
            cycle_time = cycle_times.get((p_code, phase_canon))
            if not cycle_time or cycle_time <= 0:
                continue
                
            # Expected quantity in 2 hours
            expected_qty_2h = (120.0 / cycle_time)
            actual_qty = data["qty"]
            
            # Calculate efficiency
            efficiency = (actual_qty / expected_qty_2h) * 100
            
            # We flag low efficiency (e.g. < 60%) as bottleneck
            if efficiency < 60.0:
                # Find product unit price from one of the active orders
                unit_price = 0.0
                for o in data["orders"]:
                    if o in price_map:
                        unit_price = price_map[o]
                        break
                        
                lost_qty = max(0, expected_qty_2h - actual_qty)
                lost_value = lost_qty * unit_price
                
                # Only raise warning if lost value is significant (e.g. > € 200)
                if lost_value > 200:
                    warnings.append({
                        "category": "BOTTLENECK",
                        "title": f"Bottleneck Phase {phase_canon}",
                        "severity": "medium" if efficiency >= 40 else "high",
                        "message": f"Phase {phase_canon} is producing at reduced speed for code {p_code} ({efficiency:.1f}% of expected output).",
                        "detail": f"Produced: {actual_qty} pcs (expected: {expected_qty_2h:.1f} pcs). Estimated theoretical economic loss in the last 2 hours: {lost_value:,.0f} €."
                    })

        return {
            "labels": labels,
            "chartData": {
                "budget": budget_cumulative,
                "actual": actual_cumulative,
                "hourlyActual": [round(actual_by_hour[slot], 2) for slot in hourly_intervals]
            },
            "warnings": warnings,
            "dayProgress": {
                "actual": round(cum_actual, 2),
                "target": daily_target,
                "percentage": round((cum_actual / daily_target) * 100, 1) if daily_target > 0 else 0
            }
        }
