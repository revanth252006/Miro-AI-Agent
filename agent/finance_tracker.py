# -*- coding: utf-8 -*-
"""
Miro Personal Finance Tracker — Local SQLite-based expense tracking.
No API keys needed. All data stays on your machine.
"""

import sqlite3
import os
import re
import asyncio
from datetime import datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "miro_finance.db")

# Category keywords for auto-detection
_CATEGORY_MAP = {
    "food": ["food", "lunch", "dinner", "breakfast", "snack", "coffee", "tea", "restaurant",
             "zomato", "swiggy", "biryani", "pizza", "burger", "meal", "eat", "ate"],
    "transport": ["uber", "ola", "auto", "cab", "bus", "train", "metro", "petrol", "fuel",
                  "diesel", "parking", "toll", "flight", "travel", "ride"],
    "shopping": ["shopping", "clothes", "shoes", "amazon", "flipkart", "bought", "purchase",
                 "online", "order", "gadget", "phone", "laptop"],
    "bills": ["bill", "rent", "electricity", "water", "wifi", "internet", "recharge",
              "subscription", "netflix", "spotify", "insurance", "emi"],
    "health": ["medicine", "doctor", "hospital", "pharmacy", "medical", "gym", "health"],
    "education": ["book", "course", "tuition", "class", "exam", "fee", "college", "school"],
    "entertainment": ["movie", "game", "concert", "party", "outing", "fun"],
}


def _init_db():
    """Create the expenses table if it doesn't exist."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            amount REAL NOT NULL,
            category TEXT NOT NULL DEFAULT 'other',
            note TEXT,
            date TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def _detect_category(text: str) -> str:
    """Auto-detect expense category from message text."""
    t = text.lower()
    best_cat = "other"
    best_score = 0
    for cat, keywords in _CATEGORY_MAP.items():
        score = sum(1 for kw in keywords if kw in t)
        if score > best_score:
            best_score = score
            best_cat = cat
    return best_cat


def _extract_amount(text: str) -> float | None:
    """Extract numeric amount from text like '500', '₹1500', 'rs 200'."""
    patterns = [
        r'₹\s*([\d,]+(?:\.\d+)?)',
        r'rs\.?\s*([\d,]+(?:\.\d+)?)',
        r'rupees?\s*([\d,]+(?:\.\d+)?)',
        r'spent\s*([\d,]+(?:\.\d+)?)',
        r'([\d,]+(?:\.\d+)?)\s*(?:rupees?|rs|₹)',
        r'([\d,]+(?:\.\d+)?)\s+on\b',
        r'([\d,]+(?:\.\d+)?)\s+for\b',
    ]
    for pat in patterns:
        match = re.search(pat, text.lower())
        if match:
            amount_str = match.group(1).replace(",", "")
            try:
                return float(amount_str)
            except ValueError:
                continue
    # Last resort: find any standalone number
    match = re.search(r'\b(\d+(?:\.\d+)?)\b', text)
    if match:
        val = float(match.group(1))
        if val > 0:
            return val
    return None


async def log_expense(text: str) -> str:
    """Parse and log an expense from user message.
    
    Examples:
    - "I spent 500 on food today"
    - "₹1500 for shopping"
    - "200 uber ride"
    """
    _init_db()
    
    amount = _extract_amount(text)
    if not amount:
        return "I couldn't detect the amount. Please say something like 'I spent 500 on food'."
    
    category = _detect_category(text)
    note = text.strip()
    today = datetime.now().strftime("%Y-%m-%d")
    
    def _insert():
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "INSERT INTO expenses (amount, category, note, date) VALUES (?, ?, ?, ?)",
            (amount, category, note, today)
        )
        conn.commit()
        conn.close()
    
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _insert)
    return f"✅ Logged **₹{amount:.0f}** under **{category}** for today."


async def get_spending_summary(period: str = "week") -> str:
    """Get spending summary for today/week/month."""
    _init_db()
    
    now = datetime.now()
    if period == "today":
        start = now.strftime("%Y-%m-%d")
        label = "today"
    elif period == "month":
        start = now.replace(day=1).strftime("%Y-%m-%d")
        label = "this month"
    else:  # week
        start = (now - timedelta(days=7)).strftime("%Y-%m-%d")
        label = "this week"
    
    def _query():
        conn = sqlite3.connect(DB_PATH)
        # Category breakdown
        rows = conn.execute(
            "SELECT category, SUM(amount) FROM expenses WHERE date >= ? GROUP BY category ORDER BY SUM(amount) DESC",
            (start,)
        ).fetchall()
        total = conn.execute(
            "SELECT SUM(amount) FROM expenses WHERE date >= ?",
            (start,)
        ).fetchone()[0] or 0
        conn.close()
        return rows, total
    
    loop = asyncio.get_running_loop()
    rows, total = await loop.run_in_executor(None, _query)
    
    if not rows:
        return f"No expenses logged for {label}."
    
    lines = [f"### 💰 Spending Summary ({label})\n"]
    lines.append(f"| Category | Amount |")
    lines.append(f"|----------|--------|")
    for cat, amt in rows:
        emoji = {"food": "🍕", "transport": "🚗", "shopping": "🛍️", "bills": "📄",
                 "health": "💊", "education": "📚", "entertainment": "🎮"}.get(cat, "💸")
        lines.append(f"| {emoji} {cat.title()} | ₹{amt:,.0f} |")
    lines.append(f"\n**Total: ₹{total:,.0f}**")
    return "\n".join(lines)


# Initialize DB on import
_init_db()
