import pandas as pd
import re

CATEGORY_KEYWORDS = {
    "Food": ["swiggy", "zomato", "restaurant", "cafe", "mcdonald", "starbucks", "grocery", "blinkit", "zepto", "instamart", "supermarket"],
    "Transport": ["uber", "ola", "metro", "fuel", "petrol", "shell", "irctc", "rapido", "auto", "flight"],
    "Shopping": ["amazon", "flipkart", "myntra", "zara", "retail", "mall", "store", "ajio", "meesho"],
    "Entertainment": ["netflix", "spotify", "bookmyshow", "cinema", "steam", "disney", "prime", "theatre"],
    "Utilities": ["electricity", "bescom", "airtel", "jio", "wifi", "broadband", "water", "gas", "recharge"],
    "Health": ["pharmacy", "apollo", "medplus", "hospital", "clinic", "doctor", "gym", "cult"],
    "Income": ["salary", "interest", "dividend", "refund", "credit", "cashback", "upi credit"]
}

def auto_categorize(description: str) -> str:
    desc = str(description).lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(re.search(rf"\b{kw}", desc) for kw in keywords):
            return category
    return "Miscellaneous"

def process_bank_statement_csv(file) -> pd.DataFrame:
    df = pd.read_csv(file)
    df.columns = [c.strip().lower() for c in df.columns]
    
    # Auto-detect column headers
    date_col = next((c for c in df.columns if any(k in c for k in ["date", "txn_date", "trans_date", "value_date"])), None)
    desc_col = next((c for c in df.columns if any(k in c for k in ["desc", "narration", "particulars", "remarks", "title", "details"])), None)
    amount_col = next((c for c in df.columns if any(k in c for k in ["amount", "debit", "withdrawal", "spent", "value"])), None)
    
    if not (date_col and desc_col and amount_col):
        raise ValueError("CSV must contain identifiable columns for Date, Description, and Amount.")
    
    clean_df = pd.DataFrame()
    clean_df['date'] = pd.to_datetime(df[date_col], errors='coerce').dt.strftime('%Y-%m-%d')
    clean_df['description'] = df[desc_col].astype(str)
    clean_df['amount'] = df[amount_col].astype(str).str.replace(r"[^\d.]", "", regex=True).astype(float)
    
    # Remove empty or invalid rows
    clean_df = clean_df.dropna(subset=['date', 'amount'])
    clean_df = clean_df[clean_df['amount'] > 0]
    
    # Auto-assign category & type
    clean_df['category'] = clean_df['description'].apply(auto_categorize)
    clean_df['type'] = clean_df['category'].apply(lambda c: 'Income' if c == 'Income' else 'Expense')
    
    return clean_df[['date', 'description', 'amount', 'category', 'type']]