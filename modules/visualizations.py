"""Visualization helpers for the CashCanvas expense tracker."""

from __future__ import annotations

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
import pandas as pd
import seaborn as sns
from matplotlib.patches import Patch

from database.db_operations import EXPENSE_CATEGORIES

DARK_BACKGROUND = "#0e1117"
AXIS_BACKGROUND = "#111827"
GRID_COLOR = "#374151"
TEXT_COLOR = "#f3f4f6"
CATEGORY_PALETTE = sns.color_palette("husl", 15)
LINE_BLUE = "#3b82f6"
LINE_PURPLE = "#8b5cf6"
LINE_TEAL = "#14b8a6"
CATEGORY_COLOR_MAP = {
    category: CATEGORY_PALETTE[index % len(CATEGORY_PALETTE)]
    for index, category in enumerate(EXPENSE_CATEGORIES)
}


def _no_data_figure(message: str = "No data available"):
    """Return a polished placeholder figure for empty datasets."""

    fig, ax = plt.subplots(figsize=(7, 4), facecolor=DARK_BACKGROUND)
    ax.set_facecolor(AXIS_BACKGROUND)
    ax.axis("off")
    ax.text(
        0.5,
        0.5,
        message,
        ha="center",
        va="center",
        fontsize=15,
        color=TEXT_COLOR,
        transform=ax.transAxes,
    )
    fig.tight_layout()
    return fig


