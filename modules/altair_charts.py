"""Altair chart helpers for CashCanvas."""

from __future__ import annotations

import math

import altair as alt
import numpy as np
import pandas as pd

from database.db_operations import EXPENSE_CATEGORIES

DARK_BACKGROUND = "#0F172A"
AXIS_LABEL_COLOR = "#E2E8F0"
TITLE_COLOR = "#F8FAFC"
GRID_COLOR = "#334155"
AXIS_DOMAIN_COLOR = "#64748B"
CYAN = "#22D3EE"
BLUE = "#3B82F6"
PURPLE = "#8B5CF6"
GREEN = "#10B981"
AMBER = "#F59E0B"
RED = "#EF4444"
PINK = "#EC4899"
CATEGORY_COLORS = [CYAN, BLUE, PURPLE, GREEN, AMBER, RED, PINK, "#06B6D4", "#60A5FA", "#A78BFA", "#34D399", "#FBBF24", "#F87171", "#F472B6", "#67E8F9"]
CATEGORY_COLOR_MAP = {
    category: CATEGORY_COLORS[index % len(CATEGORY_COLORS)]
    for index, category in enumerate(EXPENSE_CATEGORIES)
}

ONE_DAY_MILLISECONDS = 86_400_000


def _rupee_axis(**kwargs) -> alt.Axis:
    """Return a money axis that never switches to scientific notation."""

    return alt.Axis(
        labelExpr="'₹' + format(datum.value, ',.0f')",
        **kwargs,
    )


def _date_axis(row_count: int, include_year: bool = True) -> alt.Axis:
    """Return daily temporal ticks without duplicate sub-day date labels."""

    label_format = "%d %b %Y" if include_year else "%d %b"
    tick_count = max(2, min(int(row_count), 8))
    label_angle = -35 if row_count > 6 else 0
    return alt.Axis(
        format=label_format,
        labelAngle=label_angle,
        tickCount=tick_count,
        tickMinStep=ONE_DAY_MILLISECONDS,
    )


def _empty_chart(message: str = "No data available") -> alt.Chart:
    """Return a minimal readable placeholder chart for empty inputs."""

    empty_data = pd.DataFrame({"message": [message]})
    chart = (
        alt.Chart(empty_data)
        .mark_text(color=TITLE_COLOR, fontSize=16)
        .encode(text="message:N")
        .properties(width=700, height=360)
    )
    return _apply_dark_theme(chart)


def _apply_dark_theme(chart: alt.Chart) -> alt.Chart:
    """Apply the same dark theme configuration to every visible chart."""

    return chart.configure(
        background=DARK_BACKGROUND,
    ).configure_title(
        color=TITLE_COLOR,
        fontSize=16,
        anchor="start",
    ).configure_axis(
        labelColor=AXIS_LABEL_COLOR,
        titleColor=TITLE_COLOR,
        domainColor=AXIS_DOMAIN_COLOR,
        gridColor=GRID_COLOR,
        tickColor=AXIS_DOMAIN_COLOR,
    ).configure_legend(
        labelColor=AXIS_LABEL_COLOR,
        titleColor=TITLE_COLOR,
        orient="bottom",
        direction="horizontal",
    ).configure_view(
        fill=DARK_BACKGROUND,
        stroke=None,
    )


def _clean_transactions(df: pd.DataFrame) -> pd.DataFrame:
    """Return a sorted copy with safe date and amount columns."""

    if df is None or df.empty:
        return pd.DataFrame()

    frame = df.copy()
    frame["txn_date"] = pd.to_datetime(frame["txn_date"], errors="coerce")
    frame["amount"] = pd.to_numeric(frame["amount"], errors="coerce")
    frame = frame.loc[frame["txn_date"].notna() & frame["amount"].notna()].copy()
    frame["amount"] = frame["amount"].clip(lower=0.0)
    frame = frame.sort_values("txn_date")
    return frame


