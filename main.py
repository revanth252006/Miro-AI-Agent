import cv2
import sys
import time
import math
import threading
import numpy as np
import pyautogui
import uvicorn
import os
import speech_recognition as sr
import asyncio
import zipfile
import webbrowser  
import pyttsx3     
from fastapi.staticfiles import StaticFiles

# --- DEPENDENCIES CHECK ---
try:
    from cvzone.HandTrackingModule import HandDetector
    from cvzone.ClassificationModule import Classifier
    import pvporcupine 
    import pyaudio
except ImportError:
    print("❌ CRITICAL: Missing libraries.") 
    time.sleep(5)
    sys.exit()

sys.path.append(".")

# --- IMPORT AGENT ---
try:
    from agent.assistant import VoiceAssistant, set_system_state_callback, app
    AGENT_AVAILABLE = True
except ImportError as e:
    print(f"❌ Agent Import Error: {e}")
    AGENT_AVAILABLE = False
    app = None

# --- GLOBAL STATE MANAGER ---
class SystemState:
    def __init__(self):
        self.camera_active = False
        self.mode = "IDLE" 
        self.listening_for_wake_word = True
        self.browser_opened = False 
        self.stop_event = threading.Event()

STATE = SystemState()

# ==========================================
# 0. TEXT TO SPEECH ENGINE
# ==========================================
def speak(text):
    """Makes the AI speak out loud"""
    try:
        engine = pyttsx3.init()
        engine.setProperty('rate', 170) 
        engine.setProperty('volume', 1.0)
        engine.say(text)
        engine.runAndWait()
        del engine
    except Exception as e:
        print(f"❌ TTS Error: {e}")

# ==========================================
# 1. VIRTUAL MOUSE LOGIC
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
# 2. SIGN DETECTOR LOGIC
# ==========================================
class SignDetector:
    def __init__(self):
        self.classifier = None
        self.labels = []
        try:
            self.classifier = Classifier("sign_detection/Model/keras_model.h5", "sign_detection/Model/labels.txt")
            print("✅ Sign Model Loaded.")
        except:
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
# 3. WAKE WORD ENGINE
# ==========================================
class WakeWordListener:
    def __init__(self):
        from dotenv import load_dotenv
        load_dotenv()
        self.access_key = os.getenv("PICOVOICE_API_KEY")
        if not self.access_key:
            print("❌ Error: Missing PICOVOICE_API_KEY in .env")
            self.porcupine = None
            return

        self.miro_path = self._find_or_extract_model()
        
        try:
            if self.miro_path:
                print(f"✅ Found Custom Wake Word: {self.miro_path}")
                self.porcupine = pvporcupine.create(access_key=self.access_key, keyword_paths=[self.miro_path])
            else:
                print("⚠️ Using Default 'Jarvis'.")
                self.porcupine = pvporcupine.create(access_key=self.access_key, keywords=['jarvis'])
        except Exception as e:
            print(f"❌ Porcupine Error: {e}")
            self.porcupine = None
        
        self.pa = pyaudio.PyAudio()
        self.audio_stream = None

    def _find_or_extract_model(self):
        for file in os.listdir("."):
            if file.lower().endswith(".ppn") and "hey" in file.lower(): return file
        for file in os.listdir("."):
            if file.lower().endswith(".zip") and "hey" in file.lower():
                try:
                    with zipfile.ZipFile(file, 'r') as zip_ref: zip_ref.extractall(".")
                    for f in os.listdir("."):
                        if f.lower().endswith(".ppn") and "hey" in f.lower(): return f
                except: pass
        return None

    def start(self):
        if not self.porcupine: return False
        self.audio_stream = self.pa.open(rate=self.porcupine.sample_rate, channels=1, format=pyaudio.paInt16, input=True, frames_per_buffer=self.porcupine.frame_length)
        return True

    def listen(self):
        if not self.audio_stream: return False
        try:
            pcm = self.audio_stream.read(self.porcupine.frame_length, exception_on_overflow=False)
            pcm = np.frombuffer(pcm, dtype=np.int16)
            keyword_index = self.porcupine.process(pcm)
            if keyword_index >= 0: return True
        except: pass
        return False

    def close(self):
        if self.audio_stream: self.audio_stream.close()
        if self.pa: self.pa.terminate()
        if self.porcupine: self.porcupine.delete()

