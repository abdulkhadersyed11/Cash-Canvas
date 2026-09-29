import json
import sqlite3
import pandas as pd
import streamlit as st
from datetime import datetime

# ==========================================
# CATEGORY CATALOGS & CONSTANTS
# ==========================================

EXPENSE_CATEGORIES = [
    "Food", "Groceries", "Travel", "Transportation", "Shopping", "Clothing",
    "Electronics", "Housing & Rent", "Utilities", "Health & Medical", "Fitness",
    "Entertainment", "Subscriptions", "Education", "Personal Care", "Investments",
    "Gifts & Donations", "Miscellaneous", "Other"
]

DEFAULT_CATALOG = EXPENSE_CATEGORIES
DEFAULT_CATEGORIES = EXPENSE_CATEGORIES
CATEGORIES = EXPENSE_CATEGORIES
BASE_CATEGORIES = EXPENSE_CATEGORIES
ALL_CATEGORIES = EXPENSE_CATEGORIES


def canonicalize_category(category: str, *args, **kwargs) -> str:
    """Normalizes category strings to standard catalog casing."""
    if category is None or pd.isna(category):
        return "Other"

    cleaned = str(category).strip()
    if not cleaned:
        return "Other"

    catalog_map = {c.lower(): c for c in EXPENSE_CATEGORIES}
    if cleaned.lower() in catalog_map:
        return catalog_map[cleaned.lower()]

    return cleaned.title()


# ==========================================
# RESILIENT USER RECORD WRAPPER
# ==========================================

class UserRecord(dict):
    def __init__(self, id_val, username_val, password_val, password_hash_val=None, **kwargs):
        super().__init__()
        self["id"] = id_val
        self["user_id"] = id_val
        self["username"] = username_val
        self["password"] = password_val
        self["password_hash"] = password_hash_val if password_hash_val else password_val
        for k, v in kwargs.items():
            if k not in self:
                self[k] = v

    def __getattr__(self, name):
        if name in self:
            return self[name]
        if name == "user_id":
            return self.get("id")
        if name == "id":
            return self.get("user_id")
        raise AttributeError(f"'UserRecord' object has no attribute '{name}'")

    def __setattr__(self, name, value):
        self[name] = value

    def __getitem__(self, key):
        if isinstance(key, int):
            ordered = [
                self.get("id"),
                self.get("username"),
                self.get("password"),
                self.get("password_hash")
            ]
            return ordered[key]
        if key == "user_id":
            return super().get("user_id", super().get("id"))
        if key == "id":
            return super().get("id", super().get("user_id"))
        return super().__getitem__(key)

    def get(self, key, default=None):
        if key == "user_id":
            return super().get("user_id", super().get("id", default))
        if key == "id":
            return super().get("id", super().get("user_id", default))
        return super().get(key, default)


class BudgetDataFrame(pd.DataFrame):
    @property
    def _constructor(self):
        return BudgetDataFrame

    def get(self, key, default=None):
        if key in self.columns:
            return self[key]
        if "category" in self.columns and "monthly_limit" in self.columns:
            match = self[self["category"].astype(str).str.lower() == str(key).strip().lower()]
            if not match.empty:
                return float(match["monthly_limit"].iloc[0])
        return default


# ==========================================
# DATABASE CONNECTION & SCHEMA MIGRATION
# ==========================================

def get_db_connection(db_path: str = "cashcanvas.db") -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def get_connection(db_path: str = "cashcanvas.db") -> sqlite3.Connection:
    return get_db_connection(db_path)


