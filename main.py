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
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv
from duckduckgo_search import DDGS  # <--- REAL-TIME SEARCH TOOL

# --- 1. SETUP & SECRETS ---
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
PICOVOICE_API_KEY = os.getenv("PICOVOICE_API_KEY")

# --- 2. DEPENDENCIES CHECK ---
try:
    from cvzone.HandTrackingModule import HandDetector
    from cvzone.ClassificationModule import Classifier
    import pvporcupine 
    import pyaudio
except ImportError:
    print("❌ CRITICAL: Missing libraries. Run 'pip install cvzone mediapipe pvporcupine pyaudio duckduckgo-search'") 
    sys.exit()

sys.path.append(".")

# ==========================================
# 🌐 FASTAPI SERVER (The Brain)
# ==========================================
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

connected_clients = []

# --- 👂 WAKE WORD SOCKET ---
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_clients.append(websocket)
    print("🟢 Agent Connected (WebSocket)")
    try:
        while True:
            await websocket.receive_text() # Keep alive
    except:
        if websocket in connected_clients:
            connected_clients.remove(websocket)
        print("🔴 Agent Disconnected")

async def broadcast_wake_signal():
    for client in connected_clients:
        try: await client.send_text("WAKE_UP")
        except: pass

# ==========================================
# 🧠 AGGRESSIVE REAL-TIME SEARCH CHAT
# ==========================================
class UserMessage(BaseModel):
    message: str

@app.post("/chat")
async def chat_endpoint(data: UserMessage):
    print(f"📩 RECEIVED: {data.message}") 

    try:
        if not GEMINI_API_KEY:
            return {"response": "❌ Error: Missing GEMINI_API_KEY in .env"}

        # --- 1. FORCE SEARCH (Aggressive) ---
        search_context = ""
        # We search for almost everything to guarantee fresh data
        triggers = ["price", "stock", "news", "weather", "who", "what", "current", "latest", "today", "now", "search"]
        
        if any(t in data.message.lower() for t in triggers):
            print("🔍 Searching Internet...")
            try:
                # Get raw results
                results = DDGS().text(data.message, max_results=3)
                if results:
                    print("✅ WEB DATA FOUND!")
                    # Format as bullet points for the AI
                    formatted = "\n".join([f"* {r['title']}: {r['body']}" for r in results])
                    search_context = f"\n\n[LIVE SEARCH DATA - USE THIS]:\n{formatted}\n"
                else:
                    print("⚠️ No results found.")
            except Exception as e:
                print(f"⚠️ Search Error: {e}")

        # --- 2. FORCE AI TO USE DATA ---
        system_instruction = """
        You are Miro, an AI Agent with LIVE internet access.
        
        CRITICAL RULES:
        1. If '[LIVE SEARCH DATA]' is provided below, you MUST use it to answer.
        2. Do NOT say "I don't have real-time access". You DO have it in the prompt.
        3. If the user asks for stocks/news, quote the numbers from the search data.
        4. Be direct and concise.
        """
        
        final_prompt = f"{system_instruction}\n\nUser Question: {data.message}{search_context}"

        # --- 3. GENERATE ANSWER ---
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel('gemini-pro')
        response = model.generate_content(final_prompt)
        
        return {"response": response.text}

    except Exception as e:
        print(f"❌ AI Error: {e}")
        return {"response": "I'm having trouble thinking right now."}

# ==========================================
# 🔄 GLOBAL STATE MANAGER
# ==========================================
class SystemState:
    def __init__(self):
        self.camera_active = False 
        self.mode = "IDLE" 
        self.stop_event = threading.Event()

STATE = SystemState()

# ==========================================
# 🖱️ VIRTUAL MOUSE LOGIC
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

        if fingers[1] == 1 and fingers[2] == 1:
            length, info, img = detector.findDistance(lmList[8][0:2], lmList[12][0:2], img)
            if length < 40:
                cv2.circle(img, (info[4], info[5]), 15, (0, 255, 0), cv2.FILLED)
                if time.time() - self.last_click_time > 0.5: 
                    pyautogui.click()
                    self.last_click_time = time.time()
        return img

