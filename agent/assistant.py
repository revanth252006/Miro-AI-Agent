import warnings
import logging
import os
import sys
import asyncio
import json
import base64
import io
import re
import glob
import uuid
import time
import PyPDF2 
from PIL import Image
from dotenv import load_dotenv

# --- SETUP PATHS ---
current_dir = os.path.dirname(os.path.abspath(__file__)) 
parent_dir = os.path.dirname(current_dir)                
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

import google.generativeai as genai
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# IMPORT MEMORY
try:
    from memory import MemoryManager
except ImportError:
    from agent.memory import MemoryManager

# --- Clean Logs ---
warnings.filterwarnings("ignore")
logging.getLogger("uvicorn.error").disabled = True
logging.getLogger("uvicorn.access").disabled = True

load_dotenv()
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

# --- HARDWARE CONNECTION ---
SYSTEM_CALLBACK = None
def set_system_state_callback(callback_func):
    global SYSTEM_CALLBACK
    SYSTEM_CALLBACK = callback_func

# --- SESSION MANAGER (NEW) ---
SESSIONS_DIR = os.path.join(current_dir, "sessions")
if not os.path.exists(SESSIONS_DIR):
    os.makedirs(SESSIONS_DIR)

class SessionManager:
    def get_all_sessions(self):
        """Returns a list of all chat sessions sorted by date."""
        sessions = []
        files = glob.glob(os.path.join(SESSIONS_DIR, "*.json"))
        files.sort(key=os.path.getmtime, reverse=True)
        
        for f in files:
            try:
                with open(f, 'r') as file:
                    data = json.load(file)
                    sessions.append({
                        "id": os.path.basename(f).replace(".json", ""),
                        "title": data.get("title", "New Chat"),
                        "timestamp": os.path.getmtime(f)
                    })
            except: pass
        return sessions

    def load_session(self, session_id):
        """Loads specific chat history."""
        path = os.path.join(SESSIONS_DIR, f"{session_id}.json")
        if os.path.exists(path):
            with open(path, 'r') as f: return json.load(f)
        return None

    def save_session(self, session_id, history, title=None):
        """Saves chat history to file."""
        path = os.path.join(SESSIONS_DIR, f"{session_id}.json")
        
        # If updating existing, keep the old title unless new one provided
        existing_title = "New Chat"
        if os.path.exists(path) and not title:
            try:
                with open(path, 'r') as f: existing_title = json.load(f).get("title", "New Chat")
            except: pass
        
        final_title = title if title else existing_title
        
        data = {"history": history, "title": final_title}
        with open(path, 'w') as f: json.dump(data, f, indent=4)

    def create_session(self):
        """Creates a fresh session ID."""
        session_id = str(uuid.uuid4())[:8]
        self.save_session(session_id, [], "New Chat")
        return session_id

    def delete_session(self, session_id):
        path = os.path.join(SESSIONS_DIR, f"{session_id}.json")
        if os.path.exists(path): os.remove(path)

