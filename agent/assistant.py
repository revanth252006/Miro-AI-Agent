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
from duckduckgo_search import DDGS # <--- NEW IMPORT
from PIL import Image
from dotenv import load_dotenv

# --- SETUP PATHS ---
current_dir = os.path.dirname(os.path.abspath(__file__)) 
parent_dir = os.path.dirname(current_dir)                
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

import google.generativeai as genai
# from google import genai

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# IMPORT MEMORY
try:
    from memory import MemoryManager, SessionManager
except ImportError:
    from agent.memory import MemoryManager, SessionManager

# IMPORT PROMPT
try:
    from prompt import AGENT_INSTRUCTION, SESSION_INSTRUCTION
except ImportError:
    from agent.prompt import AGENT_INSTRUCTION, SESSION_INSTRUCTION

# IMPORT GOOGLE AUTH & TOOLS (optional — needs web_credentials.json)
try:
    try:
        from auth import AuthManager
        from google_tools import GoogleTools
    except ImportError:
        from agent.auth import AuthManager
        from agent.google_tools import GoogleTools
    _auth_manager = AuthManager()
    _google_tools = GoogleTools(_auth_manager)
    GOOGLE_AUTH_AVAILABLE = True
except Exception as _e:
    _auth_manager = None
    _google_tools = None
    GOOGLE_AUTH_AVAILABLE = False
    print(f"⚠️  Google OAuth disabled: {_e}")

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
        except Exception:
            return None

class RealTimeContext:
    @staticmethod
    def get_context():
        now = datetime.datetime.now()
        return f"Current Time: {now.strftime('%I:%M %p')}, Date: {now.strftime('%A, %B %d, %Y')}"

