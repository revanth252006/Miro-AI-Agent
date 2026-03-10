import json
import os
import re
import glob
import uuid
import datetime
import threading
from typing import Optional

# --- CONFIGURATION ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MEMORY_FILE = os.path.join(BASE_DIR, "brain.json")
SESSIONS_DIR = os.path.join(BASE_DIR, "sessions")

if not os.path.exists(SESSIONS_DIR):
    os.makedirs(SESSIONS_DIR)

# ─────────────────────────────────────────────────────────────────
# LEARNING PATTERNS — structured extraction rules
# ─────────────────────────────────────────────────────────────────
_PREFERENCE_PATTERNS = [
    # Name
    (r"\bmy name is\s+([A-Za-z]+)", "name"),
    (r"\bcall me\s+([A-Za-z]+)", "name"),
    # Likes / Loves / Enjoys
    (r"\bi (?:like|love|enjoy|prefer|adore)\s+(.+?)(?:\.|$)", "like"),
    # Dislikes / Hates
    (r"\bi (?:hate|dislike|don't like|do not like|despise)\s+(.+?)(?:\.|$)", "dislike"),
    # Want / Need
    (r"\bi (?:want|need|wish for)\s+(.+?)(?:\.|$)", "want"),
    # Habits
    (r"\bi (?:usually|always|often|regularly)\s+(.+?)(?:\.|$)", "habit"),
    # Goals
    (r"\bmy goal is\s+(.+?)(?:\.|$)", "goal"),
    (r"\bi(?:'m| am) trying to\s+(.+?)(?:\.|$)", "goal"),
    (r"\bi(?:'m| am) working on\s+(.+?)(?:\.|$)", "project"),
    # Skills
    (r"\bi(?:'m| am) (?:a|an)\s+([A-Za-z\s]+?)(?:\.|$)", "role"),
    # Location
    (r"\bi(?:'m| am) (?:from|in|based in)\s+([A-Za-z\s,]+?)(?:\.|$)", "location"),
]

