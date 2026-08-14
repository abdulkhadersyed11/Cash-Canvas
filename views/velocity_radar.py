"""Display helpers for the Velocity Radar view."""

from __future__ import annotations

import pandas as pd


FORECAST_TABLE_COLUMNS = {
    "date",
    "actual_cumulative",
    "forecast_cumulative",
    "lower_band",
    "upper_band",
    "budget_limit",
}


def prepare_forecast_table(radar_df: pd.DataFrame) -> pd.DataFrame:
    """Return the exact chart values with judge-friendly column names."""

    missing = FORECAST_TABLE_COLUMNS.difference(radar_df.columns)
    if missing:
        missing_text = ", ".join(sorted(missing))
        raise ValueError(f"Velocity radar table is missing required columns: {missing_text}")

    table = radar_df[
        [
            "date",
            "actual_cumulative",
            "forecast_cumulative",
            "lower_band",
            "upper_band",
            "budget_limit",
        ]
    ].copy()
    table = table.rename(
        columns={
            "date": "Date",
            "actual_cumulative": "Actual Spending",
            "forecast_cumulative": "Forecast",
            "lower_band": "Lower Band",
            "upper_band": "Upper Band",
            "budget_limit": "Budget Limit",
        }
    )
    table["Date"] = pd.to_datetime(table["Date"], errors="coerce").dt.strftime("%d %b %Y")
    return table
