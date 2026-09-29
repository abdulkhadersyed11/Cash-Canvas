"""Main entry point for the CashCanvas Streamlit app."""

from __future__ import annotations
from views.statement_uploader import render_statement_uploader_view
import re
from datetime import date

import pandas as pd
import streamlit as st

from auth.login import ensure_session_defaults, main as show_login_page
from database.db_operations import (
    EXPENSE_CATEGORIES,
    add_transaction,
    canonicalize_category,
    get_budget_months,
    get_budgets_for_month,
    get_total_budget,
    get_transactions,
    set_budget,
)
from database.db_setup import initialize_database
from modules.ai_summarizer import generate_monthly_summary
from modules.altair_charts import (
    create_category_donut_chart,
    create_cumulative_spending_chart,
    create_daily_ewma_chart,
    create_forecast_budget_chart,
    create_monthly_bar_chart,
    create_velocity_radar_chart,
    prepare_category_donut_data,
    prepare_cumulative_spending_data,
    prepare_daily_ewma_data,
    prepare_monthly_bar_data,
    validate_daily_ewma_data,
)
from modules.forecasting import (
    compute_category_trends,
    compute_velocity_radar,
    generate_trend_insight,
)
from modules.whatif_simulator import simulate_whatif
from views.velocity_radar import prepare_forecast_table

PAGE_DASHBOARD = "📊 Dashboard"
PAGE_ADD_EXPENSE = "➕ Add Expense"
PAGE_SET_BUDGETS = "💰 Set Budgets"
PAGE_VELOCITY_RADAR = "🚦 Velocity Radar"
PAGE_AI_SUMMARY = "✨ AI Monthly Summary"
NAVIGATION_OPTIONS = [
    PAGE_DASHBOARD,
    PAGE_ADD_EXPENSE,
    PAGE_SET_BUDGETS,
    PAGE_VELOCITY_RADAR,
    PAGE_AI_SUMMARY,
]

CATEGORY_EMOJIS = {
    "Food": "🍽️",
    "Transport": "🚌",
    "Shopping": "🛍️",
    "Entertainment": "🎬",
    "Housing/Rent": "🏠",
    "Utilities": "💡",
    "Healthcare": "🩺",
    "Education": "🎓",
    "Personal Care": "🧴",
    "Travel": "✈️",
    "Subscriptions": "📺",
    "Savings/Investments": "📈",
    "EMI/Debt": "💳",
    "Gifts/Donations": "🎁",
    "Other": "🧾",
}


def _current_month_year() -> str:
    """Return the current month in YYYY-MM format."""

    return pd.Timestamp.today().strftime("%Y-%m")


def _month_label(month_year: str) -> str:
    """Return a readable month label such as August 2026."""

    return pd.Period(month_year, freq="M").strftime("%B %Y")


def _month_sort_key(month_year: str) -> pd.Period:
    """Convert a YYYY-MM month string into a sortable period."""

    return pd.Period(month_year, freq="M")


def _format_currency(amount: float) -> str:
    """Format a number as Indian rupees."""

    return f"₹{amount:,.2f}"


def _widget_key(prefix: str, month_year: str, category: str) -> str:
    """Build a stable Streamlit widget key."""

    safe_category = re.sub(r"[^a-z0-9]+", "_", category.casefold()).strip("_")
    return f"{prefix}_{month_year}_{safe_category}"


def _latest_transaction_month(transactions: pd.DataFrame) -> str:
    """Return the latest transaction month, or the current month if there is no data."""

    if transactions is None or transactions.empty:
        return _current_month_year()

    frame = transactions.copy()
    frame["txn_date"] = pd.to_datetime(frame["txn_date"])
    return frame["txn_date"].max().strftime("%Y-%m")


def _month_options_for_user(user_id: int, transactions: pd.DataFrame) -> list[str]:
    """Return the month values the user can choose from."""

    months = {_current_month_year()}

    if transactions is not None and not transactions.empty:
        frame = transactions.copy()
        frame["txn_date"] = pd.to_datetime(frame["txn_date"])
        months.update(frame["txn_date"].dt.to_period("M").astype(str).tolist())

    months.update(get_budget_months(user_id))
    return sorted(months, key=_month_sort_key, reverse=True)


def _default_month_for_dashboard(transactions: pd.DataFrame, options: list[str]) -> str:
    """Choose the dashboard month using the current month when possible."""

    current_month = _current_month_year()
    if current_month in options and _month_has_transactions(transactions, current_month):
        return current_month

    latest_month = _latest_transaction_month(transactions)
    if latest_month in options:
        return latest_month

    return current_month


