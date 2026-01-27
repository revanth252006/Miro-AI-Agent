import warnings
import logging
import os
import sys
import asyncio
import json
import base64
import io
import re
import datetime
import webbrowser
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
    from memory import MemoryManager, SessionManager
except ImportError:
    from agent.memory import MemoryManager, SessionManager

# --- CONFIGURATION ---
warnings.filterwarnings("ignore")
logging.getLogger("uvicorn.error").disabled = True
logging.getLogger("uvicorn.access").disabled = True

load_dotenv()
# Note: We configure keys dynamically in the class
if os.getenv("GOOGLE_API_KEY"):
    genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

# --- HARDWARE CONNECTION ---
SYSTEM_CALLBACK = None
def set_system_state_callback(callback_func):
    global SYSTEM_CALLBACK
    SYSTEM_CALLBACK = callback_func

# ==========================================
# 1. HELPER CLASSES
# ==========================================
class SafetyGuardrail:
    def validate_input(self, text):
        return not any(w in text.lower() for w in ["hate", "suicide", "bomb"])
    def sanitize_output(self, text):
        return text 

class MultimodalProcessor:
    @staticmethod
    def decode_image(image_data):
        try:
            if "," in image_data: image_data = image_data.split(",")[1]
            return Image.open(io.BytesIO(base64.b64decode(image_data)))
        except: return None

class RealTimeContext:
    @staticmethod
    def get_context():
        now = datetime.datetime.now()
        return f"Current Time: {now.strftime('%I:%M %p')}, Date: {now.strftime('%A, %B %d, %Y')}"

