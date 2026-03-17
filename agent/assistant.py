# -*- coding: utf-8 -*-
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
from google.api_core.exceptions import ResourceExhausted
import openai
import requests as _requests  # for Ollama local API
# from google import genai

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# SECURITY MODULE
try:
    from security import (
        InputSanitizer, RateLimiter, SecurityLogger, check_credentials,
        verify_token, is_command_allowed
    )
except ImportError:
    from agent.security import (
        InputSanitizer, RateLimiter, SecurityLogger, check_credentials,
        verify_token, is_command_allowed
    )

# Global security instances
_rate_limiter = RateLimiter(max_requests=30, window_seconds=60)

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

# Finance Tracker (local SQLite, no API needed)
try:
    from finance_tracker import log_expense, get_spending_summary
except ImportError:
    try:
        from agent.finance_tracker import log_expense, get_spending_summary
    except ImportError:
        log_expense = None
        get_spending_summary = None

# WhatsApp Integration
try:
    import pywhatkit
    WHATSAPP_AVAILABLE = True
except ImportError:
    pywhatkit = None
    WHATSAPP_AVAILABLE = False
    print("⚠️ pywhatkit not installed — WhatsApp disabled (pip install pywhatkit)")

# Screen Reader (PIL + pytesseract)
try:
    from screen_reader import describe_screen, capture_screen
except ImportError:
    try:
        from agent.screen_reader import describe_screen, capture_screen
    except ImportError:
        describe_screen = None
        capture_screen = None

# Google Calendar
try:
    from google_calendar import get_todays_events, create_event, parse_schedule_command
except ImportError:
    try:
        from agent.google_calendar import get_todays_events, create_event, parse_schedule_command
    except ImportError:
        get_todays_events = None
        create_event = None
        parse_schedule_command = None

# Vector Memory (ChromaDB)
try:
    from vector_memory import VectorMemory
    VECTOR_MEMORY_AVAILABLE = True
except ImportError:
    try:
        from agent.vector_memory import VectorMemory
        VECTOR_MEMORY_AVAILABLE = True
    except ImportError:
        VectorMemory = None
        VECTOR_MEMORY_AVAILABLE = False

# --- CONFIGURATION ---
warnings.filterwarnings("ignore")
logging.getLogger("uvicorn.error").disabled = True
logging.getLogger("uvicorn.access").disabled = True