def _month_has_transactions(transactions: pd.DataFrame, month_year: str) -> bool:
    """Return True when the DataFrame has at least one transaction in the month."""

    if transactions is None or transactions.empty:
        return False

    frame = transactions.copy()
    frame["txn_date"] = pd.to_datetime(frame["txn_date"])
    month_mask = frame["txn_date"].dt.to_period("M") == pd.Period(month_year, freq="M")
    return bool(month_mask.any())


def _filter_transactions_by_month(transactions: pd.DataFrame, month_year: str) -> pd.DataFrame:
    """Return a copy of the user's transactions for one month."""

    if transactions is None or transactions.empty:
        return pd.DataFrame(columns=transactions.columns if transactions is not None else [])

    frame = transactions.copy()
    frame["txn_date"] = pd.to_datetime(frame["txn_date"])
    month_mask = frame["txn_date"].dt.to_period("M") == pd.Period(month_year, freq="M")
    return frame.loc[month_mask].copy()


def _transaction_month_options(transactions: pd.DataFrame) -> list[str]:
    """Return only the months that actually contain transactions."""

    if transactions is None or transactions.empty:
        return []

    frame = transactions.copy()
    frame["txn_date"] = pd.to_datetime(frame["txn_date"])
    months = frame["txn_date"].dt.to_period("M").astype(str).unique().tolist()
    return sorted(months, key=_month_sort_key, reverse=True)


def _category_emoji(category: str) -> str:
    """Return a friendly emoji for a budget category."""

    return CATEGORY_EMOJIS.get(category, "🧾")


