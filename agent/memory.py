import json
import os

# Save file inside the agent folder
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MEMORY_FILE = os.path.join(BASE_DIR, "brain.json")

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
        """
        Saves a message to history.
        role: 'user' or 'model'
        """
        self.data["history"].append({"role": role, "parts": [text]})
        
        # Limit to last 30 messages to prevent errors
        if len(self.data["history"]) > 30:
            self.data["history"] = self.data["history"][-30:]
        
        self.save()

    def get_history(self):
        """Returns past conversations for Gemini."""
        return self.data["history"]