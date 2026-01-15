import warnings
import logging
import os
import sys
import asyncio
import json
import base64
import io
import re
import PyPDF2 
from PIL import Image
from dotenv import load_dotenv
# --- NEW IMPORTS ---
from duckduckgo_search import DDGS 
import pyautogui 
from fastapi.responses import RedirectResponse

# --- SETUP PATHS ---
current_dir = os.path.dirname(os.path.abspath(__file__)) 
parent_dir = os.path.dirname(current_dir)                
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

import google.generativeai as genai
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# --- INTERNAL MEMORY CLASS (Fixes Pylance/Import Errors) ---
MEMORY_FILE = os.path.join(current_dir, "long_term_memory.json")

class MemoryManager:
    def __init__(self):
        self.memory = {"user_name": "User", "facts": []}
        self.load_memory()

    def load_memory(self):
        if os.path.exists(MEMORY_FILE):
            try:
                with open(MEMORY_FILE, 'r') as f:
                    data = json.load(f)
                    self.memory.update(data)
            except: pass

    def save_memory(self):
        with open(MEMORY_FILE, 'w') as f:
            json.dump(self.memory, f, indent=4)

    def add_fact(self, fact):
        if fact not in self.memory.get("facts", []):
            self.memory.setdefault("facts", []).append(fact)
            self.save_memory()
    
    def get_context(self):
        return json.dumps(self.memory, indent=2)
    
    def get_name(self):
        return self.memory.get("user_name", "User")
    
    def set_name(self, name):
        self.memory["user_name"] = name
        self.save_memory()
    
    def get_history(self):
        return []

# --- AUTH & GOOGLE ---
try:
    from agent.auth import AuthManager
    from agent.google_tools import GoogleTools
    auth_manager = AuthManager()
    google_tools = GoogleTools(auth_manager)
    GOOGLE_ENABLED = True
except ImportError:
    print("⚠️ Google Auth modules missing. Running in Offline Mode.")
    GOOGLE_ENABLED = False

# --- CONFIG ---
warnings.filterwarnings("ignore")
logging.getLogger("uvicorn.error").disabled = True
load_dotenv()
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

# --- HARDWARE CALLBACK ---
SYSTEM_CALLBACK = None
def set_system_state_callback(callback_func):
    global SYSTEM_CALLBACK
    SYSTEM_CALLBACK = callback_func

# --- PERSONALITY PROMPTS ---
PERSONALITIES = {
    "Miro": "You are M.I.R.O. You are ultra-polite, highly intelligent, and formal. Call the user 'Sir'.",
    "bro": "You are a chill bro. You use slang, you're relaxed, and you're funny. Call the user 'Bro' or 'Buddy'.",
    "professional": "You are a highly efficient Executive Assistant. You are concise, precise, and serious.",
    "default": "You are Miro, a Native Multimodal AI. You can see video, hear audio, search the web, and see the screen."
}

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# --- LOGIN ROUTES ---
@app.get("/login")
def login():
    if GOOGLE_ENABLED:
        return RedirectResponse(auth_manager.get_login_url("http://localhost:8000/auth/callback"))
    return "Google Auth Not Configured"

@app.get("/auth/callback")
def auth_callback(code: str):
    if GOOGLE_ENABLED:
        user_id, name = auth_manager.exchange_code(code, "http://localhost:8000/auth/callback")
        return RedirectResponse(f"http://localhost:5500/frontend/index.html?uid={user_id}&name={name}")
    return "Error"

# --- TOOLS ---
async def perform_search(query):
    try:
        results = DDGS().text(query, max_results=3)
        if not results: return "No results."
        return "\n".join([f"- {r['title']}: {r['body']}" for r in results])
    except Exception as e: return f"Search Error: {str(e)}"

async def capture_screen():
    try:
        return pyautogui.screenshot().resize((1280, 720))
    except: return None

