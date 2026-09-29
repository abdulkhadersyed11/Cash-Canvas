import pandas as pd
import numpy as np


def calculate_ewma_burn_rate(df: pd.DataFrame, days_in_month: int = 30, span: int = 7) -> float:
    """Calculates recent daily burn rate using Exponentially Weighted Moving Average (EWMA)."""
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return 0.0

    df_clean = df.copy()
    df_clean.columns = [str(c).strip().lower() for c in df_clean.columns]

    if "amount" not in df_clean.columns:
        return 0.0

    date_col = "txn_date" if "txn_date" in df_clean.columns else ("date" if "date" in df_clean.columns else None)

    if date_col:
        df_clean["parsed_date"] = pd.to_datetime(df_clean[date_col], errors="coerce")
        df_clean = df_clean.dropna(subset=["parsed_date", "amount"])
        if df_clean.empty:
            return 0.0
        daily_spend = df_clean.groupby(df_clean["parsed_date"].dt.day)["amount"].sum()
    else:
        daily_spend = pd.to_numeric(df_clean["amount"], errors="coerce").dropna()

    if daily_spend.empty:
        return 0.0

    ewma_series = daily_spend.ewm(span=span, adjust=False).mean()
    current_burn_rate = float(ewma_series.iloc[-1]) if not ewma_series.empty else 0.0
    return max(0.0, current_burn_rate)


def generate_velocity_forecast(df: pd.DataFrame, monthly_budget: float = 0.0, days_in_month: int = 30) -> pd.DataFrame:
    """
    Generates a day-by-day projected trajectory.
    Guarantees valid Timestamp objects so .normalize() never encounters NaT,
    even when a category has 0 transactions (e.g. Travel).
    """
    if days_in_month <= 0:
        days_in_month = 30

    monthly_budget = float(monthly_budget) if monthly_budget else 0.0
    daily_budget_pace = (monthly_budget / days_in_month) if days_in_month > 0 else 0.0

    # Determine reference year and month
    ref_year, ref_month = None, None
    df_clean = pd.DataFrame()

    if df is not None and isinstance(df, pd.DataFrame) and not df.empty:
        df_clean = df.copy()
        df_clean.columns = [str(c).strip().lower() for c in df_clean.columns]
        date_col = "txn_date" if "txn_date" in df_clean.columns else ("date" if "date" in df_clean.columns else None)

        if date_col and "amount" in df_clean.columns:
            df_clean["parsed_date"] = pd.to_datetime(df_clean[date_col], errors="coerce")
            valid_dates = df_clean["parsed_date"].dropna()
            if not valid_dates.empty:
                ref_year = int(valid_dates.iloc[-1].year)
                ref_month = int(valid_dates.iloc[-1].month)

    now = pd.Timestamp.now()
    if ref_year is None or ref_month is None:
        ref_year, ref_month = now.year, now.month

    # Determine last active day for actuals
    daily_totals = pd.Series(0.0, index=range(1, days_in_month + 1))
    has_real_txns = False

    if not df_clean.empty and "parsed_date" in df_clean.columns and "amount" in df_clean.columns:
        df_clean["amount"] = pd.to_numeric(df_clean["amount"], errors="coerce").fillna(0.0)
        df_clean["day"] = df_clean["parsed_date"].dt.day
        recorded = df_clean.groupby("day")["amount"].sum()
        for d, amt in recorded.items():
            if 1 <= d <= days_in_month:
                daily_totals[d] = amt
                has_real_txns = True

    if has_real_txns:
        non_zero_days = daily_totals[daily_totals > 0].index
        last_active_day = int(non_zero_days.max()) if len(non_zero_days) > 0 else 1
    else:
        # For zero-transaction categories, anchor to current day of month or day 1
        if ref_year == now.year and ref_month == now.month:
            last_active_day = min(int(now.day), days_in_month)
        else:
            last_active_day = days_in_month

    cumulative_actual = daily_totals.cumsum()
    current_spent = float(cumulative_actual.loc[last_active_day])
    burn_rate = calculate_ewma_burn_rate(df_clean, days_in_month)

    forecast_records = []
    for day in range(1, days_in_month + 1):
        try:
            row_date = pd.Timestamp(year=ref_year, month=ref_month, day=day)
        except ValueError:
            row_date = pd.Timestamp(year=ref_year, month=ref_month, day=1) + pd.Timedelta(days=day - 1)

        budget_line = daily_budget_pace * day

        if day <= last_active_day:
            actual_val = float(cumulative_actual.loc[day])
            projected_val = actual_val
            lower_b = actual_val
            upper_b = actual_val
        else:
            remaining_days = day - last_active_day
            actual_val = np.nan
            projected_val = current_spent + (burn_rate * remaining_days)
            margin = burn_rate * 0.15 * (remaining_days ** 0.5)
            lower_b = max(0.0, projected_val - margin)
            upper_b = projected_val + margin

        forecast_records.append({
            "date": row_date,
            "day": day,
            "actual_spend": actual_val,
            "projected_spend": projected_val,
            "actual_cumulative": actual_val,
            "forecast_cumulative": projected_val,
            "lower_band": round(lower_b, 2),
            "upper_band": round(upper_b, 2),
            "budget_limit": monthly_budget,
            "ideal_pace": budget_line,
        })

    res_df = pd.DataFrame(forecast_records)
    res_df["date"] = pd.to_datetime(res_df["date"])
    return res_df


