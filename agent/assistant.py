import warnings
import logging
import os
import sys
import asyncio
import json
import base64
import io
import re
import PyPDF2  # <--- NEW: For reading PDFs
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

# --- PERSONALITY PROMPTS ---
PERSONALITIES = {
    "jarvis": "You are J.A.R.V.I.S. You are ultra-polite, highly intelligent, and formal. Call the user 'Sir'.",
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
        # 1. Initialize Memory
        self.memory = MemoryManager()
        self.user_name = self.memory.get_name()
        self.knowledge_base = "" # <--- NEW: Stores text from uploaded files
        
        # 2. Load Past History
        past_history = self.memory.get_history()
        
        # If no history, start fresh.
        if not past_history:
            initial = f"Hello {self.user_name}!" if self.user_name else "Hello! I am Miro."
            self.chat_history = [{"role": "model", "parts": [initial]}]
        else:
            self.chat_history = past_history

        # 3. Initialize Model with Default Persona
        self.current_persona = "default"
        self.model = self._init_model()
        self.chat = self.model.start_chat(history=self.chat_history)
        
        self.email_mode = False; self.email_step = 0; self.email_draft = {}

    def _init_model(self):
        """Re-initializes the model with the current personality AND knowledge base."""
        
        # --- NEW: Inject Knowledge Base (RAG) ---
        kb_context = ""
        if self.knowledge_base:
            kb_context = f"""
            FILE CONTEXT (The user just uploaded this):
            --- START OF FILE ---
            {self.knowledge_base[:30000]} 
            --- END OF FILE ---
            Use the information above to answer questions.
            """

        base_instruction = f"""
        CRITICAL INSTRUCTIONS:
        1. LANGUAGE MATCHING: You MUST reply in the EXACT SAME LANGUAGE the user is currently speaking.
           - If User says "Hello" (English) -> You MUST reply in English.
           - If User says "Namaste" (Telugu) -> You MUST reply in Telugu.
           - Do NOT get stuck in one language. Switch instantly based on the latest input.
        2. KNOWLEDGE BASE: If file context is provided above, use it.
        3. System Control: You can open apps, change volume, and take screenshots.
        4. Vision: Analyze images if provided.
        5. Voice: Reply in plain spoken text (No markdown, no *bold*).
        {kb_context}
        """
        full_instruction = f"{PERSONALITIES[self.current_persona]}\n{base_instruction}"
        return genai.GenerativeModel("gemini-2.0-flash-exp", system_instruction=full_instruction)

    def switch_personality(self, persona_key):
        """Switches the AI mood."""
        if persona_key in PERSONALITIES:
            self.current_persona = persona_key
            self.model = self._init_model() 
            # Restart chat to apply new prompt, but keep history
            self.chat = self.model.start_chat(history=self.chat_history)
            return f"Mode switched to {persona_key.upper()}."
        return "Personality not found."

    def clean_response(self, text):
        return re.sub(r'[\*\#\`\_]', '', text).strip()

    # --- NEW: PROCESS FILE UPLOAD ---
    async def process_file(self, file_data, filename):
        """Extracts text from uploaded PDF or TXT files."""
        try:
            print(f"📂 Processing file: {filename}")
            decoded = base64.b64decode(file_data.split(",")[1])
            text = ""
            
            if filename.lower().endswith(".pdf"):
                reader = PyPDF2.PdfReader(io.BytesIO(decoded))
                for page in reader.pages:
                    text += page.extract_text() + "\n"
            else:
                text = decoded.decode("utf-8")
            
            # Store in Knowledge Base and Update Model
            self.knowledge_base = text
            self.model = self._init_model()
            self.chat = self.model.start_chat(history=self.chat_history)
            
            resp = f"I have read '{filename}'. You can now ask me questions about it!"
            self.memory.add_message("model", resp)
            return resp
        except Exception as e:
            return f"❌ Error reading file: {str(e)}"

    async def process_message(self, data: str):
        global SYSTEM_CALLBACK
        
        # --- LAZY IMPORT TOOLS ---
        try:
            from tools import (get_system_time, search_web, open_website, send_email, 
                             search_product, get_weather, set_volume, take_screenshot, 
                             minimize_windows, open_application)
        except ImportError:
            return "Error: tools.py not found."

        # Parse Input
        user_text = ""
        user_image = None
        try:
            parsed = json.loads(data)
            
            # --- NEW: CHECK FOR FILE UPLOAD ---
            if "type" in parsed and parsed["type"] == "upload":
                return await self.process_file(parsed["file"], parsed["filename"])

            user_text = parsed.get("text", "")
            if "image" in parsed:
                img_data = base64.b64decode(parsed["image"].split(",")[1])
                user_image = Image.open(io.BytesIO(img_data))
        except json.JSONDecodeError:
            user_text = data

        clean_text = user_text.lower().strip()
        if not clean_text and not user_image: return "" 

        # --- MEMORY: SAVE USER MESSAGE ---
        self.memory.add_message("user", user_text)

        # --- MEMORY: CHECK FOR NAME ---
        name_match = re.search(r"my name is (\w+)", clean_text)
        if name_match:
            new_name = name_match.group(1).capitalize()
            self.memory.set_name(new_name)
            resp = f"Nice to meet you, {new_name}. I'll remember that!"
            self.memory.add_message("model", resp)
            return resp

        # --- 1. PERSONALITY SWITCHING ---
        if "activate jarvis" in clean_text or "activate miro" in clean_text: return self.switch_personality("jarvis")
        if "activate bro" in clean_text: return self.switch_personality("bro")
        if "activate professional" in clean_text: return self.switch_personality("professional")
        if "reset mode" in clean_text: return self.switch_personality("default")

        # --- 2. SYSTEM AUTOMATION ---
        if "volume" in clean_text:
            if "up" in clean_text or "increase" in clean_text: return await set_volume("up")
            if "down" in clean_text or "decrease" in clean_text: return await set_volume("down")
            if "mute" in clean_text: return await set_volume("mute")
        
        if "screenshot" in clean_text: return await take_screenshot()
        if "minimize" in clean_text or "hide windows" in clean_text: return await minimize_windows()
        
        if "open" in clean_text:
            # --- STABLE FIX: LIST ITERATION (Do not change) ---
            apps_list = ["notepad", "calculator", "chrome", "vscode", "settings", "cmd", "terminal", "explorer"]
            for app in apps_list:
                if app in clean_text: return await open_application(app)

        # --- 3. HARDWARE CONTROLS ---
        if "disconnect" in clean_text or "stop" in clean_text: 
            if SYSTEM_CALLBACK: SYSTEM_CALLBACK("stop")
            return "Disconnected."

        if "activate" in clean_text:
            if "mouse" in clean_text: 
                if SYSTEM_CALLBACK: SYSTEM_CALLBACK("mouse"); return "Mouse Active."
            if "sign" in clean_text: 
                if SYSTEM_CALLBACK: SYSTEM_CALLBACK("sign"); return "Sign Active."
            if "vision" in clean_text or "camera" in clean_text: 
                if SYSTEM_CALLBACK: SYSTEM_CALLBACK("vision"); return "Vision Camera On."

        # --- 4. VISION & TOOLS ---
        try:
            tool_result = ""
            if user_image:
                print("📸 Processing Image...")
                response = self.chat.send_message([user_text, user_image])
                clean_resp = self.clean_response(response.text)
                self.memory.add_message("model", clean_resp)
                return clean_resp

            # Tool Checks
            if "open" in clean_text and "search" in clean_text:
                sites = ["youtube", "google", "amazon", "flipkart"]
                site = next((s for s in sites if clean_text.find(s) != -1), None)
                if site:
                    query = clean_text.replace("open","").replace(site,"").replace("search","").replace("for","").replace("the","").strip()
                    if site in ["amazon", "flipkart"]: tool_result = await search_product(query)
                    else: tool_result = await open_website(site, search_query=query)
            elif "search" in clean_text or "cost" in clean_text or "price" in clean_text:
                query = clean_text.replace("search","").replace("for","").strip()
                tool_result = await search_web(query)
            elif "open" in clean_text:
                site = clean_text.replace("open","").strip()
                if len(site) > 2: tool_result = await open_website(site)
            elif "time" in clean_text: tool_result = await get_system_time()
            elif "weather" in clean_text: tool_result = await get_weather("Hyderabad")

            if tool_result:
                response = self.chat.send_message(f"User: {user_text}\nTool Result: {tool_result}\nSummarize naturally.")
                clean_resp = self.clean_response(response.text)
                self.memory.add_message("model", clean_resp)
                return clean_resp
            
            # --- NORMAL CHAT ---
            response = self.chat.send_message(user_text)
            clean_resp = self.clean_response(response.text)
            self.memory.add_message("model", clean_resp)
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
            if response:
                await websocket.send_text(response)
    except: pass