class VoiceAssistant:
    def __init__(self, user_id="guest"):
        self.user_id = user_id
        self.memory = MemoryManager()
        self.user_name = self.memory.get_name()
        self.knowledge_base = "" 
        self.chat_history = [{"role": "model", "parts": ["System Ready."]}]
        self.current_persona = "default"
        self.model = self._init_model()
        self.chat = self.model.start_chat(history=self.chat_history)

    def _init_model(self):
        kb_context = f"FILE: {self.knowledge_base[:30000]}" if self.knowledge_base else ""
        mem = self.memory.get_context()
        
        system = f"""
        {PERSONALITIES[self.current_persona]}
        CAPABILITIES:
        1. WEB SEARCH: Use search tool for live info.
        2. SCREEN SENSE: See the screen.
        3. MEMORY: {mem}
        4. NATIVE MEDIA: Analyze Video/Audio/Images directly.
        5. GOOGLE APPS: Check emails, create docs (if logged in).
        INSTRUCTION: Match user language exactly.
        {kb_context}
        """
        return genai.GenerativeModel("gemini-2.0-flash-exp", system_instruction=system)

    def switch_personality(self, persona_key):
        if persona_key in PERSONALITIES:
            self.current_persona = persona_key
            self.model = self._init_model() 
            self.chat = self.model.start_chat(history=self.chat_history)
            return f"Mode switched to {persona_key.upper()}."
        return "Personality not found."

    def clean_response(self, text):
        return re.sub(r'[\*\#\`\_]', '', text).strip()

    async def process_file(self, file_data, filename, mime_type="application/pdf"):
        try:
            print(f"📂 Processing: {filename}")
            decoded = base64.b64decode(file_data.split(",")[1])
            
            if "video" in mime_type or "audio" in mime_type or "image" in mime_type:
                part = {"mime_type": mime_type, "data": decoded}
                resp = self.chat.send_message([f"Analyze this {mime_type}.", part])
                return self.clean_response(resp.text)
            
            text = ""
            if filename.lower().endswith(".pdf"):
                reader = PyPDF2.PdfReader(io.BytesIO(decoded))
                for p in reader.pages: text += p.extract_text() + "\n"
            else: text = decoded.decode("utf-8")
            
            self.knowledge_base = text
            self.model = self._init_model()
            self.chat = self.model.start_chat(history=self.chat_history)
            return f"Read {filename}."
        except Exception as e: return f"File Error: {str(e)}"

    async def process_message(self, data: str):
        global SYSTEM_CALLBACK
        try: from tools import get_system_time, set_volume, take_screenshot, minimize_windows, open_application, search_product, get_weather
        except: pass

        user_text = ""; user_image = None
        try:
            parsed = json.loads(data)
            if "type" in parsed and parsed["type"] == "upload":
                return await self.process_file(parsed["file"], parsed["filename"], parsed.get("mime", "application/pdf"))
            user_text = parsed.get("text", "")
            if "image" in parsed:
                img_data = base64.b64decode(parsed["image"].split(",")[1])
                user_image = Image.open(io.BytesIO(img_data))
        except: user_text = data

        clean_text = user_text.lower().strip()
        if not clean_text and not user_image: return "" 

        # --- MEMORY UPDATE ---
        if "my name is" in clean_text: 
            self.memory.set_name(clean_text.split("is")[-1].strip())
        if "i live in" in clean_text or "i like" in clean_text:
            self.memory.add_fact(clean_text)

        # --- GOOGLE COMMANDS ---
        if GOOGLE_ENABLED:
            if "check email" in clean_text:
                raw = google_tools.check_emails(self.user_id)
                resp = self.chat.send_message(f"Emails:\n{raw}\nSummarize.")
                return self.clean_response(resp.text)
            
            if "create doc" in clean_text:
                try:
                    title = clean_text.split("called")[1].split("with")[0].strip()
                    content = clean_text.split("with")[1].strip()
                    return google_tools.create_doc(self.user_id, title, content)
                except: return "Say: 'Create doc called Title with content Content'"

        # --- PERSONALITY ---
        if "activate jarvis" in clean_text: return self.switch_personality("jarvis")
        if "activate bro" in clean_text: return self.switch_personality("bro")
        if "activate professional" in clean_text: return self.switch_personality("professional")
        if "reset mode" in clean_text: return self.switch_personality("default")

        # --- SYSTEM ---
        if "volume" in clean_text:
            if "up" in clean_text: await set_volume("up")
            if "down" in clean_text: await set_volume("down")
            if "mute" in clean_text: await set_volume("mute")
            return "Volume Adjusted"
        
        if "open" in clean_text:
            for app in ["notepad", "calculator", "chrome", "vscode"]:
                if app in clean_text: await open_application(app); return f"Opening {app}"

        if "disconnect" in clean_text: SYSTEM_CALLBACK("stop"); return "Disconnected."
        if "activate" in clean_text:
            if "mouse" in clean_text: SYSTEM_CALLBACK("mouse"); return "Mouse Active"
            if "sign" in clean_text: SYSTEM_CALLBACK("sign"); return "Sign Active"
            if "vision" in clean_text: SYSTEM_CALLBACK("vision"); return "Vision Camera"

        # --- VISION / SEARCH / SCREEN ---
        try:
            if "screen" in clean_text and "see" in clean_text:
                screen = await capture_screen()
                resp = self.chat.send_message(["Analyze screen:", screen])
                return self.clean_response(resp.text)

            if "search" in clean_text:
                q = clean_text.replace("search", "").strip()
                res = await perform_search(q)
                resp = self.chat.send_message(f"Query: {user_text}\nData: {res}")
                return self.clean_response(resp.text)

            if user_image:
                resp = self.chat.send_message([user_text, user_image])
            else:
                resp = self.chat.send_message(user_text)
            return self.clean_response(resp.text)

        except Exception as e: return f"Error: {str(e)}"

    def run(self):
        print("🚀 Miro V10 (Final) running on port 8000")
        uvicorn.run(app, host="0.0.0.0", port=8000, log_level="error")

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        init_msg = await websocket.receive_text()
        user_id = json.loads(init_msg).get("uid", "guest")
    except: user_id = "guest"

    assistant = VoiceAssistant(user_id)
    try:
        while True:
            data = await websocket.receive_text()
            resp = await assistant.process_message(data)
            if resp: await websocket.send_text(resp)
    except: pass

if __name__ == "__main__":
    VoiceAssistant().run()