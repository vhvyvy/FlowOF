"""Matplotlib chart generators for agency analytics reports."""
from __future__ import annotations

import io
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from matplotlib.figure import Figure

# ── Palette ───────────────────────────────────────────────────────────────────
ACCENT   = "#6366f1"   # indigo
ACCENT2  = "#22d3ee"   # cyan
PROFIT   = "#34d399"   # emerald
EXPENSE  = "#f87171"   # red
GREY     = "#94a3b8"
GREY_LT  = "#e2e8f0"
BG       = "#ffffff"
GRID_CLR = "#e2e8f0"
FONT     = "DejaVu Sans"

MONTH_LABELS: dict[str, str] = {
    "01": "Янв", "02": "Фев", "03": "Мар", "04": "Апр",
    "05": "Май", "06": "Июн", "07": "Июл", "08": "Авг",
    "09": "Сен", "10": "Окт", "11": "Ноя", "12": "Дек",
}


def _short_month(ym: str) -> str:
    """'2025-06' → 'Июн 25'"""
    try:
        y, m = ym.split("-")
        return f"{MONTH_LABELS.get(m, m)} {y[2:]}"
    except Exception:
        return ym


def _dollar(v: float) -> str:
    return f"${v:,.0f}"


def _apply_theme(fig: Figure, *axes) -> None:
    fig.patch.set_facecolor(BG)
    for ax in axes:
        ax.set_facecolor(BG)
        ax.yaxis.grid(True, color=GRID_CLR, linewidth=0.7, linestyle="--", zorder=0)
        ax.set_axisbelow(True)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_color(GRID_CLR)
        ax.spines["bottom"].set_color(GRID_CLR)
        ax.tick_params(colors="#475569", labelsize=8)
        for label in ax.get_xticklabels() + ax.get_yticklabels():
            label.set_fontfamily(FONT)


def _to_png(fig: Figure) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    buf.seek(0)
    plt.close(fig)
    return buf.read()


def _title(ax, text: str) -> None:
    ax.set_title(text, fontfamily=FONT, fontsize=11, fontweight="bold", color="#1e293b", pad=10)


# ── 1. Revenue trend ──────────────────────────────────────────────────────────

def chart_revenue_trend(monthly_series: list[dict]) -> bytes:
    labels = [_short_month(r["month"]) for r in monthly_series]
    values = [r["revenue"] for r in monthly_series]

    fig, ax = plt.subplots(figsize=(10, 4))
    _apply_theme(fig, ax)
    _title(ax, "Выручка по месяцам")

    ax.plot(labels, values, color=ACCENT, linewidth=2.2, marker="o", markersize=5, zorder=3)
    ax.fill_between(labels, values, alpha=0.12, color=ACCENT)

    # Value labels on each point
    for i, (lbl, v) in enumerate(zip(labels, values)):
        ax.annotate(
            _dollar(v), (i, v),
            textcoords="offset points", xytext=(0, 8),
            ha="center", fontsize=7, color="#334155", fontfamily=FONT,
        )

    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: _dollar(x)))
    ax.set_ylabel("Выручка", fontfamily=FONT, fontsize=9, color="#475569")
    plt.xticks(rotation=30, ha="right")
    fig.tight_layout()
    return _to_png(fig)


# ── 2. Revenue / Expenses / Profit ────────────────────────────────────────────

def chart_revenue_expenses_profit(monthly_series: list[dict]) -> bytes:
    labels = [_short_month(r["month"]) for r in monthly_series]
    rev  = [r["revenue"]  for r in monthly_series]
    exp  = [r["expenses"] for r in monthly_series]
    prof = [r["profit"]   for r in monthly_series]

    fig, ax = plt.subplots(figsize=(11, 4.5))
    _apply_theme(fig, ax)
    _title(ax, "Выручка / Расходы / Прибыль по месяцам")

    ax.plot(labels, rev,  color=ACCENT,  linewidth=2.2, marker="o", markersize=4, label="Выручка",  zorder=3)
    ax.plot(labels, exp,  color=EXPENSE, linewidth=2.0, marker="s", markersize=4, label="Расходы",  zorder=3)
    ax.plot(labels, prof, color=PROFIT,  linewidth=2.0, marker="^", markersize=4, label="Прибыль",  zorder=3)

    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: _dollar(x)))
    ax.set_ylabel("Сумма, $", fontfamily=FONT, fontsize=9, color="#475569")
    ax.legend(fontsize=8, framealpha=0.7, prop={"family": FONT})
    plt.xticks(rotation=30, ha="right")
    fig.tight_layout()
    return _to_png(fig)


