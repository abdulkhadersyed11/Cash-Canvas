import streamlit as st
import pandas as pd
import numpy as np
from modules.forecasting import calculate_ewma_burn_rate, generate_velocity_forecast
from modules.altair_charts import build_velocity_radar_chart
from database.db_operations import get_user_yearly_budgets, get_yearly_category_budgets


def prepare_forecast_table(
    df: pd.DataFrame = None,
    monthly_budget: float = 0.0,
    days_in_month: int = 30,
    *args,
    **kwargs
) -> pd.DataFrame:
    """
    Prepares the forecast calculation table for app.py.
    Provides all standard display aliases to satisfy formatting loops.
    """
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame()

    table = df.copy()

    if "forecast_cumulative" not in table.columns and "projected_spend" not in table.columns:
        b = monthly_budget or kwargs.get("budget_limit", 0.0)
        d = days_in_month or kwargs.get("days_in_month", 30)
        table = generate_velocity_forecast(table, b, d)

    act_val = table["actual_cumulative"] if "actual_cumulative" in table.columns else (
        table["actual_spend"] if "actual_spend" in table.columns else np.nan
    )
    proj_val = table["forecast_cumulative"] if "forecast_cumulative" in table.columns else (
        table["projected_spend"] if "projected_spend" in table.columns else 0.0
    )
    pace_val = table["ideal_pace"] if "ideal_pace" in table.columns else 0.0
    budget_val = table["budget_limit"] if "budget_limit" in table.columns else 0.0
    lower_val = table["lower_band"] if "lower_band" in table.columns else 0.0
    upper_val = table["upper_band"] if "upper_band" in table.columns else 0.0

    if "date" in table.columns:
        table["Date"] = pd.to_datetime(table["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    if "day" in table.columns:
        table["Day"] = table["day"]

    # 1. Actuals Aliases
    table["Actual Spending"] = act_val
    table["Actual Spend"] = act_val
    table["Actual"] = act_val
    table["Actual Cumulative"] = act_val

    # 2. Forecast Aliases
    table["Forecast"] = proj_val
    table["Forecast Spending"] = proj_val
    table["Forecast Spend"] = proj_val
    table["Forecast Cumulative"] = proj_val
    table["Projected"] = proj_val
    table["Projected Spending"] = proj_val
    table["Projected Spend"] = proj_val

    # 3. Budget & Pace Aliases
    table["Ideal Pace"] = pace_val
    table["Budget Pace"] = pace_val
    table["Pace"] = pace_val
    table["Budget Limit"] = budget_val
    table["Budget"] = budget_val

    # 4. Confidence Band Aliases
    table["Lower Band"] = lower_val
    table["Lower Bound"] = lower_val
    table["Upper Band"] = upper_val
    table["Upper Bound"] = upper_val

    # 5. Variance Aliases
    table["Variance"] = proj_val - budget_val
    table["Difference"] = table["Variance"]

    return table


def render_velocity_radar_view(user_id: int, all_user_transactions: pd.DataFrame):
    """Renders the standalone Velocity Radar view."""
    st.header("⚡ Spending Velocity Radar")
    st.caption("Proactive burn rate forecasting with Exponentially Weighted Moving Averages (EWMA).")

    if all_user_transactions is None or all_user_transactions.empty:
        st.info("No transactions available. Upload a statement in the 'Statement Importer' first.")
        return

    df = all_user_transactions.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]

    if "txn_date" in df.columns and "date" not in df.columns:
        df["date"] = df["txn_date"]

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
    df = df.dropna(subset=["date", "amount"])
    df["year_month"] = df["date"].dt.to_period("M").astype(str)

    available_months = sorted(df["year_month"].unique(), reverse=True)
    if not available_months:
        st.warning("No valid transaction dates found.")
        return

    selected_month = st.selectbox("📅 Select Month to Analyze", available_months, index=0)
    month_year = selected_month.split("-")[0]

    yearly_budgets = get_user_yearly_budgets(user_id)
    monthly_budget = yearly_budgets.get(month_year, 0.0)

    if monthly_budget <= 0:
        st.warning(
            f"⚠️ No budget limit defined for {month_year}. "
            f"Please go to **Statement Importer**, select {month_year}, and configure category targets."
        )
        return

    month_data = df[df["year_month"] == selected_month].sort_values("date")
    total_spent = month_data["amount"].sum()
    days_in_month = pd.Period(selected_month).days_in_month

    forecast_df = generate_velocity_forecast(month_data, monthly_budget, days_in_month)

    m1, m2, m3 = st.columns(3)
    m1.metric("Total Spent", f"₹{total_spent:,.2f}")
    m2.metric(f"{month_year} Monthly Budget", f"₹{monthly_budget:,.2f}")
    m3.metric("Projected Month-End Spend", f"₹{forecast_df['projected_spend'].iloc[-1]:,.2f}")

    radar_chart = build_velocity_radar_chart(forecast_df, monthly_budget)
    st.altair_chart(radar_chart, use_container_width=True)