# 💸 CashCanvas

**Proactive Expense Tracker with AI Summarizer & Spending Velocity Radar**

*Built for the Mini Project & Samsung Innovation Campus Program*

![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)
![Streamlit](https://img.shields.io/badge/Streamlit-App-FF4B4B?logo=streamlit&logoColor=white)
![SQLite](https://img.shields.io/badge/Database-SQLite-003B57?logo=sqlite&logoColor=white)
![Gemini AI](https://img.shields.io/badge/AI-Google%20Gemini-8E44AD?logo=googlegemini&logoColor=white)
![Status](https://img.shields.io/badge/Status-Completed-brightgreen)

---

## 📖 About

Most expense trackers are purely **retrospective** — they log and chart what you've already spent, meaning the first sign of overspending is your low bank balance at month-end. By then, it's too late to make adjustments.

**CashCanvas** is built around a proactive concept: don't just record where the money went—analyze *how fast* it's moving and alert you **before** the month ends.

Its primary engine, the **Spending Velocity Radar**, utilizes rolling Exponentially Weighted Moving Average (EWMA) burn-rate calculations to project whether you are on pace to exceed your budget while you still have time to adjust your habits. Every user gets a dedicated, password-protected account with complete data isolation scoped in SQLite.

---

## ✨ Features

| # | Feature | What it does |
|---|---------|---------------|
| 1 | **Login & Registration** | Secure per-user accounts via `bcrypt` password hashing — every query is scoped to `user_id` |
| 2 | **Descriptive Dashboard** | Interactive category, monthly, and cumulative spend visualizers (`Matplotlib`, `Seaborn`, `Altair`) |
| 3 | **Dual-Line Trend Engine** 🎁 | Daily actual spend vs. smoothed EWMA trend line with automatic smart-insight banners |
| 4 | **Category-wise EWMA Trends** 🎁 | Per-category velocity breakdown (e.g., Food ↑, Transport →, Shopping ↑↑, Entertainment ↓) |
| 5 | **AI Monthly Summarizer** | Plain-English financial recaps powered safely via the Google Gemini API (`google-genai`) |
| 6 | **Spending Velocity Radar** | EWMA + 1-sigma confidence corridor overspend projection model |
| 7 | **What-If Simulator** | Real-time Streamlit slider that recalculates savings forecasts on the fly |
| 8 | **Embedded SQLite Backend** | Persistent, relational storage for user accounts and transaction ledgers |

*🎁 = High-value analytical extensions built directly on top of the core EWMA forecasting engine.*

---

## 🧠 Tech Stack & Algorithms

| Layer | Technology | Function |
|-------|-----------|----------|
| **Forecasting Engine** | EWMA (`df['amount'].ewm(span=5).mean()`) | Computes recency-weighted daily burn rates, prioritizing recent spending surges |
| **Statistical Analysis** | NumPy & Pandas | Calculates cumulative totals (`cumsum()`), standard deviation ($\sigma$), and 1-sigma confidence bands |
| **Category Trend Analysis** | Pandas `groupby` + EWMA | Evaluates spending velocity per category and tags items as *Increasing / Rapid Increase / Stable / Decreasing* |
| **Smart Insight Engine** | Rule-based analytics | Compares multi-day EWMA windows to output actionable natural-language alerts |
| **Interactive Rendering** | Altair (Vega-Lite) | Multi-layered charts: actual spend (solid), forecast (dashed), confidence band (shaded), budget limit |
| **Simulation Engine** | Streamlit `st.session_state` | Captures slider inputs live, re-indexes daily burn rate, and re-renders projections |
| **Storage Backend** | SQLite (`sqlite3`) | Relational database engine supporting fast local aggregation queries |
| **Authentication & Security** | `bcrypt` + `python-dotenv` | Salts and hashes user credentials while isolating private API keys |
| **Generative AI** | Google Gemini (`google-genai`) | Transforms aggregated monthly metrics into clear, 3-bullet financial insights |

---

## 🏗️ Architecture

All user interactions route through `app.py` and query `db_operations.py`, strictly filtered by the active session `user_id`:

```text
auth/login.py  →  Verifies bcrypt hash & sets st.session_state['user_id']
      │
      ▼
app.py (Router & Session Controller)
      │
      ├── Dashboard View       → Category/Monthly aggregations, Dual-line EWMA 
      │                           trend charts, Smart Insight banners, Trend tables 🎁
      │
      ├── Velocity Radar View  → EWMA forecasting model, Altair multi-layer charts,
      │                           Live What-If scenario simulator
      │
      └── AI Summary View      → ai_summarizer.py (Gemini API integration)
                │
                ▼
      database/db_operations.py   (Hand-crafted SQL CRUD queries)
                │
                ▼
         cashcanvas.db (SQLite Relational Database)