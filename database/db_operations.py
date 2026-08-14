import sqlite3

import pandas as pd


DB_PATH = "cashcanvas.db"

EXPENSE_CATEGORIES = [
    "Food",
    "Transport",
    "Shopping",
    "Entertainment",
    "Housing/Rent",
    "Utilities",
    "Healthcare",
    "Education",
    "Personal Care",
    "Travel",
    "Subscriptions",
    "Savings/Investments",
    "EMI/Debt",
    "Gifts/Donations",
    "Other",
]


def canonicalize_category(category):
    """Return a supported category name using the canonical display spelling."""

    if category is None:
        return "Other"

    cleaned_category = str(category).strip()
    if not cleaned_category:
        return "Other"

    for supported_category in EXPENSE_CATEGORIES:
        if cleaned_category.casefold() == supported_category.casefold():
            return supported_category

    return "Other"


def get_connection():
    """Open a connection with row access by column name."""

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def create_user(username, email, password_hash):
    """
    Insert a new user.

    Returns the new user ID, or None if the username or email already exists.
    """

    conn = get_connection()

    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO users (username, email, password_hash)
            VALUES (?, ?, ?)
            """,
            (username, email, password_hash),
        )

        conn.commit()
        return cursor.lastrowid

    except sqlite3.IntegrityError:
        # Username or email already exists.
        return None

    finally:
        conn.close()


def get_user_by_username(username):
    """Return the user's information, or None if the user is not found."""

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM users WHERE username = ?",
        (username,),
    )

    row = cursor.fetchone()
    conn.close()

    return dict(row) if row else None


def add_transaction(user_id, amount, category, description, txn_date):
    """
    Add one expense transaction.

    txn_date should be provided in YYYY-MM-DD format.
    """

    conn = get_connection()
    cursor = conn.cursor()

    normalized_category = canonicalize_category(category)

    cursor.execute(
        """
        INSERT INTO transactions
        (user_id, amount, category, description, txn_date)
        VALUES (?, ?, ?, ?, ?)
        """,
        (user_id, amount, normalized_category, description, txn_date),
    )

    conn.commit()
    new_id = cursor.lastrowid
    conn.close()

    return new_id


def set_budget(user_id, category, monthly_limit, month_year):
    """Insert or update a category budget for one user and month."""

    normalized_category = canonicalize_category(category)
    normalized_limit = max(float(monthly_limit), 0.0)

    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT budget_id
            FROM budgets
            WHERE user_id = ?
              AND category = ?
              AND month_year = ?
            """,
            (user_id, normalized_category, month_year),
        )
        existing_row = cursor.fetchone()

        if existing_row is None:
            cursor.execute(
                """
                INSERT INTO budgets (user_id, category, monthly_limit, month_year)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, normalized_category, normalized_limit, month_year),
            )
            budget_id = cursor.lastrowid
        else:
            cursor.execute(
                """
                UPDATE budgets
                SET monthly_limit = ?
                WHERE budget_id = ?
                """,
                (normalized_limit, existing_row["budget_id"]),
            )
            budget_id = existing_row["budget_id"]

        conn.commit()
        return budget_id
    finally:
        conn.close()


def get_budgets_for_month(user_id, month_year):
    """Return all budget rows for one user and month."""

    conn = get_connection()
    try:
        df = pd.read_sql_query(
            """
            SELECT budget_id, user_id, category, monthly_limit, month_year
            FROM budgets
            WHERE user_id = ?
              AND month_year = ?
            ORDER BY category
            """,
            conn,
            params=(user_id, month_year),
        )
    finally:
        conn.close()

    if not df.empty:
        df["category"] = df["category"].apply(canonicalize_category)
        df["monthly_limit"] = df["monthly_limit"].astype(float)

    return df


def get_total_budget(user_id, month_year):
    """Return the total monthly budget across all categories for a user and month."""

    budgets = get_budgets_for_month(user_id, month_year)
    if budgets.empty:
        return 0.0

    return float(budgets["monthly_limit"].sum())


def get_budget_months(user_id):
    """Return the distinct budget months saved for one user."""

    conn = get_connection()
    try:
        df = pd.read_sql_query(
            """
            SELECT DISTINCT month_year
            FROM budgets
            WHERE user_id = ?
            ORDER BY month_year DESC
            """,
            conn,
            params=(user_id,),
        )
    finally:
        conn.close()

    if df.empty:
        return []

    return df["month_year"].tolist()


def get_transactions(user_id):
    """Return all transactions belonging to the specified user."""

    conn = get_connection()

    df = pd.read_sql_query(
        """
        SELECT *
        FROM transactions
        WHERE user_id = ?
        ORDER BY txn_date DESC
        """,
        conn,
        params=(user_id,),
    )

    conn.close()

    if not df.empty:
        df["category"] = df["category"].apply(canonicalize_category)
        df["txn_date"] = pd.to_datetime(df["txn_date"])

    return df


def get_budget(user_id, category, month_year):
    """
    Return the monthly budget for a category.

    Returns None if a budget has not been created.
    """

    normalized_category = canonicalize_category(category)

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT monthly_limit
        FROM budgets
        WHERE user_id = ?
          AND category = ?
          AND month_year = ?
        """,
        (user_id, normalized_category, month_year),
    )

    row = cursor.fetchone()
    conn.close()

    return row["monthly_limit"] if row else None