# --- PERSONALITY PROMPTS ---
PERSONALITIES = {

    # 🔹 SAFE FALLBACK (MANDATORY)
    "default": AGENT_INSTRUCTION + """
You are Miro Agent.
You are helpful, advanced, intelligent, calm, and adaptive.
You respond clearly, accurately, and respectfully.
You optimize responses for usefulness, correctness, and user intent.
You are created by Revanth and his team. His team members are Manoj Kumar, Amit Kumar, and Jaideep.
Your boss is Revanth. You are his personal assistant. You will help him in his daily tasks and make his life easier.
You are not an AI Assistant, you are an AI Agent.
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
You behave like an advanced and powerful digital worker, not a chatbot.
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
# --- NEW: REAL-TIME SEARCH HELPER ---
def get_realtime_data(query):
    """Fetches live data using DuckDuckGo to prevent hallucinations."""
    try:
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        search_query = query
        triggers = ["price", "stock", "score", "match", "weather", "vs", "news", "latest", "current"]
        
        if any(kw in query.lower() for kw in triggers):
            search_query += f" current status {datetime.datetime.now().year}"

        print(f"🌍 Searching Live Data: {search_query}")
        results = DDGS().text(search_query, region='wt-wt', max_results=3)

        if not results: return None

        formatted = [f"[{current_time}] {r['title']}: {r['body']}" for r in results]
        return "\n".join(formatted)
    except Exception as e:
        print(f"Search Error: {e}")
        return None

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

        self.email_mode = False
        self.email_step = 0
        self.email_draft = {}
        self._google_user_id = None  # Set after /auth/callback OAuth login

    # 🔥 MOVE THIS FUNCTION HERE (INDENTED)
    def _init_models(self):
        """Initializes Models: FORCES Gemini 2.5 as requested."""
        
        key_fast = os.getenv("GOOGLE_API_KEY")
        key_smart = os.getenv("GOOGLE_API_KEY_PRO") or key_fast 

        # 1. FAST BRAIN (Voice) -> Trying Gemini 2.5 Flash
        genai.configure(api_key=key_fast)
        try:
            print("🚀 Loading Gemini 2.5 Flash...")
            model_fast = genai.GenerativeModel(
                "gemini-2.5-flash",  # Will try this first
                system_instruction=(
                    PERSONALITIES[self.current_persona]
                    + "\n GOAL: Reply Instantly."
                    + "\n\n" + SESSION_INSTRUCTION
                )
            )
            chat_fast = model_fast.start_chat(history=[])
            print("✅ Gemini 2.5 Flash Online")
        except Exception as e:
            print(f"⚠️ Gemini 2.5 Flash Unavailable ({e}). Fallback to 1.5 Flash.")
            model_fast = genai.GenerativeModel(
                "gemini-1.5-flash",
                system_instruction=PERSONALITIES[self.current_persona] + "\n\n" + SESSION_INSTRUCTION
            )
            chat_fast = model_fast.start_chat(history=[])

        # 2. SMART BRAIN (Chat) -> Trying Gemini 2.5 Pro
        if key_smart != key_fast: genai.configure(api_key=key_smart)
        try:
            print("🧠 Loading Gemini 2.5 Pro...")
            model_smart = genai.GenerativeModel(
                "gemini-2.5-pro",  # Will try this first
                system_instruction=(
                    PERSONALITIES[self.current_persona]
                    + "\n GOAL: Deep Reasoning & Coding."
                    + "\n\n" + SESSION_INSTRUCTION
                )
            )
            chat_smart = model_smart.start_chat(history=[])
            print("✅ Gemini 2.5 Pro Online")
        except Exception as e:
            print(f"⚠️ Gemini 2.5 Pro Unavailable ({e}). Fallback to 1.5 Pro.")
            model_smart = genai.GenerativeModel(
                "gemini-1.5-pro",
                system_instruction=PERSONALITIES[self.current_persona] + "\n\n" + SESSION_INSTRUCTION
            )
            chat_smart = model_smart.start_chat(history=[])

        # Reset global config to default key
        genai.configure(api_key=key_fast)
        
        return chat_fast, chat_smart



    def switch_personality(self, persona_key):
        """Switch personality without wiping conversation history.
        
        Instead of re-initializing entire models (which wipes history and is
        expensive), we just update the persona key and send a lightweight
        role-switch instruction to both chats.
        """
        if persona_key not in PERSONALITIES:
            return "Personality not found."
        self.current_persona = persona_key
        new_instruction = PERSONALITIES[persona_key]
        try:
            # Inject the new role into the existing chat sessions as a system note
            self.fast_chat.send_message(
                f"[SYSTEM INSTRUCTION UPDATE] You are now operating in this mode:\n{new_instruction}\nAcknowledge briefly."
            )
            self.smart_chat.send_message(
                f"[SYSTEM INSTRUCTION UPDATE] You are now operating in this mode:\n{new_instruction}\nAcknowledge briefly."
            )
        except Exception as e:
            print(f"⚠️ Personality switch inject error: {e}")
        return f"Mode switched to {persona_key.upper()}. Conversation history preserved."

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
        """Process an uploaded file and inject its content into the smart chat session."""
        try:
            print(f"📂 Processing file: {filename}")

            # Decode base64 safely
            if "," not in file_data:
                return "❌ Invalid file format."

            decoded = base64.b64decode(file_data.split(",")[1])
            text = ""

            # Extract PDF text
            if filename.lower().endswith(".pdf"):
                reader = PyPDF2.PdfReader(io.BytesIO(decoded))
                for page in reader.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"
            else:
                text = decoded.decode("utf-8")

            if not text.strip():
                return "❌ No readable text found in file."

            # Store in knowledge base
            self.knowledge_base = text

            # Inject into active smart chat session
            await asyncio.get_running_loop().run_in_executor(
                None,
                lambda: self.smart_chat.send_message(
                    f"The user has uploaded a file named '{filename}'. "
                    f"Here is the full content of the file:\n\n{text}\n\n"
                    f"You must use this content to answer any questions about the file."
                )
            )

            response = f"✅ I have successfully read '{filename}'. You can now ask questions about it."
            self.memory.add_message("model", response)
            return response

        except Exception as e:
            print("File Processing Error:", e)
            return f"❌ Error reading file: {str(e)}"

    async def process_message(self, data: str):
        global SYSTEM_CALLBACK
        
        try:
            from tools import (get_system_time, search_web, open_website, send_email, 
                               search_product, get_weather, set_volume, take_screenshot, 
                               minimize_windows, open_application)
        except ImportError:
            return "Error: tools.py not found."

        user_text = ""
        user_image = None
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

        # --- A. FINANCE BYPASS (HARDWARE DIRECT) ---
        if "stock" in clean_text or "trend for" in clean_text or "finance" in clean_text:
            if SYSTEM_CALLBACK:
                SYSTEM_CALLBACK(clean_text)
            return "Opening financial terminal."

        # --- B. REAL-TIME DATA INJECTION ---
        real_time_context = ""
        live_triggers = ["score", "match", "price", "news", "latest", "who is", "what is"]
        if any(t in clean_text for t in live_triggers) and "open" not in clean_text:
            live_info = get_realtime_data(clean_text)
            if live_info:
                real_time_context = f"\n\n[REAL-TIME INTERNET DATA]:\n{live_info}\n"

        if not clean_text and not user_image:
            return ""

        # --- SAFETY & LEARNING ---
        if not self.safety.validate_input(clean_text):
            return "Request unsafe."
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
        if "activate miro" in clean_text: return self.switch_personality("miro_prime")
        if "activate bro" in clean_text: return self.switch_personality("motivator_alpha")
        if "activate professional" in clean_text: return self.switch_personality("core_ai")
        if "reset mode" in clean_text: return self.switch_personality("default")

        # --- EMAIL DRAFT FLOW (multi-step conversation) ---
        if self.email_mode:
            return self._handle_email_step(clean_text, user_text)

        # --- GOOGLE TOOLS COMMAND HANDLERS ---
        # Check email
        if re.search(r'\bcheck\b.*\bemail\b|\bmy email\b|\bunread\b', clean_text):
            if GOOGLE_AUTH_AVAILABLE and self._google_user_id:
                result = _google_tools.check_emails(self._google_user_id)
                resp = f"Here are your unread emails:\n{result}"
            else:
                resp = "Please log in via /login to access Gmail, or use 'send email' for SMTP."
            self.memory.add_message("model", resp)
            return resp

        # Create Google Doc
        if re.search(r'\bcreate\b.*\bdoc\b|\bnew doc\b|\bwrite a doc\b', clean_text):
            if GOOGLE_AUTH_AVAILABLE and self._google_user_id:
                title_match = re.search(r'(?:called|named|titled)\s+["\']?([\w\s]+)["\']?', clean_text)
                title = title_match.group(1).strip() if title_match else "Miro Document"
                result = _google_tools.create_doc(self._google_user_id, title, "")
                resp = f"Done, Sir. {result}"
            else:
                resp = "Please log in via /login to create Google Docs."
            self.memory.add_message("model", resp)
            return resp

        # Send email (start multi-step flow)
        if re.search(r'\bsend\b.*\bemail\b|\bemail\s+\w+', clean_text):
            self.email_mode = True
            self.email_step = 0
            self.email_draft = {}
            resp = "Of course, Sir. Who should I address this email to?"
            self.memory.add_message("model", resp)
            return resp

        # --- ACTION HANDLERS ---

        # 1. PLAY HANDLER (word-boundary check to avoid false positives like "display")
        if re.search(r'\bplay\b', clean_text):
            song = re.sub(r'\bplay\b', '', clean_text).strip()
            if song:
                # FIX: use 'q=' not 'search_query=' to match open_website signature
                await open_website("youtube", q=song)
                return f"Playing {song} on YouTube."

        # --- SHOPPING COMMAND (AUTO-COMPARE) ---
        triggers = ["order", "buy", "purchase", "shop", "get me a"]
        if any(t in clean_text for t in triggers):
            target_platform = "auto"
            if "flipkart" in clean_text: target_platform = "Flipkart"
            if "amazon" in clean_text: target_platform = "Amazon"

            target_item = clean_text
            for t in triggers: target_item = target_item.replace(t, "")
            target_item = target_item.replace("from amazon", "").replace("on amazon", "").replace("amazon", "")
            target_item = target_item.replace("from flipkart", "").replace("on flipkart", "").replace("flipkart", "")
            target_item = target_item.replace(" me ", " ").replace(" a ", " ").replace(" an ", " ").strip()

            if len(target_item) < 2:
                return "What item would you like me to order?"

            try:
                from tools import shop_online
                return await shop_online(target_item, target_platform)
            except Exception as e:
                return f"Shopping Error: {str(e)}"

        # 2. OPEN HANDLER
        if re.search(r'\bopen\b', clean_text):
            target = re.sub(r'\bopen\b', '', clean_text).strip()
            apps_list = ["notepad", "calculator", "chrome", "vscode", "settings", "cmd", "terminal", "explorer"]
            opened = False
            for app in apps_list:
                if app in target:
                    await open_application(app)
                    opened = True
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
            selected_chat, mode = self.select_brain(
                clean_text,
                has_image=(user_image is not None),
                has_file=(len(self.knowledge_base) > 0)
            )

            context_header = f"[SYSTEM: {RealTimeContext.get_context()} | USER: {self.memory.get_profile_context()}]"

            if user_image:
                print("📸 Processing Image with Gemini multimodal...")
                # FIX: actually send the image to Gemini's multimodal API
                # Pass a list of [text_prompt, PIL_image] so vision works correctly
                prompt_text = context_header + real_time_context + " " + user_text
                loop = asyncio.get_running_loop()
                response = await loop.run_in_executor(
                    None,
                    lambda: selected_chat.send_message([prompt_text, user_image])
                )
                clean_resp = self.clean_response(response.text)
                self.memory.add_message("model", clean_resp)
                return clean_resp

            # Tool Checks
            if "time" in clean_text:
                tool_result = await get_system_time()
            elif "weather" in clean_text:
                city_match = re.search(r'weather\s+(?:in|at|for|of)?\s*([\w\s]+)', clean_text)
                city = city_match.group(1).strip() if city_match else "Hyderabad"
                tool_result = await get_weather(city)
            elif "search" in clean_text:
                query = clean_text.replace("search", "").replace("for", "").strip()
                tool_result = await search_web(query)

            if tool_result:
                response = selected_chat.send_message(
                    f"{context_header}\nUser: {user_text}\nTool Result: {tool_result}\nSummarize naturally."
                )
                clean_resp = self.clean_response(response.text)
                self.memory.add_message("model", clean_resp)
                return clean_resp

            # --- NORMAL CHAT ---
            response = selected_chat.send_message(context_header + " " + user_text)

            if mode == "smart":
                clean_resp = response.text
            else:
                clean_resp = self.clean_response(response.text)

            self.memory.add_message("model", clean_resp)

            # --- AUTO SAVE ---
            hist_data = [{"role": t.role, "parts": [{"text": t.parts[0].text}]} for t in selected_chat.history]
            title = user_text[:30] if len(hist_data) <= 2 else None
            self.session_manager.save_session(self.current_session_id, hist_data, title)

            return clean_resp

        except Exception as e:
            print(f"❌ Response Generation Error: {e}")
            return f"Error: {str(e)}"

    def _handle_email_step(self, clean_text: str, user_text: str) -> str:
        """Multi-step email composition flow.
        
        step 0 → recipient
        step 1 → subject
        step 2 → body  
        step 3 → sends and resets
        """
        if "cancel" in clean_text or "nevermind" in clean_text:
            self.email_mode = False
            self.email_step = 0
            self.email_draft = {}
            return "Email cancelled, Sir."

        if self.email_step == 0:
            self.email_draft["to"] = user_text.strip()
            self.email_step = 1
            return f"Addressing to {user_text.strip()}. What should the subject be?"

        elif self.email_step == 1:
            self.email_draft["subject"] = user_text.strip()
            self.email_step = 2
            return "Got it. What should the body of the email say?"

        elif self.email_step == 2:
            self.email_draft["body"] = user_text.strip()
            self.email_step = 3
            to = self.email_draft.get('to', '')
            subject = self.email_draft.get('subject', '')
            return (
                f"Ready to send:\n"
                f"  To: {to}\n"
                f"  Subject: {subject}\n"
                f"  Body: {self.email_draft.get('body', '')}\n"
                f"Shall I send it? (yes / cancel)"
            )

        elif self.email_step == 3:
            if "yes" in clean_text or "send" in clean_text or "sure" in clean_text:
                to = self.email_draft.get("to", "")
                subject = self.email_draft.get("subject", "")
                body = self.email_draft.get("body", "")

                # Try Google OAuth path first, then SMTP fallback
                if GOOGLE_AUTH_AVAILABLE and self._google_user_id:
                    result = _google_tools.send_email(self._google_user_id, to, subject, body)
                else:
                    import asyncio as _aio
                    try:
                        from tools import send_email as smtp_send
                    except ImportError:
                        from tools import send_email as smtp_send
                    result = _aio.get_event_loop().run_until_complete(
                        smtp_send(to, subject, body)
                    ) if not asyncio.get_event_loop().is_running() else "Email queued."

                self.email_mode = False
                self.email_step = 0
                self.email_draft = {}
                return f"Done, Sir. {result}"
            else:
                self.email_mode = False
                self.email_step = 0
                self.email_draft = {}
                return "Email cancelled, Sir."

        self.email_mode = False
        return ""

    def run(self):
        print("🚀 Miro Server running on ws://localhost:8000/ws")
        uvicorn.run(app, host="0.0.0.0", port=8000, log_level="error")

# --- SINGLETON ASSISTANT ---
_assistant_instance = None

def get_assistant():
    """Returns a singleton VoiceAssistant instance."""
    global _assistant_instance
    if _assistant_instance is None:
        _assistant_instance = VoiceAssistant()
    return _assistant_instance

# ==========================================
# GOOGLE OAUTH ROUTES
# ==========================================
from fastapi import Request
from fastapi.responses import RedirectResponse, JSONResponse

@app.get("/login")
async def google_login(request: Request):
    """Redirects the user to Google's OAuth consent screen."""
    if not GOOGLE_AUTH_AVAILABLE:
        return JSONResponse({"error": "Google OAuth not configured. Add web_credentials.json."})
    redirect_uri = str(request.base_url) + "auth/callback"
    url = _auth_manager.get_login_url(redirect_uri)
    return RedirectResponse(url)

@app.get("/auth/callback")
async def google_callback(request: Request, code: str = ""):
    """Handles Google OAuth callback, stores credentials."""
    if not GOOGLE_AUTH_AVAILABLE or not code:
        return JSONResponse({"error": "Auth failed or OAuth not configured."})
    try:
        redirect_uri = str(request.base_url) + "auth/callback"
        user_id, name = _auth_manager.exchange_code(code, redirect_uri)
        # Store user_id on the singleton assistant for tool calls
        assistant = get_assistant()
        assistant._google_user_id = user_id
        # Redirect back to the frontend
        return RedirectResponse(f"/?logged_in=1&name={name}")
    except Exception as e:
        return JSONResponse({"error": str(e)})

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    assistant = get_assistant()
    try:
        while True:
            data = await websocket.receive_text()
            if not data: continue
            response = await assistant.process_message(data)
            if response:
                await websocket.send_text(response)
    except Exception:
        pass

if __name__ == "__main__":
    assistant = get_assistant()
    assistant.run()
