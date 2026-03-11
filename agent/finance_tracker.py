# -*- coding: utf-8 -*-
"""
Miro Personal Finance Tracker — Encrypted SQLite-based expense tracking.
Uses MIRO_SECRET_TOKEN for encryption. All data stays on your machine.
SECURITY: Database is encrypted at rest. Decrypted only while agent is running.
"""

import sqlite3
import os
import re
import asyncio
import tempfile
import atexit
from datetime import datetime, timedelta

# --- Encryption ---
try:
    from cryptography.fernet import Fernet, InvalidToken
    ENCRYPTION_AVAILABLE = True
except ImportError:
    ENCRYPTION_AVAILABLE = False
    print("⚠️ cryptography not installed — finance.db will NOT be encrypted (pip install cryptography)")

try:
    from security import derive_fernet_key
except ImportError:
    try:
        from agent.security import derive_fernet_key
    except ImportError:
        derive_fernet_key = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH_ENCRYPTED = os.path.join(BASE_DIR, "miro_finance.db.enc")
DB_PATH_LEGACY = os.path.join(BASE_DIR, "miro_finance.db")  # Pre-encryption path

# Temp decrypted DB path (only exists while running)
_temp_db_path = None

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


# ─────────────────────────────────────────────────────────────────
# ENCRYPTION HELPERS
# ─────────────────────────────────────────────────────────────────
def _get_fernet():
    """Returns a Fernet instance or None."""
    if not ENCRYPTION_AVAILABLE or not derive_fernet_key:
        return None
    try:
        key = derive_fernet_key()
        return Fernet(key)
    except Exception:
        return None


def _get_db_path() -> str:
    """Returns the path to the working (decrypted) database.
    
    On first call:
    1. If encrypted DB exists → decrypt to temp file
    2. If legacy plain DB exists → use it (will encrypt on cleanup)
    3. Otherwise → create new temp DB
    """
    global _temp_db_path
    
    if _temp_db_path and os.path.exists(_temp_db_path):
        return _temp_db_path
    
    fernet = _get_fernet()
    
    # Case 1: Encrypted DB exists → decrypt to temp
    if fernet and os.path.exists(DB_PATH_ENCRYPTED):
        try:
            with open(DB_PATH_ENCRYPTED, "rb") as f:
                encrypted_data = f.read()
            decrypted = fernet.decrypt(encrypted_data)
            
            fd, _temp_db_path = tempfile.mkstemp(suffix=".db", prefix="miro_fin_")
            os.close(fd)
            with open(_temp_db_path, "wb") as f:
                f.write(decrypted)
            return _temp_db_path
        except (InvalidToken, Exception) as e:
            print(f"⚠️ Finance DB decryption failed: {e}")
    
    # Case 2: Legacy unencrypted DB exists → use it directly
    if os.path.exists(DB_PATH_LEGACY):
        _temp_db_path = DB_PATH_LEGACY
        return _temp_db_path
    
    # Case 3: No DB exists → create new temp DB
    if fernet:
        fd, _temp_db_path = tempfile.mkstemp(suffix=".db", prefix="miro_fin_")
        os.close(fd)
    else:
        _temp_db_path = DB_PATH_LEGACY
    
    return _temp_db_path


def _encrypt_and_cleanup():
    """Encrypt the working DB back and delete temp file. Called on exit."""
    global _temp_db_path
    
    if not _temp_db_path or not os.path.exists(_temp_db_path):
        return
    
    fernet = _get_fernet()
    if fernet:
        try:
            with open(_temp_db_path, "rb") as f:
                plain_data = f.read()
            encrypted = fernet.encrypt(plain_data)
            with open(DB_PATH_ENCRYPTED, "wb") as f:
                f.write(encrypted)
            # Remove temp file and legacy unencrypted file
            if _temp_db_path != DB_PATH_LEGACY and os.path.exists(_temp_db_path):
                try:
                    os.remove(_temp_db_path)
                except Exception:
                    pass
            # Remove legacy plain DB if encrypted version now exists
            if os.path.exists(DB_PATH_LEGACY) and os.path.exists(DB_PATH_ENCRYPTED):
                try:
                    os.remove(DB_PATH_LEGACY)
                except Exception:
                    pass
        except Exception as e:
            print(f"⚠️ Finance DB encryption on exit failed: {e}")


# Register cleanup on exit
atexit.register(_encrypt_and_cleanup)


def _init_db():
    """Create the expenses table if it doesn't exist."""
    db_path = _get_db_path()
    conn = sqlite3.connect(db_path)
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
    SECURITY: Never logs raw financial data to console/log files.
    
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
        db_path = _get_db_path()
        conn = sqlite3.connect(db_path)
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
    """Get spending summary for today/week/month.
    SECURITY: Never exposes raw financial data in logs."""
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
        db_path = _get_db_path()
        conn = sqlite3.connect(db_path)
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
