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

# --- SESSION MANAGER ---
SESSIONS_DIR = os.path.join(current_dir, "sessions")
if not os.path.exists(SESSIONS_DIR): os.makedirs(SESSIONS_DIR)

class SessionManager:
    def get_all_sessions(self):
        sessions = []
        files = glob.glob(os.path.join(SESSIONS_DIR, "*.json"))
        files.sort(key=os.path.getmtime, reverse=True)
        for f in files:
            try:
                with open(f, 'r') as file:
                    data = json.load(file)
                    sessions.append({"id": os.path.basename(f).replace(".json", ""), "title": data.get("title", "New Chat")})
            except: pass
        return sessions

    def load_session(self, session_id):
        path = os.path.join(SESSIONS_DIR, f"{session_id}.json")
        if os.path.exists(path):
            with open(path, 'r') as f: return json.load(f)
        return None

    def save_session(self, session_id, history, title=None):
        path = os.path.join(SESSIONS_DIR, f"{session_id}.json")
        existing_title = "New Chat"
        if os.path.exists(path):
            try:
                with open(path, 'r') as f: existing_title = json.load(f).get("title", "New Chat")
            except: pass
        data = {"history": history, "title": title if title else existing_title}
        with open(path, 'w') as f: json.dump(data, f, indent=4)

    def create_session(self):
        session_id = str(uuid.uuid4())[:8]
        self.save_session(session_id, [], "New Chat")
        return session_id

# --- PERSONALITY PROMPTS (Original) ---
PERSONALITIES = {
    "Miro": "You are M.I.R.O. You are ultra-polite, highly intelligent, and formal. Call the user 'Sir'.",
    "bro": "You are a chill bro. You use slang, you're relaxed, and you're funny. Call the user 'Bro' or 'Buddy'.",
    "professional": "You are a highly efficient Executive Assistant. You are concise, precise, and serious.",
    "default": "You are Miro, a helpful and friendly AI Assistant. You were created by Revanth and his team."
}

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

class VoiceAssistant:
    def __init__(self):
        self.memory = MemoryManager()
        self.session_manager = SessionManager()
        self.user_name = self.memory.get_name()
        self.knowledge_base = "" 
        
        self.current_session_id = self.session_manager.create_session()
        self.current_persona = "default"
        self.model = self._init_model()
        self.chat = self.model.start_chat(history=[])

    def _init_model(self):
        kb_context = ""
        if self.knowledge_base:
            kb_context = f"FILE CONTEXT:\n{self.knowledge_base[:30000]}\n"

        # RESTORED ORIGINAL PROMPT
        base_instruction = f"""
        CRITICAL INSTRUCTIONS:
        1. LANGUAGE MATCHING: You MUST reply in the EXACT SAME LANGUAGE the user is currently speaking.
        2. KNOWLEDGE BASE: If file context is provided above, use it.
        3. System Control: You can open apps, change volume, and take screenshots.
        4. Vision: Analyze images if provided.
        5. Voice: Reply in plain spoken text (No markdown, no *bold*).
        {kb_context}
        """
        full_instruction = f"{PERSONALITIES[self.current_persona]}\n{base_instruction}"
        return genai.GenerativeModel("gemini-2.0-flash-exp", system_instruction=full_instruction)

    def switch_personality(self, persona_key):
        if persona_key in PERSONALITIES:
            self.current_persona = persona_key
            self.model = self._init_model() 
            self.chat = self.model.start_chat(history=self._get_gemini_history())
            return f"Mode switched to {persona_key.upper()}."
        return "Personality not found."

    def _get_gemini_history(self):
        return [{"role": h["role"], "parts": [h["parts"][0]["text"]]} for h in self.chat.history]

    def clean_response(self, text):
        return re.sub(r'[\*\#\`\_]', '', text).strip()

    async def process_file(self, file_data, filename):
        try:
            decoded = base64.b64decode(file_data.split(",")[1])
            text = ""
            if filename.lower().endswith(".pdf"):
                reader = PyPDF2.PdfReader(io.BytesIO(decoded))
                for page in reader.pages: text += page.extract_text() + "\n"
            else: text = decoded.decode("utf-8")
            self.knowledge_base = text
            self.model = self._init_model()
            self.chat = self.model.start_chat(history=self._get_gemini_history())
            return f"I have read '{filename}'. You can now ask me questions about it!"
        except Exception as e: return f"❌ Error: {str(e)}"

    async def process_message(self, data: str):
        global SYSTEM_CALLBACK
        try:
            from tools import (get_system_time, search_web, open_website, send_email, 
                             search_product, get_weather, set_volume, take_screenshot, 
                             minimize_windows, open_application)
        except ImportError: return "Error: tools.py not found."

        user_text = ""; user_image = None
        try:
            parsed = json.loads(data)
            if parsed.get("type") == "get_history": return json.dumps({"type": "history_list", "data": self.session_manager.get_all_sessions()})
            if parsed.get("type") == "load_session":
                sd = self.session_manager.load_session(parsed["id"])
                if sd:
                    self.current_session_id = parsed["id"]
                    history = [{"role": h["role"], "parts": [h["parts"][0]["text"]]} for h in sd.get("history", [])]
                    self.chat = self.model.start_chat(history=history)
                    return json.dumps({"type": "chat_loaded", "history": sd.get("history", []), "title": sd.get("title")})
            if parsed.get("type") == "new_chat":
                self.current_session_id = self.session_manager.create_session()
                self.chat = self.model.start_chat(history=[])
                return json.dumps({"type": "chat_loaded", "history": [], "title": "New Chat"})

            if parsed.get("type") == "upload": return await self.process_file(parsed["file"], parsed["filename"])
            user_text = parsed.get("text", ""); 
            if "image" in parsed:
                img_data = base64.b64decode(parsed["image"].split(",")[1])
                user_image = Image.open(io.BytesIO(img_data))
        except: user_text = data

        clean_text = user_text.lower().strip()
        if not clean_text and not user_image: return "" 

        # --- RESTORED ORIGINAL FEATURE LOGIC ---
        self.memory.add_message("user", user_text)
        if "activate jarvis" in clean_text: return self.switch_personality("jarvis")
        if "activate bro" in clean_text: return self.switch_personality("bro")
        if "volume" in clean_text:
            if "up" in clean_text: return await set_volume("up")
            if "down" in clean_text: return await set_volume("down")
        if "screenshot" in clean_text: return await take_screenshot()
        if "open" in clean_text:
            for app in ["notepad", "calculator", "chrome"]:
                if app in clean_text: return await open_application(app)
        if "activate" in clean_text:
            if "mouse" in clean_text: SYSTEM_CALLBACK("mouse"); return "Mouse Active."
            if "vision" in clean_text: SYSTEM_CALLBACK("vision"); return "Vision Camera On."

        try:
            if user_image: response = self.chat.send_message([user_text, user_image])
            else: response = self.chat.send_message(user_text)
            
            clean_resp = self.clean_response(response.text)
            
            # --- SAVE SESSION (Gemini Internal History) ---
            hist = []
            for c in self.chat.history:
                hist.append({"role": c.role, "parts": [{"text": c.parts[0].text}]})
            
            title = None
            if len(hist) <= 2: title = user_text[:30]
            self.session_manager.save_session(self.current_session_id, hist, title)
            
            return clean_resp
        except Exception as e: return f"Error: {str(e)}"

    def run(self):
        uvicorn.run(app, host="0.0.0.0", port=8000, log_level="error")

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    assistant = VoiceAssistant()
    try:
        while True:
            data = await websocket.receive_text()
            response = await assistant.process_message(data)
            if response: await websocket.send_text(response)
    except: pass