# ── 3. Top chatters bar ───────────────────────────────────────────────────────

def chart_top_chatters(top_chatters: list[dict], period: str = "") -> bytes:
    if not top_chatters:
        return _empty_chart(f"Топ чаттеров ({period})")

    # Sort ascending so highest is at top of horizontal bar
    sorted_data = sorted(top_chatters, key=lambda x: x["revenue"])
    names  = [d["chatter"]  for d in sorted_data]
    values = [d["revenue"]  for d in sorted_data]

    fig, ax = plt.subplots(figsize=(9, max(3, len(names) * 0.55 + 1.5)))
    _apply_theme(fig, ax)
    _title(ax, f"Топ чаттеров — {period}" if period else "Топ чаттеров")
    ax.xaxis.grid(True, color=GRID_CLR, linewidth=0.7, linestyle="--", zorder=0)
    ax.yaxis.grid(False)

    bars = ax.barh(names, values, color=ACCENT, height=0.6, zorder=3)
    for bar, v in zip(bars, values):
        ax.text(
            bar.get_width() + max(values) * 0.01, bar.get_y() + bar.get_height() / 2,
            _dollar(v), va="center", ha="left", fontsize=8, color="#334155", fontfamily=FONT,
        )
    ax.set_xlabel("Выручка, $", fontfamily=FONT, fontsize=9, color="#475569")
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: _dollar(x)))
    fig.tight_layout()
    return _to_png(fig)


# ── 4. Chatter MoM change ─────────────────────────────────────────────────────

def chart_chatter_mom_change(
    current_chatters: list[dict],
    prev_chatters: list[dict],
    period: str = "",
    period_prev: str = "",
) -> bytes:
    """Divergent bar: revenue change current vs prev month, top by |delta|."""
    curr_map = {d["chatter"]: d["revenue"] for d in current_chatters}
    prev_map = {d["chatter"]: d["revenue"] for d in prev_chatters}
    all_names = set(curr_map) | set(prev_map)

    deltas = {}
    for name in all_names:
        c = curr_map.get(name, 0.0)
        p = prev_map.get(name, 0.0)
        if p > 0 or c > 0:
            deltas[name] = c - p

    if not deltas:
        return _empty_chart("Изменение выручки чаттеров")

    # Top 12 by abs delta
    top = sorted(deltas.items(), key=lambda x: abs(x[1]), reverse=True)[:12]
    top_sorted = sorted(top, key=lambda x: x[1])
    names  = [t[0] for t in top_sorted]
    values = [t[1] for t in top_sorted]
    colors = [PROFIT if v >= 0 else EXPENSE for v in values]

    fig, ax = plt.subplots(figsize=(9, max(3, len(names) * 0.55 + 1.5)))
    _apply_theme(fig, ax)
    label = f"Изменение выручки чаттеров: {period_prev} → {period}"
    _title(ax, label if period else "Изменение выручки чаттеров MoM")
    ax.xaxis.grid(True, color=GRID_CLR, linewidth=0.7, linestyle="--", zorder=0)
    ax.yaxis.grid(False)

    bars = ax.barh(names, values, color=colors, height=0.6, zorder=3)
    ax.axvline(0, color="#475569", linewidth=0.8)
    for bar, v in zip(bars, values):
        offset = max(abs(val) for val in values) * 0.015
        x_pos = bar.get_width() + (offset if v >= 0 else -offset)
        ha = "left" if v >= 0 else "right"
        sign = "+" if v >= 0 else ""
        ax.text(
            x_pos, bar.get_y() + bar.get_height() / 2,
            f"{sign}{_dollar(v)}", va="center", ha=ha,
            fontsize=8, color="#334155", fontfamily=FONT,
        )
    ax.set_xlabel("Изменение выручки ($)", fontfamily=FONT, fontsize=9, color="#475569")
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{'+'if x>=0 else ''}{_dollar(x)}"))
    fig.tight_layout()
    return _to_png(fig)


# ── 5. Transaction count ──────────────────────────────────────────────────────