class MemoryManager:
    """
    Manages the global brain.json for user facts and long-term learning.
    
    Storage schema:
    {
      "user_name": str | null,
      "history": [...],          # last 50 Gemini-format messages
      "profile": {
        "facts": [...],          # raw statements for legacy compat
        "structured": {          # keyed by category
          "like": [...],
          "dislike": [...],
          "habit": [...],
          "goal": [...],
          ...
        },
        "last_updated": "ISO datetime"
      }
    }
    """
    def __init__(self):
        self._lock = threading.Lock()
        self.data = self._load()
        # Ensure structure
        if "profile" not in self.data:
            self.data["profile"] = {"facts": [], "structured": {}}
        if "structured" not in self.data["profile"]:
            self.data["profile"]["structured"] = {}
        if "history" not in self.data:
            self.data["history"] = []
        self.save()

    def _load(self):
        with self._lock:
            if os.path.exists(MEMORY_FILE):
                try:
                    with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                        return json.load(f)
                except Exception:
                    pass
        return {"user_name": None, "history": [], "profile": {"facts": [], "structured": {}}}

    def save(self):
        with self._lock:
            with open(MEMORY_FILE, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)

    def set_name(self, name: str):
        self.data["user_name"] = name
        self.save()

    def get_name(self) -> Optional[str]:
        return self.data.get("user_name")

    def add_message(self, role: str, text: str):
        """Saves a message to the main history in Gemini SDK-compatible format."""
        self.data["history"].append({"role": role, "parts": [{"text": text}]})
        # Cap at 50 messages to prevent JSON bloat
        if len(self.data["history"]) > 50:
            self.data["history"] = self.data["history"][-50:]
        self.save()

    def get_history(self):
        return self.data.get("history", [])

    # ─────────────────────────────────────────────────────────────────
    # UPGRADED SELF-LEARNING SYSTEM
    # ─────────────────────────────────────────────────────────────────
    def learn_fact(self, text: str) -> list[str]:
        """
        Scans input text for learnable facts using regex patterns.
        Stores structured facts by category. Returns a list of newly learned facts.
        Deduplicates: only stores a fact if it's not already known.
        """
        if not text or len(text) < 5:
            return []
        
        text_lower = text.lower().strip()
        learned = []
        structured = self.data["profile"].setdefault("structured", {})
        raw_facts = self.data["profile"].setdefault("facts", [])

        for pattern, category in _PREFERENCE_PATTERNS:
            match = re.search(pattern, text_lower)
            if match:
                value = match.group(1).strip().rstrip(".,!?")
                if len(value) < 2 or len(value) > 120:
                    continue
                
                # Special handling: update name at top level
                if category == "name":
                    cap_name = value.capitalize()
                    if self.data.get("user_name") != cap_name:
                        self.data["user_name"] = cap_name
                        learned.append(f"name: {cap_name}")
                else:
                    cat_list = structured.setdefault(category, [])
                    # Deduplicate: skip if very similar entry exists
                    already_known = any(
                        value in existing or existing in value
                        for existing in cat_list
                    )
                    if not already_known:
                        cat_list.append(value)
                        # Keep per-category cap at 20 items
                        if len(cat_list) > 20:
                            structured[category] = cat_list[-20:]
                        learned.append(f"{category}: {value}")
        
        # Legacy: also store in raw facts for backward compatibility
        if learned:
            raw_facts.append({"text": text, "extracted": learned, "ts": str(datetime.datetime.now())})
            if len(raw_facts) > 100:
                self.data["profile"]["facts"] = raw_facts[-100:]
            self.data["profile"]["last_updated"] = str(datetime.datetime.now())
            self.save()

        return learned

    def get_profile_context(self) -> str:
        """
        Returns a formatted string of learned user facts for injection into prompts.
        Shows the most recently learned / important facts first.
        """
        lines = []
        name = self.data.get("user_name")
        if name:
            lines.append(f"- User's name: **{name}**")

        structured = self.data.get("profile", {}).get("structured", {})
        
        category_labels = {
            "like": "Likes/Enjoys",
            "dislike": "Dislikes",
            "habit": "Habits",
            "goal": "Goals",
            "project": "Current Projects",
            "role": "Role/Identity",
            "location": "Location",
            "want": "Wants/Needs",
        }
        for cat, label in category_labels.items():
            items = structured.get(cat, [])
            if items:
                # Show up to 5 most recent per category
                snippet = ", ".join(items[-5:])
                lines.append(f"- {label}: {snippet}")

        return "\n".join(lines) if lines else "No user profile facts yet."

    def get_memory_summary(self) -> dict:
        """Returns a summary of what Miro knows about the user."""
        structured = self.data.get("profile", {}).get("structured", {})
        return {
            "name": self.data.get("user_name"),
            "total_facts": sum(len(v) for v in structured.values()),
            "categories": {k: len(v) for k, v in structured.items() if v},
            "last_updated": self.data.get("profile", {}).get("last_updated", "never"),
        }


class SessionManager:
    """Manages separate JSON files for sidebar chat history."""
    def __init__(self):
        self.sessions_dir = SESSIONS_DIR
        self._lock = threading.Lock()

    def create_session(self) -> str:
        return str(uuid.uuid4())[:8]
    
    def save_session(self, session_id: str, history: list, title: str = None):
        session_file = os.path.join(self.sessions_dir, f"{session_id}.json")
        current_title = "New Chat"
        
        if os.path.exists(session_file):
            try:
                with open(session_file, "r") as f:
                    current_title = json.load(f).get("title", "New Chat")
            except Exception:
                pass

        # Auto-generate a title from the first user message if no title
        if not title or title == "New Chat":
            for msg in history[:3]:
                if msg.get("role") == "user":
                    raw = msg.get("parts", [{}])
                    text = raw[0].get("text", "") if isinstance(raw, list) else str(raw)
                    if text:
                        title = text[:48].replace("\n", " ") + ("..." if len(text) > 48 else "")
                        break
            
        data = {
            "id": session_id,
            "title": title or current_title,
            "history": history,
            "timestamp": str(datetime.datetime.now())
        }
        with self._lock:
            with open(session_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
    
    def load_session(self, session_id: str) -> Optional[dict]:
        session_file = os.path.join(self.sessions_dir, f"{session_id}.json")
        if os.path.exists(session_file):
            try:
                with open(session_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return None
    
    def get_all_sessions(self) -> list:
        sessions = []
        if os.path.exists(self.sessions_dir):
            files = glob.glob(os.path.join(self.sessions_dir, "*.json"))
            files.sort(key=os.path.getmtime, reverse=True)
            for file_path in files:
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        sessions.append({
                            "id": data["id"],
                            "title": data.get("title", "Chat"),
                            "timestamp": data.get("timestamp", "")
                        })
                except Exception:
                    continue
        return sessions