def compute_velocity_radar(df: pd.DataFrame = None, *args, **kwargs):
    """Computes velocity trajectory and summary dictionary compatible with what-if callers."""
    data = df if df is not None else kwargs.get("filtered_transactions", kwargs.get("transactions", pd.DataFrame()))
    if data is None or not isinstance(data, pd.DataFrame):
        data = pd.DataFrame()

    budget = kwargs.get("budget_limit", kwargs.get("monthly_budget", kwargs.get("budget", 0.0)))
    if not budget and len(args) > 0 and isinstance(args[0], (int, float)):
        budget = args[0]
    elif not budget and len(args) > 1 and isinstance(args[1], (int, float)):
        budget = args[1]
    budget = float(budget) if budget else 0.0

    days_in_month = kwargs.get("days_in_month", 30)
    category = kwargs.get("category", None)

    if not data.empty and category and str(category).strip().lower() != "all":
        col_to_check = None
        for c in data.columns:
            if str(c).lower() == "category":
                col_to_check = c
                break
        if col_to_check:
            data = data[data[col_to_check].astype(str).str.strip().str.lower() == str(category).strip().lower()]

    radar_df = generate_velocity_forecast(data, budget, days_in_month)
    burn_rate = calculate_ewma_burn_rate(data, days_in_month)
    projected_spend = float(radar_df["projected_spend"].iloc[-1]) if not radar_df.empty else 0.0

    amt_col = None
    for c in data.columns:
        if str(c).lower() == "amount":
            amt_col = c
            break
    total_spent = float(pd.to_numeric(data[amt_col], errors="coerce").sum()) if amt_col else 0.0

    summary_info = {
        "burn_rate": burn_rate,
        "budget_limit": budget,
        "projected_spend": projected_spend,
        "total_spent": total_spent,
        "status": "Exceeded" if (projected_spend > budget and budget > 0) else "On Track"
    }

    return radar_df, summary_info


def generate_trend_insight(transactions=None, *args, **kwargs):
    """Analyzes category spending velocity and returns (insight_message, metric_val, trend_direction)."""
    if transactions is None or not isinstance(transactions, pd.DataFrame) or transactions.empty:
        return ("No transactions available to generate trend insights.", 0.0, "neutral")

    try:
        df = transactions.copy()
        df.columns = [str(c).strip().lower() for c in df.columns]

        amt_col = "amount" if "amount" in df.columns else None
        cat_col = "category" if "category" in df.columns else None

        if amt_col and cat_col:
            df[amt_col] = pd.to_numeric(df[amt_col], errors="coerce").fillna(0.0)

            if "type" in df.columns:
                df = df[df["type"].astype(str).str.lower() != "income"]
            else:
                df = df[df[cat_col].astype(str).str.lower() != "income"]

            cat_totals = df.groupby(cat_col)[amt_col].sum().sort_values(ascending=False)

            if not cat_totals.empty and float(cat_totals.iloc[0]) > 0:
                top_cat = cat_totals.index[0]
                top_spend = float(cat_totals.iloc[0])
                total_spent = float(cat_totals.sum())
                pct = (top_spend / total_spent * 100) if total_spent > 0 else 0.0

                msg = f"Your highest expenditure is **{top_cat}** at ₹{top_spend:,.2f} ({pct:.1f}% of tracked spend)."
                return (msg, top_spend, "up")
    except Exception:
        pass

    return ("Spending trends appear stable across all tracked categories.", 0.0, "stable")