def chart_tx_count(monthly_series: list[dict]) -> bytes:
    labels = [_short_month(r["month"]) for r in monthly_series]
    # monthly_series doesn't have tx_count; derive from monthly_detail if available
    # fallback: just show revenue / avg_check ≈ count (not available here)
    # Since monthly_series only has revenue/expenses/profit, we render a placeholder note
    # We accept monthly_detail rows here too (caller passes the right data)
    values = [r.get("tx_count", 0) for r in monthly_series]

    fig, ax = plt.subplots(figsize=(10, 4))
    _apply_theme(fig, ax)
    _title(ax, "Количество транзакций по месяцам")

    bars = ax.bar(labels, values, color=ACCENT, width=0.6, zorder=3)
    for bar, v in zip(bars, values):
        if v:
            ax.text(
                bar.get_x() + bar.get_width() / 2, bar.get_height() + max(values) * 0.01,
                str(int(v)), ha="center", fontsize=7, color="#334155", fontfamily=FONT,
            )
    ax.set_ylabel("Транзакции", fontfamily=FONT, fontsize=9, color="#475569")
    plt.xticks(rotation=30, ha="right")
    fig.tight_layout()
    return _to_png(fig)


# ── 6. Avg check ──────────────────────────────────────────────────────────────

def chart_avg_check(monthly_detail: list[dict]) -> bytes:
    """Avg check = revenue / tx_count per month."""
    rows = [
        (r["month"], r["revenue"] / r.get("tx_count", 1) if r.get("tx_count") else None)
        for r in monthly_detail
        if r.get("revenue")
    ]
    labels = [_short_month(r[0]) for r in rows]
    values = [r[1] for r in rows]

    fig, ax = plt.subplots(figsize=(10, 4))
    _apply_theme(fig, ax)
    _title(ax, "Средний чек по месяцам")

    ax.plot(labels, values, color=ACCENT2, linewidth=2.2, marker="o", markersize=5, zorder=3)
    ax.fill_between(labels, values, alpha=0.12, color=ACCENT2)

    for i, (lbl, v) in enumerate(zip(labels, values)):
        if v is not None:
            ax.annotate(
                _dollar(v), (i, v),
                textcoords="offset points", xytext=(0, 8),
                ha="center", fontsize=7, color="#334155", fontfamily=FONT,
            )

    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: _dollar(x)))
    ax.set_ylabel("Средний чек, $", fontfamily=FONT, fontsize=9, color="#475569")
    plt.xticks(rotation=30, ha="right")
    fig.tight_layout()
    return _to_png(fig)


# ── 7. Expenses by category ───────────────────────────────────────────────────

def chart_expenses_by_category(expenses_by_category: list[dict], period: str = "") -> bytes:
    if not expenses_by_category:
        return _empty_chart(f"Расходы по категориям ({period})")

    sorted_data = sorted(expenses_by_category, key=lambda x: x["amount"])
    names  = [d["category"] for d in sorted_data]
    values = [d["amount"]   for d in sorted_data]

    fig, ax = plt.subplots(figsize=(9, max(3, len(names) * 0.6 + 1.5)))
    _apply_theme(fig, ax)
    _title(ax, f"Расходы по категориям — {period}" if period else "Расходы по категориям")
    ax.xaxis.grid(True, color=GRID_CLR, linewidth=0.7, linestyle="--", zorder=0)
    ax.yaxis.grid(False)

    palette = [EXPENSE, "#fb923c", "#fbbf24", "#a3e635", "#34d399", "#22d3ee", "#818cf8", "#e879f9"]
    bar_colors = [palette[i % len(palette)] for i in range(len(names))]

    bars = ax.barh(names, values, color=bar_colors, height=0.6, zorder=3)
    for bar, v in zip(bars, values):
        ax.text(
            bar.get_width() + max(values) * 0.01, bar.get_y() + bar.get_height() / 2,
            _dollar(v), va="center", ha="left", fontsize=8, color="#334155", fontfamily=FONT,
        )
    ax.set_xlabel("Сумма, $", fontfamily=FONT, fontsize=9, color="#475569")
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: _dollar(x)))
    fig.tight_layout()
    return _to_png(fig)


# ── KPI charts (data pre-fetched by router via kpi_service) ──────────────────

