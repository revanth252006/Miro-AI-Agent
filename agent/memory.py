import json
import os
import glob
import uuid

# 1. Define BASE_DIR first (The folder where this script is located)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 2. Define filenames using the newly created BASE_DIR
MEMORY_FILE = os.path.join(BASE_DIR, "brain.json")
SESSIONS_DIR = os.path.join(BASE_DIR, "sessions")

# 3. Create the sessions folder if it doesn't exist
if not os.path.exists(SESSIONS_DIR):
    os.makedirs(SESSIONS_DIR)

class MemoryManager:
    def __init__(self):
        self.data = self._load()

    def _load(self):
        """Loads memory from file, or creates empty if new."""
        if os.path.exists(MEMORY_FILE):
            try:
                with open(MEMORY_FILE, "r") as f:
                    return json.load(f)
            except:
                pass
        return {"user_name": None, "history": []}

    def save(self):
        """Writes memory to file."""
        with open(MEMORY_FILE, "w") as f:
            json.dump(self.data, f, indent=2)

    def set_name(self, name):
        self.data["user_name"] = name
        self.save()

    def get_name(self):
        return self.data.get("user_name")

    def add_message(self, role, text):
        """Saves a message to history."""
        self.data["history"].append({"role": role, "parts": [text]})
        if len(self.data["history"]) > 30:
            self.data["history"] = self.data["history"][-30:]
        self.save()

    def get_history(self):
        return self.data["history"]

class SessionManager:
    """Manages separate JSON files for each chat conversation."""
    def get_all_sessions(self):
        sessions = []
        files = glob.glob(os.path.join(SESSIONS_DIR, "*.json"))
        # Sort by last modified time (newest first)
        files.sort(key=os.path.getmtime, reverse=True)
        for f in files:
            try:
                with open(f, 'r') as file:
                    data = json.load(file)
                    sessions.append({
                        "id": os.path.basename(f).replace(".json", ""),
                        "title": data.get("title", "New Chat")
                    })
            except: pass
        return sessions

    def load_session(self, session_id):
        path = os.path.join(SESSIONS_DIR, f"{session_id}.json")
        if os.path.exists(path):
            with open(path, 'r') as f: return json.load(f)
        return None

    def save_session(self, session_id, history, title=None):
        path = os.path.join(SESSIONS_DIR, f"{session_id}.json")
        if os.path.exists(path) and not title:
            try:
                with open(path, 'r') as f: title = json.load(f).get("title", "New Chat")
            except: title = "New Chat"
        
        with open(path, 'w') as f:
            json.dump({"history": history, "title": title or "New Chat"}, f, indent=2)

    def create_session(self):
        session_id = str(uuid.uuid4())[:8]
        self.save_session(session_id, [], "New Chat")
        return session_id