def compute_category_trends(df: pd.DataFrame) -> pd.DataFrame:
    """Computes category trends with 'Percentage Change' and 'Latest EWMA' for the Dashboard table."""
    empty_df = pd.DataFrame(
        columns=["Category", "Total Spend", "Total Spent", "Latest EWMA", "Daily Average", "Percentage Change", "Trend", "Direction"]
    )
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return empty_df

    df_clean = df.copy()
    df_clean.columns = [str(c).strip().lower() for c in df_clean.columns]

    amt_col = "amount" if "amount" in df_clean.columns else None
    cat_col = "category" if "category" in df_clean.columns else None
    date_col = "txn_date" if "txn_date" in df_clean.columns else ("date" if "date" in df_clean.columns else None)

    if not amt_col or not cat_col:
        return empty_df

    df_clean[amt_col] = pd.to_numeric(df_clean[amt_col], errors="coerce").fillna(0.0)

    if "type" in df_clean.columns:
        df_clean = df_clean[df_clean["type"].astype(str).str.lower() != "income"]
    else:
        df_clean = df_clean[df_clean[cat_col].astype(str).str.lower() != "income"]

    if date_col:
        df_clean["parsed_date"] = pd.to_datetime(df_clean[date_col], errors="coerce")

    records = []
    categories = df_clean[cat_col].dropna().unique()

    for cat in categories:
        cat_df = df_clean[df_clean[cat_col] == cat]
        total_spend = float(cat_df[amt_col].sum())

        if "parsed_date" in cat_df.columns and not cat_df["parsed_date"].dropna().empty:
            cat_daily = cat_df.groupby(cat_df["parsed_date"].dt.day)[amt_col].sum()
            ewma_val = float(cat_daily.ewm(span=7, adjust=False).mean().iloc[-1]) if not cat_daily.empty else 0.0
        else:
            ewma_val = total_spend / 30.0

        daily_avg = total_spend / 30.0
        pct_change = round(((ewma_val - daily_avg) / daily_avg * 100) if daily_avg > 0 else 0.0, 2)

        if ewma_val > daily_avg * 1.05:
            trend_str = "🔺 Increasing"
            direction_str = "up"
        elif ewma_val < daily_avg * 0.95:
            trend_str = "🟢 Decreasing"
            direction_str = "down"
        else:
            trend_str = "⚪ Stable"
            direction_str = "stable"

        records.append({
            "Category": cat,
            "Total Spend": total_spend,
            "Total Spent": total_spend,
            "Latest EWMA": round(ewma_val, 2),
            "Daily Average": round(daily_avg, 2),
            "Percentage Change": pct_change,
            "Trend": trend_str,
            "Direction": direction_str,
        })

    trends_df = pd.DataFrame(records)
    if not trends_df.empty:
        trends_df = trends_df.sort_values("Total Spend", ascending=False).reset_index(drop=True)

    return trends_df


def prepare_forecast_table(df: pd.DataFrame, monthly_budget: float = 0.0, days_in_month: int = 30) -> pd.DataFrame:
    """Wrapper function returning velocity forecast dataframe."""
    return generate_velocity_forecast(df, monthly_budget, days_in_month)


def calculate_burn_rate(df: pd.DataFrame, days_elapsed: int) -> float:
    """Calculates linear arithmetic average daily burn rate."""
    if df is None or not isinstance(df, pd.DataFrame) or df.empty or days_elapsed <= 0:
        return 0.0
    amt_col = "amount" if "amount" in df.columns else None
    if not amt_col:
        for c in df.columns:
            if str(c).lower() == "amount":
                amt_col = c
                break
    total_spent = float(pd.to_numeric(df[amt_col], errors="coerce").sum()) if amt_col else 0.0
    return total_spent / days_elapsed


def forecast_end_of_month(current_spent: float, burn_rate: float, days_remaining: int) -> float:
    """Projects month-end spend using current spend and burn rate."""
    return float(current_spent) + (float(burn_rate) * max(0, int(days_remaining)))