def _format_currency(value: float) -> str:
    """Format a numeric value as Indian rupees for display fields."""

    return f"₹{float(value):,.2f}"


def _month_label(month_period: pd.Period) -> str:
    """Format a period as a readable month label such as Jul 2026."""

    return month_period.strftime("%b %Y")


def prepare_category_donut_data(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate transactions by category for the donut chart."""

    frame = _clean_transactions(df)
    if frame.empty:
        return pd.DataFrame(
            columns=[
                "category",
                "total_spent",
                "transaction_count",
                "percentage_of_total",
                "percentage_label",
                "theta",
                "radius",
                "total_spent_display",
                "percentage_display",
            ]
        )

    grouped = (
        frame.groupby("category", dropna=False)
        .agg(total_spent=("amount", "sum"), transaction_count=("amount", "size"))
        .sort_values("total_spent", ascending=False)
        .reset_index()
    )
    total_spent = float(grouped["total_spent"].sum())

    if total_spent <= 0:
        grouped["percentage_of_total"] = 0.0
    else:
        grouped["percentage_of_total"] = grouped["total_spent"] / total_spent * 100.0

    grouped["total_spent_display"] = grouped["total_spent"].apply(_format_currency)
    grouped["percentage_display"] = grouped["percentage_of_total"].map(lambda value: f"{value:.2f}%")

    cumulative_share = grouped["percentage_of_total"].cumsum()
    previous_share = cumulative_share.shift(fill_value=0.0)
    grouped["theta"] = ((previous_share + cumulative_share) / 2.0) * (math.pi / 50.0)
    grouped["radius"] = 145.0
    grouped["percentage_label"] = grouped["percentage_display"]
    grouped.loc[grouped["percentage_of_total"] < 7.0, "percentage_label"] = ""

    return grouped


def create_category_donut_chart(df: pd.DataFrame) -> alt.Chart:
    """Create an interactive Altair donut chart for category spending."""

    required = {"category", "total_spent", "transaction_count", "percentage_of_total"}
    prepared = df if df is not None and required.issubset(df.columns) else prepare_category_donut_data(df)
    if prepared is None or prepared.empty:
        return _empty_chart("No category spending data available")

    hover = alt.selection_point(fields=["category"], on="mouseover", clear="mouseout", nearest=True)
    chart_base = (
        alt.Chart(prepared)
        .mark_arc(innerRadius=78, outerRadius=140, stroke=DARK_BACKGROUND, strokeWidth=2)
        .encode(
            theta=alt.Theta("total_spent:Q", stack=True),
            color=alt.Color(
                "category:N",
                scale=alt.Scale(domain=EXPENSE_CATEGORIES, range=[CATEGORY_COLOR_MAP[category] for category in EXPENSE_CATEGORIES]),
                legend=alt.Legend(
                    title="Category",
                    orient="bottom",
                    columns=3,
                    labelColor=AXIS_LABEL_COLOR,
                    titleColor=TITLE_COLOR,
                ),
            ),
            opacity=alt.condition(hover, alt.value(1.0), alt.value(0.82)),
            tooltip=[
                alt.Tooltip("category:N", title="Category"),
                alt.Tooltip("total_spent:Q", title="Amount (₹)", format=",.2f"),
                alt.Tooltip("percentage_of_total:Q", title="Percentage of Total", format=".2f"),
                alt.Tooltip("transaction_count:Q", title="Transactions"),
            ],
        )
        .add_params(hover)
    )

    labels = (
        alt.Chart(prepared.loc[prepared["percentage_label"] != ""])
        .mark_text(color=TITLE_COLOR, fontWeight="bold", fontSize=12)
        .encode(
            theta=alt.Theta("theta:Q"),
            radius=alt.Radius("radius:Q"),
            text=alt.Text("percentage_label:N"),
        )
    )

    chart = (
        alt.layer(chart_base, labels)
        .properties(title="Category Spending Breakdown", width=720, height=420)
        .configure_arc(outerRadius=140)
    )
    return _apply_dark_theme(chart)


def prepare_monthly_bar_data(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate transactions by month for the monthly bar chart."""

    frame = _clean_transactions(df)
    if frame.empty:
        return pd.DataFrame(
            columns=[
                "month_period",
                "month_label",
                "total_spent",
                "transaction_count",
                "change_from_previous_month",
                "total_spent_display",
                "change_from_previous_month_display",
            ]
        )

    frame["month_period"] = frame["txn_date"].dt.to_period("M")
    grouped = (
        frame.groupby("month_period", as_index=False)
        .agg(total_spent=("amount", "sum"), transaction_count=("amount", "size"))
        .sort_values("month_period")
        .reset_index(drop=True)
    )
    grouped["month_label"] = grouped["month_period"].apply(_month_label)
    grouped["total_spent_display"] = grouped["total_spent"].apply(_format_currency)
    grouped["change_from_previous_month"] = grouped["total_spent"].pct_change() * 100.0
    grouped["change_from_previous_month_display"] = grouped["change_from_previous_month"].map(
        lambda value: "N/A" if pd.isna(value) else f"{value:.2f}%"
    )
    return grouped


def create_monthly_bar_chart(df: pd.DataFrame) -> alt.Chart:
    """Create an interactive monthly spending comparison chart."""

    required = {"month_period", "month_label", "total_spent", "transaction_count"}
    prepared = df if df is not None and required.issubset(df.columns) else prepare_monthly_bar_data(df)
    if prepared is None or prepared.empty:
        return _empty_chart("No monthly spending data available")

    ordered_labels = prepared["month_label"].tolist()
    hover = alt.selection_point(fields=["month_label"], on="mouseover", clear="mouseout")

    bars = (
        alt.Chart(prepared)
        .mark_bar(cornerRadiusTopLeft=6, cornerRadiusTopRight=6)
        .encode(
            x=alt.X("month_label:N", sort=ordered_labels, title="Month"),
            y=alt.Y("total_spent:Q", title="Total Spend", axis=_rupee_axis()),
            color=alt.condition(hover, alt.value(CYAN), alt.value(BLUE)),
            opacity=alt.condition(hover, alt.value(1.0), alt.value(0.86)),
            tooltip=[
                alt.Tooltip("month_label:N", title="Month"),
                alt.Tooltip("total_spent:Q", title="Total Spending (₹)", format=",.2f"),
                alt.Tooltip("transaction_count:Q", title="Transactions"),
                alt.Tooltip(
                    "change_from_previous_month_display:N",
                    title="Change From Previous Month",
                ),
            ],
        )
        .add_params(hover)
    )

    labels = (
        alt.Chart(prepared)
        .mark_text(color=TITLE_COLOR, dy=-8, fontWeight="bold")
        .encode(
            x=alt.X("month_label:N", sort=ordered_labels),
            y=alt.Y("total_spent:Q"),
            text=alt.Text("total_spent_display:N"),
        )
    )

    chart = (
        alt.layer(bars, labels)
        .properties(title="Monthly Spending Comparison", width=720, height=380)
    )
    return _apply_dark_theme(chart)


def prepare_cumulative_spending_data(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate transactions by day and compute the cumulative spend."""

    frame = _clean_transactions(df)
    if frame.empty:
        return pd.DataFrame(columns=["date", "daily_spend", "cumulative_spend"])

    daily = frame.groupby(frame["txn_date"].dt.normalize())["amount"].sum().sort_index()
    full_index = pd.date_range(daily.index.min(), daily.index.max(), freq="D")
    daily = daily.reindex(full_index, fill_value=0.0)
    cumulative = daily.cumsum()

    prepared = pd.DataFrame(
        {
            "date": full_index,
            "daily_spend": daily.values,
            "cumulative_spend": cumulative.values,
        }
    )
    prepared["date"] = pd.to_datetime(prepared["date"])
    prepared["daily_spend"] = pd.to_numeric(prepared["daily_spend"])
    prepared["cumulative_spend"] = pd.to_numeric(prepared["cumulative_spend"])
    return prepared


def create_cumulative_spending_chart(df: pd.DataFrame) -> alt.Chart:
    """Create an interactive cumulative spending chart."""

    required = {"date", "daily_spend", "cumulative_spend"}
    prepared = df if df is not None and required.issubset(df.columns) else prepare_cumulative_spending_data(df)
    if prepared is None or prepared.empty:
        return _empty_chart("No cumulative spending data available")

    hover = alt.selection_point(fields=["date"], nearest=True, on="mouseover", clear="mouseout")

    line = (
        alt.Chart(prepared)
        .mark_line(color=CYAN, strokeWidth=3)
        .encode(
            x=alt.X("date:T", title="Date", axis=_date_axis(len(prepared))),
            y=alt.Y("cumulative_spend:Q", title="Cumulative Spend", axis=_rupee_axis()),
            tooltip=[
                alt.Tooltip("date:T", title="Date", format="%d %b %Y"),
                alt.Tooltip("daily_spend:Q", title="Daily Spend (₹)", format=",.2f"),
                alt.Tooltip("cumulative_spend:Q", title="Cumulative Spend (₹)", format=",.2f"),
            ],
        )
    )

    points = alt.Chart(prepared).mark_point(color=CYAN, filled=True, size=70).encode(
        x="date:T",
        y="cumulative_spend:Q",
    )

    rule = (
        alt.Chart(prepared)
        .mark_rule(color=AXIS_DOMAIN_COLOR)
        .encode(x="date:T")
        .transform_filter(hover)
    )

    tooltip_points = (
        alt.Chart(prepared)
        .mark_point(opacity=0, size=120)
        .encode(
            x="date:T",
            y="cumulative_spend:Q",
            tooltip=[
                alt.Tooltip("date:T", title="Date", format="%d %b %Y"),
                alt.Tooltip("daily_spend:Q", title="Daily Spend (₹)", format=",.2f"),
                alt.Tooltip("cumulative_spend:Q", title="Cumulative Spend (₹)", format=",.2f"),
            ],
        )
        .add_params(hover)
    )

    chart = (
        alt.layer(line, points, rule, tooltip_points)
        .properties(title="Cumulative Spending Trend", width=720, height=380)
        .interactive()
    )
    return _apply_dark_theme(chart)


def prepare_daily_ewma_data(df: pd.DataFrame, span: int = 7) -> pd.DataFrame:
    """Aggregate daily expenses and compute EWMA for the trend chart."""

    frame = _clean_transactions(df)
    if frame.empty:
        return pd.DataFrame(columns=["date", "daily_expenses", "ewma_trend"])

    daily = frame.groupby(frame["txn_date"].dt.normalize())["amount"].sum().sort_index()
    full_index = pd.date_range(daily.index.min(), daily.index.max(), freq="D")
    daily = daily.reindex(full_index, fill_value=0.0)
    ewma = daily.ewm(span=span, adjust=False).mean()

    prepared = pd.DataFrame(
        {
            "date": full_index,
            "daily_expenses": daily.values,
            "ewma_trend": ewma.values,
        }
    )
    prepared["date"] = pd.to_datetime(prepared["date"])
    prepared["daily_expenses"] = pd.to_numeric(prepared["daily_expenses"])
    prepared["ewma_trend"] = pd.to_numeric(prepared["ewma_trend"])
    return prepared


def validate_daily_ewma_data(prepared: pd.DataFrame) -> str | None:
    """Return a readable validation message, or None for chart-ready data."""

    required = {"date", "daily_expenses", "ewma_trend"}
    if prepared is None or prepared.empty:
        return "No daily spending data is available for this chart."

    missing = required.difference(prepared.columns)
    if missing:
        return "Daily/EWMA data is missing required columns: " + ", ".join(sorted(missing))

    for column in ["daily_expenses", "ewma_trend"]:
        if not pd.api.types.is_numeric_dtype(prepared[column]):
            return f"{column} must contain numeric values."
        numeric_values = prepared[column].to_numpy(dtype=float, na_value=np.nan)
        if not np.isfinite(numeric_values).all():
            return f"{column} contains a non-finite value."

    if not pd.api.types.is_datetime64_any_dtype(prepared["date"]):
        return "Daily/EWMA dates must use a datetime dtype."
    if prepared["date"].isna().any():
        return "Daily/EWMA dates contain an invalid value."
    if not prepared["daily_expenses"].gt(0).any():
        return "No positive daily expenses are available for this chart."

    return None


def prepare_daily_ewma_long_data(prepared: pd.DataFrame) -> pd.DataFrame:
    """Reshape the prepared daily data into one numeric amount column."""

    error = validate_daily_ewma_data(prepared)
    if error is not None:
        return pd.DataFrame(columns=["date", "Series", "Amount"])

    long_form = prepared.melt(
        id_vars=["date"],
        value_vars=["daily_expenses", "ewma_trend"],
        var_name="Series",
        value_name="Amount",
    )
    long_form["Series"] = long_form["Series"].map(
        {
            "daily_expenses": "Daily Expenses",
            "ewma_trend": "EWMA Trend",
        }
    )
    long_form["Amount"] = pd.to_numeric(long_form["Amount"])
    return long_form


def create_daily_ewma_chart(df: pd.DataFrame, span: int = 7) -> alt.Chart:
    """Create an interactive daily expenses versus EWMA trend chart."""

    required = {"date", "daily_expenses", "ewma_trend"}
    prepared = df if df is not None and required.issubset(df.columns) else prepare_daily_ewma_data(df, span=span)
    validation_error = validate_daily_ewma_data(prepared)
    if validation_error is not None:
        return _empty_chart(validation_error)

    long_form = prepare_daily_ewma_long_data(prepared)

    hover = alt.selection_point(fields=["date"], nearest=True, on="mouseover", clear="mouseout")

    lines = (
        alt.Chart(long_form)
        .mark_line(strokeWidth=2.5)
        .encode(
            x=alt.X("date:T", title="Date", axis=_date_axis(len(prepared))),
            y=alt.Y(
                "Amount:Q",
                title="Spend",
                scale=alt.Scale(zero=True),
                axis=_rupee_axis(),
            ),
            color=alt.Color(
                "Series:N",
                scale=alt.Scale(domain=["Daily Expenses", "EWMA Trend"], range=[BLUE, PURPLE]),
                legend=alt.Legend(title="Series", orient="bottom", labelColor=AXIS_LABEL_COLOR, titleColor=TITLE_COLOR),
            ),
            tooltip=[
                alt.Tooltip("date:T", title="Date", format="%d %b %Y"),
                alt.Tooltip("Series:N", title="Series"),
                alt.Tooltip("Amount:Q", title="Amount (₹)", format=",.2f"),
            ],
        )
    )

    points = (
        alt.Chart(long_form)
        .mark_point(filled=True, size=60)
        .encode(
            x="date:T",
            y="Amount:Q",
            color=alt.Color(
                "Series:N",
                scale=alt.Scale(domain=["Daily Expenses", "EWMA Trend"], range=[BLUE, PURPLE]),
                legend=None,
            ),
        )
    )

    rule = alt.Chart(prepared).mark_rule(color=AXIS_DOMAIN_COLOR).encode(x="date:T").transform_filter(hover)

    tooltip_points = (
        alt.Chart(prepared)
        .mark_point(opacity=0, size=120)
        .encode(
            x="date:T",
            y="ewma_trend:Q",
            tooltip=[
                alt.Tooltip("date:T", title="Date", format="%d %b %Y"),
                alt.Tooltip("daily_expenses:Q", title="Daily Expenses (₹)", format=",.2f"),
                alt.Tooltip("ewma_trend:Q", title="EWMA Trend (₹)", format=",.2f"),
            ],
        )
        .add_params(hover)
    )

    chart = (
        alt.layer(lines, points, rule, tooltip_points)
        .properties(title="Daily Expenses vs EWMA Trend", width=720, height=380)
    )
    return _apply_dark_theme(chart)


def _validate_radar_columns(radar_df: pd.DataFrame) -> None:
    """Raise a readable error if the radar frame is missing required data."""

    required_columns = {
        "date",
        "actual_cumulative",
        "forecast_cumulative",
        "upper_band",
        "lower_band",
        "budget_limit",
    }
    missing_columns = required_columns.difference(radar_df.columns)
    if missing_columns:
        missing_text = ", ".join(sorted(missing_columns))
        raise ValueError(f"Velocity radar data is missing required columns: {missing_text}")


def create_velocity_radar_chart(radar_df: pd.DataFrame, budget_limit: float) -> alt.Chart:
    """Create the focused forecast radar chart without forcing the budget into scale."""

    if radar_df is None or radar_df.empty:
        return _empty_chart("No velocity radar data available")

    _validate_radar_columns(radar_df)

    chart_data = radar_df.copy()
    chart_data["date"] = pd.to_datetime(chart_data["date"], errors="coerce")
    chart_data = chart_data.loc[chart_data["date"].notna()].sort_values("date")
    for column in [
        "actual_cumulative",
        "forecast_cumulative",
        "upper_band",
        "lower_band",
        "budget_limit",
    ]:
        chart_data[column] = pd.to_numeric(chart_data[column], errors="coerce")

    chart_data["actual_display"] = chart_data["actual_cumulative"].map(
        lambda value: "—" if pd.isna(value) else _format_currency(value)
    )
    chart_data["forecast_display"] = chart_data["forecast_cumulative"].map(
        lambda value: "—" if pd.isna(value) else _format_currency(value)
    )
    chart_data["lower_display"] = chart_data["lower_band"].map(
        lambda value: "—" if pd.isna(value) else _format_currency(value)
    )
    chart_data["upper_display"] = chart_data["upper_band"].map(
        lambda value: "—" if pd.isna(value) else _format_currency(value)
    )
    chart_data["budget_display"] = chart_data["budget_limit"].map(
        lambda value: "—" if pd.isna(value) else _format_currency(value)
    )
    chart_data["hover_value"] = chart_data["actual_cumulative"].combine_first(
        chart_data["forecast_cumulative"]
    )

    actual_data = chart_data.loc[chart_data["actual_cumulative"].notna()].copy()
    forecast_data = chart_data.loc[chart_data["forecast_cumulative"].notna()].copy()
    band_data = chart_data.loc[
        chart_data["lower_band"].notna() & chart_data["upper_band"].notna()
    ].copy()
    actual_data["series"] = "Actual"
    forecast_data["series"] = "Forecast"
    band_data["series"] = "Confidence Band"

    y_candidates = pd.concat(
        [
            actual_data[["actual_cumulative"]].rename(columns={"actual_cumulative": "value"}),
            forecast_data[["forecast_cumulative"]].rename(columns={"forecast_cumulative": "value"}),
            band_data[["upper_band"]].rename(columns={"upper_band": "value"}),
            band_data[["lower_band"]].rename(columns={"lower_band": "value"}),
        ],
        ignore_index=True,
    )
    numeric_candidates = pd.to_numeric(y_candidates["value"], errors="coerce").dropna()
    focus_max = float(numeric_candidates.max()) if not numeric_candidates.empty else 0.0
    focus_max = max(focus_max, 1.0)
    budget_value = max(float(budget_limit), 0.0)
    budget_visible = budget_value <= focus_max * 1.5
    chart_y_max = focus_max * 1.15
    if budget_visible:
        chart_y_max = max(chart_y_max, budget_value * 1.08, 1.0)

    hover = alt.selection_point(fields=["date"], nearest=True, on="mouseover", clear="mouseout")
    series_domain = ["Actual", "Forecast", "Confidence Band"]
    series_range = [CYAN, AMBER, PURPLE]
    if budget_visible:
        series_domain.append("Budget Limit")
        series_range.append(RED)
    legend = alt.Legend(
        title="Series",
        orient="bottom",
        direction="horizontal",
        labelColor=AXIS_LABEL_COLOR,
        titleColor=TITLE_COLOR,
    )

    confidence_band = (
        alt.Chart(band_data)
        .mark_area(opacity=0.18)
        .encode(
            x=alt.X("date:T", title="Date", axis=_date_axis(len(chart_data))),
            y=alt.Y(
                "lower_band:Q",
                title="Spend",
                scale=alt.Scale(domain=[0, chart_y_max]),
                axis=_rupee_axis(),
            ),
            y2="upper_band:Q",
            color=alt.Color(
                "series:N",
                scale=alt.Scale(domain=series_domain, range=series_range),
                legend=legend,
            ),
            tooltip=[
                alt.Tooltip("date:T", title="Date", format="%d %b %Y"),
                alt.Tooltip("lower_band:Q", title="Lower Band (₹)", format=",.2f"),
                alt.Tooltip("upper_band:Q", title="Upper Band (₹)", format=",.2f"),
            ],
        )
    )

    actual_line = (
        alt.Chart(actual_data)
        .mark_line(strokeWidth=3)
        .encode(
            x=alt.X("date:T", title="Date", axis=_date_axis(len(chart_data))),
            y=alt.Y(
                "actual_cumulative:Q",
                title="Spend",
                scale=alt.Scale(domain=[0, chart_y_max]),
                axis=_rupee_axis(),
            ),
            color=alt.Color(
                "series:N",
                scale=alt.Scale(domain=series_domain, range=series_range),
                legend=legend,
            ),
            tooltip=[
                alt.Tooltip("date:T", title="Date", format="%d %b %Y"),
                alt.Tooltip("actual_cumulative:Q", title="Actual Spending (₹)", format=",.2f"),
            ],
        )
    )

    forecast_line = (
        alt.Chart(forecast_data)
        .mark_line(strokeWidth=3, strokeDash=[8, 5])
        .encode(
            x=alt.X("date:T", title="Date", axis=_date_axis(len(chart_data))),
            y=alt.Y(
                "forecast_cumulative:Q",
                title="Spend",
                scale=alt.Scale(domain=[0, chart_y_max]),
                axis=_rupee_axis(),
            ),
            color=alt.Color(
                "series:N",
                scale=alt.Scale(domain=series_domain, range=series_range),
                legend=legend,
            ),
            tooltip=[
                alt.Tooltip("date:T", title="Date", format="%d %b %Y"),
                alt.Tooltip("forecast_cumulative:Q", title="Forecast (₹)", format=",.2f"),
            ],
        )
    )

    budget_data = pd.DataFrame(
        {
            "budget_limit": [budget_value],
            "budget_display": [_format_currency(budget_value)],
            "series": ["Budget Limit"],
        }
    )
    budget_rule = (
        alt.Chart(budget_data)
        .mark_rule(strokeWidth=2.5)
        .encode(
            y=alt.Y(
                "budget_limit:Q",
                title="Spend",
                scale=alt.Scale(domain=[0, chart_y_max]),
                axis=_rupee_axis(),
            ),
            color=alt.Color(
                "series:N",
                scale=alt.Scale(domain=series_domain, range=series_range),
                legend=legend,
            ),
            tooltip=[alt.Tooltip("budget_limit:Q", title="Budget Limit (₹)", format=",.2f")],
        )
        if budget_visible
        else None
    )

    hover_points = (
        alt.Chart(chart_data)
        .mark_point(opacity=0, size=120)
        .encode(
            x=alt.X("date:T", title="Date", axis=_date_axis(len(chart_data))),
            y=alt.Y(
                "hover_value:Q",
                title="Spend",
                scale=alt.Scale(domain=[0, chart_y_max]),
                axis=_rupee_axis(),
            ),
            tooltip=[
                alt.Tooltip("date:T", title="Date", format="%d %b %Y"),
                alt.Tooltip("actual_cumulative:Q", title="Actual Spending (₹)", format=",.2f"),
                alt.Tooltip("forecast_cumulative:Q", title="Forecast (₹)", format=",.2f"),
                alt.Tooltip("lower_band:Q", title="Lower Band (₹)", format=",.2f"),
                alt.Tooltip("upper_band:Q", title="Upper Band (₹)", format=",.2f"),
                alt.Tooltip("budget_limit:Q", title="Budget Limit (₹)", format=",.2f"),
            ],
        )
        .add_params(hover)
    )

    hover_rule = (
        alt.Chart(chart_data)
        .mark_rule(color=AXIS_DOMAIN_COLOR)
        .encode(x="date:T")
        .transform_filter(hover)
    )

    layers: list[alt.Chart] = [confidence_band, actual_line, forecast_line, hover_points, hover_rule]
    if budget_rule is not None:
        layers.insert(1, budget_rule)

    chart = alt.layer(*layers).properties(title="Spending Forecast", width=720, height=380)
    return _apply_dark_theme(chart)


def create_forecast_budget_chart(current_spend: float, forecast_spend: float, budget_limit: float) -> alt.Chart:
    """Create a horizontal chart that compares current spend, forecast and budget."""

    comparison_df = pd.DataFrame(
        [
            {"measure": "Current Spend", "value": max(float(current_spend), 0.0)},
            {"measure": "Forecast Month End", "value": max(float(forecast_spend), 0.0)},
            {"measure": "Budget Limit", "value": max(float(budget_limit), 0.0)},
        ]
    )
    comparison_df["value_display"] = comparison_df["value"].apply(_format_currency)
    x_domain = max(float(comparison_df["value"].max()), 1.0) * 1.22

    bars = (
        alt.Chart(comparison_df)
        .mark_bar(size=26, cornerRadiusEnd=5)
        .encode(
            y=alt.Y(
                "measure:N",
                sort=["Current Spend", "Forecast Month End", "Budget Limit"],
                title=None,
                axis=alt.Axis(labelColor=AXIS_LABEL_COLOR, titleColor=TITLE_COLOR),
            ),
            x=alt.X(
                "value:Q",
                scale=alt.Scale(domain=[0, x_domain]),
                title="Amount (₹)",
                axis=_rupee_axis(),
            ),
            color=alt.Color("measure:N", scale=alt.Scale(domain=["Current Spend", "Forecast Month End", "Budget Limit"], range=[BLUE, AMBER, RED]), legend=None),
            tooltip=[
                alt.Tooltip("measure:N", title="Measure"),
                alt.Tooltip("value:Q", title="Amount (₹)", format=",.2f"),
            ],
        )
    )

    labels = (
        alt.Chart(comparison_df)
        .mark_text(color=TITLE_COLOR, align="left", dx=6, fontWeight="bold")
        .encode(
            y=alt.Y("measure:N", sort=["Current Spend", "Forecast Month End", "Budget Limit"]),
            x="value:Q",
            text=alt.Text("value_display:N"),
        )
    )

    chart = alt.layer(bars, labels).properties(title="Forecast vs Budget", width=720, height=260)
    return _apply_dark_theme(chart)