# ==========================================
# ✋ SIGN DETECTOR LOGIC
# ==========================================
class SignDetector:
    def __init__(self):
        try:
            self.classifier = Classifier("sign_detection/Model/keras_model.h5", "sign_detection/Model/labels.txt")
            print("✅ Sign Model Loaded.")
        except:
            self.classifier = None
            print("⚠️ Sign Model not found.")

    def process(self, img, hands):
        if not self.classifier or not hands: return img, None
        hand = hands[0]
        x, y, w, h = hand['bbox']
        imgWhite = np.ones((300, 300, 3), np.uint8) * 255
        imgCrop = img[y - 20:y + h + 20, x - 20:x + w + 20]
        try:
            aspectRatio = h / w
            if aspectRatio > 1:
                k = 300 / h
                wCal = math.ceil(k * w)
                imgResize = cv2.resize(imgCrop, (wCal, 300))
                wGap = math.ceil((300 - wCal) / 2)
                imgWhite[:, wGap:wCal + wGap] = imgResize
            else:
                k = 300 / w
                hCal = math.ceil(k * h)
                imgResize = cv2.resize(imgCrop, (300, hCal))
                hGap = math.ceil((300 - hCal) / 2)
                imgWhite[hGap:hCal + hGap, :] = imgResize
            
            prediction, index = self.classifier.getPrediction(imgWhite, draw=False)
            label = self.classifier.labels[index]
            cv2.rectangle(img, (x - 20, y - 20), (x + w + 20, y + h + 20), (255, 0, 255), 4)
            cv2.putText(img, label, (x, y - 26), cv2.FONT_HERSHEY_COMPLEX, 1.7, (255, 255, 255), 2)
            return img, label
        except: 
            return img, None

# ==========================================
# 🎤 WAKE WORD THREAD
# ==========================================
def voice_loop_thread(loop):
    if not PICOVOICE_API_KEY:
        print("❌ PICOVOICE_API_KEY missing. Voice disabled.")
        return

    miro_path = None
    for file in os.listdir("."):
        if file.endswith(".ppn") and "hey" in file.lower():
            miro_path = file
            break
            
    try:
        if miro_path:
            porcupine = pvporcupine.create(access_key=PICOVOICE_API_KEY, keyword_paths=[miro_path])
            print(f"✅ Wake Word Active: {miro_path}")
        else:
            porcupine = pvporcupine.create(access_key=PICOVOICE_API_KEY, keywords=['jarvis'])
            print("⚠️ Using Default Wake Word: Jarvis")

        pa = pyaudio.PyAudio()
        stream = pa.open(rate=porcupine.sample_rate, channels=1, format=pyaudio.paInt16, input=True, frames_per_buffer=porcupine.frame_length)
        
        print("👂 Listening for Wake Word...")
        
        while not STATE.stop_event.is_set():
            pcm = stream.read(porcupine.frame_length, exception_on_overflow=False)
            pcm = np.frombuffer(pcm, dtype=np.int16)
            keyword_index = porcupine.process(pcm)

            if keyword_index >= 0:
                print("⚡ WAKE WORD DETECTED!")
                STATE.camera_active = True 
                asyncio.run_coroutine_threadsafe(broadcast_wake_signal(), loop)
                time.sleep(1)

    except Exception as e:
        print(f"❌ Voice Error: {e}")

# ==========================================
# 📸 CAMERA THREAD
# ==========================================
def camera_loop():
    cap = None
    detector = HandDetector(maxHands=1)
    mouse_engine = VirtualMouse()
    sign_engine = SignDetector()

    while not STATE.stop_event.is_set():
        if STATE.camera_active:
            if cap is None or not cap.isOpened():
                cap = cv2.VideoCapture(0)
                cap.set(3, 640)
                cap.set(4, 480)
            
            success, img = cap.read()
            if success:
                hands, img = detector.findHands(img, flipType=False)
                
                if STATE.mode == "SIGN":
                    img, label = sign_engine.process(img, hands)
                    cv2.putText(img, f"SIGN: {label}", (10, 50), cv2.FONT_HERSHEY_PLAIN, 2, (0, 255, 0), 2)
                else:
                    img = mouse_engine.process(img, hands, detector)
                    cv2.putText(img, "MOUSE MODE", (10, 50), cv2.FONT_HERSHEY_PLAIN, 2, (0, 255, 0), 2)
                
                cv2.imshow("Miro Vision", img)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    STATE.camera_active = False 
                    cv2.destroyAllWindows()
                    cap.release()
                    cap = None
        else:
            if cap: 
                cap.release()
                cap = None
                cv2.destroyAllWindows()
            time.sleep(0.5)

# ==========================================
# 🚀 MAIN ENTRY POINT
# ==========================================
if __name__ == "__main__":
    print("--- 🚀 MIRO SYSTEM STARTING ---")
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    vt = threading.Thread(target=voice_loop_thread, args=(loop,), daemon=True)
    vt.start()

    ct = threading.Thread(target=camera_loop, daemon=True)
    ct.start()
    
    # HOST FRONTEND IF EXISTS
    if os.path.exists("frontend"):
        print("🌍 Hosting Frontend at http://localhost:8000")
        app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
    
    uvicorn.run(app, host="0.0.0.0", port=8000)