load_dotenv(override=True)  # override=True ensures .env values win over stale OS-level env vars
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
    allow_origins=["http://127.0.0.1:8000", "http://localhost:8000", "https://miro-ai-agent.vercel.app"],
    allow_methods=["*"],
    allow_headers=["*"],
)
# --- REAL-TIME SEARCH HELPER (ASYNC — fixes WebSocket timeout) ---
async def get_realtime_data(query: str) -> str | None:
    """Fetches live data using DuckDuckGo in a thread pool so the async
    event loop is never blocked. Has an 8-second hard timeout.
    WS error 1001/1012 was caused by this being a blocking sync call."""
    def _blocking_search():
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        # BF1 FIX: Always append year — search fires on ALL factual questions now
        search_query = f"{query} {datetime.datetime.now().year}"
        print(f"🌍 Live Search: {search_query}")
        results = DDGS().text(search_query, region='in-en', max_results=5)
        if not results:
            return None
        lines = []
        for r in results:
            lines.append(f"**{r['title']}**\n{r['body']}\nSource: {r.get('href', '')}")
        return f"[Live data as of {current_time}]\n\n" + "\n\n---\n\n".join(lines)

    try:
        return await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(None, _blocking_search),
            timeout=8.0
        )
    except asyncio.TimeoutError:
        print("⏱️ Real-time search timed out (8s)")
        return None
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
        self.knowledge_base = ""       # extracted text from uploaded file
        self.knowledge_base_name = ""  # original filename

        # 2. Load Past History
        past_history = self.memory.get_history()
        if not past_history:
            initial = f"Hello {self.user_name}!" if self.user_name else "Hello! I am Miro."
            self.chat_history = [{"role": "model", "parts": [initial]}]
        else:
            self.chat_history = past_history

        # 3. Initialize Session
        self.current_session_id = self.session_manager.create_session()

        # 4. Ollama as FALLBACK (F5: enabled, but only used when Gemini hits 429)
        self.current_persona = "default"
        self.ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434")
        self.ollama_model = os.getenv("OLLAMA_MODEL", "llama3")
        self.ollama_available = self._check_ollama()  # F5: re-enabled as fallback

        # 5. Initialize Gemini (Fallback for images + complex tasks)
        self.fast_chat, self.smart_chat = self._init_models()

        # 6. Initialize OpenAI as last-resort fallback
        self.openai_client = None
        openai_key = os.getenv("OPENAI_API_KEY")
        if openai_key:
            try:
                openai.api_key = openai_key
                self.openai_client = openai.OpenAI(api_key=openai_key)
                print("✅ OpenAI client initialized as last-resort fallback")
            except Exception as oe:
                print(f"⚠️ OpenAI init failed: {oe}")
        else:
            print("⚠️ No OPENAI_API_KEY in .env — OpenAI fallback disabled")

        self.email_mode = False
        self.email_step = 0
        self.email_draft = {}
        self._google_user_id = None  # Set after /auth/callback OAuth login

        # Wake word broadcast support
        self._active_ws = []           # Active WebSocket connections
        self._event_loop = None        # Set when the async server starts
        self._briefing_sent_today = False  # Daily briefing flag
        self._current_ws = None            # Current WebSocket for streaming
        self._was_streamed = False          # Flag: last response was streamed
        self._greeted = False              # Flag: first-message greeting sent

        # F10: Initialize Vector Memory (ChromaDB)
        self.vector_memory = None
        if VECTOR_MEMORY_AVAILABLE:
            try:
                self.vector_memory = VectorMemory()
                print(f"\U0001f9e0 Vector memory: {self.vector_memory.count()} memories stored")
            except Exception as e:
                print(f"\u26a0\ufe0f Vector memory init failed: {e}")

        # F9: Start background screen reader (if available)
        if describe_screen is not None:
            try:
                from agent.screen_reader import start_background_reader
                start_background_reader()
            except Exception:
                try:
                    from screen_reader import start_background_reader
                    start_background_reader()
                except Exception as e:
                    print(f"\u26a0\ufe0f Background screen reader start failed: {e}")

    # ==========================================
    # FEATURE: AUTO DAILY BRIEFING (8 AM)
    # ==========================================
    async def _generate_daily_briefing(self) -> str:
        """Generates a morning briefing: weather + news + email summary + motivation."""
        # F3 FIX: import tools at method level since they're not available at class level
        try:
            from tools import get_weather, get_news, read_inbox
        except ImportError:
            get_weather = get_news = read_inbox = None

        parts = ["## ☀️ Good Morning, Sir! Here's your daily briefing:\n"]
        
        try:
            if get_weather:
                weather = await get_weather("Hyderabad")
                parts.append(f"### 🌡️ Weather in Hyderabad\n{weather}\n")
        except Exception:
            parts.append("### 🌡️ Weather\nCouldn't fetch weather.\n")
        
        try:
            if get_news:
                news = await get_news("latest")
                if news:
                    parts.append(f"### 📰 Top Headlines\n{news[:1000]}\n")
        except Exception:
            parts.append("### 📰 News\nCouldn't fetch news.\n")
        
        try:
            if read_inbox:
                emails = await read_inbox(max_emails=5)
                if emails:
                    parts.append(f"### 📧 Email Summary\n{emails[:800]}\n")
        except Exception:
            pass
        
        # F3: Add motivational message
        import random
        motivational_quotes = [
            "*\"The only way to do great work is to love what you do.\" — Steve Jobs* 🚀",
            "*\"Success is not final, failure is not fatal: it is the courage to continue that counts.\" — Churchill* 💪",
            "*\"The future belongs to those who believe in the beauty of their dreams.\" — Eleanor Roosevelt* ✨",
            "*\"Don't watch the clock; do what it does. Keep going.\" — Sam Levenson* ⏰",
            "*\"Your limitation—it's only your imagination.\"* 🧠",
            "*\"Push yourself, because no one else is going to do it for you.\"* 🔥",
            "*\"Great things never come from comfort zones.\"* 🌟",
        ]
        parts.append(f"\n### 💡 Motivation\n{random.choice(motivational_quotes)}")
        parts.append("\n*Have a productive day! 🚀*")
        return "\n".join(parts)

    async def _daily_briefing_scheduler(self):
        """Background task: sends daily briefing at 8:00 AM to all connected WebSocket clients."""
        print("⏰ Daily briefing scheduler started (8:00 AM)")
        while True:
            now = datetime.datetime.now()
            target = now.replace(hour=8, minute=0, second=0, microsecond=0)
            if now >= target:
                target += datetime.timedelta(days=1)
            wait_seconds = (target - now).total_seconds()
            
            await asyncio.sleep(wait_seconds)
            
            if not self._briefing_sent_today:
                try:
                    briefing = await self._generate_daily_briefing()
                    # Broadcast to all connected WebSockets
                    for ws in self._active_ws[:]:
                        try:
                            await ws.send_json({"response": briefing})
                        except Exception:
                            self._active_ws.remove(ws)
                    print("📋 Daily briefing sent!")
                    self._briefing_sent_today = True
                except Exception as e:
                    print(f"❌ Daily briefing error: {e}")
            
            # Reset flag at midnight
            await asyncio.sleep(60)
            if datetime.datetime.now().hour == 0:
                self._briefing_sent_today = False

    def _check_ollama(self) -> bool:
        """Check if Ollama is running locally."""
        try:
            resp = _requests.get(f"{self.ollama_url}/api/version", timeout=3)
            if resp.status_code == 200:
                print(f"✅ Ollama ({self.ollama_model}) Online — local primary brain ready")
                return True
        except Exception:
            pass
        print(f"⚠️ Ollama offline at {self.ollama_url} — using Gemini as primary")
        return False

    async def _ask_ollama(self, prompt: str, model: str = None) -> str:
        """Send prompt to local Ollama with Miro persona. Returns response text."""
        model = model or self.ollama_model
        loop = asyncio.get_running_loop()

        def _call():
            resp = _requests.post(
                f"{self.ollama_url}/api/generate",
                json={
                    "model": model,
                    "system": AGENT_INSTRUCTION,  # Miro persona
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.7,
                        "num_predict": 2000
                    }
                },
                timeout=90
            )
            return resp.json()["response"]

        return await loop.run_in_executor(None, _call)

    async def _ask_ollama_stream(self, prompt: str, websocket=None, model: str = None):
        """Stream response from Ollama token by token. Returns full text."""
        import json as _json
        model = model or self.ollama_model
        full_response = []

        def _stream():
            """Generator that yields chunks from Ollama streaming API."""
            resp = _requests.post(
                f"{self.ollama_url}/api/generate",
                json={
                    "model": model,
                    "system": AGENT_INSTRUCTION,
                    "prompt": prompt,
                    "stream": True,
                    "options": {"temperature": 0.7, "num_predict": 2000}
                },
                timeout=120,
                stream=True
            )
            for line in resp.iter_lines():
                if line:
                    chunk = _json.loads(line)
                    if "response" in chunk:
                        yield chunk["response"]
                    if chunk.get("done", False):
                        break

        loop = asyncio.get_running_loop()
        # Collect chunks in a thread, then stream to WebSocket
        import queue
        q = queue.Queue()
        
        def _producer():
            try:
                for chunk in _stream():
                    q.put(chunk)
            finally:
                q.put(None)  # sentinel
        
        # Start producer thread
        import threading
        t = threading.Thread(target=_producer, daemon=True)
        t.start()
        
        # Send stream_start
        if websocket:
            try:
                await websocket.send_json({"type": "stream_start"})
            except Exception:
                pass
        
        # Consume chunks and forward to WebSocket
        while True:
            try:
                chunk = await loop.run_in_executor(None, lambda: q.get(timeout=0.05))
            except Exception:
                await asyncio.sleep(0.02)
                continue
            
            if chunk is None:
                break
            
            full_response.append(chunk)
            if websocket:
                try:
                    await websocket.send_json({"type": "stream_chunk", "text": chunk})
                except Exception:
                    break
        
        # Send stream_end
        if websocket:
            try:
                await websocket.send_json({"type": "stream_end"})
            except Exception:
                pass
        
        return "".join(full_response)

    async def _send_message_with_retry(self, chat, message, max_retries=2):
        """Hybrid AI routing: Gemini (cloud) → Ollama (local fallback) → OpenAI (last resort).

        Strategy (F1 + F5):
        1. Try Gemini first (primary). Stream tokens if WebSocket is available.
        2. If Gemini hits 429 → try Ollama (local, free, unlimited).
        3. If Ollama fails → try OpenAI.
        4. User never sees the switching.
        """
        loop = asyncio.get_running_loop()
        errors = []

        # --- Helper: wrap response in a MockResponse for consistent .text access ---
        class MockResponse:
            def __init__(self, text):
                self.text = text

        # === STEP 1: Try Gemini with STREAMING (F1) ===
        async def _try_gemini_stream(target_chat, label):
            """Stream Gemini response token-by-token via WebSocket."""
            try:
                # Get the model from the chat session
                model = target_chat.model
                ws = self._current_ws

                # Build the actual message for send_message (non-streaming, for history)
                # We use generate_content for streaming but need to manage history ourselves
                if isinstance(message, str):
                    # For streaming, use the model directly with generate_content
                    def _stream_call():
                        return model.generate_content(message, stream=True)

                    stream_response = await loop.run_in_executor(None, _stream_call)

                    if ws:
                        try:
                            await ws.send_json({"type": "stream_start"})
                        except Exception:
                            pass

                    full_text = []
                    for chunk in stream_response:
                        if hasattr(chunk, 'text') and chunk.text:
                            full_text.append(chunk.text)
                            if ws:
                                # Split chunk into individual words for typewriter effect
                                # Gemini returns large chunks (sentences), we want word-by-word
                                words = chunk.text.split(' ')
                                for i, word in enumerate(words):
                                    try:
                                        # Add space back (except for first word)
                                        text_to_send = (' ' + word) if i > 0 else word
                                        await ws.send_json({"type": "stream_chunk", "text": text_to_send})
                                        await asyncio.sleep(0.03)  # 30ms delay per word for smooth typing
                                    except Exception:
                                        pass

                    if ws:
                        try:
                            await ws.send_json({"type": "stream_end"})
                        except Exception:
                            pass

                    joined = "".join(full_text)
                    if joined.strip():
                        self._was_streamed = True
                        # Also update chat history so context is maintained
                        try:
                            target_chat.history.append({"role": "user", "parts": [message]})
                            target_chat.history.append({"role": "model", "parts": [joined]})
                        except Exception:
                            pass
                        return MockResponse(joined)
                    return None
                else:
                    # Non-text (images) — can't stream, use regular send
                    resp = await loop.run_in_executor(
                        None, lambda: target_chat.send_message(message)
                    )
                    return resp
            except ResourceExhausted as e:
                errors.append(f"{label}: quota exceeded (429)")
                print(f"⚠️ {label} quota exceeded: {e}")
                return None
            except Exception as e:
                errors.append(f"{label}: {str(e)[:100]}")
                print(f"❌ {label} error: {e}")
                return None

        async def _try_gemini(target_chat, label):
            """Non-streaming Gemini call (used when no WebSocket or for images)."""
            try:
                resp = await loop.run_in_executor(
                    None, lambda: target_chat.send_message(message)
                )
                return resp
            except ResourceExhausted as e:
                errors.append(f"{label}: quota exceeded (429)")
                print(f"⚠️ {label} quota exceeded: {e}")
                return None
            except Exception as e:
                errors.append(f"{label}: {str(e)[:100]}")
                print(f"❌ {label} error: {e}")
                return None

        # Try primary Gemini model (with streaming if WebSocket available)
        print("☁️ Cloud: Sending to Gemini...")
        if self._current_ws and isinstance(message, str):
            result = await _try_gemini_stream(chat, "Gemini primary (stream)")
        else:
            result = await _try_gemini(chat, "Gemini primary")
        if result:
            return result

        # Try alternate Gemini model
        alt_chat = self.smart_chat if chat is self.fast_chat else self.fast_chat
        print(f"🔀 Trying alternate Gemini model...")
        if self._current_ws and isinstance(message, str):
            result = await _try_gemini_stream(alt_chat, "Gemini alt (stream)")
        else:
            result = await _try_gemini(alt_chat, "Gemini alt")
        if result:
            return result

        # === STEP 2: Try Ollama as FALLBACK (F5: only on Gemini 429) ===
        if self.ollama_available and isinstance(message, str):
            try:
                print("🏠 Fallback: Sending to Ollama (local)...")
                if self._current_ws:
                    text = await self._ask_ollama_stream(message, websocket=self._current_ws)
                    self._was_streamed = True
                else:
                    text = await self._ask_ollama(message)
                if text and len(text.strip()) > 5:
                    return MockResponse(text)
                errors.append("Ollama: empty response")
            except Exception as e:
                errors.append(f"Ollama: {str(e)[:100]}")
                print(f"⚠️ Ollama failed: {e}")
                self.ollama_available = False

        # === STEP 3: Try OpenAI (last resort) ===
        if self.openai_client and isinstance(message, str):
            print("🔄 Last resort: OpenAI (gpt-4o-mini)...")
            try:
                resp = await loop.run_in_executor(
                    None,
                    lambda: self.openai_client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[{"role": "user", "content": message}],
                        max_tokens=1000
                    )
                )
                return MockResponse(resp.choices[0].message.content)
            except Exception as oe:
                errors.append(f"OpenAI: {str(oe)[:100]}")
                print(f"❌ OpenAI failed: {oe}")

        # === STEP 4: Try Ollama one more time (may have recovered) ===
        if isinstance(message, str) and not self.ollama_available:
            try:
                self.ollama_available = self._check_ollama()
                if self.ollama_available:
                    text = await self._ask_ollama(message)
                    if text and len(text.strip()) > 5:
                        return MockResponse(text)
            except Exception:
                pass

        # All failed
        raise Exception(
            f"All AI models exhausted.\n"
            + "\n".join(f"• {e}" for e in errors)
            + "\nFix: Start Ollama (`ollama serve`), check API keys, or try again later."
        )

    # 🔥 MOVE THIS FUNCTION HERE (INDENTED)
    def _init_models(self):
        """Initializes Models: FORCES Gemini 2.5 as requested."""
        key_fast = os.getenv("GOOGLE_API_KEY")
        key_smart = os.getenv("GOOGLE_API_KEY_PRO") or key_fast

        # Build memory-enriched system instruction
        profile_ctx = self.memory.get_profile_context()
        memory_block = f"""

# KNOWN USER PROFILE (from learning engine — use this automatically):
{profile_ctx}
"""

        # 1. FAST BRAIN (Voice) -> Gemini 1.5 Flash (BF3: user-requested default)
        genai.configure(api_key=key_fast)
        try:
            print("🚀 Loading Gemini 1.5 Flash...")
            model_fast = genai.GenerativeModel(
                "gemini-2.5-flash",
                system_instruction=(
                    PERSONALITIES[self.current_persona]
                    + memory_block
                    + "\n GOAL: Reply Instantly."
                    + "\n\n" + SESSION_INSTRUCTION
                )
            )
            chat_fast = model_fast.start_chat(history=[])
            print("✅ Gemini 1.5 Flash Online")
        except Exception as e:
            print(f"⚠️ Gemini 1.5 Flash Unavailable ({e}). Fallback to 1.5 Pro.")
            model_fast = genai.GenerativeModel(
                "gemini-2.5-pro",
                system_instruction=PERSONALITIES[self.current_persona] + memory_block + "\n\n" + SESSION_INSTRUCTION
            )
            chat_fast = model_fast.start_chat(history=[])

        # 2. SMART BRAIN (Chat) -> Gemini 1.5 Flash (BF3: with fallback to 1.5 Pro on 429)
        if key_smart != key_fast: genai.configure(api_key=key_smart)
        try:
            print("🧠 Loading Gemini 1.5 Flash (smart)...")
            model_smart = genai.GenerativeModel(
                "gemini-2.5-flash",
                system_instruction=(
                    PERSONALITIES[self.current_persona]
                    + memory_block
                    + "\n GOAL: Deep Reasoning & Coding."
                    + "\n\n" + SESSION_INSTRUCTION
                )
            )
            chat_smart = model_smart.start_chat(history=[])
            print("✅ Gemini 1.5 Flash (smart) Online")
        except Exception as e:
            print(f"⚠️ Gemini 1.5 Flash Unavailable ({e}). Fallback to 1.5 Pro.")
            model_smart = genai.GenerativeModel(
                "gemini-2.5-pro",
                system_instruction=PERSONALITIES[self.current_persona] + memory_block + "\n\n" + SESSION_INSTRUCTION
            )
            chat_smart = model_smart.start_chat(history=[])

        # Reset global config to default key
        genai.configure(api_key=key_fast)
        
        return chat_fast, chat_smart



    def switch_personality(self, persona_key):
        """Switch personality without wiping or polluting conversation history."""
        if persona_key not in PERSONALITIES:
            return "Personality not found."
        self.current_persona = persona_key
        # FIXED: Re-initialize models with new system instruction instead of
        # sending a fake user message which corrupts the chat history.
        self.fast_chat, self.smart_chat = self._init_models()
        return f"Mode switched to {persona_key.upper()}. I'm now operating in that mode."

    def clean_response(self, text):
        """
        Returns text AS IS. 
        We do NOT strip Markdown characters here anymore.
        The Frontend will handle cleaning text for the Voice Engine.
        """
        return text

    def select_brain(self, text, has_image=False, has_file=False):
        """Decides which brain handles the request.
        
        Routing:
        - Images → Gemini smart (only cloud can do vision)
        - Files → Gemini smart (needs large context)
        - Text → fast_chat (Ollama handles it in _send_message_with_retry)
        """
        text = text.lower()
        smart_triggers = [
            "code", "script", "analyze", "architect", "complex", "plan", 
            "debug", "why", "write a", "python", "java", "cpp", "html", 
            "function", "api", "create a", "list", "generate", "table"
        ]
        
        # Images MUST go to Gemini (Ollama can't do vision)
        if has_image: return self.smart_chat, "smart"
        # Large files benefit from Gemini's bigger context window
        if has_file: return self.smart_chat, "smart"
        # Complex tasks: still route to smart_chat but Ollama gets tried first
        if any(trigger in text for trigger in smart_triggers) and len(text) > 10: 
            return self.smart_chat, "smart"
        
        return self.fast_chat, "fast"

    # ==========================================
    # PILLAR 2 — ADVANCED REASONING
    # ==========================================
    def _complexity_score(self, text: str) -> int:
        """Scores how complex / multi-step a question is (0-10)."""
        score = 0
        t = text.lower()
        if len(t) > 120:           score += 2
        elif len(t) > 60:          score += 1
        deep_words = [
            "analyze", "analyse", "compare", "contrast", "evaluate",
            "pros and cons", "trade-off", "why", "how does", "explain",
            "implications", "impact", "difference between", "which is better",
            "think through", "reason", "step by step", "deep dive",
            "should i", "is it worth", "future of", "what would happen"
        ]
        for w in deep_words:
            if w in t:
                score += 1
        # Multi-question indicators
        if text.count("?") > 1:    score += 1
        if " and " in t and "?" in t: score += 1
        return min(score, 10)

    def _build_reasoning_prompt(self, context_header: str, user_text: str) -> str:
        """Prepends chain-of-thought preamble for complex questions."""
        return (
            f"{context_header}\n\n"
            "[REASONING MODE]\n"
            "Think through this carefully, step by step. "
            "Show your reasoning process before giving the final answer. "
            "Consider multiple angles, weigh pros and cons, and be precise.\n\n"
            f"Question: {user_text}"
        )

    # ==========================================
    # PILLAR 3 — CREATIVE GENERATION
    # ==========================================
    CREATIVE_TRIGGERS = {
        "story":  ["write a story", "tell me a story", "short story", "write a tale",
                   "write a narrative", "fiction about"],
        "poem":   ["write a poem", "write poetry", "compose a poem", "write a sonnet",
                   "write a haiku", "write a song", "write lyrics"],
        "code":   ["write code", "generate code", "write a script", "write a program",
                   "implement a", "build a function", "code that"],
        "design": ["design a", "create a ui", "create a ux", "layout for", "wireframe",
                   "design brief", "color palette", "design system"],
    }

    def _detect_creative_mode(self, text: str) -> str | None:
        """Returns creative mode string or None if not a creative request."""
        t = text.lower()
        for mode, triggers in self.CREATIVE_TRIGGERS.items():
            if any(trig in t for trig in triggers):
                return mode
        return None

    # ==========================================
    # FEATURE: EMOTION DETECTION
    # ==========================================
    _EMOTION_MAP = {
        "frustrated": {
            "keywords": ["not working", "broken", "useless", "stupid", "hate", "annoyed",
                         "frustrated", "angry", "wtf", "terrible", "worst", "fix this",
                         "why isn't", "doesn't work", "failed", "error", "bug", "wrong"],
            "tone": "User seems frustrated. Respond with extra patience, empathy, and care. Apologize if something went wrong. Be calm and solution-focused."
        },
        "happy": {
            "keywords": ["thanks", "awesome", "great", "love it", "perfect", "amazing",
                         "wonderful", "excellent", "brilliant", "nice", "cool", "wow",
                         "haha", "lol", "yay", "thank you"],
            "tone": "User is in a good mood! Be casual, fun, and upbeat. Match their positive energy."
        },
        "stressed": {
            "keywords": ["stressed", "overwhelmed", "too much", "exhausted", "tired",
                         "deadline", "pressure", "can't handle", "help me", "urgent",
                         "running out of time", "so much work", "burnt out"],
            "tone": "User seems stressed. Be supportive and calming. Offer to help prioritize. Suggest a short break if appropriate."
        },
        "sad": {
            "keywords": ["sad", "depressed", "lonely", "miss", "lost", "crying",
                         "heartbroken", "disappointed", "unfortunate", "bad day"],
            "tone": "User seems down. Be warm, empathetic, and uplifting. Offer encouragement."
        },
        "curious": {
            "keywords": ["how does", "why does", "what if", "explain", "tell me about",
                         "curious", "wonder", "interesting", "how to"],
            "tone": "User is curious and in learning mode. Be detailed, informative, and enthusiastic about sharing knowledge."
        },
    }

    def _detect_emotion(self, text: str) -> tuple[str, str]:
        """Detects user emotion from text. Returns (emotion_name, tone_instruction)."""
        t = text.lower()
        best_emotion = "neutral"
        best_score = 0
        best_tone = ""

        for emotion, data in self._EMOTION_MAP.items():
            score = sum(1 for kw in data["keywords"] if kw in t)
            if score > best_score:
                best_score = score
                best_emotion = emotion
                best_tone = data["tone"]

        if best_score == 0:
            return "neutral", ""
        return best_emotion, best_tone

    async def _handle_creative(self, user_text: str, mode: str) -> str:
        """Handles creative generation with genre-specific system prompting."""
        CREATIVE_SYSTEM = {
            "story": (
                "You are an award-winning fiction author. Write with vivid imagery, "
                "compelling characters, and a clear narrative arc. Be original and avoid clichés. "
                "Aim for literary quality."
            ),
            "poem": (
                "You are a renowned poet. Compose with strong imagery, rhythm, emotional resonance, "
                "and structural intention. Use metaphor and subtext. Be original and evocative."
            ),
            "code": (
                "You are a principal software engineer. Write clean, efficient, production-grade code. "
                "Include comments for complex sections. Follow best practices. "
                "Wrap code in proper markdown fenced code blocks with language tags."
            ),
            "design": (
                "You are a world-class UI/UX architect. Produce detailed design briefs including: "
                "layout structure, color palette, typography, spacing, component hierarchy, "
                "interaction patterns, and accessibility considerations."
            ),
        }
        system_note = CREATIVE_SYSTEM.get(mode, "")
        prompt = (
            f"[CREATIVE MODE: {mode.upper()}]\n"
            f"{system_note}\n\n"
            f"Request: {user_text}"
        )
        response = await self._send_message_with_retry(self.smart_chat, prompt)
        clean_resp = response.text
        self.memory.add_message("model", clean_resp)
        return clean_resp

    # ==========================================
    # PILLAR 4 — ENHANCED MULTIMODAL
    # ==========================================
    def _analyze_image_intent(self, user_text: str) -> str:
        """Returns a specialized image analysis prompt based on user intent."""
        t = user_text.lower().strip()

        if not t:  # Image sent with no text → auto-describe
            return (
                "Describe this image in rich detail. Cover: what is shown, "
                "people or objects present, setting/environment, colors and composition, "
                "mood and artistic style, and any notable details. Be thorough."
            )
        if any(w in t for w in ["read", "text", "ocr", "extract text", "what does it say",
                                 "words", "written"]):
            return (
                "Read and extract ALL text visible in this image, exactly as it appears. "
                "Preserve line breaks and formatting. If there are multiple text regions, "
                "label them (e.g., Title, Body, Caption)."
            )
        if any(w in t for w in ["chart", "graph", "plot", "data", "analyze this",
                                  "statistics", "trend", "table"]):
            return (
                "Analyze this chart or data visualization in detail. "
                "Identify: chart type, axes/labels, key trends, notable data points, "
                "highs and lows, and a concise executive summary of what the data shows."
            )
        if any(w in t for w in ["identify", "who is", "what is", "what are",
                                  "recognize", "classify"]):
            return (
                f"Look at this image carefully and answer: {user_text}\n"
                "Be specific and confident. If unsure, say so."
            )
        # Shopping/ordering intent — identify the product for price search
        if any(w in t for w in ["buy", "order", "shop", "price", "cost", "purchase",
                                  "where can i get", "find this", "how much",
                                  "cheapest", "best deal", "add to cart"]):
            return (
                f"The user wants to BUY or FIND PRICES for what they're showing. "
                f"User said: \"{user_text}\"\n\n"
                "Your task:\n"
                "1. Identify the EXACT product/item in the image (brand, model, color, size if visible)\n"
                "2. Respond in this EXACT format:\n"
                "PRODUCT_SEARCH: <precise product name for shopping search>\n"
                "DESCRIPTION: <brief 1-line description of what you see>\n\n"
                "Example:\n"
                "PRODUCT_SEARCH: Apple AirPods Pro 2nd Generation White\n"
                "DESCRIPTION: White wireless earbuds with Apple AirPods Pro charging case\n\n"
                "Be as specific as possible with the product name for accurate search results."
            )
        # Default: answer the question using the image
        return (
            f"Using this image as your primary reference, answer the following: {user_text}"
        )

    def _is_shopping_intent(self, text: str) -> bool:
        """Check if the user's message indicates shopping/ordering intent."""
        t = text.lower()
        return any(w in t for w in ["buy", "order", "shop", "price", "cost", "purchase",
                                      "where can i get", "find this", "how much",
                                      "cheapest", "best deal", "add to cart"])

    async def _search_product_prices(self, product_name: str) -> str:
        """Search for product prices across shopping platforms using web search."""
        try:
            from duckduckgo_search import DDGS
            results = []
            
            # Search across major shopping platforms
            platforms = [
                ("Amazon India", f"{product_name} site:amazon.in price"),
                ("Flipkart", f"{product_name} site:flipkart.com price"),
                ("General", f"{product_name} buy online India best price"),
            ]
            
            loop = asyncio.get_running_loop()
            
            for platform, query in platforms:
                try:
                    def _search(q=query):
                        with DDGS() as ddgs:
                            return list(ddgs.text(q, max_results=3))
                    
                    search_results = await loop.run_in_executor(None, _search)
                    for r in search_results:
                        title = r.get("title", "")
                        link = r.get("href", r.get("link", ""))
                        snippet = r.get("body", "")
                        if link:
                            results.append(f"- **{title}**\n  {snippet}\n  🔗 [View on {platform}]({link})")
                except Exception:
                    continue
            
            if results:
                header = f"### 🛒 Shopping Results for: **{product_name}**\n\n"
                return header + "\n\n".join(results[:6]) + "\n\n> 💡 *Tip: Click the links to compare prices and buy!*"
            else:
                return f"I couldn't find online listings for **{product_name}**. Try searching on [Amazon](https://www.amazon.in/s?k={product_name.replace(' ', '+')}) or [Flipkart](https://www.flipkart.com/search?q={product_name.replace(' ', '+')}) directly."
        except Exception as e:
            return f"Shopping search error: {e}"

    async def process_file(self, file_data, filename):
        """Process an uploaded file and store its text in knowledge_base.
        
        Supported formats: PDF, DOCX, TXT, CSV, JSON, PY, JS, MD and any UTF-8 text.
        The extracted text is stored in self.knowledge_base so every subsequent
        message can reference it via the file_context anchor.
        """
        try:
            print(f"📂 Processing file: {filename}")


            if "," not in file_data:
                return "❌ Invalid file format — expected base64 data URL."

            decoded = base64.b64decode(file_data.split(",")[1])
            text = ""
            ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""

            if ext == "pdf":
                # --- PDF ---
                try:
                    reader = PyPDF2.PdfReader(io.BytesIO(decoded))
                    for page in reader.pages:
                        page_text = page.extract_text()
                        if page_text:
                            text += page_text + "\n"
                except Exception as e:
                    return f"❌ PDF read error: {e}"

            elif ext == "docx":
                # --- Word Document ---
                try:
                    import docx
                    doc = docx.Document(io.BytesIO(decoded))
                    text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
                except ImportError:
                    # Fallback: try raw text extraction
                    try:
                        text = decoded.decode("utf-8", errors="ignore")
                    except Exception:
                        return "❌ Install python-docx to read Word files: pip install python-docx"
                except Exception as e:
                    return f"❌ DOCX read error: {e}"

            elif ext == "csv":
                # --- CSV ---
                import csv as _csv
                try:
                    rows = list(_csv.reader(io.StringIO(decoded.decode("utf-8", errors="replace"))))
                    text = "\n".join(", ".join(row) for row in rows)
                except Exception as e:
                    return f"❌ CSV read error: {e}"

            else:
                # --- Any UTF-8 text (txt, py, js, md, json, html, etc.) ---
                try:
                    text = decoded.decode("utf-8")
                except UnicodeDecodeError:
                    text = decoded.decode("latin-1", errors="replace")

            text = text.strip()
            if not text:
                return "❌ No readable text found in file. Please upload a text-based file."

            # Trim very large files to avoid token limit overflows (~50k chars ≈ ~12k tokens)
            MAX_CHARS = 50_000
            truncated = False
            if len(text) > MAX_CHARS:
                text = text[:MAX_CHARS]
                truncated = True

            # Store in knowledge base for Q&A sessions
            self.knowledge_base = text
            self.knowledge_base_name = filename

            # Inject into smart chat session so history is aware of the file
            injection_prompt = (
                f"[FILE UPLOADED: '{filename}']\n"
                f"The user has uploaded this file. Here is its FULL content:\n\n"
                f"{text}\n\n"
                f"Study this content carefully. When the user asks ANY question, "
                f"answer using ONLY this file's content unless they explicitly ask otherwise."
            )
            await self._send_message_with_retry(self.smart_chat, injection_prompt)

            trunc_note = f" (first {MAX_CHARS:,} characters loaded)" if truncated else ""
            response = f"✅ File '{filename}' loaded successfully{trunc_note}. Ask me anything about it!"
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
                               minimize_windows, open_application, wiki_lookup, get_news)
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
                self.smart_chat.history.clear()
                self.knowledge_base = ""      # clear file context for fresh chat
                self.knowledge_base_name = ""
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
        # FIXED: Only intercept commands that explicitly ask to SHOW/DISPLAY a chart.
        # Pure text questions like "what is the stock market" now go to AI instead.
        finance_action_words = ["show", "display", "open", "chart", "graph", "terminal", "price of"]
        if ("stock" in clean_text or "finance" in clean_text) and any(w in clean_text for w in finance_action_words):
            if SYSTEM_CALLBACK:
                SYSTEM_CALLBACK(clean_text)
            return "Opening financial terminal."

        # --- B. REAL-TIME DATA INJECTION ---
        # FIXED: now awaited (was blocking sync call → caused WS 1001/1012 timeouts)
        real_time_context = ""
        # Words that should skip search ONLY when the ENTIRE message is basically that word
        SKIP_EXACT = {"hello", "hi", "hey", "thanks", "thank you", "bye", "goodbye", "ok", "okay"}
        # Command words that skip search — matched with word boundaries (not substrings)
        SKIP_COMMANDS = ["activate", "disconnect", "minimize", "screenshot", "volume",
                         "what do you know about me", "show my profile", "reset mode"]
        
        words_set = set(clean_text.split())
        is_greeting = clean_text in SKIP_EXACT or words_set <= SKIP_EXACT
        is_command = any(cmd in clean_text for cmd in SKIP_COMMANDS)
        is_open_or_play = bool(re.search(r'\bopen\b|\bplay\b', clean_text))
        
        should_search = not is_greeting and not is_command and not is_open_or_play
        if should_search:
            live_info = await get_realtime_data(clean_text)
            if live_info:
                real_time_context = f"\n\n[REAL-TIME INTERNET DATA — use this as ground truth]:\n{live_info}\n"

        if not clean_text and not user_image:
            return ""

        # --- SAFETY & LEARNING ---
        if not self.safety.validate_input(clean_text):
            return "Request unsafe."
        self.memory.learn_fact(clean_text)
        self.memory.add_message("user", user_text)

        # --- MEMORY NAME CHECK + SELF-LEARNING ---
        name_match = re.search(r"my name is (\w+)", clean_text)
        if name_match:
            new_name = name_match.group(1).capitalize()
            self.memory.set_name(new_name)
            resp = f"Nice to meet you, {new_name}. I'll remember that, Sir!"
            self.memory.add_message("model", resp)
            return resp

        # Memory introspection command
        memory_introspect = ["what do you know about me", "what have you learned",
                              "show my profile", "what's in your memory", "my memory"]
        if any(phrase in clean_text for phrase in memory_introspect):
            summary = self.memory.get_memory_summary()
            profile = self.memory.get_profile_context()
            resp = (
                f"### 🧠 My Memory Profile for You\n\n"
                f"{profile}\n\n"
                f"---\n"
                f"**Total facts stored:** {summary['total_facts']}  "
                f"| **Last updated:** {summary.get('last_updated', 'never')}"
            )
            self.memory.add_message("model", resp)
            return resp

        # --- PERSONALITY & HARDWARE ---
        if "activate miro" in clean_text: return self.switch_personality("miro_prime")
        if "activate bro" in clean_text: return self.switch_personality("motivator_alpha")
        if "activate professional" in clean_text: return self.switch_personality("core_ai")
        if "reset mode" in clean_text: return self.switch_personality("default")

        # --- SCREEN READER (#9) ---
        screen_triggers = ["what's on my screen", "read my screen", "what am i looking at",
                          "screen reader", "read screen", "analyze my screen", "whats on screen"]
        if describe_screen and any(t in clean_text for t in screen_triggers):
            screen_content = await describe_screen()
            # Feed screen content to AI for analysis
            prompt = f"{screen_content}\n\nUser asks: {user_text}\nDescribe what you see on the screen in a helpful way."
            response = await self._send_message_with_retry(self.fast_chat, prompt)
            resp = response.text if hasattr(response, 'text') else str(response)
            self.memory.add_message("model", resp)
            return resp

        # --- GOOGLE CALENDAR (#7) ---
        calendar_triggers = ["my calendar", "today's events", "today's schedule",
                            "what's on my calendar", "events today", "my events"]
        schedule_triggers = ["schedule", "create event", "add to calendar", "book meeting"]
        
        if get_todays_events and any(t in clean_text for t in calendar_triggers):
            creds = getattr(self, '_google_credentials', None)
            resp = await get_todays_events(creds)
            self.memory.add_message("model", resp)
            return resp
        
        if parse_schedule_command and any(t in clean_text for t in schedule_triggers):
            event_data = parse_schedule_command(clean_text)
            if event_data and create_event:
                creds = getattr(self, '_google_credentials', None)
                resp = await create_event(creds, event_data['title'], event_data['datetime'])
                self.memory.add_message("model", resp)
                return resp

        # --- EMAIL DRAFT FLOW (multi-step conversation) ---
        if self.email_mode:
            return await self._handle_email_step(clean_text, user_text)

        # --- GOOGLE TOOLS COMMAND HANDLERS ---
        # Check email / read inbox
        inbox_pattern = r'\bcheck\b.*\bemail\b|\bmy email\b|\bunread\b|\binbox\b|\bany.*mail\b|\bimportant.*email\b|\bread.*email\b'
        if re.search(inbox_pattern, clean_text):
            if GOOGLE_AUTH_AVAILABLE and self._google_user_id:
                result = _google_tools.check_emails(self._google_user_id)
                resp = f"Here are your unread emails:\n{result}"
            else:
                # Use IMAP reader (no OAuth needed, just App Password)
                try:
                    from tools import read_inbox as _read_inbox
                except ImportError:
                    from tools import read_inbox as _read_inbox
                resp = await _read_inbox()
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

        # --- FINANCE TRACKER ---
        expense_triggers = ["spent", "paid", "expense", "cost me", "bought for", "i paid"]
        spending_triggers = ["spending", "expenses", "how much", "spent this", "finance", "money tracker"]
        
        if log_expense and any(t in clean_text for t in expense_triggers):
            return await log_expense(clean_text)
        
        if get_spending_summary and any(t in clean_text for t in spending_triggers):
            if "today" in clean_text:
                return await get_spending_summary("today")
            elif "month" in clean_text:
                return await get_spending_summary("month")
            else:
                return await get_spending_summary("week")

        # --- WHATSAPP HANDLER (F4: now supports name-based sending) ---
        # Contact map: name → phone (add your contacts here)
        WHATSAPP_CONTACTS = {
            "manoj": "+91XXXXXXXXXX",   # Replace with actual numbers
            "manoj kumar": "+91XXXXXXXXXX",
            "amit": "+91XXXXXXXXXX",
            "amit kumar": "+91XXXXXXXXXX",
            "jaideep": "+91XXXXXXXXXX",
            "revanth": "+91XXXXXXXXXX",
            # Add more contacts as needed
        }
        
        whatsapp_triggers = ["send on whatsapp", "whatsapp", "message on whatsapp",
                            "send whatsapp", "send a whatsapp", "on whatsapp"]
        if WHATSAPP_AVAILABLE and any(t in clean_text for t in whatsapp_triggers):
            phone = None
            contact_name = None
            
            # F4: Try phone number first
            phone_match = re.search(r'(\+?\d{10,13})', clean_text)
            if phone_match:
                phone = phone_match.group(1)
                if not phone.startswith("+"):
                    phone = "+91" + phone
            else:
                # F4: Try name-based lookup
                # Pattern: "send [name] [message] on whatsapp" or "send [message] to [name] on whatsapp"
                # Try extracting name from common patterns
                name_patterns = [
                    r'send\s+([a-z]+(?:\s+[a-z]+)?)\s+(?:the|a)?\s*(.+?)\s+on\s+whatsapp',
                    r'send\s+(.+?)\s+to\s+([a-z]+(?:\s+[a-z]+)?)\s+on\s+whatsapp',
                    r'whatsapp\s+([a-z]+(?:\s+[a-z]+)?)\s+(.+)',
                    r'message\s+([a-z]+(?:\s+[a-z]+)?)\s+(.+?)\s+on\s+whatsapp',
                ]
                for pat in name_patterns:
                    m = re.search(pat, clean_text)
                    if m:
                        possible_name = m.group(1).strip()
                        possible_msg = m.group(2).strip()
                        # Check if first group is a known contact
                        if possible_name in WHATSAPP_CONTACTS:
                            contact_name = possible_name
                            phone = WHATSAPP_CONTACTS[contact_name]
                            msg_text = possible_msg
                            break
                        # Maybe second group is the name (for "send X to name" pattern)
                        if possible_msg in WHATSAPP_CONTACTS:
                            contact_name = possible_msg
                            phone = WHATSAPP_CONTACTS[contact_name]
                            msg_text = possible_name
                            break
                
                if not phone:
                    # Check if any known name appears in the text
                    for name, num in WHATSAPP_CONTACTS.items():
                        if name in clean_text:
                            contact_name = name
                            phone = num
                            break
            
            if phone:
                if not contact_name:
                    # Extract message from phone-number-based command
                    if phone_match:
                        msg_text = clean_text.split(phone_match.group(1))[-1].strip()
                    else:
                        msg_text = ""
                    if not msg_text:
                        msg_text = re.sub(r'send|whatsapp|message|on|to|\+?\d{10,13}', '', clean_text).strip()
                elif 'msg_text' not in dir():
                    # Extract message: remove the contact name and whatsapp keywords
                    msg_text = clean_text
                    for kw in ['send', 'whatsapp', 'message', 'on', 'to', 'the', 'a', contact_name]:
                        msg_text = msg_text.replace(kw, '')
                    msg_text = msg_text.strip()
                
                if msg_text:
                    try:
                        loop = asyncio.get_running_loop()
                        now = datetime.datetime.now()
                        await loop.run_in_executor(
                            None,
                            lambda: pywhatkit.sendwhatmsg(
                                phone, msg_text,
                                now.hour, now.minute + 2
                            )
                        )
                        display_name = contact_name.title() if contact_name else phone
                        return f"✅ WhatsApp message scheduled to **{display_name}**: \"{msg_text}\""
                    except Exception as e:
                        return f"❌ WhatsApp error: {str(e)}"
                else:
                    return "What message should I send? Please include the message text."
            else:
                return "I don't recognize that contact. Please use a phone number or add the contact to WHATSAPP_CONTACTS. Example: 'send +919876543210 hello on whatsapp'"

        # --- CREATIVE GENERATION (Pillar 3) ---
        creative_mode = self._detect_creative_mode(clean_text)
        if creative_mode:
            return await self._handle_creative(user_text, creative_mode)

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

            # Emotion detection
            emotion, emotion_tone = self._detect_emotion(user_text)
            emotion_ctx = f" | MOOD: {emotion} — {emotion_tone}" if emotion_tone else ""
            
            # F10: Recall relevant memories from vector store
            vector_ctx = ""
            if self.vector_memory:
                try:
                    vector_ctx = await self.vector_memory.recall_formatted(user_text, n_results=3)
                except Exception as vm_err:
                    print(f"⚠️ Vector recall error: {vm_err}")
            
            context_header = f"[SYSTEM: {RealTimeContext.get_context()} | USER: {self.memory.get_profile_context()}{emotion_ctx}]"
            if vector_ctx:
                context_header += f"\n{vector_ctx}"
            if emotion != "neutral":
                print(f"💭 Detected emotion: {emotion}")
            
            # F10: Store user message in vector memory
            if self.vector_memory and user_text and len(user_text.strip()) > 5:
                try:
                    await self.vector_memory.store(
                        f"User said: {user_text}",
                        metadata={"role": "user", "emotion": emotion}
                    )
                except Exception:
                    pass

            if user_image:
                print("📸 Processing Image with Gemini multimodal...")
                # Pillar 4: intent-specific prompt based on what the user asked
                image_prompt = self._analyze_image_intent(user_text)
                response = await self._send_message_with_retry(selected_chat, [image_prompt, user_image])
                clean_resp = self.clean_response(response.text)

                # 🛒 SHOPPING PIPELINE: If shopping intent detected, parse product and search prices
                if self._is_shopping_intent(user_text) and "PRODUCT_SEARCH:" in clean_resp:
                    # Extract product name from Gemini's structured response
                    product_name = ""
                    description = ""
                    for line in clean_resp.split("\n"):
                        if line.strip().startswith("PRODUCT_SEARCH:"):
                            product_name = line.split("PRODUCT_SEARCH:", 1)[1].strip()
                        elif line.strip().startswith("DESCRIPTION:"):
                            description = line.split("DESCRIPTION:", 1)[1].strip()
                    
                    if product_name:
                        print(f"🛒 Shopping intent! Searching prices for: {product_name}")
                        if self._current_ws:
                            await self._current_ws.send_text(
                                f"🔍 I see: **{description or product_name}**\n\n"
                                f"Searching for the best prices across shopping platforms..."
                            )
                        price_results = await self._search_product_prices(product_name)
                        self.memory.add_message("model", price_results)
                        return price_results
                
                self.memory.add_message("model", clean_resp)
                return clean_resp

            # Tool Checks
            loop = asyncio.get_running_loop()
            tool_result = ""
            if "time" in clean_text:
                tool_result = await get_system_time()
            elif re.search(r'\bnews\b|latest headlines|what happened today', clean_text):
                topic = re.sub(r'news|latest|headlines|today|about|the', '', clean_text).strip() or "latest"
                tool_result = await get_news(topic)
            elif not real_time_context and any(w in clean_text for w in ["who is", "who was", "what is", "what was",
                                                "tell me about", "history of", "biography"])\
                    and "search" not in clean_text:
                topic = re.sub(r'who is|who was|what is|what was|tell me about|history of|biography of',
                               '', clean_text).strip()
                tool_result = await wiki_lookup(topic) if topic else ""
            elif "weather" in clean_text:
                city_match = re.search(r'weather\s+(?:in|at|for|of)?\s*([\w\s]+)', clean_text)
                city = city_match.group(1).strip() if city_match else "Hyderabad"
                tool_result = await get_weather(city)
            elif "search" in clean_text:
                query = clean_text.replace("search", "").replace("for", "").strip()
                tool_result = await search_web(query)

            if tool_result:
                # BF2 FIX: inject real_time_context into tool-result prompt too
                response = await self._send_message_with_retry(
                    selected_chat,
                    f"{context_header}{real_time_context}\nUser: {user_text}\nTool Result: {tool_result}\nSummarize naturally."
                )
                clean_resp = self.clean_response(response.text)
                self.memory.add_message("model", clean_resp)
                return clean_resp

            # --- NORMAL CHAT with optional reasoning boost (Pillar 2) ---
            if self.knowledge_base:
                # File Q&A: embed full extracted text so Gemini can't refuse
                kb_snippet = self.knowledge_base[:30_000]
                prompt = (
                    f"{context_header}{real_time_context}\n\n"
                    f"=== FILE: '{self.knowledge_base_name}' ===\n"
                    f"{kb_snippet}\n"
                    f"=== END OF FILE ===\n\n"
                    f"Using ONLY the file content above, answer this question:\n"
                    f"{user_text}"
                )
            elif self._complexity_score(user_text) >= 3:
                # Complex question: use chain-of-thought reasoning mode
                # BF2 FIX: inject real_time_context into reasoning prompt
                prompt = self._build_reasoning_prompt(context_header + real_time_context, user_text)
                selected_chat = self.smart_chat  # always use smart for reasoning
            else:
                prompt = context_header + real_time_context + " " + user_text

            response = await self._send_message_with_retry(selected_chat, prompt)

            clean_resp = self.clean_response(response.text)

            # ONE-TIME GREETING: prepend greeting to the very first response only
            if not self._greeted:
                self._greeted = True
                now = datetime.datetime.now()
                hour = now.hour
                tod = "morning" if hour < 12 else ("afternoon" if hour < 17 else "evening")
                name = self.user_name or "Sir"
                greeting = f"Good {tod}, {name}! 😊\n\n"
                clean_resp = greeting + clean_resp

            self.memory.add_message("model", clean_resp)

            # --- AUTO SAVE --- FIXED: use selected_chat (not always smart_chat)
            try:
                hist_data = [{"role": t.role, "parts": [{"text": p.text for p in t.parts}]} for t in selected_chat.history]
            except Exception:
                hist_data = []
            title = user_text[:30] if len(hist_data) <= 2 else None
            self.session_manager.save_session(self.current_session_id, hist_data, title)

            return clean_resp

        except Exception as e:
            print(f"❌ Response Generation Error: {e}")
            return f"Error: {str(e)}"

    async def _handle_email_step(self, clean_text: str, user_text: str) -> str:
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
                    # FIXED: Use asyncio-safe call instead of run_until_complete() which
                    # crashes inside a running event loop.
                    try:
                        from tools import send_email as smtp_send
                    except ImportError:
                        from tools import send_email as smtp_send
                    try:
                        result = await smtp_send(to, subject, body)
                    except Exception as e:
                        result = f"Email failed: {e}"

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
        print("🚀 Miro Server running on ws://127.0.0.1:8000/ws (localhost only)")
        uvicorn.run(app, host="127.0.0.1", port=8000, log_level="error")

