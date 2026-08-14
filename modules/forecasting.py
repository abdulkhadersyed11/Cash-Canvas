"""Forecasting helpers for the CashCanvas spending velocity radar."""

from __future__ import annotations

import numpy as np
import pandas as pd


def _empty_category_trend_frame() -> pd.DataFrame:
    """Return the empty result shape for category trend summaries."""

    return pd.DataFrame(
        columns=["category", "latest_ewma", "pct_change", "trend_label", "trend_arrow"]
    )


def compute_velocity_radar(
    df: pd.DataFrame,
    budget_limit: float,
    span: int = 5,
    month_year: str | None = None,
    user_id: int | None = None,
    category: str | None = None,
):
    """Project month-end spending from the latest daily EWMA burn rate.

    Parameters
    ----------
    df:
        Transaction rows containing at least ``txn_date`` and ``amount``.
    budget_limit:
        Monthly budget ceiling copied unchanged to every output row.
    span:
        EWMA span used to estimate the recency-weighted burn rate.
    month_year:
        Selected month in ``YYYY-MM`` format.
    user_id, category:
        Optional safety filters for mixed imported or test data.

    Returns
    -------
    tuple[pd.DataFrame, bool]
        A DataFrame with the per-day projection columns and a boolean flag that
        indicates whether the month-end forecast exceeds the budget.
    """

    columns = [
        "date",
        "actual_cumulative",
        "forecast_cumulative",
        "upper_band",
        "lower_band",
        "budget_limit",
        "daily_spend",
        "daily_ewma",
        "future_day_number",
        "forecast_daily_rate",
        "daily_standard_deviation",
        "as_of_date",
    ]

    if span < 1:
        raise ValueError("EWMA span must be at least 1.")

    frame = pd.DataFrame() if df is None else df.copy()
    if not frame.empty:
        missing = {"txn_date", "amount"}.difference(frame.columns)
        if missing:
            missing_text = ", ".join(sorted(missing))
            raise ValueError(f"Forecast data is missing required columns: {missing_text}")

        frame["txn_date"] = pd.to_datetime(frame["txn_date"], errors="coerce")
        frame["amount"] = pd.to_numeric(frame["amount"], errors="coerce")
        frame = frame.loc[frame["txn_date"].notna() & frame["amount"].notna()].copy()
        # CashCanvas stores expenses; negative imports must not reduce the total.
        frame["amount"] = frame["amount"].clip(lower=0.0)

        if user_id is not None:
            if "user_id" not in frame.columns:
                raise ValueError("Forecast data needs a user_id column when user_id is provided.")
            frame = frame.loc[frame["user_id"] == user_id].copy()

        if category is not None:
            if "category" not in frame.columns:
                raise ValueError("Forecast data needs a category column when category is provided.")
            frame = frame.loc[frame["category"] == category].copy()

    if month_year is not None:
        selected_period = pd.Period(month_year, freq="M")
    elif not frame.empty:
        selected_period = frame["txn_date"].min().to_period("M")
    else:
        return pd.DataFrame(columns=columns), False

    month_start = selected_period.start_time.normalize()
    month_end = selected_period.end_time.normalize()
    today = pd.Timestamp.today().normalize()
    current_period = today.to_period("M")

    # A future budget month has no historical burn rate yet. Returning an empty
    # result avoids inventing a forecast before that month begins.
    if selected_period > current_period:
        empty_result = pd.DataFrame(columns=columns)
        empty_result.attrs["future_month"] = True
        empty_result.attrs["month_year"] = str(selected_period)
        return empty_result, False

    # Current months stop at today; completed months stop at their real month end.
    as_of_date = today if selected_period == current_period else month_end
    as_of_date = min(as_of_date, month_end)

    calendar_days = pd.date_range(month_start, month_end, freq="D")
    historical_days = pd.date_range(month_start, as_of_date, freq="D")

    if frame.empty:
        daily_spend = pd.Series(0.0, index=historical_days, dtype=float)
    else:
        frame["calendar_date"] = frame["txn_date"].dt.normalize()
        month_mask = frame["txn_date"].dt.to_period("M") == selected_period
        historical_mask = frame["calendar_date"] <= as_of_date
        selected_rows = frame.loc[month_mask & historical_mask].copy()

        if selected_rows.empty:
            daily_spend = pd.Series(0.0, index=historical_days, dtype=float)
        else:
            daily_spend = (
                selected_rows.groupby("calendar_date")["amount"].sum().sort_index()
            )
            daily_spend = daily_spend.reindex(historical_days, fill_value=0.0)

    # Missing historical dates are real zero-spend days and therefore take part
    # in the EWMA. Future dates are deliberately not added to this series.
    daily_ewma = daily_spend.ewm(span=span, adjust=False).mean()
    valid_ewma = daily_ewma.dropna()
    latest_ewma_rate = float(valid_ewma.iloc[-1]) if not valid_ewma.empty else 0.0
    latest_ewma_rate = max(latest_ewma_rate, 0.0)

    actual_history = daily_spend.cumsum().cummax().clip(lower=0.0)
    current_cumulative = float(actual_history.iloc[-1]) if not actual_history.empty else 0.0

    daily_standard_deviation = float(daily_spend.std(ddof=0)) if not daily_spend.empty else 0.0
    if not np.isfinite(daily_standard_deviation):
        daily_standard_deviation = 0.0

    actual_cumulative = pd.Series(np.nan, index=calendar_days, dtype=float)
    actual_cumulative.loc[historical_days] = actual_history.values

    daily_spend_output = pd.Series(np.nan, index=calendar_days, dtype=float)
    daily_spend_output.loc[historical_days] = daily_spend.values
    daily_ewma_output = pd.Series(np.nan, index=calendar_days, dtype=float)
    daily_ewma_output.loc[historical_days] = daily_ewma.values

    forecast_cumulative = pd.Series(np.nan, index=calendar_days, dtype=float)
    upper_band = pd.Series(np.nan, index=calendar_days, dtype=float)
    lower_band = pd.Series(np.nan, index=calendar_days, dtype=float)
    future_day_number = pd.Series(np.nan, index=calendar_days, dtype=float)
    forecast_daily_rate = pd.Series(np.nan, index=calendar_days, dtype=float)

    forecast_days = pd.date_range(as_of_date, month_end, freq="D")
    day_numbers = np.arange(len(forecast_days), dtype=float)

    # Day zero is the as-of date. Every future point extends from the same
    # current cumulative anchor, which makes the path monotonic and explainable.
    projected_values = current_cumulative + (latest_ewma_rate * day_numbers)
    projected_values = np.maximum.accumulate(np.maximum(projected_values, current_cumulative))
    uncertainty = daily_standard_deviation * np.sqrt(day_numbers)
    upper_values = np.maximum(projected_values + uncertainty, projected_values)
    lower_values = np.maximum(projected_values - uncertainty, current_cumulative)
    lower_values = np.maximum(lower_values, 0.0)
    lower_values = np.minimum(lower_values, projected_values)

    forecast_cumulative.loc[forecast_days] = projected_values
    upper_band.loc[forecast_days] = upper_values
    lower_band.loc[forecast_days] = lower_values
    future_day_number.loc[forecast_days] = day_numbers
    forecast_daily_rate.loc[forecast_days] = latest_ewma_rate

    normalized_budget = max(float(budget_limit), 0.0)

    result = pd.DataFrame(
        {
            "date": calendar_days,
            "actual_cumulative": actual_cumulative.values,
            "forecast_cumulative": forecast_cumulative.values,
            "upper_band": upper_band.values,
            "lower_band": lower_band.values,
            "budget_limit": normalized_budget,
            "daily_spend": daily_spend_output.values,
            "daily_ewma": daily_ewma_output.values,
            "future_day_number": future_day_number.values,
            "forecast_daily_rate": forecast_daily_rate.values,
            "daily_standard_deviation": daily_standard_deviation,
            "as_of_date": as_of_date,
        }
    )

    forecast_at_month_end = float(result["forecast_cumulative"].dropna().iloc[-1])
    remaining_days = int((month_end - as_of_date).days)
    result.attrs.update(
        {
            "month_year": str(selected_period),
            "month_start": month_start,
            "month_end": month_end,
            "as_of_date": as_of_date,
            "remaining_days": remaining_days,
            "latest_ewma_rate": latest_ewma_rate,
            "base_latest_ewma_rate": latest_ewma_rate,
            "current_cumulative": current_cumulative,
            "daily_standard_deviation": daily_standard_deviation,
            "forecast_at_month_end": forecast_at_month_end,
            "budget_limit": normalized_budget,
        }
    )

    will_overspend = bool(forecast_at_month_end > normalized_budget)

    return result, will_overspend