def _prepare_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Return a sorted copy of the data with a normalized datetime column."""

    if df is None or df.empty:
        return pd.DataFrame()

    frame = df.copy()
    frame["txn_date"] = pd.to_datetime(frame["txn_date"])
    frame = frame.sort_values("txn_date")
    return frame


def _style_axis(ax) -> None:
    """Apply a simple dark theme to a Matplotlib axis."""

    ax.set_facecolor(AXIS_BACKGROUND)
    ax.tick_params(colors=TEXT_COLOR, labelsize=10)
    ax.xaxis.label.set_color(TEXT_COLOR)
    ax.yaxis.label.set_color(TEXT_COLOR)
    ax.title.set_color(TEXT_COLOR)
    for spine in ax.spines.values():
        spine.set_color(GRID_COLOR)
    ax.grid(True, color=GRID_COLOR, alpha=0.28, linewidth=0.8)


def _format_currency_axis(ax) -> None:
    """Format the y-axis with rupee labels."""

    ax.yaxis.set_major_formatter(mtick.FuncFormatter(lambda value, _: f"₹{value:,.0f}"))


def _apply_date_axis(ax, dates: pd.Index) -> None:
    """Apply readable date formatting and handle single-date charts."""

    unique_dates = pd.to_datetime(pd.Index(dates).unique())
    if len(unique_dates) == 1:
        center_date = pd.Timestamp(unique_dates[0])
        ax.set_xlim(center_date - pd.Timedelta(days=1), center_date + pd.Timedelta(days=1))

    locator = mdates.AutoDateLocator()
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))


def plot_category_pie(df: pd.DataFrame):
    """Plot total spend by category as a donut chart with a detailed legend."""

    frame = _prepare_frame(df)
    if frame.empty:
        return _no_data_figure()

    category_totals = (
        frame.groupby("category", dropna=False)["amount"].sum().sort_values(ascending=False)
    )
    if category_totals.empty:
        return _no_data_figure()

    colors = [CATEGORY_COLOR_MAP.get(category, CATEGORY_PALETTE[0]) for category in category_totals.index]
    total_spend = float(category_totals.sum())

    fig, ax = plt.subplots(figsize=(7.5, 5.2), facecolor=DARK_BACKGROUND)
    ax.set_facecolor(AXIS_BACKGROUND)

    wedges, _, autotexts = ax.pie(
        category_totals.values,
        labels=None,
        autopct=lambda pct: f"{pct:.1f}%",
        startangle=90,
        colors=colors,
        pctdistance=0.78,
        wedgeprops={"width": 0.38, "edgecolor": DARK_BACKGROUND},
        textprops={"color": TEXT_COLOR, "fontsize": 10},
    )

    legend_labels = [f"{category} - ₹{amount:,.2f}" for category, amount in category_totals.items()]
    legend_handles = [Patch(facecolor=color, edgecolor=DARK_BACKGROUND) for color in colors]
    ax.legend(
        legend_handles,
        legend_labels,
        title="Categories",
        loc="center left",
        bbox_to_anchor=(1.02, 0.5),
        frameon=False,
        labelcolor=TEXT_COLOR,
        fontsize=9,
        title_fontsize=10,
    )

    for autotext in autotexts:
        autotext.set_color(TEXT_COLOR)
        autotext.set_fontweight("bold")

    ax.set_title(f"Spending by Category  •  Total {_format_currency_axis_text(total_spend)}")
    ax.axis("equal")
    fig.tight_layout()
    return fig


def _format_currency_axis_text(amount: float) -> str:
    """Return a rupee string for chart titles and annotations."""

    return f"₹{amount:,.2f}"


def plot_monthly_bar(df: pd.DataFrame):
    """Plot total spend per month as an annotated bar chart."""

    frame = _prepare_frame(df)
    if frame.empty:
        return _no_data_figure()

    grouped = (
        frame.groupby(frame["txn_date"].dt.to_period("M"))
        .agg(total_spent=("amount", "sum"), transaction_count=("amount", "size"))
        .sort_index()
    )
    if grouped.empty:
        return _no_data_figure()

    fig, ax = plt.subplots(figsize=(7.5, 4.5), facecolor=DARK_BACKGROUND)
    ax.set_facecolor(AXIS_BACKGROUND)

    month_labels = [period.strftime("%b %Y") for period in grouped.index]
    month_colors = sns.color_palette("crest", n_colors=len(grouped))
    bars = ax.bar(month_labels, grouped["total_spent"].values, color=month_colors, width=0.62)

    ax.set_title("Monthly Spending Comparison")
    ax.set_xlabel("Month")
    ax.set_ylabel("Total Spend")
    ax.tick_params(axis="x", rotation=30)
    for tick_label in ax.get_xticklabels():
        tick_label.set_ha("right")

    _format_currency_axis(ax)
    _style_axis(ax)

    labels = [f"₹{value:,.2f}" for value in grouped["total_spent"].values]
    ax.bar_label(bars, labels=labels, padding=3, color=TEXT_COLOR, fontsize=9)

    fig.tight_layout()
    return fig


def plot_spending_trend(df: pd.DataFrame):
    """Plot cumulative spending over time using daily totals."""

    frame = _prepare_frame(df)
    if frame.empty:
        return _no_data_figure()

    daily_spend = frame.groupby(frame["txn_date"].dt.normalize())["amount"].sum().sort_index()
    if daily_spend.empty:
        return _no_data_figure()

    cumulative_spend = daily_spend.cumsum()

    fig, ax = plt.subplots(figsize=(7.5, 4.5), facecolor=DARK_BACKGROUND)
    ax.set_facecolor(AXIS_BACKGROUND)
    ax.plot(
        cumulative_spend.index,
        cumulative_spend.values,
        color=LINE_TEAL,
        linewidth=2.5,
        marker="o",
        markersize=5,
        label="Cumulative Spend",
    )

    ax.set_title("Cumulative Spending Trend")
    ax.set_xlabel("Date")
    ax.set_ylabel("Cumulative Spend")
    ax.legend(facecolor=AXIS_BACKGROUND, edgecolor=GRID_COLOR, labelcolor=TEXT_COLOR)

    _style_axis(ax)
    _format_currency_axis(ax)
    _apply_date_axis(ax, cumulative_spend.index)

    last_date = cumulative_spend.index[-1]
    last_value = float(cumulative_spend.iloc[-1])
    ax.annotate(
        f"Latest: ₹{last_value:,.2f}",
        xy=(last_date, last_value),
        xytext=(10, 12),
        textcoords="offset points",
        color=TEXT_COLOR,
        fontsize=9,
        bbox={"boxstyle": "round,pad=0.3", "facecolor": AXIS_BACKGROUND, "edgecolor": GRID_COLOR},
    )

    fig.autofmt_xdate()
    fig.tight_layout()
    return fig


def plot_actual_vs_trend(df: pd.DataFrame, span: int = 7):
    """Plot daily expenses against the EWMA-smoothed spending trend."""

    frame = _prepare_frame(df)
    if frame.empty:
        return _no_data_figure()

    daily_spend = frame.groupby(frame["txn_date"].dt.normalize())["amount"].sum().sort_index()
    if daily_spend.empty:
        return _no_data_figure()

    # EWMA smooths the daily totals by weighting recent spending more heavily.
    ewma_trend = daily_spend.ewm(span=span, adjust=False).mean()

    fig, ax = plt.subplots(figsize=(7.5, 4.5), facecolor=DARK_BACKGROUND)
    ax.set_facecolor(AXIS_BACKGROUND)
    ax.plot(
        daily_spend.index,
        daily_spend.values,
        color=LINE_BLUE,
        linewidth=2.2,
        marker="o",
        markersize=5,
        label="Daily Expenses",
    )
    ax.plot(
        ewma_trend.index,
        ewma_trend.values,
        color=LINE_PURPLE,
        linewidth=2.2,
        marker="o",
        markersize=5,
        label="EWMA Trend",
    )

    ax.set_title("Daily Expenses vs EWMA Trend")
    ax.set_xlabel("Date")
    ax.set_ylabel("Spend")
    ax.legend(facecolor=AXIS_BACKGROUND, edgecolor=GRID_COLOR, labelcolor=TEXT_COLOR)

    _style_axis(ax)
    _format_currency_axis(ax)
    _apply_date_axis(ax, daily_spend.index)

    last_date = daily_spend.index[-1]
    last_daily = float(daily_spend.iloc[-1])
    last_ewma = float(ewma_trend.iloc[-1])
    ax.annotate(
        f"Daily: ₹{last_daily:,.2f}",
        xy=(last_date, last_daily),
        xytext=(10, 18),
        textcoords="offset points",
        color=TEXT_COLOR,
        fontsize=9,
        bbox={"boxstyle": "round,pad=0.3", "facecolor": AXIS_BACKGROUND, "edgecolor": GRID_COLOR},
    )
    ax.annotate(
        f"EWMA: ₹{last_ewma:,.2f}",
        xy=(last_date, last_ewma),
        xytext=(10, -26),
        textcoords="offset points",
        color=TEXT_COLOR,
        fontsize=9,
        bbox={"boxstyle": "round,pad=0.3", "facecolor": AXIS_BACKGROUND, "edgecolor": GRID_COLOR},
    )

    fig.autofmt_xdate()
    fig.tight_layout()
    return fig
