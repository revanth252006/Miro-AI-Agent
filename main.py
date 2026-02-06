import cv2
import sys
import time
import math
import threading
import numpy as np
import pyautogui
import uvicorn
import os
import asyncio
import google.generativeai as genai
import speech_recognition as sr  # <--- NEW: For listening
import pyttsx3                   # <--- NEW: For speaking
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv
from duckduckgo_search import DDGS

# --- 1. SETUP & SECRETS ---
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
PICOVOICE_API_KEY = os.getenv("PICOVOICE_API_KEY")

# --- 2. AUDIO ENGINE SETUP ---
engine = pyttsx3.init()
voices = engine.getProperty('voices')
# Try to find a good voice (Index 1 is usually female/better on Windows)
if len(voices) > 1:
    engine.setProperty('voice', voices[1].id)
engine.setProperty('rate', 170)

def speak(text):
    print(f"🗣️ MIRO: {text}")
    engine.say(text)
    engine.runAndWait()

# --- 3. DEPENDENCIES CHECK ---
try:
    from cvzone.HandTrackingModule import HandDetector
    from cvzone.ClassificationModule import Classifier
    import pvporcupine 
    import pyaudio
except ImportError:
    print("❌ CRITICAL: Missing libraries. Run 'pip install cvzone mediapipe pvporcupine pyaudio duckduckgo-search SpeechRecognition pyttsx3'") 
    sys.exit()

sys.path.append(".")

# ==========================================
# 🌐 FASTAPI SERVER
# ==========================================
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# 🧠 AI BRAIN (Shared Function)
# ==========================================
def ask_miro(prompt):
    """Processes text through Gemini with Search capability"""
    try:
        if not GEMINI_API_KEY:
            return "I need a Gemini API key to work."

        # 1. Search Check
        search_context = ""
        triggers = ["price", "stock", "news", "weather", "who", "what", "current", "latest", "today", "now", "search", "time"]
        
        if any(t in prompt.lower() for t in triggers):
            print("🔍 Searching Internet...")
            try:
                results = DDGS().text(prompt, max_results=2)
                if results:
                    formatted = "\n".join([f"* {r['title']}: {r['body']}" for r in results])
                    search_context = f"\n\n[LIVE SEARCH DATA]:\n{formatted}\n"
            except Exception as e:
                print(f"⚠️ Search Error: {e}")

        # 2. Gemini Prompt
        system_instruction = """
        You are Miro, a helpful voice assistant.
        - Keep answers SHORT and CONVERSATIONAL (1-2 sentences).
        - If you have [LIVE SEARCH DATA], use it.
        - If the user asks to "activate mouse" or "open eyes", confirm you are doing it.
        """
        
        final_prompt = f"{system_instruction}\n\nUser: {prompt}{search_context}"
        
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel('gemini-pro')
        response = model.generate_content(final_prompt)
        return response.text
    except Exception as e:
        return "I'm having trouble connecting to the server."

# ==========================================
# 🔄 GLOBAL STATE
# ==========================================
class SystemState:
    def __init__(self):
        self.camera_active = False 
        self.mode = "IDLE"  # Modes: IDLE, MOUSE, SIGN
        self.stop_event = threading.Event()

STATE = SystemState()

# ==========================================
# 🎤 VOICE THREAD (Wake Word + Command)
# ==========================================
def listen_for_command():
    r = sr.Recognizer()
    with sr.Microphone() as source:
        print("🎤 Listening for command...")
        # Optional: Play a sound here to indicate listening
        try:
            audio = r.listen(source, timeout=5, phrase_time_limit=5)
            command = r.recognize_google(audio)
            print(f"You said: {command}")
            return command.lower()
        except sr.WaitTimeoutError:
            return None
        except sr.UnknownValueError:
            return None
        except Exception as e:
            print(f"Error: {e}")
            return None

def voice_loop_thread():
    if not PICOVOICE_API_KEY:
        print("❌ Voice disabled (No API Key).")
        return

    # Try to load custom wake word, else default to Jarvis
    miro_path = None
    for file in os.listdir("."):
        if file.endswith(".ppn"):
            miro_path = file
            break
            
    try:
        if miro_path:
            porcupine = pvporcupine.create(access_key=PICOVOICE_API_KEY, keyword_paths=[miro_path])
        else:
            porcupine = pvporcupine.create(access_key=PICOVOICE_API_KEY, keywords=['jarvis'])
        
        pa = pyaudio.PyAudio()
        stream = pa.open(rate=porcupine.sample_rate, channels=1, format=pyaudio.paInt16, input=True, frames_per_buffer=porcupine.frame_length)
        
        print("👂 Listening for Wake Word...")
        
        while not STATE.stop_event.is_set():
            pcm = stream.read(porcupine.frame_length, exception_on_overflow=False)
            pcm = np.frombuffer(pcm, dtype=np.int16)
            keyword_index = porcupine.process(pcm)

            if keyword_index >= 0:
                print("⚡ WAKE WORD DETECTED!")
                
                # 1. PAUSE DETECTION & SPEAK
                # DO NOT ACTIVATE MOUSE HERE AUTOMATICALLY
                speak("Yes?") 
                
                # 2. LISTEN FOR COMMAND (Requires a new microphone stream usually, or handling pyaudio carefully)
                # For simplicity, we pause the stream to use SpeechRecognition
                stream.close() 
                
                command = listen_for_command()
                
                if command:
                    # --- CONTROL LOGIC ---
                    if "mouse" in command or "control" in command:
                        STATE.mode = "MOUSE"
                        STATE.camera_active = True
                        speak("Activating visual mouse control.")
                        
                    elif "sign" in command:
                        STATE.mode = "SIGN"
                        STATE.camera_active = True
                        speak("Sign language mode active.")
                        
                    elif "stop" in command or "sleep" in command:
                        STATE.camera_active = False
                        STATE.mode = "IDLE"
                        speak("Going to sleep.")
                        
                    else:
                        # Ask AI
                        response = ask_miro(command)
                        speak(response)

                # 3. RESTART WAKE WORD LISTENER
                stream = pa.open(rate=porcupine.sample_rate, channels=1, format=pyaudio.paInt16, input=True, frames_per_buffer=porcupine.frame_length)

    except Exception as e:
        print(f"❌ Voice Error: {e}")