def _safe_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Return a non-shared copy for display logic."""

    if df is None:
        return pd.DataFrame()
    return df.copy()


def _prepare_category_chart_table(prepared: pd.DataFrame) -> pd.DataFrame:
    """Format the exact prepared donut data without recalculating it."""

    if prepared is None or prepared.empty:
        return pd.DataFrame(
            columns=["Category", "Total Spent", "Percentage of Total", "Transaction Count"]
        )

    result = prepared[
        ["category", "total_spent", "percentage_of_total", "transaction_count"]
    ].copy().rename(
        columns={
            "category": "Category",
            "total_spent": "Total Spent",
            "percentage_of_total": "Percentage of Total",
            "transaction_count": "Transaction Count",
        }
    )
    result["Total Spent"] = result["Total Spent"].apply(_format_currency)
    result["Percentage of Total"] = result["Percentage of Total"].apply(lambda value: f"{value:.2f}%")
    return result


def _prepare_monthly_chart_table(prepared: pd.DataFrame) -> pd.DataFrame:
    """Format the exact prepared monthly data without recalculating it."""

    if prepared is None or prepared.empty:
        return pd.DataFrame(
            columns=["Month", "Total Spent", "Transaction Count", "Month-over-Month Change"]
        )

    result = prepared[
        [
            "month_label",
            "total_spent",
            "transaction_count",
            "change_from_previous_month",
        ]
    ].copy().rename(
        columns={
            "month_label": "Month",
            "total_spent": "Total Spent",
            "transaction_count": "Transaction Count",
            "change_from_previous_month": "Month-over-Month Change",
        }
    )
    result["Total Spent"] = result["Total Spent"].apply(_format_currency)
    result["Month-over-Month Change"] = result["Month-over-Month Change"].apply(
        lambda value: "N/A" if pd.isna(value) else f"{value:.2f}%"
    )
    return result


def _prepare_cumulative_chart_table(prepared: pd.DataFrame) -> pd.DataFrame:
    """Format the exact prepared cumulative data without recalculating it."""

    if prepared is None or prepared.empty:
        return pd.DataFrame(columns=["Date", "Daily Spend", "Cumulative Spend"])

    result = prepared[["date", "daily_spend", "cumulative_spend"]].copy().rename(
        columns={
            "date": "Date",
            "daily_spend": "Daily Spend",
            "cumulative_spend": "Cumulative Spend",
        }
    )
    result["Date"] = pd.to_datetime(result["Date"]).dt.strftime("%d %b %Y")
    result["Daily Spend"] = result["Daily Spend"].apply(_format_currency)
    result["Cumulative Spend"] = result["Cumulative Spend"].apply(_format_currency)
    return result


def _prepare_ewma_chart_table(prepared: pd.DataFrame) -> pd.DataFrame:
    """Format the exact prepared daily/EWMA data without recalculating it."""

    if prepared is None or prepared.empty:
        return pd.DataFrame(columns=["Date", "Daily Expenses", "EWMA Trend"])

    result = prepared[["date", "daily_expenses", "ewma_trend"]].copy().rename(
        columns={
            "date": "Date",
            "daily_expenses": "Daily Expenses",
            "ewma_trend": "EWMA Trend",
        }
    )
    result["Date"] = pd.to_datetime(result["Date"]).dt.strftime("%d %b %Y")
    result["Daily Expenses"] = result["Daily Expenses"].apply(_format_currency)
    result["EWMA Trend"] = result["EWMA Trend"].apply(_format_currency)
    return result


def _prepare_category_trends_table(trends: pd.DataFrame) -> pd.DataFrame:
    """Rename the trend table columns into readable labels."""

    if trends is None or trends.empty:
        return pd.DataFrame(columns=["Category", "Latest EWMA", "Percentage Change", "Trend", "Direction"])

    result = trends.rename(
        columns={
            "category": "Category",
            "latest_ewma": "Latest EWMA",
            "pct_change": "Percentage Change",
            "trend_label": "Trend",
            "trend_arrow": "Direction",
        }
    )
    result["Latest EWMA"] = result["Latest EWMA"].apply(_format_currency)
    result["Percentage Change"] = result["Percentage Change"].apply(lambda value: f"{value:.2f}%")
    return result[["Category", "Latest EWMA", "Percentage Change", "Trend", "Direction"]]


def _prepare_recent_expenses_table(transactions: pd.DataFrame) -> pd.DataFrame:
    """Show the most recent 10 transactions for the dashboard."""

    if transactions is None or transactions.empty:
        return pd.DataFrame(columns=["Date", "Category", "Description", "Amount"])

    recent = _safe_dataframe(transactions).sort_values("txn_date", ascending=False).head(10).copy()
    recent["Date"] = pd.to_datetime(recent["txn_date"]).dt.strftime("%Y-%m-%d")
    recent["Category"] = recent["category"]
    recent["Description"] = recent["description"].fillna("")
    recent["Amount"] = recent["amount"].apply(_format_currency)
    return recent[["Date", "Category", "Description", "Amount"]]


def _select_default_dashboard_month(transactions: pd.DataFrame, options: list[str]) -> str:
    """Pick the dashboard budget month using the current month when possible."""

    current_month = _current_month_year()
    if current_month in options and _month_has_transactions(transactions, current_month):
        return current_month

    latest_month = _latest_transaction_month(transactions)
    if latest_month in options:
        return latest_month

    return current_month


def _apply_pending_page() -> None:
    """Move a requested page into the selected_page key before the radio widget is created."""

    if "pending_page" in st.session_state:
        st.session_state["selected_page"] = st.session_state.pop("pending_page")

    st.session_state.setdefault("selected_page", PAGE_DASHBOARD)


def _clear_authenticated_state() -> None:
    """Clear every session key so the next run returns to the login page."""

    st.session_state.clear()


def _get_user_transactions() -> pd.DataFrame:
    """Fetch the current user's transactions fresh from SQLite."""

    user_id = st.session_state.get("user_id")
    if user_id is None:
        return pd.DataFrame()
    return get_transactions(user_id)


def _render_login_gate() -> None:
    """Render the login/register page and stop the authenticated app from loading."""

    _hide_sidebar_for_logged_out_user()
    show_login_page()
    st.stop()


