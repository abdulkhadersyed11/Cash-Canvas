"""What-if simulation helpers for the CashCanvas velocity radar."""

from __future__ import annotations

import pandas as pd


def simulate_whatif(radar_df: pd.DataFrame, adjustment_pct: float):
    """Adjust the forecast portion of a velocity radar projection.

    Parameters
    ----------
    radar_df:
        Output from ``compute_velocity_radar`` with the standard radar columns.
    adjustment_pct:
        Percentage slider adjustment applied only to the future burn rate.

    Returns
    -------
    pd.DataFrame
        A copy of the radar table with updated forecast and confidence-band
        values for the remaining days of the month.
    """

    if radar_df is None or radar_df.empty:
        return pd.DataFrame(
            columns=[
                "date",
                "actual_cumulative",
                "forecast_cumulative",
                "upper_band",
                "lower_band",
                "budget_limit",
            ]
        )

    frame = radar_df.copy(deep=True)
    frame["date"] = pd.to_datetime(frame["date"])
    adjusted_frame = frame.copy(deep=True)
    adjusted_frame.attrs = radar_df.attrs.copy()

    required_columns = {
        "date",
        "actual_cumulative",
        "forecast_cumulative",
        "upper_band",
        "lower_band",
        "budget_limit",
    }
    missing_columns = required_columns.difference(adjusted_frame.columns)
    if missing_columns:
        missing_text = ", ".join(sorted(missing_columns))
        raise ValueError(f"What-if data is missing required columns: {missing_text}")

    actual_rows = adjusted_frame.loc[adjusted_frame["actual_cumulative"].notna()].copy()
    forecast_rows = adjusted_frame.loc[adjusted_frame["forecast_cumulative"].notna()].copy()
    if actual_rows.empty or forecast_rows.empty:
        return adjusted_frame

    as_of_date = pd.Timestamp(
        adjusted_frame.attrs.get("as_of_date", actual_rows["date"].max())
    ).normalize()
    current_cumulative = float(
        adjusted_frame.attrs.get("current_cumulative", actual_rows["actual_cumulative"].iloc[-1])
    )

    future_mask = (
        (adjusted_frame["date"] > as_of_date)
        & adjusted_frame["forecast_cumulative"].notna()
    )
    if not future_mask.any():
        return adjusted_frame

    if "future_day_number" in adjusted_frame.columns:
        day_numbers = pd.to_numeric(
            adjusted_frame.loc[future_mask, "future_day_number"], errors="coerce"
        ).fillna(0.0)
    else:
        day_numbers = (adjusted_frame.loc[future_mask, "date"] - as_of_date).dt.days.astype(float)

    base_rate = float(
        adjusted_frame.attrs.get(
            "base_latest_ewma_rate",
            adjusted_frame.attrs.get("latest_ewma_rate", 0.0),
        )
    )
    if base_rate == 0.0 and "forecast_daily_rate" in adjusted_frame.columns:
        valid_rates = pd.to_numeric(
            adjusted_frame["forecast_daily_rate"], errors="coerce"
        ).dropna()
        if not valid_rates.empty:
            base_rate = float(valid_rates.iloc[0])

    adjusted_rate = max(0.0, base_rate * (1.0 + float(adjustment_pct) / 100.0))
    daily_standard_deviation = max(
        0.0,
        float(adjusted_frame.attrs.get("daily_standard_deviation", 0.0)),
    )

    adjusted_forecast = current_cumulative + (adjusted_rate * day_numbers)
    adjusted_forecast = adjusted_forecast.clip(lower=current_cumulative)

    # Recalculate the corridor around the adjusted path using the same historical
    # daily volatility. Recorded actual values are never touched.
    uncertainty = daily_standard_deviation * day_numbers.pow(0.5)
    adjusted_upper = (adjusted_forecast + uncertainty).clip(lower=adjusted_forecast)
    adjusted_lower = (adjusted_forecast - uncertainty).clip(lower=current_cumulative)
    adjusted_lower = adjusted_lower.clip(lower=0.0, upper=adjusted_forecast)

    adjusted_frame.loc[future_mask, "forecast_cumulative"] = adjusted_forecast.values
    adjusted_frame.loc[future_mask, "upper_band"] = adjusted_upper.values
    adjusted_frame.loc[future_mask, "lower_band"] = adjusted_lower.values
    if "forecast_daily_rate" in adjusted_frame.columns:
        forecast_mask = adjusted_frame["forecast_cumulative"].notna()
        adjusted_frame.loc[forecast_mask, "forecast_daily_rate"] = adjusted_rate

    forecast_at_month_end = float(adjusted_frame["forecast_cumulative"].dropna().iloc[-1])
    adjusted_frame.attrs.update(
        {
            "as_of_date": as_of_date,
            "latest_ewma_rate": adjusted_rate,
            "base_latest_ewma_rate": base_rate,
            "current_cumulative": current_cumulative,
            "forecast_at_month_end": forecast_at_month_end,
            "adjustment_percentage": float(adjustment_pct),
        }
    )

    return adjusted_frame