# --- PERSONALITY PROMPTS ---
PERSONALITIES = {
    "Miro": "You are M.I.R.O. You are ultra-polite, highly intelligent, and formal. Call the user 'Sir'.",
    "bro": "You are a chill bro. You use slang, you're relaxed, and you're funny. Call the user 'Bro' or 'Buddy'.",
    "professional": "You are a highly efficient Executive Assistant. You are concise, precise, and serious.",
    "default": "You are Miro, a helpful and friendly AI Assistant. You were created by Revanth and his team."
}

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class VoiceAssistant:
    def __init__(self):
        # 1. Initialize Managers
        self.memory = MemoryManager()
        self.session_manager = SessionManager()
        self.user_name = self.memory.get_name()
        self.knowledge_base = "" 
        
        # 2. Session Setup
        self.current_session_id = self.session_manager.create_session()
        self.chat_history = [] # Raw Gemini history format

        # 3. Initialize Model
        self.current_persona = "default"
        self.model = self._init_model()
        self.chat = self.model.start_chat(history=[])
        
        self.email_mode = False; self.email_step = 0; self.email_draft = {}

    def _init_model(self):
        kb_context = ""
        if self.knowledge_base:
            kb_context = f"""
            FILE CONTEXT:
            {self.knowledge_base[:30000]} 
            """

        base_instruction = f"""
        CRITICAL INSTRUCTIONS:
        1. LANGUAGE MATCHING: Reply in the EXACT SAME LANGUAGE the user speaks.
        2. KNOWLEDGE BASE: Use the file context if provided.
        3. System Control: You can open apps, change volume, take screenshots.
        4. Vision: Analyze images if provided.
        {kb_context}
        """
        full_instruction = f"{PERSONALITIES[self.current_persona]}\n{base_instruction}"
        return genai.GenerativeModel("gemini-2.0-flash-exp", system_instruction=full_instruction)

    def switch_personality(self, persona_key):
        if persona_key in PERSONALITIES:
            self.current_persona = persona_key
            self.model = self._init_model() 
            self.chat = self.model.start_chat(history=self.chat_history)
            return f"Mode switched to {persona_key.upper()}."
        return "Personality not found."

    def clean_response(self, text):
        return re.sub(r'[\*\#\`\_]', '', text).strip()

    def _save_current_session(self, user_text_snippet=None):
        """Helper to serialize Gemini history and save to JSON."""
        serializable_history = []
        for content in self.chat.history:
            parts = [{"text": part.text} for part in content.parts]
            serializable_history.append({"role": content.role, "parts": parts})
        
        # Determine Title (Use first user message)
        title = None
        if user_text_snippet:
            # Check if title is generic "New Chat"
            current = self.session_manager.load_session(self.current_session_id)
            if current and current.get("title") == "New Chat":
                title = user_text_snippet[:30] + "..." if len(user_text_snippet) > 30 else user_text_snippet

        self.session_manager.save_session(self.current_session_id, serializable_history, title)

    # --- FILE UPLOAD ---
    async def process_file(self, file_data, filename):
        try:
            print(f"📂 Processing file: {filename}")
            decoded = base64.b64decode(file_data.split(",")[1])
            text = ""
            if filename.lower().endswith(".pdf"):
                reader = PyPDF2.PdfReader(io.BytesIO(decoded))
                for page in reader.pages: text += page.extract_text() + "\n"
            else:
                text = decoded.decode("utf-8")
            
            self.knowledge_base = text
            self.model = self._init_model()
            self.chat = self.model.start_chat(history=self.chat_history)
            return f"I have read '{filename}'. Ask me anything."
        except Exception as e: return f"❌ Error reading file: {str(e)}"

    async def process_message(self, data: str):
        global SYSTEM_CALLBACK
        
        try:
            from tools import (get_system_time, search_web, open_website, search_product, 
                             get_weather, set_volume, take_screenshot, minimize_windows, open_application)
        except ImportError: return "Error: tools.py not found."

        user_text = ""
        user_image = None
        
        try:
            parsed = json.loads(data)
            
            # --- HISTORY COMMANDS ---
            if parsed.get("type") == "get_history":
                return json.dumps({"type": "history_list", "data": self.session_manager.get_all_sessions()})
            
            if parsed.get("type") == "load_session":
                session_data = self.session_manager.load_session(parsed["id"])
                if session_data:
                    self.current_session_id = parsed["id"]
                    # Load history into Gemini format
                    self.chat_history = []
                    for h in session_data.get("history", []):
                        self.chat_history.append({"role": h["role"], "parts": [h["parts"][0]["text"]]})
                    
                    self.chat = self.model.start_chat(history=self.chat_history)
                    return json.dumps({"type": "chat_loaded", "history": session_data.get("history", []), "title": session_data.get("title")})
            
            if parsed.get("type") == "new_chat":
                self.current_session_id = self.session_manager.create_session()
                self.chat_history = []
                self.chat = self.model.start_chat(history=[])
                return json.dumps({"type": "chat_loaded", "history": [], "title": "New Chat"})

            if parsed.get("type") == "delete_session":
                self.session_manager.delete_session(parsed["id"])
                return json.dumps({"type": "history_list", "data": self.session_manager.get_all_sessions()})

            if parsed.get("type") == "upload":
                return await self.process_file(parsed["file"], parsed["filename"])

            user_text = parsed.get("text", "")
            if "image" in parsed:
                img_data = base64.b64decode(parsed["image"].split(",")[1])
                user_image = Image.open(io.BytesIO(img_data))
        except json.JSONDecodeError:
            user_text = data

        clean_text = user_text.lower().strip()
        if not clean_text and not user_image: return "" 

        # --- MEMORY ---
        self.memory.add_message("user", user_text)
        name_match = re.search(r"my name is (\w+)", clean_text)
        if name_match:
            self.memory.set_name(name_match.group(1).capitalize())

        # --- CONTROLS ---
        if "activate jarvis" in clean_text: return self.switch_personality("jarvis")
        if "activate bro" in clean_text: return self.switch_personality("bro")
        
        if "volume" in clean_text:
            if "up" in clean_text: return await set_volume("up")
            if "down" in clean_text: return await set_volume("down")
            if "mute" in clean_text: return await set_volume("mute")
        
        if "screenshot" in clean_text: return await take_screenshot()
        if "minimize" in clean_text: return await minimize_windows()
        if "open" in clean_text:
            for app in ["notepad", "calculator", "chrome", "vscode", "explorer"]:
                if app in clean_text: return await open_application(app)

        if "disconnect" in clean_text: SYSTEM_CALLBACK("stop"); return "Disconnected."
        if "activate" in clean_text:
            if "mouse" in clean_text: SYSTEM_CALLBACK("mouse"); return "Mouse Active."
            if "sign" in clean_text: SYSTEM_CALLBACK("sign"); return "Sign Active."
            if "vision" in clean_text: SYSTEM_CALLBACK("vision"); return "Vision Camera On."

        # --- RESPONSE GENERATION ---
        try:
            tool_result = ""
            if user_image:
                print("📸 Processing Image...")
                response = self.chat.send_message([user_text, user_image])
            elif "search" in clean_text:
                query = clean_text.replace("search","").strip()
                tool_result = await search_web(query)
                response = self.chat.send_message(f"User: {user_text}\nSearchResults: {tool_result}")
            else:
                response = self.chat.send_message(user_text)

            clean_resp = self.clean_response(response.text)
            self.memory.add_message("model", clean_resp)
            
            # SAVE HISTORY
            self._save_current_session(user_text)
            
            return clean_resp

        except Exception as e: return f"Error: {str(e)}"

    def run(self):
        print("🚀 Miro Server running on ws://localhost:8000/ws")
        uvicorn.run(app, host="0.0.0.0", port=8000, log_level="error")

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    assistant = VoiceAssistant()
    try:
        while True:
            data = await websocket.receive_text()
            if not data: continue
            response = await assistant.process_message(data)
            
            # Check if response is JSON (Command) or Text (Chat)
            if response and (response.startswith("{") or response.startswith("[")):
                await websocket.send_text(response)
            elif response:
                await websocket.send_text(response)
    except: pass