import json
import os
import glob
import uuid
import datetime
import threading

# --- CONFIGURATION ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MEMORY_FILE = os.path.join(BASE_DIR, "brain.json")
SESSIONS_DIR = os.path.join(BASE_DIR, "sessions")

# Create sessions folder if it doesn't exist
if not os.path.exists(SESSIONS_DIR):
    os.makedirs(SESSIONS_DIR)

class MemoryManager:
    """Manages the global 'brain.json' for user facts and long-term history."""
    def __init__(self):
        self._lock = threading.Lock()
        self.data = self._load()
        if "profile" not in self.data:
            self.data["profile"] = {"facts": [], "preferences": {}}
            self.save()

    def _load(self):
        with self._lock:  # FIXED: Protect against race conditions on startup
            if os.path.exists(MEMORY_FILE):
                try:
                    with open(MEMORY_FILE, "r") as f:
                        return json.load(f)
                except Exception:
                    pass
        return {"user_name": None, "history": [], "profile": {"facts": []}}

    def save(self):
        with self._lock:
            with open(MEMORY_FILE, "w") as f:
                json.dump(self.data, f, indent=2)

    def set_name(self, name):
        self.data["user_name"] = name
        self.save()

    def get_name(self):
        return self.data.get("user_name")

    def add_message(self, role, text):
        """Saves a message to the main history in Gemini SDK-compatible format."""
        # FIXED: parts must be a list of dicts, not plain strings, for Gemini SDK compatibility
        self.data["history"].append({"role": role, "parts": [{"text": text}]})
        # Limit to last 50 messages to prevent JSON bloat (was 30, too small)
        if len(self.data["history"]) > 50:
            self.data["history"] = self.data["history"][-50:]
        self.save()

    def get_history(self):
        return self.data.get("history", [])
    
    # --- LEARNING CAPABILITY ---
    def learn_fact(self, text):
        """Scans text for user preferences and saves them."""
        text_lower = text.lower()
        if "i like" in text_lower or "i love" in text_lower or "my name is" in text_lower:
            if text not in self.data["profile"].get("facts", []):
                self.data["profile"]["facts"].append(text)
                self.save()

    def get_profile_context(self):
        """Returns learned facts."""
        facts = self.data.get("profile", {}).get("facts", [])
        return "\n".join(f"- {f}" for f in facts[-5:]) if facts else "None"

class SessionManager:
    """Manages separate JSON files for sidebar chat history."""
    def __init__(self):
        self.sessions_dir = SESSIONS_DIR
        self._lock = threading.Lock()

    def create_session(self):
        return str(uuid.uuid4())[:8]
    
    def save_session(self, session_id, history, title=None):
        session_file = os.path.join(self.sessions_dir, f"{session_id}.json")
        current_title = "New Chat"
        
        if os.path.exists(session_file):
            try:
                with open(session_file, "r") as f:
                    current_title = json.load(f).get("title", "New Chat")
            except Exception:
                pass
            
        data = {
            "id": session_id,
            "title": title or current_title,
            "history": history,
            "timestamp": str(datetime.datetime.now())
        }
        with self._lock:
            with open(session_file, "w") as f:
                json.dump(data, f, indent=2)
    
    def load_session(self, session_id):
        session_file = os.path.join(self.sessions_dir, f"{session_id}.json")
        if os.path.exists(session_file):
            try:
                with open(session_file, "r") as f:
                    return json.load(f)
            except Exception:
                pass
        return None
    
    def get_all_sessions(self):
        sessions = []
        if os.path.exists(self.sessions_dir):
            files = glob.glob(os.path.join(self.sessions_dir, "*.json"))
            files.sort(key=os.path.getmtime, reverse=True)
            for file_path in files:
                try:
                    with open(file_path, "r") as f:
                        data = json.load(f)
                        sessions.append({"id": data["id"], "title": data.get("title", "Chat")})
                except Exception:
                    continue
        return sessions