def _hide_sidebar_for_logged_out_user() -> None:
    """Hide private navigation and its collapsed controls before authentication."""

    st.markdown(
        """
        <style>
        [data-testid="stSidebar"],
        [data-testid="stSidebarCollapsedControl"],
        [data-testid="stExpandSidebarButton"],
        [data-testid="stSidebarCollapseButton"],
        [data-testid="collapsedControl"],
        button[kind="headerNoPadding"] {
            display: none !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _add_expense_form() -> None:
    """Render the Add Expense form and redirect to the dashboard on success."""

    st.subheader("➕ Add Expense")
    st.caption("Save a new transaction for the logged-in user.")

    user_id = st.session_state.get("user_id")
    if user_id is None:
        st.error("You need to be logged in to add an expense.")
        return

    with st.form("add_expense_form", clear_on_submit=True):
        amount = st.number_input("Amount", min_value=0.01, step=10.0, format="%.2f")
        category = st.selectbox(
            "Category",
            EXPENSE_CATEGORIES,
            index=None,
            placeholder="Select an expense category",
        )
        description = st.text_input("Description")
        selected_date = st.date_input("Date", value=date.today())
        submitted = st.form_submit_button("Save Expense")

    if submitted:
        if amount <= 0:
            st.error("Amount must be greater than zero.")
            return

        if category is None:
            st.error("Please select a category.")
            return

        add_transaction(
            user_id=user_id,
            amount=float(amount),
            category=canonicalize_category(category),
            description=description.strip(),
            txn_date=selected_date.isoformat(),
        )
        st.session_state["flash_success"] = "Expense added successfully!"
        st.session_state["pending_page"] = PAGE_DASHBOARD
        st.rerun()


def _render_budget_page(transactions: pd.DataFrame) -> None:
    """Render the budget setup page using the shared budgets table."""

    st.subheader("💰 Set Budgets")
    st.caption("Set a monthly spending limit for each category. ₹0 means no budget has been set.")

    flash_message = st.session_state.pop("flash_success", None)
    if flash_message:
        st.success(flash_message)

    user_id = st.session_state.get("user_id")
    if user_id is None:
        st.error("You need to be logged in to set budgets.")
        return

    month_options = _month_options_for_user(user_id, transactions)
    default_month = _select_default_dashboard_month(transactions, month_options)
    selected_month = st.selectbox(
        "Select a month",
        month_options,
        index=month_options.index(default_month) if default_month in month_options else 0,
        format_func=_month_label,
        key="budget_page_month",
    )

    existing_budgets = get_budgets_for_month(user_id, selected_month)
    existing_lookup = {
        canonicalize_category(row["category"]): float(row["monthly_limit"])
        for _, row in existing_budgets.iterrows()
    }

    entered_amounts: dict[str, float] = {}

    with st.form("budget_form"):
        left_column, right_column = st.columns(2)
        for index, category in enumerate(EXPENSE_CATEGORIES):
            column = left_column if index % 2 == 0 else right_column
            key = _widget_key("budget", selected_month, category)
            default_value = existing_lookup.get(category, 0.0)
            with column:
                entered_amounts[category] = st.number_input(
                    category,
                    min_value=0.0,
                    step=100.0,
                    format="%.2f",
                    value=float(default_value),
                    key=key,
                )

        submitted = st.form_submit_button("Save Budgets")

    total_monthly_budget = float(sum(entered_amounts.values()))
    st.metric("Total Monthly Budget", _format_currency(total_monthly_budget))
    st.caption("₹0 means no budget has been set for that category.")

    if submitted:
        for category, amount in entered_amounts.items():
            set_budget(user_id, category, float(amount), selected_month)

        st.session_state["flash_success"] = "Budgets saved successfully!"
        st.session_state["pending_page"] = PAGE_SET_BUDGETS
        st.rerun()


def _render_budget_status(transactions: pd.DataFrame) -> None:
    """Show category-wise budget status for the selected month."""

    user_id = st.session_state.get("user_id")
    if user_id is None:
        return

    month_options = _month_options_for_user(user_id, transactions)
    default_month = _select_default_dashboard_month(transactions, month_options)
    selected_month = st.selectbox(
        "Budget month",
        month_options,
        index=month_options.index(default_month) if default_month in month_options else 0,
        format_func=_month_label,
        key="dashboard_budget_month",
    )

    month_transactions = _filter_transactions_by_month(transactions, selected_month)
    budgets = get_budgets_for_month(user_id, selected_month)
    budget_rows = budgets[budgets["monthly_limit"] > 0].copy() if not budgets.empty else pd.DataFrame()

    if budget_rows.empty:
        st.info("No budget has been set for this month yet. Open the Set Budgets page to add one.")
        if st.button("Go to Set Budgets", key="go_to_budget_page"):
            st.session_state["pending_page"] = PAGE_SET_BUDGETS
            st.rerun()
        return

    spent_by_category = (
        month_transactions.groupby("category", dropna=False)["amount"].sum()
        if not month_transactions.empty
        else pd.Series(dtype=float)
    )

    total_budget = float(budget_rows["monthly_limit"].sum())
    total_spent = float(month_transactions["amount"].sum()) if not month_transactions.empty else 0.0
    total_remaining = total_budget - total_spent
    budget_with_spent = budget_rows.copy()
    budget_with_spent["spent"] = budget_with_spent["category"].map(spent_by_category).fillna(0.0)
    over_budget_count = int((budget_with_spent["spent"] > budget_with_spent["monthly_limit"]).sum())

    st.markdown("### 💰 Category Budget Status")

    summary_columns = st.columns(4)
    summary_columns[0].metric("Total Budget", _format_currency(total_budget))
    summary_columns[1].metric("Total Spent", _format_currency(total_spent))
    summary_columns[2].metric("Total Remaining", _format_currency(total_remaining))
    summary_columns[3].metric("Number of Categories Over Budget", str(over_budget_count))

    for _, row in budget_rows.iterrows():
        category = canonicalize_category(row["category"])
        budget_amount = float(row["monthly_limit"])
        spent_amount = float(spent_by_category.get(category, 0.0))
        remaining_amount = budget_amount - spent_amount
        if budget_amount > 0:
            percentage_used = (spent_amount / budget_amount) * 100.0
        else:
            percentage_used = 0.0

        if percentage_used < 75:
            status_text = "On track"
            status_message = st.success
        elif percentage_used < 100:
            status_text = "Approaching limit"
            status_message = st.warning
        elif percentage_used == 100:
            status_text = "Limit reached"
            status_message = st.warning
        else:
            status_text = "Over budget"
            status_message = st.error
            over_budget_count += 1

        progress_value = min(percentage_used / 100.0, 1.0)
        emoji = _category_emoji(category)

        with st.container(border=True):
            st.markdown(f"#### {emoji} {category}")
            col1, col2, col3 = st.columns(3)
            col1.metric("Budget", _format_currency(budget_amount))
            col2.metric("Spent", _format_currency(spent_amount))
            col3.metric("Remaining", _format_currency(remaining_amount))
            st.progress(progress_value)

            if remaining_amount > 0:
                st.info(f"You can still spend {_format_currency(remaining_amount)}.")
            elif remaining_amount < 0:
                st.error(f"You are over budget by {_format_currency(abs(remaining_amount))}.")
            else:
                st.warning("You have used the full budget for this category.")

            status_message(f"Status: {status_text}")


def _render_dashboard(transactions: pd.DataFrame) -> None:
    """Render the dashboard with metrics, budget status, charts, and trends."""

    st.subheader("📊 Dashboard")
    st.caption("Your latest spending trends, category budgets, and transaction history.")

    flash_message = st.session_state.pop("flash_success", None)
    if flash_message:
        st.success(flash_message)

    if transactions is None or transactions.empty:
        st.info("No expenses yet. Add your first expense to see the dashboard.")
        if st.button("Add your first expense", key="empty_dashboard_add_expense"):
            st.session_state["pending_page"] = PAGE_ADD_EXPENSE
            st.rerun()
        return

    insight_message, _, trend_direction = generate_trend_insight(transactions)
    if trend_direction == "up":
        st.warning(insight_message)
    elif trend_direction == "down":
        st.success(insight_message)
    else:
        st.info(insight_message)

    total_spend = float(transactions["amount"].sum())
    transaction_count = int(len(transactions))
    average_expense = float(transactions["amount"].mean()) if transaction_count else 0.0
    top_category = (
        transactions.groupby("category", dropna=False)["amount"].sum().sort_values(ascending=False).index[0]
        if not transactions.empty
        else "No data"
    )

    with st.container(border=True):
        metric_columns = st.columns(4)
        metric_columns[0].metric("Total Spend", _format_currency(total_spend))
        metric_columns[1].metric("Number of Transactions", f"{transaction_count}")
        metric_columns[2].metric("Average Expense", _format_currency(average_expense))
        metric_columns[3].metric("Top Category", str(top_category))

    st.markdown("### 💰 Category Budget Status")
    _render_budget_status(transactions)

    with st.container(border=True):
        st.subheader("Recent Expenses")
        recent_expenses = _prepare_recent_expenses_table(transactions)
        st.dataframe(recent_expenses, use_container_width=True, hide_index=True)

    chart_options = [
        "Category Spending Breakdown",
        "Monthly Spending Comparison",
        "Cumulative Spending Trend",
        "Daily Expenses vs EWMA Trend",
    ]
    selected_chart = st.selectbox("📊 Choose a chart to display", chart_options, key="dashboard_chart_choice")
    chart_validation_error = None

    # Prepare the selected aggregation once, then reuse it for both the chart
    # and the exact table shown below it.
    if selected_chart == "Category Spending Breakdown":
        prepared_chart_data = prepare_category_donut_data(transactions)
        chart = create_category_donut_chart(prepared_chart_data)
        chart_table = _prepare_category_chart_table(prepared_chart_data)
        selected_total = (
            float(prepared_chart_data["total_spent"].sum())
            if not prepared_chart_data.empty
            else 0.0
        )
    elif selected_chart == "Monthly Spending Comparison":
        prepared_chart_data = prepare_monthly_bar_data(transactions)
        chart = create_monthly_bar_chart(prepared_chart_data)
        chart_table = _prepare_monthly_chart_table(prepared_chart_data)
        selected_total = None
    elif selected_chart == "Cumulative Spending Trend":
        prepared_chart_data = prepare_cumulative_spending_data(transactions)
        chart = create_cumulative_spending_chart(prepared_chart_data)
        chart_table = _prepare_cumulative_chart_table(prepared_chart_data)
        selected_total = None
    else:
        prepared_chart_data = prepare_daily_ewma_data(transactions, span=7)
        chart_validation_error = validate_daily_ewma_data(prepared_chart_data)
        chart = (
            None
            if chart_validation_error
            else create_daily_ewma_chart(prepared_chart_data, span=7)
        )
        chart_table = _prepare_ewma_chart_table(prepared_chart_data)
        selected_total = None

    with st.container(border=True):
        if selected_total is not None:
            st.metric("Total Spending in Chart", _format_currency(selected_total))
        if chart_validation_error:
            st.warning(chart_validation_error)
        else:
            st.altair_chart(chart, use_container_width=True)
        if selected_chart == "Daily Expenses vs EWMA Trend":
            st.caption("EWMA smooths day-to-day spending fluctuations by giving more weight to recent expenses.")
        st.dataframe(chart_table, use_container_width=True, hide_index=True)

    trends = compute_category_trends(transactions)
    if trends.empty:
        st.info("No category trend data is available yet.")
        return

    with st.container(border=True):
        st.subheader("Category Trends")
        st.dataframe(_prepare_category_trends_table(trends), use_container_width=True, hide_index=True)


def _render_velocity_radar(transactions: pd.DataFrame) -> None:
    """Render the velocity radar using either the overall or category budget scope."""

    st.subheader("🚦 Velocity Radar")
    st.caption("Choose a month and budget scope to compare spending against the saved budget.")

    user_id = st.session_state.get("user_id")
    if user_id is None:
        st.error("You need to be logged in to view the radar.")
        return

    month_options = _month_options_for_user(user_id, transactions)
    default_month = _select_default_dashboard_month(transactions, month_options)
    selected_month = st.selectbox(
        "Select a month",
        month_options,
        index=month_options.index(default_month) if default_month in month_options else 0,
        format_func=_month_label,
        key="radar_month",
    )

    budget_scope = st.radio(
        "Budget scope",
        ["Overall Budget", "Category Budget"],
        horizontal=True,
        key="radar_scope",
    )

    month_transactions = _filter_transactions_by_month(transactions, selected_month)
    month_budgets = get_budgets_for_month(user_id, selected_month)
    budget_limit = 0.0
    filtered_transactions = month_transactions
    selected_category = None

    if budget_scope == "Overall Budget":
        budget_limit = float(get_total_budget(user_id, selected_month))
    else:
        category_budgets = month_budgets[month_budgets["monthly_limit"] > 0].copy() if not month_budgets.empty else pd.DataFrame()
        if category_budgets.empty:
            st.info("Please set a budget for this month before using the Velocity Radar.")
            return

        category_options = category_budgets["category"].tolist()
        selected_category = st.selectbox(
            "Select a category",
            category_options,
            format_func=lambda value: f"{_category_emoji(value)} {value}",
            key="radar_category",
        )
        category_row = category_budgets.loc[category_budgets["category"] == selected_category]
        if category_row.empty:
            st.info("Please set a budget for this month before using the Velocity Radar.")
            return

        budget_limit = float(category_row.iloc[0]["monthly_limit"])
        filtered_transactions = month_transactions.loc[month_transactions["category"] == selected_category].copy()

    if budget_limit <= 0:
        st.info("Please set a budget for this month before using the Velocity Radar.")
        return

    radar_df, _ = compute_velocity_radar(
        filtered_transactions,
        budget_limit=budget_limit,
        month_year=selected_month,
        user_id=user_id,
        category=selected_category,
    )

    if radar_df.empty:
        if radar_df.attrs.get("future_month"):
            st.info("Forecasts are not created before the selected month begins.")
        else:
            st.info("No radar data is available yet for this selection.")
        return

    adjustment_pct = st.slider(
        "Adjust my daily spending by (%)",
        min_value=-100,
        max_value=50,
        value=0,
        step=5,
        key="radar_adjustment_pct",
    )
    adjusted_radar_df = simulate_whatif(radar_df, adjustment_pct)

    selected_budget = float(adjusted_radar_df["budget_limit"].iloc[0])
    actual_values = adjusted_radar_df["actual_cumulative"].dropna()
    forecast_values = adjusted_radar_df["forecast_cumulative"].dropna()
    spent_so_far = float(actual_values.iloc[-1]) if not actual_values.empty else 0.0
    forecast_end = float(forecast_values.iloc[-1]) if not forecast_values.empty else spent_so_far
    as_of_date = pd.Timestamp(
        adjusted_radar_df.attrs.get(
            "as_of_date",
            adjusted_radar_df.loc[
                adjusted_radar_df["actual_cumulative"].notna(), "date"
            ].max(),
        )
    ).normalize()
    month_end = pd.Period(selected_month, freq="M").end_time.normalize()
    remaining_days = int(adjusted_radar_df.attrs.get("remaining_days", (month_end - as_of_date).days))
    latest_ewma_rate = float(adjusted_radar_df.attrs.get("latest_ewma_rate", 0.0))
    base_latest_ewma_rate = float(
        adjusted_radar_df.attrs.get("base_latest_ewma_rate", latest_ewma_rate)
    )
    remaining_over_budget = selected_budget - spent_so_far
    forecast_status = "Within budget"
    if forecast_end > selected_budget:
        forecast_status = "Forecast exceeds budget"
    elif forecast_end == selected_budget:
        forecast_status = "Forecast reaches budget"

    metrics = st.columns(5)
    metrics[0].metric("Selected Budget", _format_currency(selected_budget))
    metrics[1].metric("Spent So Far", _format_currency(spent_so_far))
    metrics[2].metric("Remaining / Over Budget", _format_currency(remaining_over_budget))
    metrics[3].metric("Forecast at Month End", _format_currency(forecast_end))
    metrics[4].metric("Forecast Status", forecast_status)

    if forecast_end > selected_budget:
        st.warning("The forecast exceeds the selected budget.")
    else:
        st.success("The forecast remains within the selected budget.")

    if remaining_days == 0 and abs(forecast_end - spent_so_far) < 0.005:
        st.caption(
            "The selected month has no remaining days, so its month-end forecast "
            "equals the recorded spending."
        )
    elif remaining_days > 0 and base_latest_ewma_rate <= 0:
        st.caption(
            "No recent daily spending rate was detected, so the forecast remains "
            "at current spending."
        )
    elif remaining_days > 0 and latest_ewma_rate <= 0:
        st.caption(
            "The what-if adjustment sets the future daily spending rate to zero, "
            "so the forecast remains at current spending."
        )

    forecast_chart = create_velocity_radar_chart(adjusted_radar_df, selected_budget)
    st.altair_chart(forecast_chart, use_container_width=True)

    focus_columns = [
        "actual_cumulative",
        "forecast_cumulative",
        "upper_band",
        "lower_band",
    ]
    focus_values = pd.concat(
        [
            pd.to_numeric(adjusted_radar_df[column], errors="coerce")
            for column in focus_columns
        ],
        ignore_index=True,
    ).dropna()
    focus_max = float(focus_values.max()) if not focus_values.empty else 0.0
    if selected_budget > max(focus_max, 1.0) * 1.5:
        st.caption(
            "The selected budget is above the focused forecast range. "
            "Use the comparison chart below to view it without flattening the spending lines."
        )

    budget_chart = create_forecast_budget_chart(
        current_spend=spent_so_far,
        forecast_spend=forecast_end,
        budget_limit=selected_budget,
    )
    st.altair_chart(budget_chart, use_container_width=True)

    with st.expander("🔍 Forecast calculation details"):
        details = pd.DataFrame(
            {
                "Detail": [
                    "As-of date",
                    "Remaining days",
                    "Latest EWMA rate",
                    "Current cumulative spending",
                    "Forecast at month end",
                    "Budget limit",
                ],
                "Value": [
                    as_of_date.strftime("%d %b %Y"),
                    str(remaining_days),
                    f"{_format_currency(latest_ewma_rate)} per day",
                    _format_currency(spent_so_far),
                    _format_currency(forecast_end),
                    _format_currency(selected_budget),
                ],
            }
        )
        st.dataframe(details, use_container_width=True, hide_index=True)

    forecast_table = prepare_forecast_table(adjusted_radar_df)
    for column in ["Actual Spending", "Forecast", "Lower Band", "Upper Band", "Budget Limit"]:
        forecast_table[column] = forecast_table[column].apply(
            lambda value: "—" if pd.isna(value) else _format_currency(float(value))
        )
    st.dataframe(forecast_table, use_container_width=True, hide_index=True)

    if selected_category is not None:
        st.caption(f"Showing {selected_category} spending for {_month_label(selected_month)}.")
    else:
        st.caption(f"Showing all category spending for {_month_label(selected_month)}.")


def _render_ai_summary(transactions: pd.DataFrame) -> None:
    """Render the AI summary page with a month selector and manual generation button."""

    st.subheader("✨ AI Monthly Summary")
    st.caption("Generate one summary only after you choose a month and click the button.")

    if transactions is None or transactions.empty:
        st.info("No transactions are available yet for an AI summary.")
        return

    month_options = _transaction_month_options(transactions)
    if not month_options:
        st.info("No transaction months were found for this account.")
        return

    selected_month = st.selectbox(
        "Select a month",
        month_options,
        format_func=_month_label,
        key="ai_summary_month",
    )

    st.markdown(f"**Selected month:** {_month_label(selected_month)}")

    if st.button("✨ Generate AI Summary", key="generate_ai_summary_button"):
        month_transactions = _filter_transactions_by_month(transactions, selected_month)
        if month_transactions.empty:
            st.info("No transactions were found for the selected month.")
            return

        user_id = st.session_state.get("user_id")
        cache_key = f"{user_id}:{selected_month}"
        summary_cache = st.session_state.setdefault("ai_summary_cache", {})

        if cache_key not in summary_cache:
            with st.spinner("Generating your monthly summary..."):
                summary_cache[cache_key] = generate_monthly_summary(month_transactions, selected_month)

        st.info(summary_cache[cache_key])


from views.statement_uploader import render_statement_uploader_view


def _render_authenticated_sidebar() -> str:
    """Render the sidebar navigation."""
    selected_page = st.sidebar.radio(
        "Navigation",
        ["Dashboard", "Velocity Radar", "Statement Importer", "AI Summary"]
    )

    if st.sidebar.button("Logout"):
        _clear_authenticated_state()
        st.rerun()

    return selected_page


def _render_authenticated_app() -> None:
    """Render the active page based on sidebar selection."""
    _apply_pending_page()
    selected_page = _render_authenticated_sidebar()
    transactions = _get_user_transactions()

    if selected_page == "Dashboard":
        # Look for your dashboard function defined higher up in app.py
        if "_render_dashboard" in globals():
            _render_dashboard(transactions)
        elif "render_dashboard_view" in globals():
            render_dashboard_view(transactions)
        elif "_render_dashboard_page" in globals():
            _render_dashboard_page(transactions)

    elif selected_page == "Velocity Radar":
        # Look for your velocity radar function defined higher up in app.py
        if "_render_velocity_radar" in globals():
            _render_velocity_radar(transactions)
        elif "render_velocity_radar_view" in globals():
            render_velocity_radar_view(transactions)
        elif "_render_velocity_radar_page" in globals():
            _render_velocity_radar_page(transactions)

    elif selected_page == "Statement Importer":
        render_statement_uploader_view(st.session_state["user_id"], transactions)

    elif selected_page == "AI Summary":
        # Look for your AI summary function defined higher up in app.py
        if "_render_ai_summary" in globals():
            _render_ai_summary(transactions)
        elif "render_ai_summary_view" in globals():
            render_ai_summary_view(transactions)
        elif "_render_ai_summary_page" in globals():
            _render_ai_summary_page(transactions)


def main() -> None:
    """App entrypoint."""
    st.set_page_config(
        page_title="CashCanvas",
        page_icon="💰",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    initialize_database()
    ensure_session_defaults()

    if not st.session_state.get("logged_in"):
        _render_login_gate()
        return

    _render_authenticated_app()


if __name__ == "__main__":
    main()