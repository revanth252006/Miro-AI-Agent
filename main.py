import cv2
import sys
import time
import math
import threading
import numpy as np
import pyautogui
import uvicorn
import os
from fastapi.staticfiles import StaticFiles
from duckduckgo_search import DDGS # <--- Add this
# --- ADD THESE TO YOUR IMPORTS ---
import google.generativeai as genai
from pydantic import BaseModel
from dotenv import load_dotenv
from duckduckgo_search import DDGS  # <--- Ensure this is here

# --- SETUP API KEYS ---
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Configure Gemini immediately
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
else:
    print("⚠️ WARNING: GEMINI_API_KEY missing in .env")

# --- DEPENDENCIES ---
# Run: pip install cvzone mediapipe pyautogui tensorflow
try:
    from cvzone.HandTrackingModule import HandDetector
    from cvzone.ClassificationModule import Classifier
except ImportError:
    print("❌ CRITICAL: Missing libraries. Run: pip install cvzone mediapipe pyautogui tensorflow")
    sys.exit()

# Add current path
sys.path.append(".")

# --- IMPORT AGENT ---
try:
    from agent.assistant import VoiceAssistant, set_system_state_callback, app
    AGENT_AVAILABLE = True
except ImportError as e:
    print(f"❌ Agent Import Error: {e}")
    AGENT_AVAILABLE = False
    app = None

# --- GLOBAL STATE ---
class SystemState:
    def __init__(self):
        self.camera_active = False
        self.mode = "IDLE"  # IDLE, MOUSE, SIGN
        self.stop_event = threading.Event()

STATE = SystemState()

# ==========================================
# 1. OPTIMIZED VIRTUAL MOUSE LOGIC (FIXED)
# ==========================================
class VirtualMouse:
    def __init__(self):
        # Safety: Prevents crash when mouse hits corner
        pyautogui.FAILSAFE = False 
        self.wScr, self.hScr = pyautogui.size()
        
        # TWEAK THESE FOR SMOOTHNESS
        self.frameR = 100        # Box size (Lower = more sensitive)
        self.smoothening = 5     # Lower (3-5) = Faster, Higher (7-10) = Smoother but slower
        
        self.plocX, self.plocY = 0, 0
        self.clocX, self.clocY = 0, 0
        self.last_click_time = 0 # For non-blocking click

    def process(self, img, hands, detector):
        if not hands: return img
        
        hand = hands[0]
        lmList = hand['lmList']
        fingers = detector.fingersUp(hand)
        
        # Draw Boundary Box (Move hand inside this box to cover full screen)
        h, w, _ = img.shape
        cv2.rectangle(img, (self.frameR, self.frameR), (w - self.frameR, h - self.frameR), (255, 0, 255), 2)

        # 1. Moving Mode: Index Finger Up Only
        if fingers[1] == 1 and fingers[2] == 0:
            x1, y1 = lmList[8][0], lmList[8][1]
            
            # Convert Coordinates (Webcam -> Screen)
            x3 = np.interp(x1, (self.frameR, w - self.frameR), (0, self.wScr))
            y3 = np.interp(y1, (self.frameR, h - self.frameR), (0, self.hScr))

            # Smoothening Logic (Exponential Moving Average)
            self.clocX = self.plocX + (x3 - self.plocX) / self.smoothening
            self.clocY = self.plocY + (y3 - self.plocY) / self.smoothening

            # Move Mouse (Inverted X for natural mirror movement)
            try: pyautogui.moveTo(self.wScr - self.clocX, self.clocY)
            except: pass
            
            cv2.circle(img, (x1, y1), 15, (255, 0, 255), cv2.FILLED)
            self.plocX, self.plocY = self.clocX, self.clocY

        # 2. Clicking Mode: Index + Middle Fingers Up
        if fingers[1] == 1 and fingers[2] == 1:
            length, info, img = detector.findDistance(lmList[8][0:2], lmList[12][0:2], img)
            
            # Click Threshold
            if length < 40:
                cv2.circle(img, (info[4], info[5]), 15, (0, 255, 0), cv2.FILLED)
                
                # FIXED: Non-blocking timer instead of time.sleep()
                if time.time() - self.last_click_time > 0.5: # 0.5s delay between clicks
                    pyautogui.click()
                    self.last_click_time = time.time()
                
        return img