# ==========================================
# 4. VOICE RECOGNITION LOOP
# ==========================================
def listen_for_command():
    recognizer = sr.Recognizer()
    microphone = sr.Microphone()
    with microphone as source:
        print("🎤 Listening for command...")
        try:
            recognizer.adjust_for_ambient_noise(source, duration=0.5)
            audio = recognizer.listen(source, timeout=5)
            print("Processing...")
            command = recognizer.recognize_google(audio)
            print(f"🗣️ You said: {command}")
            return command
        except sr.WaitTimeoutError: return None
        except: return None

def voice_loop_thread():
    if not AGENT_AVAILABLE: return
    wake = WakeWordListener()
    if not wake.start(): return

    ai_logic = VoiceAssistant()
    active_word = "Hey Miro" if wake.miro_path else "Jarvis"
    print(f"👂 Voice System Online. Say '{active_word}' to wake me up.")

    while not STATE.stop_event.is_set():
        if STATE.listening_for_wake_word:
            if wake.listen():
                print(f"⚡ WAKE WORD DETECTED: {active_word}!")
                STATE.listening_for_wake_word = False
                
                # --- AUTO-NAVIGATE TO VERCEL ---
                if not STATE.browser_opened:
                     # 🔽 UPDATED: Now points to your Vercel App
                     webbrowser.open("https://miro-ai-agent.vercel.app/") 
                     STATE.browser_opened = True

                speak("I'm listening.")
                
                cmd = listen_for_command()
                if cmd:
                    print(f"🤖 Processing: {cmd}")
                    resp = asyncio.run(ai_logic.process_message(cmd))
                    print(f"🤖 AI: {resp}")
                    speak(resp)
                
                print("💤 Returning to sleep...")
                STATE.listening_for_wake_word = True
        else:
            time.sleep(0.1)
    wake.close()

# ==========================================
# 5. MAIN LOGIC
# ==========================================
def handle_command(command: str):
    command = command.lower()
    print(f"⚙️ Hardware Command: {command}")
    if "stop" in command: STATE.mode = "IDLE"; STATE.camera_active = False
    elif "mouse" in command: STATE.mode = "MOUSE"; STATE.camera_active = True
    elif "sign" in command: STATE.mode = "SIGN"; STATE.camera_active = True

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
                if STATE.mode == "MOUSE":
                    img = mouse_engine.process(img, hands, detector)
                    cv2.putText(img, "MODE: MOUSE", (10, 50), cv2.FONT_HERSHEY_PLAIN, 2, (0, 255, 0), 2)
                elif STATE.mode == "SIGN":
                    img, label = sign_engine.process(img, hands)
                    cv2.putText(img, f"MODE: SIGN ({label if label else ''})", (10, 50), cv2.FONT_HERSHEY_PLAIN, 2, (0, 255, 0), 2)
                cv2.imshow("Miro Vision", img)
                if cv2.waitKey(1) & 0xFF == ord('q'): handle_command("stop")
        else:
            if cap: cap.release(); cap = None; cv2.destroyAllWindows()
            time.sleep(0.5)

def main():
    print("--- 🚀 MIRO SYSTEM INITIALIZING ---")
    vt = threading.Thread(target=voice_loop_thread, daemon=True)
    vt.start()
    ct = threading.Thread(target=camera_loop, daemon=True)
    ct.start()
    if AGENT_AVAILABLE and app:
        print("🔗 Linking Agent...")
        set_system_state_callback(handle_command)
        # Hosting local is optional now since you use Vercel, 
        # but we keep it running for the backend API
        uvicorn.run(app, host="0.0.0.0", port=8000, log_level="error")
    else: print("❌ Critical: Agent not loaded.")

if __name__ == "__main__":
    try: main()
    except KeyboardInterrupt: STATE.stop_event.set(); sys.exit(0)