# ==========================================
# 📸 CAMERA & MOUSE LOGIC (Unchanged mostly)
# ==========================================
class VirtualMouse:
    def __init__(self):
        pyautogui.FAILSAFE = False 
        self.wScr, self.hScr = pyautogui.size()
        self.frameR = 100
        self.smoothening = 5
        self.plocX, self.plocY = 0, 0
        self.clocX, self.clocY = 0, 0
        self.last_click_time = 0 

    def process(self, img, hands, detector):
        if not hands: return img
        hand = hands[0]
        lmList = hand['lmList']
        fingers = detector.fingersUp(hand)
        h, w, _ = img.shape
        cv2.rectangle(img, (self.frameR, self.frameR), (w - self.frameR, h - self.frameR), (255, 0, 255), 2)

        # Movement Mode (Index Finger Up)
        if fingers[1] == 1 and fingers[2] == 0:
            x1, y1 = lmList[8][0], lmList[8][1]
            x3 = np.interp(x1, (self.frameR, w - self.frameR), (0, self.wScr))
            y3 = np.interp(y1, (self.frameR, h - self.frameR), (0, self.hScr))
            self.clocX = self.plocX + (x3 - self.plocX) / self.smoothening
            self.clocY = self.plocY + (y3 - self.plocY) / self.smoothening
            try: pyautogui.moveTo(self.wScr - self.clocX, self.clocY)
            except: pass
            cv2.circle(img, (x1, y1), 15, (255, 0, 255), cv2.FILLED)
            self.plocX, self.plocY = self.clocX, self.clocY

        # Click Mode (Index + Middle Finger Up)
        if fingers[1] == 1 and fingers[2] == 1:
            length, info, img = detector.findDistance(lmList[8][0:2], lmList[12][0:2], img)
            if length < 40:
                cv2.circle(img, (info[4], info[5]), 15, (0, 255, 0), cv2.FILLED)
                if time.time() - self.last_click_time > 0.5: 
                    pyautogui.click()
                    self.last_click_time = time.time()
        return img

def camera_loop():
    cap = None
    detector = HandDetector(maxHands=1)
    mouse_engine = VirtualMouse()
    # sign_engine = SignDetector() # Uncomment if you have the model

    while not STATE.stop_event.is_set():
        if STATE.camera_active:
            if cap is None:
                cap = cv2.VideoCapture(0)
                cap.set(3, 640)
                cap.set(4, 480)
            
            success, img = cap.read()
            if success:
                hands, img = detector.findHands(img, flipType=False)
                
                # ONLY ACTIVATE MOUSE IF MODE IS SPECIFICALLY "MOUSE"
                if STATE.mode == "MOUSE":
                    img = mouse_engine.process(img, hands, detector)
                    cv2.putText(img, "MOUSE MODE", (10, 50), cv2.FONT_HERSHEY_PLAIN, 2, (0, 255, 0), 2)
                elif STATE.mode == "SIGN":
                    # img, label = sign_engine.process(img, hands)
                    pass
                else:
                    cv2.putText(img, "CAMERA ON - WAITING", (10, 50), cv2.FONT_HERSHEY_PLAIN, 2, (0, 0, 255), 2)
                
                cv2.imshow("Miro Vision", img)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    STATE.camera_active = False 
                    cv2.destroyAllWindows()
                    if cap: cap.release()
                    cap = None
        else:
            if cap: 
                cap.release()
                cap = None
                cv2.destroyAllWindows()
            time.sleep(0.5)

# ==========================================
# 🚀 START
# ==========================================
if __name__ == "__main__":
    print("--- 🚀 MIRO SYSTEM STARTING ---")
    
    # Start Voice Thread
    vt = threading.Thread(target=voice_loop_thread, daemon=True)
    vt.start()

    # Start Camera Thread
    ct = threading.Thread(target=camera_loop, daemon=True)
    ct.start()
    
    # Start API
    uvicorn.run(app, host="0.0.0.0", port=8000)