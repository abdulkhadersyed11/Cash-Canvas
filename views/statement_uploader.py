import streamlit as st
import pandas as pd
from modules.csv_importer import process_bank_statement_csv
from database.db_operations import (
    bulk_insert_transactions,
    get_yearly_category_budgets,
    save_yearly_category_budgets,
    add_custom_category,
    get_all_user_categories
)

def render_statement_uploader_view(user_id: int, all_user_transactions: pd.DataFrame):
    st.header("📥 Statement Importer & Category Budget Manager")
    st.caption("Upload statements, configure category-by-category budgets by year, and add custom categories.")

    # 1. Statement Upload Section
    uploaded_file = st.file_uploader("Upload Bank Statement (.csv)", type=["csv"])

    if uploaded_file is not None:
        try:
            parsed_df = process_bank_statement_csv(uploaded_file)
            st.success(f"Parsed {len(parsed_df)} transactions from statement.")

            with st.expander("🔍 Preview Categorized Transactions", expanded=False):
                st.dataframe(parsed_df.head(15), use_container_width=True)

            if st.button("💾 Save All Transactions to Database", type="primary"):
                count = bulk_insert_transactions(user_id, parsed_df)
                st.success(f"Successfully added {count} records!")
                st.rerun()

        except Exception as e:
            st.error(f"Failed to process CSV file: {str(e)}")

    st.divider()

    # 2. Year Selector
    st.subheader("🎯 Category Budget Configuration")
    st.caption("Select a year to assign target limits for each category. These directly drive your Dashboard status cards and charts.")

    # Detect all years from transactions
    detected_years = []
    if all_user_transactions is not None and isinstance(all_user_transactions, pd.DataFrame) and not all_user_transactions.empty:
        df_temp = all_user_transactions.copy()
        df_temp.columns = [str(c).strip().lower() for c in df_temp.columns]
        date_col = "txn_date" if "txn_date" in df_temp.columns else ("date" if "date" in df_temp.columns else None)
        if date_col:
            dates = pd.to_datetime(df_temp[date_col], errors="coerce").dropna()
            detected_years = sorted(dates.dt.year.astype(str).unique().tolist())

    all_years = sorted(list(set(detected_years + ["2025", "2026", "2027"])), reverse=True)
    selected_year = st.selectbox("📅 Select Budget Year", all_years, index=0)

    # 3. Add Custom Category Section (+ Symbol)
    with st.expander("➕ Add Custom Category", expanded=False):
        st.caption("Create any custom category that isn't in the standard catalog.")
        c_col1, c_col2 = st.columns([3, 1])
        with c_col1:
            new_cat_name = st.text_input("New Category Name", placeholder="e.g. Flight Tickets, Gym, Gaming, Pet Care")
        with c_col2:
            st.write("")
            st.write("")
            if st.button("➕ Add Category", key="btn_add_cat"):
                if new_cat_name.strip():
                    added = add_custom_category(user_id, new_cat_name.strip())
                    if added:
                        st.success(f"Added '{new_cat_name.strip()}' successfully!")
                        st.rerun()
                else:
                    st.warning("Please enter a valid category name.")

    # 4. Fetch All Available Categories and Saved Budgets
    all_categories = get_all_user_categories(user_id)
    saved_budgets = get_yearly_category_budgets(user_id, selected_year)

    # 5. Form to Set Category Limits
    st.write(f"### 📑 Monthly Limits for {selected_year}")
    st.caption("Configure individual targets for each category. Starting baseline is ₹0.")

    new_budget_inputs = {}

    with st.form(f"category_budget_form_{selected_year}"):
        cols = st.columns(3)
        for idx, cat in enumerate(all_categories):
            existing_limit = float(saved_budgets.get(cat, 0.0))
            col = cols[idx % 3]
            new_budget_inputs[cat] = col.number_input(
                f"{cat} (₹)",
                min_value=0.0,
                max_value=1000000.0,
                value=existing_limit,
                step=500.0,
                key=f"cat_budget_{selected_year}_{cat}"
            )

        submit_btn = st.form_submit_button(f"💾 Save All Category Budgets for {selected_year}", type="primary")
        if submit_btn:
            save_yearly_category_budgets(user_id, selected_year, new_budget_inputs)
            st.success(f"All category budgets for {selected_year} saved successfully!")
            st.rerun()

    # 6. Combined Budget Overview
    total_budget = sum(saved_budgets.values())
    st.metric(f"Total Combined Monthly Budget ({selected_year})", f"₹{total_budget:,.2f}")

    # 7. Summary Table of Configured Limits
    active_summary = [
        {"Category": cat, "Monthly Target (₹)": f"₹{amt:,.2f}"}
        for cat, amt in sorted(saved_budgets.items()) if amt > 0
    ]
    if active_summary:
        with st.expander(f"📋 View Active Limits for {selected_year} ({len(active_summary)} configured)", expanded=True):
            st.dataframe(pd.DataFrame(active_summary), use_container_width=True)
    else:
        st.info(f"No categories have active limits set for {selected_year} yet. Enter targets above and click Save.")