def init_db(db_path: str = "cashcanvas.db") -> None:
    """Initializes tables and migrates schemas automatically."""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            password_hash TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    cursor.execute("PRAGMA table_info(users)")
    user_cols = {r[1] for r in cursor.fetchall()}
    if user_cols:
        if "id" not in user_cols and "user_id" not in user_cols:
            try:
                cursor.execute("ALTER TABLE users ADD COLUMN id INTEGER")
                cursor.execute("UPDATE users SET id = rowid WHERE id IS NULL")
            except Exception:
                pass
        if "password" not in user_cols:
            try:
                cursor.execute("ALTER TABLE users ADD COLUMN password TEXT DEFAULT ''")
            except Exception:
                pass
        if "password_hash" not in user_cols:
            try:
                cursor.execute("ALTER TABLE users ADD COLUMN password_hash TEXT DEFAULT ''")
            except Exception:
                pass

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS category_budgets (
            user_id INTEGER,
            year TEXT,
            month TEXT,
            category TEXT,
            budget REAL,
            PRIMARY KEY (user_id, year, month, category)
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS custom_categories (
            user_id INTEGER,
            category_name TEXT,
            PRIMARY KEY (user_id, category_name)
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS yearly_category_budgets (
            user_id INTEGER,
            year TEXT,
            budgets_json TEXT,
            PRIMARY KEY (user_id, year)
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS user_budgets (
            user_id INTEGER PRIMARY KEY,
            budgets_json TEXT
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS monthly_budgets (
            user_id INTEGER,
            month TEXT,
            budget_limit REAL,
            PRIMARY KEY (user_id, month)
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            txn_date TEXT,
            description TEXT,
            amount REAL,
            category TEXT,
            type TEXT
        )
        """
    )

    cursor.execute("PRAGMA table_info(transactions)")
    txn_cols = {r[1] for r in cursor.fetchall()}
    if txn_cols:
        if "id" not in txn_cols:
            try:
                cursor.execute("ALTER TABLE transactions ADD COLUMN id INTEGER")
                cursor.execute("UPDATE transactions SET id = rowid WHERE id IS NULL")
            except Exception:
                pass
        if "type" not in txn_cols:
            try:
                cursor.execute("ALTER TABLE transactions ADD COLUMN type TEXT DEFAULT 'Expense'")
            except Exception:
                pass
        if "category" not in txn_cols:
            try:
                cursor.execute("ALTER TABLE transactions ADD COLUMN category TEXT DEFAULT 'Other'")
            except Exception:
                pass
        if "description" not in txn_cols:
            try:
                cursor.execute("ALTER TABLE transactions ADD COLUMN description TEXT DEFAULT ''")
            except Exception:
                pass
        if "txn_date" not in txn_cols and "date" not in txn_cols:
            try:
                cursor.execute("ALTER TABLE transactions ADD COLUMN txn_date TEXT DEFAULT ''")
            except Exception:
                pass

    conn.commit()
    conn.close()


def init_database(db_path: str = "cashcanvas.db") -> None:
    init_db(db_path)


def create_tables(db_path: str = "cashcanvas.db") -> None:
    init_db(db_path)


# ==========================================
# 1. USER AUTHENTICATION & SESSIONS
# ==========================================

def create_user(username: str, password: str, *args, db_path: str = "cashcanvas.db", **kwargs) -> bool:
    init_db(db_path)
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    try:
        cursor.execute("PRAGMA table_info(users)")
        cols = {r[1] for r in cursor.fetchall()}

        fields = ["username"]
        placeholders = ["?"]
        values = [str(username).strip()]

        if "password" in cols:
            fields.append("password")
            placeholders.append("?")
            values.append(str(password).strip())

        if "password_hash" in cols:
            fields.append("password_hash")
            placeholders.append("?")
            values.append(str(password).strip())

        cursor.execute(
            f"INSERT INTO users ({', '.join(fields)}) VALUES ({', '.join(placeholders)})",
            tuple(values)
        )
        conn.commit()
        st.cache_data.clear()
        return True
    except sqlite3.IntegrityError:
        return False
    except Exception:
        return False
    finally:
        conn.close()


def get_user_by_username(username: str, db_path: str = "cashcanvas.db"):
    init_db(db_path)
    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    row = None
    try:
        cursor.execute("SELECT rowid AS _rowid, * FROM users WHERE username = ?", (str(username).strip(),))
        row = cursor.fetchone()
    except Exception:
        try:
            cursor.execute("SELECT * FROM users WHERE username = ?", (str(username).strip(),))
            row = cursor.fetchone()
        except Exception:
            pass
    finally:
        conn.close()

    if not row:
        return None

    row_dict = dict(row)
    uid = row_dict.get("id") or row_dict.get("user_id") or row_dict.get("_rowid")
    uname = row_dict.get("username", str(username).strip())
    pwd = row_dict.get("password") or row_dict.get("password_hash") or ""
    pwd_hash = row_dict.get("password_hash") or row_dict.get("password") or ""

    return UserRecord(uid, uname, pwd, pwd_hash, **row_dict)


def get_user_by_id(user_id: int, db_path: str = "cashcanvas.db"):
    init_db(db_path)
    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    row = None
    try:
        cursor.execute("SELECT rowid AS _rowid, * FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
    except Exception:
        try:
            cursor.execute("SELECT rowid AS _rowid, * FROM users WHERE rowid = ?", (user_id,))
            row = cursor.fetchone()
        except Exception:
            pass
    finally:
        conn.close()

    if not row:
        return None

    row_dict = dict(row)
    uid = row_dict.get("id") or row_dict.get("user_id") or row_dict.get("_rowid") or user_id
    uname = row_dict.get("username", "")
    pwd = row_dict.get("password") or row_dict.get("password_hash") or ""
    pwd_hash = row_dict.get("password_hash") or row_dict.get("password") or ""

    return UserRecord(uid, uname, pwd, pwd_hash, **row_dict)


def verify_user(username: str, password: str, db_path: str = "cashcanvas.db") -> bool:
    user = get_user_by_username(username, db_path)
    if user:
        pwd = user["password"] or user["password_hash"]
        if pwd == str(password).strip():
            return True
    return False


def authenticate_user(username: str, password: str, db_path: str = "cashcanvas.db"):
    user = get_user_by_username(username, db_path)
    if user:
        pwd = user["password"] or user["password_hash"]
        if pwd == str(password).strip():
            return user
    return None


# ==========================================
# 2. CATEGORIES (+ BUTTON SUPPORT)
# ==========================================

def add_custom_category(user_id: int, category_name: str, db_path: str = "cashcanvas.db") -> bool:
    clean_cat = canonicalize_category(category_name)
    if not clean_cat or clean_cat == "Other":
        return False
    init_db(db_path)
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT OR IGNORE INTO custom_categories (user_id, category_name) VALUES (?, ?)",
            (user_id, clean_cat)
        )
        conn.commit()
        st.cache_data.clear()
        return True
    except Exception:
        return False
    finally:
        conn.close()


def get_all_user_categories(user_id: int, db_path: str = "cashcanvas.db") -> list:
    init_db(db_path)
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT category_name FROM custom_categories WHERE user_id = ?", (user_id,))
    rows = cursor.fetchall()
    conn.close()

    customs = [r["category_name"] for r in rows if r["category_name"]]
    return sorted(list(set(EXPENSE_CATEGORIES + customs)))


def get_categories(user_id: int = None, db_path: str = "cashcanvas.db") -> list:
    if user_id:
        return get_all_user_categories(user_id, db_path)
    return EXPENSE_CATEGORIES


def get_custom_categories(user_id: int, db_path: str = "cashcanvas.db") -> list:
    init_db(db_path)
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT category_name FROM custom_categories WHERE user_id = ?", (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return [r["category_name"] for r in rows if r["category_name"]]


# ==========================================
# 3. BUDGET QUERIES & GETTERS (CACHED)
# ==========================================

@st.cache_data(ttl=60)
def get_budget_months(user_id: int = None, *args, db_path: str = "cashcanvas.db", **kwargs) -> list:
    init_db(db_path)
    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    months_set = set()

    if user_id:
        cursor.execute("SELECT DISTINCT month FROM category_budgets WHERE user_id = ?", (user_id,))
    else:
        cursor.execute("SELECT DISTINCT month FROM category_budgets")
    for r in cursor.fetchall():
        m = str(r["month"]).strip()
        if m and m.lower() not in ("all", "none"):
            months_set.add(m)

    if user_id:
        cursor.execute("SELECT DISTINCT month FROM monthly_budgets WHERE user_id = ?", (user_id,))
    else:
        cursor.execute("SELECT DISTINCT month FROM monthly_budgets")
    for r in cursor.fetchall():
        m = str(r["month"]).strip()
        if m:
            months_set.add(m)

    if user_id:
        cursor.execute("SELECT DISTINCT txn_date FROM transactions WHERE user_id = ?", (user_id,))
    else:
        cursor.execute("SELECT DISTINCT txn_date FROM transactions")
    txn_dates = [r["txn_date"] for r in cursor.fetchall() if r["txn_date"]]

    conn.close()

    for d in txn_dates:
        try:
            dt = pd.to_datetime(d, errors="coerce")
            if pd.notna(dt):
                months_set.add(dt.strftime("%B %Y"))
        except Exception:
            pass

    normalized_months = set()
    for m in months_set:
        try:
            dt = pd.to_datetime(m, errors="coerce")
            if pd.notna(dt):
                normalized_months.add(dt.strftime("%B %Y"))
            else:
                normalized_months.add(m)
        except Exception:
            normalized_months.add(m)

    if not normalized_months:
        normalized_months.add(datetime.now().strftime("%B %Y"))

    def month_sort_key(m_str):
        try:
            return pd.to_datetime(m_str)
        except Exception:
            return pd.Timestamp.min

    return sorted(list(normalized_months), key=month_sort_key, reverse=True)


@st.cache_data(ttl=60)
def get_budgets_for_month(user_id=None, month=None, *args, db_path="cashcanvas.db", **kwargs) -> pd.DataFrame:
    if isinstance(user_id, str) and month is None:
        month = user_id
        user_id = kwargs.get("user_id", 1)
    elif user_id is None:
        if len(args) > 0 and isinstance(args[0], str):
            month = args[0]
            user_id = kwargs.get("user_id", 1)
        elif len(args) > 1:
            user_id = args[0]
            month = args[1]
        else:
            user_id = kwargs.get("user_id", 1)
            month = kwargs.get("month", None)

    if user_id is None:
        user_id = 1
    if not month:
        month = datetime.now().strftime("%B %Y")

    m_str = str(month).strip()

    target_year = "2026"
    m_parts = m_str.split()
    if len(m_parts) > 1 and m_parts[-1].isdigit():
        target_year = m_parts[-1]
    elif "-" in m_str:
        target_year = m_str.split("-")[0]

    init_db(db_path)
    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    cat_budgets = {}

    cursor.execute(
        "SELECT category, budget FROM category_budgets WHERE user_id = ? AND month = ?",
        (user_id, m_str)
    )
    rows = cursor.fetchall()
    if rows:
        for r in rows:
            cat_budgets[canonicalize_category(r["category"])] = float(r["budget"])

    if not cat_budgets:
        cursor.execute(
            "SELECT category, budget FROM category_budgets WHERE user_id = ? AND year = ?",
            (user_id, target_year)
        )
        rows = cursor.fetchall()
        if rows:
            for r in rows:
                cat_budgets[canonicalize_category(r["category"])] = float(r["budget"])

    if not cat_budgets:
        cursor.execute(
            "SELECT budgets_json FROM yearly_category_budgets WHERE user_id = ? AND year = ?",
            (user_id, target_year)
        )
        row = cursor.fetchone()
        if row and row["budgets_json"]:
            try:
                raw_dict = json.loads(row["budgets_json"])
                cat_budgets = {canonicalize_category(k): float(v) for k, v in raw_dict.items()}
            except Exception:
                pass

    if not cat_budgets:
        cursor.execute("SELECT budgets_json FROM user_budgets WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        if row and row["budgets_json"]:
            try:
                raw_dict = json.loads(row["budgets_json"])
                cat_budgets = {canonicalize_category(k): float(v) for k, v in raw_dict.items()}
            except Exception:
                pass

    conn.close()

    user_cats = get_all_user_categories(user_id, db_path=db_path)
    all_cats = list(dict.fromkeys(list(cat_budgets.keys()) + user_cats + EXPENSE_CATEGORIES))

    records = []
    for cat in all_cats:
        c_name = canonicalize_category(cat)
        limit = float(cat_budgets.get(c_name, cat_budgets.get(cat, 0.0)))
        records.append({
            "category": c_name,
            "Category": c_name,
            "monthly_limit": limit,
            "budget": limit,
            "budget_limit": limit,
            "amount": limit,
            "month": m_str,
            "user_id": user_id
        })

    return BudgetDataFrame(records)


def get_budget_for_month(user_id=None, month=None, *args, db_path="cashcanvas.db", **kwargs):
    return get_budgets_for_month(user_id, month, *args, db_path=db_path, **kwargs)


def get_category_budgets(user_id: int, month: str = None, year: str = None, db_path: str = "cashcanvas.db") -> dict:
    df = get_budgets_for_month(user_id=user_id, month=month or (f"{year}-01" if year else None), db_path=db_path)
    if df.empty:
        return {}
    return dict(zip(df["category"], df["monthly_limit"]))


def get_yearly_category_budgets(user_id: int, year: str, db_path: str = "cashcanvas.db") -> dict:
    init_db(db_path)
    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    cursor.execute(
        "SELECT budgets_json FROM yearly_category_budgets WHERE user_id = ? AND year = ?",
        (user_id, str(year))
    )
    row = cursor.fetchone()
    conn.close()

    if row and row["budgets_json"]:
        try:
            return json.loads(row["budgets_json"])
        except Exception:
            pass

    return get_category_budgets(user_id, year=year, db_path=db_path)


def get_user_yearly_budgets(user_id: int, db_path: str = "cashcanvas.db") -> dict:
    init_db(db_path)
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT year, budgets_json FROM yearly_category_budgets WHERE user_id = ?", (user_id,))
    rows = cursor.fetchall()
    conn.close()

    result = {}
    for r in rows:
        try:
            b_dict = json.loads(r["budgets_json"])
            result[str(r["year"])] = float(sum(b_dict.values()))
        except Exception:
            result[str(r["year"])] = 0.0
    return result


def get_month_budget(user_id: int, month_str: str, db_path: str = "cashcanvas.db") -> float:
    init_db(db_path)
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT budget_limit FROM monthly_budgets WHERE user_id = ? AND month = ?", (user_id, str(month_str)))
    row = cursor.fetchone()
    conn.close()
    if row and row["budget_limit"]:
        return float(row["budget_limit"])

    df = get_budgets_for_month(user_id, str(month_str), db_path=db_path)
    return float(df["monthly_limit"].sum()) if not df.empty else 0.0


def get_monthly_budget(user_id: int, month_str: str = None, db_path: str = "cashcanvas.db") -> float:
    return get_month_budget(user_id, month_str or datetime.now().strftime("%B %Y"), db_path)


def get_total_budget(user_id: int, month: str = None, year: str = None, db_path: str = "cashcanvas.db") -> float:
    return get_month_budget(user_id, month or (f"{year}-01" if year else "2026-01"), db_path)


def get_overall_budget(user_id: int, month: str = None, year: str = None, db_path: str = "cashcanvas.db") -> float:
    return get_total_budget(user_id, month, year, db_path)


# ==========================================
# 4. BUDGET SETTERS & PERSISTENCE
# ==========================================

def set_budget(*args, **kwargs) -> None:
    db_path = kwargs.get("db_path", "cashcanvas.db")
    user_id = kwargs.get("user_id", 1)
    category = kwargs.get("category", None)
    amount = kwargs.get("amount", None)
    month = kwargs.get("month", "all")
    year = kwargs.get("year", "2026")

    if len(args) == 4:
        user_id, category, amount, month = args
    elif len(args) == 3:
        user_id = args[0]
        if isinstance(args[1], str) and any(c.isdigit() for c in args[1]):
            month, amount = args[1], args[2]
            category = None
        else:
            category, amount = args[1], args[2]
    elif len(args) == 2:
        if isinstance(args[0], int) and isinstance(args[1], (int, float)):
            user_id, amount = args
        elif isinstance(args[0], str) and isinstance(args[1], (int, float)):
            category, amount = args
    elif len(args) == 1 and isinstance(args[0], (int, float)):
        amount = args[0]

    amount = float(amount) if amount is not None else 0.0

    if category:
        update_category_budget(user_id, category, amount, month=month, year=year, db_path=db_path)
    else:
        set_month_budget(user_id, str(month), amount, db_path=db_path)
    st.cache_data.clear()


def set_budgets(user_id: int, budgets_dict: dict, month: str = None, year: str = "2026", db_path: str = "cashcanvas.db") -> None:
    save_category_budgets_for_year(user_id, str(year), budgets_dict, db_path=db_path)
    st.cache_data.clear()


def save_budget(*args, **kwargs) -> None:
    set_budget(*args, **kwargs)


def save_budgets(user_id: int, budgets_dict: dict, month: str = None, year: str = "2026", db_path: str = "cashcanvas.db") -> None:
    save_category_budgets_for_year(user_id, str(year), budgets_dict, db_path=db_path)


def update_category_budget(user_id: int, category: str, amount: float, month: str = "all", year: str = "2026", db_path: str = "cashcanvas.db") -> None:
    init_db(db_path)
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO category_budgets (user_id, year, month, category, budget)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id, year, month, category) DO UPDATE SET budget = excluded.budget
        """,
        (user_id, str(year), str(month), canonicalize_category(category), float(amount))
    )
    conn.commit()
    conn.close()
    st.cache_data.clear()


def set_category_budget(user_id: int, category: str, amount: float, month: str = "all", year: str = "2026", db_path: str = "cashcanvas.db") -> None:
    update_category_budget(user_id, category, amount, month, year, db_path)


def save_category_budget(user_id: int, category: str, amount: float, month: str = "all", year: str = "2026", db_path: str = "cashcanvas.db") -> None:
    update_category_budget(user_id, category, amount, month, year, db_path)


def save_category_budgets(user_id: int, budgets_dict: dict, month: str = None, year: str = "2026", db_path: str = "cashcanvas.db") -> None:
    save_category_budgets_for_year(user_id, str(year), budgets_dict, db_path)


def save_category_budgets_for_year(user_id: int, year: str, budgets_dict: dict, db_path: str = "cashcanvas.db") -> None:
    init_db(db_path)
    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    canonical_budgets = {canonicalize_category(k): float(v) for k, v in budgets_dict.items()}

    cursor.execute(
        """
        INSERT INTO yearly_category_budgets (user_id, year, budgets_json)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id, year) DO UPDATE SET budgets_json = excluded.budgets_json
        """,
        (user_id, str(year), json.dumps(canonical_budgets))
    )

    cursor.execute(
        """
        INSERT INTO user_budgets (user_id, budgets_json)
        VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET budgets_json = excluded.budgets_json
        """,
        (user_id, json.dumps(canonical_budgets))
    )

    for cat, amt in canonical_budgets.items():
        cursor.execute(
            """
            INSERT INTO category_budgets (user_id, year, month, category, budget)
            VALUES (?, ?, 'all', ?, ?)
            ON CONFLICT(user_id, year, month, category) DO UPDATE SET budget = excluded.budget
            """,
            (user_id, str(year), str(cat), float(amt))
        )

    conn.commit()
    conn.close()
    st.cache_data.clear()


def save_budgets_for_month(user_id: int, month: str, budgets_dict: dict, db_path: str = "cashcanvas.db") -> None:
    init_db(db_path)
    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    target_year = "2026"
    if month:
        m_parts = str(month).strip().split()
        if len(m_parts) > 1 and m_parts[-1].isdigit():
            target_year = m_parts[-1]
        elif "-" in str(month):
            target_year = str(month).split("-")[0]

    for cat, amt in budgets_dict.items():
        canonical_cat = canonicalize_category(cat)
        cursor.execute(
            """
            INSERT INTO category_budgets (user_id, year, month, category, budget)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id, year, month, category) DO UPDATE SET budget = excluded.budget
            """,
            (user_id, target_year, str(month).strip(), canonical_cat, float(amt))
        )
    conn.commit()
    conn.close()

    save_category_budgets_for_year(user_id, target_year, budgets_dict, db_path=db_path)
    st.cache_data.clear()


def save_yearly_category_budgets(user_id: int, year: str, budgets_dict: dict, db_path: str = "cashcanvas.db") -> None:
    save_category_budgets_for_year(user_id, year, budgets_dict, db_path=db_path)


def save_user_yearly_budget(user_id: int, year: str, amount: float, db_path: str = "cashcanvas.db") -> None:
    init_db(db_path)
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS yearly_budgets (
            user_id INTEGER,
            year TEXT,
            monthly_limit REAL,
            PRIMARY KEY (user_id, year)
        )
        """
    )
    cursor.execute(
        """
        INSERT INTO yearly_budgets (user_id, year, monthly_limit)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id, year) DO UPDATE SET monthly_limit = excluded.monthly_limit
        """,
        (user_id, str(year), float(amount))
    )
    conn.commit()
    conn.close()
    st.cache_data.clear()


def set_month_budget(user_id: int, month_str: str, amount: float, db_path: str = "cashcanvas.db") -> None:
    init_db(db_path)
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO monthly_budgets (user_id, month, budget_limit)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id, month) DO UPDATE SET budget_limit = excluded.budget_limit
        """,
        (user_id, str(month_str), float(amount))
    )
    conn.commit()
    conn.close()
    st.cache_data.clear()


def set_monthly_budget(user_id: int, month_str: str, amount: float, db_path: str = "cashcanvas.db") -> None:
    set_month_budget(user_id, month_str, amount, db_path)


def set_total_budget(user_id: int, amount: float, month: str = None, year: str = "2026", db_path: str = "cashcanvas.db") -> None:
    set_month_budget(user_id, month or f"{year}-01", amount, db_path)


def set_overall_budget(user_id: int, amount: float, month: str = None, year: str = "2026", db_path: str = "cashcanvas.db") -> None:
    set_total_budget(user_id, amount, month, year, db_path)


def reset_budget(user_id: int, month: str = None, year: str = None, db_path: str = "cashcanvas.db") -> None:
    init_db(db_path)
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    if month:
        cursor.execute("DELETE FROM category_budgets WHERE user_id = ? AND month = ?", (user_id, str(month)))
        cursor.execute("DELETE FROM monthly_budgets WHERE user_id = ? AND month = ?", (user_id, str(month)))
    elif year:
        cursor.execute("DELETE FROM category_budgets WHERE user_id = ? AND year = ?", (user_id, str(year)))
        cursor.execute("DELETE FROM yearly_category_budgets WHERE user_id = ? AND year = ?", (user_id, str(year)))
    conn.commit()
    conn.close()
    st.cache_data.clear()


# ==========================================
# 5. TRANSACTIONS & STATEMENTS (CACHED)
# ==========================================

def bulk_insert_transactions(user_id: int, df: pd.DataFrame, db_path: str = "cashcanvas.db") -> int:
    if df is None or df.empty:
        return 0

    init_db(db_path)
    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("PRAGMA table_info(transactions)")
    db_cols = {r[1] for r in cursor.fetchall()}

    if "type" not in db_cols:
        try:
            cursor.execute("ALTER TABLE transactions ADD COLUMN type TEXT DEFAULT 'Expense'")
            conn.commit()
            db_cols.add("type")
        except Exception:
            pass

    clean_df = df.copy()
    clean_df.columns = [str(c).strip().lower() for c in clean_df.columns]
    date_col = "txn_date" if "txn_date" in clean_df.columns else ("date" if "date" in clean_df.columns else None)

    count = 0
    for _, row in clean_df.iterrows():
        txn_date = str(row.get(date_col, ""))
        desc = str(row.get("description", ""))
        amount = float(row.get("amount", 0.0))
        raw_cat = str(row.get("category", "Other"))
        cat = canonicalize_category(raw_cat)
        
        # Detect income by category/description if type is missing
        t_type = str(row.get("type", "")).strip().capitalize()
        if not t_type or t_type == "None":
            if cat.lower() == "income" or "salary" in desc.lower() or "deposit" in desc.lower():
                t_type = "Income"
            else:
                t_type = "Expense"

        fields = ["user_id", "description", "amount", "category"]
        placeholders = ["?", "?", "?", "?"]
        values = [user_id, desc, amount, cat]

        if "txn_date" in db_cols:
            fields.append("txn_date")
            placeholders.append("?")
            values.append(txn_date)
        elif "date" in db_cols:
            fields.append("date")
            placeholders.append("?")
            values.append(txn_date)

        if "type" in db_cols:
            fields.append("type")
            placeholders.append("?")
            values.append(t_type)

        query = f"INSERT INTO transactions ({', '.join(fields)}) VALUES ({', '.join(placeholders)})"
        cursor.execute(query, tuple(values))
        count += 1

    conn.commit()
    conn.close()
    st.cache_data.clear()
    return count


@st.cache_data(ttl=60)
def get_user_transactions(user_id: int, db_path: str = "cashcanvas.db") -> pd.DataFrame:
    init_db(db_path)
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(transactions)")
    cols = [r[1] for r in cursor.fetchall()]

    if not cols:
        conn.close()
        return pd.DataFrame(columns=["id", "user_id", "txn_date", "description", "amount", "category", "type"])

    id_expr = "id" if "id" in cols else "rowid AS id"
    other_cols = [c for c in ["txn_date", "description", "amount", "category", "type"] if c in cols]
    cols_str = ", ".join([id_expr] + other_cols)

    query = f"SELECT {cols_str} FROM transactions WHERE user_id = ?"
    df = pd.read_sql_query(query, conn, params=(user_id,))
    conn.close()

    if "user_id" not in df.columns:
        df["user_id"] = user_id

    return df


def get_transactions(user_id: int, db_path: str = "cashcanvas.db") -> pd.DataFrame:
    return get_user_transactions(user_id, db_path)


def get_all_transactions(user_id: int = None, db_path: str = "cashcanvas.db") -> pd.DataFrame:
    init_db(db_path)
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(transactions)")
    cols = [r[1] for r in cursor.fetchall()]

    if not cols:
        conn.close()
        return pd.DataFrame(columns=["id", "user_id", "txn_date", "description", "amount", "category", "type"])

    id_expr = "id" if "id" in cols else "rowid AS id"
    other_cols = [c for c in ["user_id", "txn_date", "description", "amount", "category", "type"] if c in cols]
    cols_str = ", ".join([id_expr] + other_cols)

    if user_id:
        query = f"SELECT {cols_str} FROM transactions WHERE user_id = ?"
        df = pd.read_sql_query(query, conn, params=(user_id,))
    else:
        query = f"SELECT {cols_str} FROM transactions"
        df = pd.read_sql_query(query, conn)
    conn.close()
    return df


def add_transaction(user_id: int, date: str, description: str, amount: float, category: str, txn_type: str = "Expense", db_path: str = "cashcanvas.db") -> None:
    init_db(db_path)
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO transactions (user_id, txn_date, description, amount, category, type)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (user_id, str(date), str(description), float(amount), canonicalize_category(category), str(txn_type))
    )
    conn.commit()
    conn.close()
    st.cache_data.clear()


def delete_transaction(transaction_id: int, db_path: str = "cashcanvas.db") -> None:
    init_db(db_path)
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM transactions WHERE id = ?", (transaction_id,))
    conn.commit()
    conn.close()
    st.cache_data.clear()


def clear_transactions(user_id: int, db_path: str = "cashcanvas.db") -> None:
    init_db(db_path)
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM transactions WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    st.cache_data.clear()