def chart_kpi_scatter_rpc_chats(rows: list, period: str = "") -> bytes:
    """Scatter: X=total_chats, Y=rpc. Quadrant lines at medians."""
    from statistics import median

    pts = [
        (r.chatter, r.total_chats, r.rpc, r.revenue)
        for r in rows
        if r.total_chats and r.rpc
    ]
    if not pts:
        return _empty_chart(f"RPC × Объём диалогов — {period}")

    names, xs, ys, revs = zip(*pts)
    xs = list(xs); ys = list(ys); revs = list(revs)

    med_x = median(xs)
    med_y = median(ys)
    max_rev = max(revs) or 1
    sizes = [max(40, r / max_rev * 600) for r in revs]

    fig, ax = plt.subplots(figsize=(10, 6))
    _apply_theme(fig, ax)
    _title(ax, f"Объём диалогов × Эффективность (RPC) — {period}" if period else "Объём диалогов × Эффективность (RPC)")

    ax.scatter(xs, ys, s=sizes, color=ACCENT, alpha=0.75, zorder=3, edgecolors="white", linewidths=0.5)

    # Median lines (quadrant dividers)
    ax.axvline(med_x, color=GREY, linewidth=1.0, linestyle="--", zorder=2)
    ax.axhline(med_y, color=GREY, linewidth=1.0, linestyle="--", zorder=2)

    # Quadrant annotations
    xlim = ax.get_xlim(); ylim = ax.get_ylim()
    kw = dict(color="#94a3b8", fontsize=7, fontfamily=FONT, alpha=0.8)
    ax.text(xlim[0] + (med_x - xlim[0]) * 0.05, ylim[0] + (ylim[1] - med_y) * 0.97 + med_y,
            "мало объёма, высокий RPC", ha="left", va="top", **kw)
    ax.text(med_x + (xlim[1] - med_x) * 0.97, ylim[0] + (med_y - ylim[0]) * 0.05,
            "много чатов, слабая монетизация", ha="right", va="bottom", **kw)
    ax.text(med_x + (xlim[1] - med_x) * 0.97, ylim[0] + (ylim[1] - med_y) * 0.97 + med_y,
            "объём + монетизация", ha="right", va="top", **kw)
    ax.text(xlim[0] + (med_x - xlim[0]) * 0.05, ylim[0] + (med_y - ylim[0]) * 0.05,
            "мало чатов, слабый RPC", ha="left", va="bottom", **kw)

    # Name labels near points
    for name, x, y in zip(names, xs, ys):
        ax.annotate(name, (x, y), textcoords="offset points", xytext=(5, 4),
                    fontsize=7, color="#334155", fontfamily=FONT)

    ax.set_xlabel("Кол-во диалогов", fontfamily=FONT, fontsize=9, color="#475569")
    ax.set_ylabel("RPC ($)", fontfamily=FONT, fontsize=9, color="#475569")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: _dollar(x)))
    fig.tight_layout()
    return _to_png(fig)


def chart_kpi_open_rate(rows: list, period: str = "") -> bytes:
    """Horizontal bar: PPV Open Rate %, top-15, colour-coded by zone."""
    pts = sorted(
        [(r.chatter, float(r.ppv_open_rate)) for r in rows if r.ppv_open_rate is not None],
        key=lambda x: x[1], reverse=True,
    )[:15]
    if not pts:
        return _empty_chart(f"PPV Open Rate — {period}")

    # Sort ascending so highest is at top
    pts_sorted = list(reversed(pts))
    names  = [p[0] for p in pts_sorted]
    values = [p[1] for p in pts_sorted]

    def _zone_color(v: float) -> str:
        if v < 20:   return EXPENSE   # red
        if v < 35:   return "#fbbf24" # yellow
        return PROFIT                  # green

    colors = [_zone_color(v) for v in values]

    fig, ax = plt.subplots(figsize=(9, max(3, len(names) * 0.55 + 1.5)))
    _apply_theme(fig, ax)
    _title(ax, f"PPV Open Rate (%) — {period}" if period else "PPV Open Rate (%)")
    ax.xaxis.grid(True, color=GRID_CLR, linewidth=0.7, linestyle="--", zorder=0)
    ax.yaxis.grid(False)

    bars = ax.barh(names, values, color=colors, height=0.6, zorder=3)
    # Reference lines
    ax.axvline(20, color=EXPENSE, linewidth=1.0, linestyle=":", label="20% (критично)")
    ax.axvline(35, color=PROFIT,  linewidth=1.0, linestyle=":", label="35% (сильно)")
    ax.legend(fontsize=7, framealpha=0.7, prop={"family": FONT})

    for bar, v in zip(bars, values):
        ax.text(
            bar.get_width() + 0.3, bar.get_y() + bar.get_height() / 2,
            f"{v:.1f}%", va="center", ha="left", fontsize=8, color="#334155", fontfamily=FONT,
        )
    ax.set_xlabel("Open Rate (%)", fontfamily=FONT, fontsize=9, color="#475569")
    fig.tight_layout()
    return _to_png(fig)


