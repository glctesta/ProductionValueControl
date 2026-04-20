import logging
from datetime import date
from io import BytesIO
from typing import Optional

import matplotlib
matplotlib.use('Agg')  # backend non-interattivo, safe in thread Flask/scheduler
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker as mtick  # noqa: E402

logger = logging.getLogger(__name__)


# Palette coerente con la dashboard web
BG = '#0b111c'
PANEL = '#14202e'
PANEL_HL = '#1a2836'
TEXT = '#e8ecf2'
DIM = '#8fa3bf'
ACCENT = '#4fc3f7'
GREEN = '#81c784'
ORANGE = '#ffb74d'
RED = '#ef5350'
GRID = (1, 1, 1, 0.05)


def _fmt_eur(v) -> str:
    """Formato € con separatore di migliaia all'italiana (50.000 €)."""
    if v is None:
        return '—'
    try:
        n = float(v)
    except (TypeError, ValueError):
        return str(v)
    s = f"{n:,.0f}".replace(',', '.')
    return f"€ {s}"


class ReportService:
    """
    Produce un PNG 'stile dashboard' con KPI e grafico a 3 curve da allegare
    (inline) all'email del report giornaliero.
    """

    def generate_dashboard_png(
        self,
        metrics: dict,
        title_date: Optional[date] = None,
    ) -> BytesIO:
        # Inserire il titolo del report
        if title_date is None:
            title_date = date.today()

        fig = plt.figure(figsize=(14, 9), facecolor=BG)

        fig.suptitle(
            f'Production Value  \u2014  Report Giornaliero  {title_date.strftime("%d/%m/%Y")}',
            fontsize=17, fontweight='bold', color=TEXT, y=0.975,
        )

        # Layout: 3 righe KPI (3x3 = 9 box) + 1 grande grafico
        gs = fig.add_gridspec(
            nrows=4, ncols=3,
            height_ratios=[1, 1, 1, 4.5],
            hspace=0.35, wspace=0.18,
            left=0.035, right=0.975, top=0.915, bottom=0.06,
        )

        daily_target = metrics.get('dailyTarget')
        monthly_target = metrics.get('monthlyTarget')
        today_value = metrics.get('todayValue')
        month_value = metrics.get('monthValue')
        daily_gap = metrics.get('dailyGap')
        monthly_gap = metrics.get('monthlyGap')
        forecast_day = metrics.get('forecastDay')
        forecast_month = metrics.get('forecastMonth')
        required = metrics.get('requiredDailyAdjustment')

        def gap_color(v):
            try:
                return GREEN if float(v) <= 0 else RED
            except (TypeError, ValueError):
                return TEXT

        def forecast_color(value, target):
            try:
                return GREEN if float(value) >= float(target) else ORANGE
            except (TypeError, ValueError):
                return TEXT

        kpis = [
            ('Target Giornaliero', daily_target, ACCENT, True),
            ('Valore Prodotto Giorno', today_value, GREEN, True),
            ('Gap Giornaliero', daily_gap, gap_color(daily_gap), True),

            ('Target Mensile', monthly_target, ACCENT, True),
            ('Valore Prodotto Mese', month_value, GREEN, True),
            ('Gap Mensile', monthly_gap, gap_color(monthly_gap), True),

            ('Previsione Fine Giorno', forecast_day,
             forecast_color(forecast_day, daily_target), True),
            ('Previsione Fine Mese', forecast_month,
             forecast_color(forecast_month, monthly_target), True),
            ('Aggiustamento Richiesto', required, ORANGE, True),
        ]

        for i, (label, value, color, is_currency) in enumerate(kpis):
            r = i // 3
            c = i % 3
            ax = fig.add_subplot(gs[r, c])
            self._draw_kpi(ax, label, value, color, is_currency)

        # Grafico cumulato (3 curve)
        ax_chart = fig.add_subplot(gs[3, :])
        self._draw_chart(ax_chart, metrics.get('chart', {}))

        # Piede con info aggiuntive
        wd = metrics.get('workingDaysInMonth', 0)
        residui = metrics.get('remainingWorkingDays', 0)
        fig.text(
            0.5, 0.015,
            f"Giorno produttivo {title_date.strftime('%d/%m/%Y')}  \u00b7  "
            f"Giorni lavorativi mese: {wd}  \u00b7  Residui: {residui}",
            ha='center', color=DIM, fontsize=9, style='italic',
        )

        buf = BytesIO()
        fig.savefig(buf, format='png', facecolor=BG, dpi=110)
        plt.close(fig)
        buf.seek(0)
        return buf

    # ------------------------------------------------------------- helpers
    def _draw_kpi(self, ax, label, value, color, is_currency):
        ax.set_facecolor(PANEL)
        ax.set_xticks([])
        ax.set_yticks([])
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        for spine in ax.spines.values():
            spine.set_visible(False)

        # Barra accent a sinistra
        ax.add_patch(plt.Rectangle(
            (0, 0), 0.015, 1, transform=ax.transAxes,
            facecolor=color, clip_on=False,
        ))

        ax.text(
            0.05, 0.72, label, transform=ax.transAxes,
            fontsize=10, color=DIM, fontweight='bold',
        )
        display_value = _fmt_eur(value) if is_currency else str(value)
        ax.text(
            0.05, 0.30, display_value, transform=ax.transAxes,
            fontsize=18, color=color, fontweight='bold',
        )

    def _draw_chart(self, ax, chart_data: dict):
        ax.set_facecolor(PANEL)

        labels = chart_data.get('labels', []) or []
        target = chart_data.get('target', []) or []
        average = chart_data.get('average', []) or []
        rolling = chart_data.get('rollingMonth', []) or []

        n = len(labels)
        if n == 0:
            ax.text(
                0.5, 0.5, 'Nessun dato disponibile',
                ha='center', va='center', transform=ax.transAxes,
                color=DIM, fontsize=12, style='italic',
            )
            ax.set_xticks([])
            ax.set_yticks([])
            return

        x = list(range(n))
        ax.plot(
            x, target, color=ACCENT, linestyle='--', linewidth=2.2,
            label='Target', zorder=3,
        )
        ax.plot(
            x, average, color=ORANGE, linewidth=2.4,
            marker='o', markersize=4, label='Media (giorni lavorativi)', zorder=4,
        )

        # Rolling (salta i None -> solo punti reali)
        rolling_x = [i for i, v in enumerate(rolling) if v is not None]
        rolling_y = [v for v in rolling if v is not None]
        if rolling_x:
            ax.fill_between(
                rolling_x, 0, rolling_y,
                color=GREEN, alpha=0.18, zorder=2,
            )
            ax.plot(
                rolling_x, rolling_y, color=GREEN, linewidth=3.2,
                marker='o', markersize=6, markerfacecolor=GREEN,
                markeredgecolor=BG, markeredgewidth=1.5,
                label='Rolling Mese', zorder=5,
            )

        ax.set_xticks(x)
        ax.set_xticklabels(labels, color=DIM, fontsize=9)
        ax.tick_params(axis='y', colors=DIM, labelsize=9)
        ax.yaxis.set_major_formatter(
            mtick.FuncFormatter(lambda v, _: _fmt_eur(v))
        )
        ax.grid(True, color=GRID, linewidth=0.6)

        for spine in ('top', 'right'):
            ax.spines[spine].set_visible(False)
        for spine in ('bottom', 'left'):
            ax.spines[spine].set_color(DIM)

        ax.set_xlabel('Giorno lavorativo del mese', color=DIM, fontsize=10)
        ax.set_ylabel('Valore cumulato', color=DIM, fontsize=10)
        ax.set_title(
            'Andamento cumulato: Target vs Media vs Rolling',
            color=TEXT, fontsize=12, pad=10, loc='left',
        )

        leg = ax.legend(
            loc='upper left', facecolor=PANEL_HL, edgecolor='#253247',
            labelcolor=TEXT, fontsize=10, framealpha=0.9,
        )
        for text in leg.get_texts():
            text.set_color(TEXT)