# ==========================================
# 2. EMBEDDED SIGN DETECTOR LOGIC
# ==========================================
class SignDetector:
    def __init__(self):
        self.classifier = None
        self.labels = []
        try:
            # Update these paths if your model is elsewhere
            self.classifier = Classifier("sign_detection/Model/keras_model.h5", "sign_detection/Model/labels.txt")
            print("✅ Sign Model Loaded.")
        except:
            print("⚠️ Sign Model not found at 'sign_detection/Model/'. Check paths.")

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
# 3. CORE LOGIC & HARDWARE LOOP
# ==========================================

def handle_command(command: str):
    """Callback from AI Agent"""
    command = command.lower()
    print(f"⚙️ Hardware Command: {command}")
    
    if "stop" in command or "disconnect" in command:
        STATE.mode = "IDLE"
        STATE.camera_active = False
        
    elif "mouse" in command:
        STATE.mode = "MOUSE"
        STATE.camera_active = True
        
    elif "sign" in command or "vision" in command:
        STATE.mode = "SIGN"
        STATE.camera_active = True

def camera_loop():
    cap = None
    detector = HandDetector(maxHands=1)
    
    # Initialize Engines
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
                # IMPORTANT: Don't flip for mouse, otherwise left is right
                # img = cv2.flip(img, 1) 
                
                hands, img = detector.findHands(img, flipType=False)
                
                if STATE.mode == "MOUSE":
                    img = mouse_engine.process(img, hands, detector)
                    cv2.putText(img, "MODE: MOUSE", (10, 50), cv2.FONT_HERSHEY_PLAIN, 2, (0, 255, 0), 2)
                    
                elif STATE.mode == "SIGN":
                    img, label = sign_engine.process(img, hands)
                    cv2.putText(img, f"MODE: SIGN ({label if label else ''})", (10, 50), cv2.FONT_HERSHEY_PLAIN, 2, (0, 255, 0), 2)

                cv2.imshow("Miro Vision", img)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    handle_command("stop")
        else:
            if cap:
                cap.release()
                cap = None
                cv2.destroyAllWindows()
            time.sleep(0.5)
# ==========================================
# 🧠 REAL-TIME SEARCH CHAT (Adds to your App)
# ==========================================
class UserMessage(BaseModel):
    message: str

@app.post("/chat")
async def chat_endpoint(data: UserMessage):
    print(f"📩 RECEIVED: {data.message}") 

    try:
        # 1. SEARCH THE WEB (DuckDuckGo)
        search_context = ""
        print("🔍 Searching web...")
        try:
            # Search specifically for the user's query
            results = DDGS().text(data.message, max_results=3)
            if results:
                search_context = f"\n\nReal-Time Web Search Results:\n{str(results)}\n"
        except Exception as e:
            print(f"⚠️ Search skipped: {e}")

        # 2. CREATE SMART PROMPT
        system_instruction = """
        You are Miro, an AI assistant with real-time web access.
        - If 'Real-Time Web Search Results' are provided below, USE THEM to answer accurately.
        - If the user asks about current events (stock prices, sports, news), trust the search results.
        - Be concise and friendly.
        """
        
        final_prompt = f"{system_instruction}\n\nUser: {data.message}{search_context}"

        # 3. GET ANSWER FROM GEMINI
        model = genai.GenerativeModel('gemini-pro')
        response = model.generate_content(final_prompt)
        
        return {"response": response.text}

    except Exception as e:
        print(f"❌ Error: {e}")
        return {"response": "I'm having trouble connecting to the internet right now."}
# ==========================================
# 4. MAIN ENTRY POINT
# ==========================================
def main():
    print("--- 🚀 MIRO SYSTEM INITIALIZING ---")
    
    # 1. Start Camera Thread
    t = threading.Thread(target=camera_loop, daemon=True)
    t.start()

    # 2. Link & Start Server
    if AGENT_AVAILABLE and app:
        print("🔗 Linking Agent to Hardware...")
        set_system_state_callback(handle_command)
        
        if os.path.exists("frontend"):
            print("🌍 Hosting Frontend at http://localhost:8000")
            app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
            
        uvicorn.run(app, host="0.0.0.0", port=8000, log_level="error")
    else:
        print("❌ Critical: Agent not loaded.")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        STATE.stop_event.set()
        sys.exit(0)