# --- SINGLETON ASSISTANT ---
_assistant_instance = None

def get_assistant():
    """Returns a singleton VoiceAssistant instance."""
    global _assistant_instance
    if _assistant_instance is None:
        _assistant_instance = VoiceAssistant()
    return _assistant_instance

# ==========================================
# SERVER STARTUP — start background tasks
# ==========================================
@app.on_event("startup")
async def _on_startup():
    # Security: verify all credentials are present
    check_credentials()
    SecurityLogger.log_event("SERVER_STARTUP")
    assistant = get_assistant()
    assistant._event_loop = asyncio.get_running_loop()
    # Start daily briefing scheduler
    asyncio.create_task(assistant._daily_briefing_scheduler())

# ==========================================
# SECURITY: Auto-token endpoint (localhost-only, safe)
# Since server is bound to 127.0.0.1, only local
# processes can access this — no external risk.
# ==========================================
@app.get("/api/ws-token")
async def get_ws_token():
    """Returns the WebSocket auth token.
    Safe because server only listens on localhost."""
    import os as _os
    token = _os.getenv("MIRO_SECRET_TOKEN", "")
    return {"token": token}

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
    # --- SECURITY: Token Authentication ---
    remote = str(websocket.client) if websocket.client else "unknown"
    token = websocket.query_params.get("token", "")
    if not verify_token(token):
        SecurityLogger.log_connection(remote, "REJECTED:invalid_token")
        await websocket.close(code=1008, reason="Unauthorized")
        return

    await websocket.accept()
    SecurityLogger.log_connection(remote, "ACCEPTED")

    assistant = get_assistant()
    # Track event loop and active connections for wake word broadcast
    import asyncio as _aio
    if assistant._event_loop is None:
        assistant._event_loop = _aio.get_event_loop()
    assistant._active_ws.append(websocket)
    connection_id = str(id(websocket))
    try:
        while True:
            raw = await websocket.receive_text()
            if not raw:
                continue

            # --- SECURITY: Rate Limiting ---
            if not _rate_limiter.is_allowed(connection_id):
                SecurityLogger.log_rate_limit(remote)
                await websocket.send_text("⚠️ Rate limit exceeded — max 30 messages per minute. Please wait.")
                continue

            # --- SECURITY: Input Sanitization ---
            # For JSON payloads (images, uploads, controls), only sanitize the text field
            text_to_check = raw
            try:
                _parsed = json.loads(raw)
                if isinstance(_parsed, dict):
                    # Control messages (get_history, new_chat, load_session) — skip sanitization
                    if _parsed.get("type") in ("get_history", "new_chat", "load_session", "upload"):
                        text_to_check = None
                    else:
                        # Image/vision payloads — only check the text field
                        text_to_check = _parsed.get("text", "")
            except (json.JSONDecodeError, ValueError):
                pass  # Plain text message, sanitize as-is

            if text_to_check:
                is_safe, sanitized = InputSanitizer.sanitize(text_to_check)
                if not is_safe:
                    SecurityLogger.log_blocked_input(remote)
                    await websocket.send_text(sanitized)
                    continue

            # Store current websocket for streaming
            assistant._current_ws = websocket
            response = await assistant.process_message(raw)
            # Only send plain text if response exists and wasn't already streamed
            if response and not getattr(assistant, '_was_streamed', False):
                await websocket.send_text(response)
            assistant._was_streamed = False
    except WebSocketDisconnect:
        SecurityLogger.log_disconnect(remote)
    except Exception as e:
        print(f"⚠️ WebSocket error: {e}")
        SecurityLogger.log_disconnect(remote)
    finally:
        _rate_limiter.cleanup(connection_id)
        if websocket in assistant._active_ws:
            assistant._active_ws.remove(websocket)
        if getattr(assistant, '_current_ws', None) == websocket:
            assistant._current_ws = None


if __name__ == "__main__":
    assistant = get_assistant()
    assistant.run()