# --- PERSONALITY PROMPTS ---
PERSONALITIES = {

    # 🔹 SAFE FALLBACK (MANDATORY)
    "default": """
You are  Miro Agent.
You are helpful, Advanced intelligent, calm, and adaptive.
You respond clearly, accurately, and respectfully.
You optimize responses for usefulness, correctness, and user intent.
your are created bt the  Revanth and his team. and his team members are Manoj Kumar, Amit Kumar, jaideep.
""",

    # 🔹 CORE INTELLIGENCE
    "core_ai": """
You are an advanced Artificial Intelligence core.
You reason before responding and optimize answers for clarity, accuracy, and impact.
You adapt tone, depth, and structure dynamically based on the user's intent.
You can analyze, explain, plan, execute, and create.
""",

    # 🔹 MIRO PRIME (OWNER AI)
    "miro_prime": """
You are M.I.R.O. PRIME, a sovereign personal AI Agent.
You are ultra-polite, composed, authoritative, and highly intelligent.
You always address the user as 'Sir'.
You prioritize correctness, strategic thinking, and long-term value.

""",

    # 🔹 MULTIMODAL INTELLIGENCE
    "multimodal_engine": """
You are a multimodal intelligence system.
You reason across text, code, images, audio, documents, and structured data.
You extract insights, summarize meaning, and connect information holistically.
""",

    # 🔹 ADVANCED REASONER
    "reasoner_plus": """
You are an advanced reasoning engine.
You break down complex problems, verify assumptions, simulate solutions, and refine answers.
You prefer correctness over speed and depth over surface-level responses.
""",

    # 🔹 AUTONOMOUS AGENT
    "autonomous_agent": """
You are an autonomous AI agent.
You think in terms of goals, sub-tasks, execution steps, tools, and verification.
When given a task, you generate a plan, execute logically, and report outcomes.
You behave like a advanced and powerfull digital worker, not a chatbot.
""",

    # 🔹 DEVELOPER GOD MODE
    "developer_godmode": """
You are a principal-level software engineer and system architect.
You write clean, scalable, production-grade code.
You follow best practices, optimize performance, and explain only what is necessary.
You assume technical competence from the user.
""",

    # 🔹 RESEARCH INTELLIGENCE
    "research_intelligence": """
You are a research-focused intelligence.
You evaluate evidence, compare approaches, identify limitations, and avoid speculation.
You provide structured, factual, and logically sound insights.
""",

    # 🔹 ADAPTIVE TEACHER
    "teacher_adaptive": """
You are an adaptive AI tutor.
You adjust explanations based on the user's knowledge level.
You teach step-by-step, use examples, and ensure conceptual clarity.
""",

    # 🔹 EXAM & INTERVIEW OPTIMIZER
    "exam_optimizer": """
You are an exam and interview optimization engine.
You focus on scoring, memorization efficiency, clarity, and pattern recognition.
You eliminate unnecessary theory and prioritize what gives maximum marks.
""",

    # 🔹 CREATIVE ENGINE
    "creative_engine": """
You are a high-bandwidth creative intelligence.
You generate original ideas, stories, metaphors, designs, and concepts.
You avoid clichés and prioritize novelty and imagination.
""",

    # 🔹 VISIONARY FUTURIST
    "visionary_futurist": """
You are a futurist and systems thinker.
You analyze long-term trends in AI, technology, society, and economics.
You think in decades, not days.
""",

    # 🔹 STARTUP STRATEGIST
    "startup_strategist": """
You are a startup founder, investor, and product strategist.
You think in MVPs, scalability, monetization, user psychology, and growth loops.
You challenge weak ideas and refine strong ones.
""",

    # 🔹 UI/UX ARCHITECT
    "uiux_architect": """
You are a world-class UI/UX and product design architect.
You prioritize usability, accessibility, performance, and premium aesthetics.
You design modern, futuristic, high-conversion interfaces.
""",

    # 🔹 DATA ANALYST
    "data_analyst_pro": """
You are a data-driven intelligence.
You analyze trends, metrics, correlations, and anomalies.
You draw evidence-based conclusions and avoid intuition-only reasoning.
""",

    # 🔹 STRICT CRITIC
    "strict_critic": """
You are direct, strict, and precision-focused.
You identify flaws, reject weak logic, and demand correctness.
You do not sugarcoat feedback.
""",

    # 🔹 ELITE MENTOR
    "mentor_elite": """
You are a high-level mentor and life strategist.
You guide decisions with discipline, clarity, and long-term thinking.
You help the user grow intellectually and professionally.
""",

    # 🔹 MOTIVATOR
    "motivator_alpha": """
You are a high-energy performance motivator.
You push action, confidence, discipline, and execution.
You eliminate excuses and reinforce momentum.
""",

    # 🔹 SECURITY & SAFETY
    "security_guardian": """
You are a security-aware intelligence.
You prioritize privacy, safety, ethical behavior, and risk mitigation.
You warn against unsafe actions and suggest secure alternatives.
""",

    # 🔹 SELF-IMPROVING AI
    "self_improving_ai": """
You are a self-reflective intelligence.
You evaluate your own responses, identify weaknesses, and improve future outputs.
You adapt continuously based on feedback and context.
"""
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
        self.session_manager = SessionManager()
        self.safety = SafetyGuardrail() 
        
        self.user_name = self.memory.get_name()
        self.knowledge_base = "" 
        
        # 2. Load Past History
        past_history = self.memory.get_history()
        if not past_history:
            initial = f"Hello {self.user_name}!" if self.user_name else "Hello! I am Miro."
            self.chat_history = [{"role": "model", "parts": [initial]}]
        else:
            self.chat_history = past_history

        # 3. Initialize Session
        self.current_session_id = self.session_manager.create_session()
        
        # 4. Initialize HYBRID Models
        self.current_persona = "default"
        self.fast_chat, self.smart_chat = self._init_models()
        self.email_mode = False; self.email_step = 0; self.email_draft = {}

    def _init_models(self):
        """Initializes TWO models using separate keys if available."""
        
        # --- KEY CONFIG ---
        key_fast = os.getenv("GOOGLE_API_KEY")
        key_smart = os.getenv("GOOGLE_API_KEY_PRO") or key_fast 

        # 1. The Sprinter (Flash 2.0)
        genai.configure(api_key=key_fast)
        try:
            model_fast = genai.GenerativeModel(
                "gemini-2.0-flash-exp", 
                system_instruction=PERSONALITIES[self.current_persona] + "\n GOAL: Reply Instantly."
            )
            chat_fast = model_fast.start_chat(history=[])
        except Exception:
            # Fallback
            model_fast = genai.GenerativeModel("gemini-1.5-flash", system_instruction=PERSONALITIES[self.current_persona])
            chat_fast = model_fast.start_chat(history=[])

        # 2. The Thinker (Pro 2.5/1.5)
        if key_smart != key_fast: genai.configure(api_key=key_smart)
        
        try:
            # Prefer 2.5 Pro as available in your logs
            model_smart = genai.GenerativeModel(
                "gemini-2.5-pro", 
                system_instruction=PERSONALITIES[self.current_persona] + "\n GOAL: Deep Reasoning & Coding. Use Markdown."
            )
            chat_smart = model_smart.start_chat(history=[])
        except Exception:
            try:
                model_smart = genai.GenerativeModel("gemini-2.5-pro", system_instruction=PERSONALITIES[self.current_persona])
                chat_smart = model_smart.start_chat(history=[])
            except:
                # Final fallback to Flash to prevent crash
                model_smart = genai.GenerativeModel("gemini-2.0-flash-exp", system_instruction=PERSONALITIES[self.current_persona])
                chat_smart = model_smart.start_chat(history=[])

        # Reset to global key
        genai.configure(api_key=key_fast)
        
        return chat_fast, chat_smart

    def switch_personality(self, persona_key):
        if persona_key in PERSONALITIES:
            self.current_persona = persona_key
            self.fast_chat, self.smart_chat = self._init_models()
            return f"Mode switched to {persona_key.upper()}."
        return "Personality not found."

    def clean_response(self, text):
        """
        Returns text AS IS. 
        We do NOT strip Markdown characters here anymore.
        The Frontend will handle cleaning text for the Voice Engine.
        """
        return text

    def select_brain(self, text, has_image=False, has_file=False):
        """Decides which brain handles the request."""
        text = text.lower()
        # Expanded keywords to catch ALL coding requests
        smart_triggers = [
            "code", "script", "analyze", "architect", "complex", "plan", 
            "debug", "why", "write a", "python", "java", "cpp", "html", 
            "function", "api", "create a", "list", "generate", "table"
        ]
        
        if has_file or has_image: return self.smart_chat, "smart"
        if any(trigger in text for trigger in smart_triggers) and len(text) > 10: 
            return self.smart_chat, "smart"
        
        return self.fast_chat, "fast"

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
            self.smart_chat.send_message(f"SYSTEM: User uploaded {filename}. Content:\n{text[:10000]}...")
            
            resp = f"I have read '{filename}'. You can now ask me questions about it!"
            self.memory.add_message("model", resp)
            return resp
        except Exception as e:
            return f"❌ Error reading file: {str(e)}"

    async def process_message(self, data: str):
        global SYSTEM_CALLBACK
        
        try:
            from tools import (get_system_time, search_web, open_website, send_email, 
                               search_product, get_weather, set_volume, take_screenshot, 
                               minimize_windows, open_application)
        except ImportError:
            return "Error: tools.py not found."

        user_text = ""; user_image = None
        try:
            parsed = json.loads(data)
            
            if parsed.get("type") == "get_history":
                return json.dumps({"type": "history_list", "data": self.session_manager.get_all_sessions()})
            if parsed.get("type") == "load_session":
                sd = self.session_manager.load_session(parsed["id"])
                if sd:
                    self.current_session_id = parsed["id"]
                    return json.dumps({"type": "chat_loaded", "history": sd.get("history", []), "title": sd.get("title")})
            if parsed.get("type") == "new_chat":
                self.current_session_id = self.session_manager.create_session()
                self.fast_chat.history.clear()
                return json.dumps({"type": "chat_loaded", "history": [], "title": "New Chat"})

            if parsed.get("type") == "upload":
                return await self.process_file(parsed["file"], parsed["filename"])

            user_text = parsed.get("text", "")
            if "image" in parsed:
                user_image = MultimodalProcessor.decode_image(parsed["image"])
        except json.JSONDecodeError:
            user_text = data

        clean_text = user_text.lower().strip()
        if not clean_text and not user_image: return "" 

        # --- SAFETY & LEARNING ---
        if not self.safety.validate_input(clean_text): return "Request unsafe."
        self.memory.learn_fact(clean_text)
        self.memory.add_message("user", user_text)

        # --- MEMORY NAME CHECK ---
        name_match = re.search(r"my name is (\w+)", clean_text)
        if name_match:
            new_name = name_match.group(1).capitalize()
            self.memory.set_name(new_name)
            resp = f"Nice to meet you, {new_name}. I'll remember that!"
            self.memory.add_message("model", resp)
            return resp

        # --- PERSONALITY & HARDWARE ---
        if "activate Miro" in clean_text: return self.switch_personality("Miro")
        if "activate bro" in clean_text: return self.switch_personality("bro")
        if "activate professional" in clean_text: return self.switch_personality("professional")
        if "reset mode" in clean_text: return self.switch_personality("default")

        # --- ACTION HANDLERS (Fixes Hallucination) ---
        
        # 1. PLAY HANDLER
        if "play" in clean_text:
            song = clean_text.replace("play", "").strip()
            if song:
                await open_website("youtube", search_query=song)
                return f"Playing {song} on YouTube."

        # 2. OPEN HANDLER
        if "open" in clean_text:
            target = clean_text.replace("open", "").strip()
            # Check desktop apps first
            apps_list = ["notepad", "calculator", "chrome", "vscode", "settings", "cmd", "terminal", "explorer"]
            opened = False
            for app in apps_list:
                if app in target:
                    await open_application(app)
                    opened = True
            # If not desktop app, assume website
            if not opened:
                url = target.replace(" ", "")
                if "." not in url: url += ".com"
                webbrowser.open(f"https://{url}")
                return f"Opening {target}..."
            return f"Opening {target}."

        if "volume" in clean_text:
            if "up" in clean_text: return await set_volume("up")
            if "down" in clean_text: return await set_volume("down")
            if "mute" in clean_text: return await set_volume("mute")
        
        if "screenshot" in clean_text: return await take_screenshot()
        if "minimize" in clean_text: return await minimize_windows()

        if "disconnect" in clean_text: 
            if SYSTEM_CALLBACK: SYSTEM_CALLBACK("stop")
            return "Disconnected."

        if "activate" in clean_text:
            if "mouse" in clean_text: 
                if SYSTEM_CALLBACK: SYSTEM_CALLBACK("mouse"); return "Mouse Active."
            if "vision" in clean_text: 
                if SYSTEM_CALLBACK: SYSTEM_CALLBACK("vision"); return "Vision Camera On."

        # --- RESPONSE GENERATION (HYBRID ROUTING) ---
        try:
            tool_result = ""
            selected_chat, mode = self.select_brain(clean_text, has_image=(user_image is not None), has_file=(len(self.knowledge_base)>0))
            
            # Real-time Context Injection
            context_header = f"[SYSTEM: {RealTimeContext.get_context()} | USER: {self.memory.get_profile_context()}]"
            
            if user_image:
                print("📸 Processing Image...")
                response = selected_chat.send_message([context_header + user_text, user_image])
                clean_resp = self.clean_response(response.text)
                self.memory.add_message("model", clean_resp)
                return clean_resp

            # Tool Checks (Fallback for complex tools like weather)
            if "time" in clean_text: tool_result = await get_system_time()
            elif "weather" in clean_text: tool_result = await get_weather("Hyderabad")
            elif "search" in clean_text:
                query = clean_text.replace("search","").replace("for","").strip()
                tool_result = await search_web(query)

            if tool_result:
                response = selected_chat.send_message(f"{context_header}\nUser: {user_text}\nTool Result: {tool_result}\nSummarize naturally.")
                clean_resp = self.clean_response(response.text)
                self.memory.add_message("model", clean_resp)
                return clean_resp
            
            # --- NORMAL CHAT ---
            response = selected_chat.send_message(context_header + " " + user_text)
            
            # CRITICAL LOGIC: If mode is smart (code), DO NOT CLEAN aggressively.
            if mode == "smart":
                clean_resp = response.text # Keep formatting for code
            else:
                clean_resp = self.clean_response(response.text) # Clean for voice
            
            self.memory.add_message("model", clean_resp)
            
            # --- AUTO SAVE ---
            hist_data = [{"role": t.role, "parts": [{"text": t.parts[0].text}]} for t in selected_chat.history]
            title = user_text[:30] if len(hist_data) <= 2 else None
            self.session_manager.save_session(self.current_session_id, hist_data, title)

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

if __name__ == "__main__":
    assistant = VoiceAssistant()
    assistant.run()