def chart_kpi_top_revenue(rows: list, period: str = "") -> bytes:
    """Horizontal bar: top-10 chatters by revenue this month."""
    pts = sorted(
        [(r.chatter, r.revenue) for r in rows],
        key=lambda x: x[1], reverse=True,
    )[:10]
    if not pts:
        return _empty_chart(f"Топ-10 по выручке — {period}")

    pts_sorted = list(reversed(pts))
    names  = [p[0] for p in pts_sorted]
    values = [p[1] for p in pts_sorted]

    fig, ax = plt.subplots(figsize=(9, max(3, len(names) * 0.55 + 1.5)))
    _apply_theme(fig, ax)
    _title(ax, f"Топ-10 по выручке — {period}" if period else "Топ-10 по выручке")
    ax.xaxis.grid(True, color=GRID_CLR, linewidth=0.7, linestyle="--", zorder=0)
    ax.yaxis.grid(False)

    bars = ax.barh(names, values, color=ACCENT, height=0.6, zorder=3)
    for bar, v in zip(bars, values):
        ax.text(
            bar.get_width() + max(values) * 0.01, bar.get_y() + bar.get_height() / 2,
            _dollar(v), va="center", ha="left", fontsize=8, color="#334155", fontfamily=FONT,
        )
    ax.set_xlabel("Выручка ($)", fontfamily=FONT, fontsize=9, color="#475569")
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: _dollar(x)))
    fig.tight_layout()
    return _to_png(fig)


def chart_kpi_biggest_movers(rows: list, period: str = "", period_prev: str = "") -> bytes:
    """Divergent bar: revenue_delta MoM, top by |delta|."""
    pts = [
        (r.chatter, float(r.revenue_delta))
        for r in rows
        if r.revenue_delta is not None
    ]
    if not pts:
        return _empty_chart("Крупнейшие изменения выручки MoM")

    pts_sorted = sorted(pts, key=lambda x: abs(x[1]), reverse=True)[:12]
    pts_sorted = sorted(pts_sorted, key=lambda x: x[1])
    names  = [p[0] for p in pts_sorted]
    values = [p[1] for p in pts_sorted]
    colors = [PROFIT if v >= 0 else EXPENSE for v in values]

    label = (f"Крупнейшие изменения выручки: {period_prev} → {period}"
             if period else "Крупнейшие изменения выручки MoM")

    fig, ax = plt.subplots(figsize=(9, max(3, len(names) * 0.55 + 1.5)))
    _apply_theme(fig, ax)
    _title(ax, label)
    ax.xaxis.grid(True, color=GRID_CLR, linewidth=0.7, linestyle="--", zorder=0)
    ax.yaxis.grid(False)

    bars = ax.barh(names, values, color=colors, height=0.6, zorder=3)
    ax.axvline(0, color="#475569", linewidth=0.8)
    max_abs = max(abs(v) for v in values) or 1
    for bar, v in zip(bars, values):
        offset = max_abs * 0.015
        x_pos = bar.get_width() + (offset if v >= 0 else -offset)
        ha = "left" if v >= 0 else "right"
        ax.text(
            x_pos, bar.get_y() + bar.get_height() / 2,
            f"{'+'if v>=0 else ''}{v:.1f}%",
            va="center", ha=ha, fontsize=8, color="#334155", fontfamily=FONT,
        )
    ax.set_xlabel("Изменение выручки (%)", fontfamily=FONT, fontsize=9, color="#475569")
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{'+'if x>=0 else ''}{x:.0f}%"))
    fig.tight_layout()
    return _to_png(fig)


# ── Helper ────────────────────────────────────────────────────────────────────

def _empty_chart(title: str) -> bytes:
    fig, ax = plt.subplots(figsize=(7, 3))
    _apply_theme(fig, ax)
    _title(ax, title)
    ax.text(0.5, 0.5, "Нет данных", transform=ax.transAxes,
            ha="center", va="center", fontsize=14, color=GREY, fontfamily=FONT)
    ax.set_axis_off()
    return _to_png(fig)
