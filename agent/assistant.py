import warnings
import logging
import os
import sys
import asyncio
import json
import base64
import io
from PIL import Image
from dotenv import load_dotenv

# --- 1. SETUP PATHS (CRITICAL FIX) ---
# This forces Python to look in the 'Unified_AI_Assistant' folder for imports.
# It fixes the "Import could not be resolved" error.
current_dir = os.path.dirname(os.path.abspath(__file__)) # agent/
parent_dir = os.path.dirname(current_dir)                # Unified_AI_Assistant/
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

# Now we can import standard modules without errors
import google.generativeai as genai
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# --- 2. Clean Logs ---
warnings.filterwarnings("ignore")
logging.getLogger("uvicorn.error").disabled = True
logging.getLogger("uvicorn.access").disabled = True

load_dotenv()
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

# --- 3. HARDWARE CONNECTION ---
SYSTEM_CALLBACK = None
def set_system_state_callback(callback_func):
    global SYSTEM_CALLBACK
    SYSTEM_CALLBACK = callback_func

# --- 4. System Instruction ---
SYSTEM_INSTRUCTION = """
You are Miro, an advanced AI Assistant.
RULES:
1. Vision: If provided with an image, analyze it.
2. Unreleased Tech: Search for rumors/leaks (iPhone 17, etc.).
3. Real World Actions: Use tools. Don't say "I can't".
4. No Code: No python blocks.
5. Multilingual: Reply in user's language.
"""

# --- 5. Server Setup ---
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class VoiceAssistant:
    def __init__(self):
        self.model = genai.GenerativeModel("gemini-2.0-flash-exp", system_instruction=SYSTEM_INSTRUCTION)
        self.chat = self.model.start_chat(history=[
            {"role": "user", "parts": ["System Initialized."]},
            {"role": "model", "parts": ["Hello! I am Miro. Ready to help."]}
        ])
        
        # Session States
        self.email_mode = False; self.email_step = 0; self.email_draft = {}
        self.ride_mode = False; self.ride_step = 0; self.ride_details = {}

    async def process_message(self, data: str):
        global SYSTEM_CALLBACK
        
        # --- LAZY IMPORT (Simplified) ---
        # Since we added 'parent_dir' to sys.path at the top, 
        # we can just import 'tools' directly.
        try:
            from tools import get_system_time, search_web, open_website, send_email, book_ride, search_product, get_weather
        except ImportError:
            return "❌ Error: tools.py not found. Please check your folder structure."

        # --- PARSE INPUT (Text vs Image) ---
        user_text = ""
        user_image = None
        
        try:
            parsed = json.loads(data)
            user_text = parsed.get("text", "")
            if "image" in parsed:
                img_data = base64.b64decode(parsed["image"].split(",")[1])
                user_image = Image.open(io.BytesIO(img_data))
        except json.JSONDecodeError:
            user_text = data

        clean_text = user_text.lower().strip()
        for filler in ["please", "can you", "try to", "ok", "hey miro", "yeah", "do it"]:
            clean_text = clean_text.replace(filler, "")
        clean_text = clean_text.strip()

        # --- 1. VISION HANDLING ---
        if user_image:
            try:
                print("📸 Processing Image with Vision AI...")
                response = self.chat.send_message([user_text, user_image])
                return response.text
            except Exception as e:
                return f"Vision Error: {str(e)}"

        # --- 2. HARDWARE CONTROLS ---
        if "disconnect" in clean_text or "stop" in clean_text: 
            if SYSTEM_CALLBACK: SYSTEM_CALLBACK("stop")
            return "🔌 Disconnected."

        if "activate" in clean_text:
            if "mouse" in clean_text: 
                if SYSTEM_CALLBACK: SYSTEM_CALLBACK("mouse")
                return "🖱️ Mouse Active."
            if "sign" in clean_text: 
                if SYSTEM_CALLBACK: SYSTEM_CALLBACK("sign")
                return "✌️ Sign Active."
            
            # --- THE VISION FIX ---
            if "vision" in clean_text or "camera" in clean_text: 
                if SYSTEM_CALLBACK: SYSTEM_CALLBACK("vision")
                return "👁️ Vision Camera On." # Matches Frontend Check Exactly

        # --- 3. INTERACTIVE MODES ---
        if self.email_mode:
            if "cancel" in clean_text: self.email_mode = False; return "❌ Cancelled."
            if self.email_step == 1: self.email_draft["to"] = user_text.strip(); self.email_step = 2; return "Got it. Subject?"
            if self.email_step == 2: self.email_draft["sub"] = user_text.strip(); self.email_step = 3; return "Message?"
            if self.email_step == 3: 
                self.email_mode = False
                return await send_email(self.email_draft["to"], self.email_draft["sub"], user_text.strip())

        if self.ride_mode:
            if "cancel" in clean_text: self.ride_mode = False; return "❌ Cancelled."
            if self.ride_step == 1: self.ride_details["dest"] = user_text.strip(); self.ride_step = 2; return "Pickup location?"
            if self.ride_step == 2:
                self.ride_mode = False
                return await book_ride(user_text.strip(), self.ride_details["dest"])

        # Triggers
        if "send email" in clean_text: self.email_mode = True; self.email_step = 1; return "Who is this email for?"
        if "book" in clean_text and ("ride" in clean_text or "cab" in clean_text): self.ride_mode = True; self.ride_step = 1; return "Where do you want to go?"

        # --- 4. DYNAMIC TOOLS ---
        try:
            tool_result = ""
            if "open" in clean_text and "search" in clean_text:
                sites = ["youtube", "google", "amazon", "flipkart"]
                site = next((s for s in sites if clean_text.find(s) != -1), None)
                if site:
                    query = clean_text.replace("open","").replace(site,"").replace("search","").replace("for","").replace("the","").strip()
                    if site in ["amazon", "flipkart"]: tool_result = await search_product(query)
                    else: tool_result = await open_website(site, search_query=query)

            elif "buy" in clean_text or "shop" in clean_text:
                product = clean_text.replace("buy","").replace("shop for","").strip()
                tool_result = await search_product(product)

            elif "search" in clean_text or "cost" in clean_text or "price" in clean_text or "news" in clean_text:
                query = clean_text.replace("search","").replace("for","").strip()
                tool_result = await search_web(query)

            elif "open" in clean_text:
                site = clean_text.replace("open","").strip()
                if len(site) > 2: tool_result = await open_website(site)

            elif "time" in clean_text: tool_result = await get_system_time()
            elif "weather" in clean_text: tool_result = await get_weather("Hyderabad")

            if tool_result:
                response = self.chat.send_message(f"User: {user_text}\nTool Result: {tool_result}\nSummarize naturally.")
                return response.text
            
            response = self.chat.send_message(user_text)
            return response.text

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
            response = await assistant.process_message(data)
            await websocket.send_text(response)
    except: pass