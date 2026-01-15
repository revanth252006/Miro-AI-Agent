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
from duckduckgo_search import DDGS # <--- NEW: For Web Search
import pyautogui # <--- NEW: For Screen Share

# --- SETUP PATHS ---
current_dir = os.path.dirname(os.path.abspath(__file__)) 
parent_dir = os.path.dirname(current_dir)                
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

import google.generativeai as genai
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# --- MEMORY MANAGER (Real-Time Learning) ---
# Saves facts to a file so Miro remembers them forever.
MEMORY_FILE = os.path.join(current_dir, "long_term_memory.json")

class MemoryManager:
    def __init__(self):
        self.memory = {}
        self.load_memory()

    def load_memory(self):
        if os.path.exists(MEMORY_FILE):
            try:
                with open(MEMORY_FILE, 'r') as f:
                    self.memory = json.load(f)
            except: self.memory = {}
        else:
            self.memory = {"user_name": "Revanth", "facts": []}

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
        return [] # We keep history ephemeral for speed, facts are persistent

# --- CONFIG ---
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

# --- TOOLS ---
async def perform_search(query):
    """Real-time Web Search (Google Integration)"""
    try:
        print(f"🔍 Searching: {query}")
        results = DDGS().text(query, max_results=3)
        if not results: return "No results found."
        return "\n".join([f"- {r['title']}: {r['body']}" for r in results])
    except Exception as e: return f"Search Error: {str(e)}"

async def capture_screen():
    """Captures Screen for analysis"""
    try:
        print("📸 Capturing Screen...")
        screenshot = pyautogui.screenshot()
        screenshot = screenshot.resize((1280, 720)) # Optimize size
        return screenshot
    except: return None

# --- PERSONALITY ---
PERSONALITIES = {
    "default": "You are Miro, a highly intelligent AI Assistant with Real-Time Internet Access and Screen Capabilities."
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
        self.memory = MemoryManager()
        self.user_name = self.memory.get_name()
        self.knowledge_base = "" 
        self.chat_history = [{"role": "model", "parts": [f"Hello {self.user_name}! I am ready."]}]
        
        self.current_persona = "default"
        self.model = self._init_model()
        self.chat = self.model.start_chat(history=self.chat_history)
        
    def _init_model(self):
        kb_context = ""
        if self.knowledge_base:
            kb_context = f"FILE CONTENT: {self.knowledge_base[:30000]}"

        # Inject Memory and Search Instructions
        user_memory = self.memory.get_context()

        base_instruction = f"""
        SYSTEM_ROLE: You are Miro, an Advanced AI.
        
        CAPABILITIES:
        1. REAL-TIME SEARCH: You can search the web. If user asks for current info (news, prices), USE SEARCH.
        2. SCREEN SENSE: You can see the user's screen.
        3. MEMORY: You have long-term memory.
           CURRENT MEMORY: {user_memory}
           - If user tells you a fact ("I live in Hyderabad"), SAVE IT.
        4. HARDWARE: You control Mouse, Sign Detection, and Vision.
        5. FILES: {kb_context}
        
        CRITICAL RULES:
        - Match Language EXACTLY (English/Telugu).
        - Reply in plain spoken text.
        """
        return genai.GenerativeModel("gemini-2.0-flash-exp", system_instruction=base_instruction)

    def clean_response(self, text):
        return re.sub(r'[\*\#\`\_]', '', text).strip()

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
            return f"I have read '{filename}'."
        except Exception as e: return f"Error reading file: {str(e)}"

    async def process_message(self, data: str):
        global SYSTEM_CALLBACK
        
        # Lazy Import Tools
        try:
            from tools import (get_system_time, search_web, open_website, send_email, 
                             search_product, get_weather, set_volume, take_screenshot, 
                             minimize_windows, open_application)
        except ImportError: return "Error: tools.py not found."

        user_text = ""; user_image = None
        try:
            parsed = json.loads(data)
            if "type" in parsed and parsed["type"] == "upload":
                return await self.process_file(parsed["file"], parsed["filename"])
            user_text = parsed.get("text", "")
            if "image" in parsed:
                img_data = base64.b64decode(parsed["image"].split(",")[1])
                user_image = Image.open(io.BytesIO(img_data))
        except json.JSONDecodeError: user_text = data

        clean_text = user_text.lower().strip()
        if not clean_text and not user_image: return "" 

        # --- MEMORY UPDATE ---
        if "my name is" in clean_text:
            name = clean_text.split("is")[-1].strip()
            self.memory.set_name(name)
            return f"Nice to meet you, {name}."
        if "i live in" in clean_text or "i like" in clean_text:
            self.memory.add_fact(clean_text)

        # --- SYSTEM AUTOMATION (Your Old Logic) ---
        if "volume" in clean_text:
            if "up" in clean_text: return await set_volume("up")
            if "down" in clean_text: return await set_volume("down")
            if "mute" in clean_text: return await set_volume("mute")
        
        if "minimize" in clean_text: return await minimize_windows()
        
        if "open" in clean_text:
            # Stable App Opener
            apps_list = ["notepad", "calculator", "chrome", "vscode", "settings", "cmd", "terminal", "explorer"]
            for app in apps_list:
                if app in clean_text: return await open_application(app)

        # --- HARDWARE TRIGGERS (Your Old Logic) ---
        if "disconnect" in clean_text: 
            if SYSTEM_CALLBACK: SYSTEM_CALLBACK("stop")
            return "Disconnected."

        if "activate" in clean_text:
            if "mouse" in clean_text: 
                if SYSTEM_CALLBACK: SYSTEM_CALLBACK("mouse"); return "Mouse Active."
            if "sign" in clean_text: 
                if SYSTEM_CALLBACK: SYSTEM_CALLBACK("sign"); return "Sign Active."
            if "vision" in clean_text: 
                if SYSTEM_CALLBACK: SYSTEM_CALLBACK("vision"); return "Vision Camera On."

        try:
            tool_result = ""
            
            # --- NEW: SCREEN SHARE ---
            if "screen" in clean_text and ("what" in clean_text or "see" in clean_text or "analyze" in clean_text):
                screen_img = await capture_screen()
                if screen_img:
                    response = self.chat.send_message(["Here is my screen. What do you see?", screen_img])
                    return self.clean_response(response.text)

            # --- NEW: WEB SEARCH ---
            if "search" in clean_text or "google" in clean_text or "news" in clean_text or "price" in clean_text:
                q = clean_text.replace("search for", "").replace("google", "").replace("search", "").strip()
                search_res = await perform_search(q)
                response = self.chat.send_message(f"User Query: {user_text}\nWeb Search Results:\n{search_res}\nAnswer based on this.")
                return self.clean_response(response.text)

            # --- STANDARD CHAT ---
            if user_image:
                print("📸 Processing Image...")
                response = self.chat.send_message([user_text, user_image])
                return self.clean_response(response.text)

            if "time" in clean_text: tool_result = await get_system_time()
            elif "weather" in clean_text: tool_result = await get_weather("Hyderabad")

            if tool_result:
                response = self.chat.send_message(f"User: {user_text}\nTool Result: {tool_result}\nSummarize naturally.")
            else:
                response = self.chat.send_message(user_text)
            
            return self.clean_response(response.text)

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
            if response:
                await websocket.send_text(response)
    except: pass