def compute_category_trends(df: pd.DataFrame, span: int = 5, lookback_days: int = 14):
    """Summarize recent spending trends for each category.

    The function looks back over a fixed day window, fills missing days with zero
    spend, smooths each category with EWMA, and then compares the recent half of
    the window against the earlier half.
    """

    if df is None or df.empty:
        return _empty_category_trend_frame()

    frame = df.copy()
    frame["txn_date"] = pd.to_datetime(frame["txn_date"])

    today = pd.Timestamp.today().normalize()
    end_date = today
    start_date = end_date - pd.Timedelta(days=lookback_days - 1)
    date_index = pd.date_range(start_date, end_date, freq="D")

    results = []
    half_window = max(1, lookback_days // 2)

    # Work one category at a time so the trend label reflects that category's own burn pattern.
    for category, category_frame in frame.groupby("category"):
        # Roll the category's transactions into a daily series and fill missing days with zero.
        daily_series = (
            category_frame.groupby(category_frame["txn_date"].dt.normalize())["amount"]
            .sum()
            .reindex(date_index, fill_value=0.0)
            .sort_index()
        )

        if daily_series.empty:
            continue

        # EWMA gives more weight to the most recent days, which makes it useful for spotting momentum.
        ewma_series = daily_series.ewm(span=span, adjust=False).mean()

        recent_half = ewma_series.iloc[-half_window:]
        earlier_half = ewma_series.iloc[: len(ewma_series) - len(recent_half)]

        latest_ewma = float(ewma_series.iloc[-1])
        recent_mean = float(recent_half.mean()) if not recent_half.empty else 0.0
        earlier_mean = float(earlier_half.mean()) if not earlier_half.empty else 0.0

        # Percentage change compares the recent average momentum against the earlier average momentum.
        if earlier_mean == 0:
            pct_change = 0.0 if recent_mean == 0 else 100.0
        else:
            pct_change = ((recent_mean - earlier_mean) / abs(earlier_mean)) * 100.0

        # Convert the percentage change into a label that is easy to explain in the UI.
        if pct_change > 25:
            trend_label = "Rapid increase"
            trend_arrow = "↑↑"
        elif pct_change > 5:
            trend_label = "Increasing"
            trend_arrow = "↑"
        elif pct_change < -5:
            trend_label = "Decreasing"
            trend_arrow = "↓"
        else:
            trend_label = "Stable"
            trend_arrow = "→"

        results.append(
            {
                "category": category,
                "latest_ewma": latest_ewma,
                "pct_change": pct_change,
                "trend_label": trend_label,
                "trend_arrow": trend_arrow,
            }
        )

    if not results:
        return _empty_category_trend_frame()

    return (
        pd.DataFrame(results)
        .sort_values("pct_change", ascending=False)
        .reset_index(drop=True)
    )


def generate_trend_insight(df: pd.DataFrame, window: int = 10, threshold_pct: int = 15):
    """Generate a short natural-language insight about overall spending momentum.

    The function compares the EWMA-smoothed spending average in the most recent
    window against the EWMA-smoothed average in the previous window.
    """

    if df is None or df.empty:
        message = "Your spending has been steady over the recent period."
        return message, 0.0, "stable"

    frame = df.copy()
    frame["txn_date"] = pd.to_datetime(frame["txn_date"])

    today = pd.Timestamp.today().normalize()
    end_date = today
    start_date = end_date - pd.Timedelta(days=(window * 2) - 1)
    date_index = pd.date_range(start_date, end_date, freq="D")

    # Collapse all categories into one daily total so the insight reflects whole-account spending.
    daily_spend = (
        frame.groupby(frame["txn_date"].dt.normalize())["amount"]
        .sum()
        .reindex(date_index, fill_value=0.0)
        .sort_index()
    )

    # EWMA emphasizes recent days more heavily than older days, which makes the trend responsive.
    ewma_series = daily_spend.ewm(span=window, adjust=False).mean()

    recent_window = ewma_series.iloc[-window:]
    previous_window = ewma_series.iloc[:-window]

    recent_mean = float(recent_window.mean()) if not recent_window.empty else 0.0
    previous_mean = float(previous_window.mean()) if not previous_window.empty else 0.0

    # Compute the relative change between the two halves of the lookback window.
    if previous_mean == 0:
        pct_change = 0.0 if recent_mean == 0 else 100.0
    else:
        pct_change = ((recent_mean - previous_mean) / abs(previous_mean)) * 100.0

    if pct_change >= threshold_pct:
        message = (
            f"Your spending trend has increased by {pct_change:.0f}% over the last {window} days. "
            "Consider reducing discretionary expenses to stay within your monthly budget."
        )
        trend_direction = "up"
    elif pct_change <= -threshold_pct:
        message = (
            f"Good progress: your spending trend has decreased by {abs(pct_change):.0f}% over the last "
            f"{window} days."
        )
        trend_direction = "down"
    else:
        message = "Your spending has been steady over the recent period."
        trend_direction = "stable"

    return message, pct_change, trend_direction
