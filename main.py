import cv2
import sys
import time
import threading
import pyautogui
import os
import uvicorn
from fastapi.staticfiles import StaticFiles

# Add current path
sys.path.append(".")

# --- 1. IMPORT VISION MODULES ---
try:
    from virtual_mouse.mouse_logic import VirtualMouse
    MOUSE_AVAILABLE = True
except ImportError:
    print("⚠️ Virtual Mouse not found. Mouse mode disabled.")
    MOUSE_AVAILABLE = False

try:
    from sign_detection.detector import SignDetector
    SIGN_AVAILABLE = True
except ImportError:
    print("⚠️ Sign Detector not found. Sign mode disabled.")
    SIGN_AVAILABLE = False

# --- 2. IMPORT AGENT & SERVER ---
try:
    from agent.assistant import VoiceAssistant, set_system_state_callback, app
    AGENT_AVAILABLE = True
except ImportError as e:
    AGENT_AVAILABLE = False
    app = None
    print(f"❌ Agent Import Error: {e}")
    print("👉 HINT: Make sure you updated agent/assistant.py to use Lazy Imports!")

# --- GLOBAL STATE MANAGER ---
class SystemState:
    def __init__(self):
        self.camera_active = False
        self.mode = "IDLE"  # Options: IDLE, MOUSE, SIGN, VISION
        self.stop_event = threading.Event()

STATE = SystemState()

# --- COMMAND HANDLER ---
def handle_command(command: str):
    """
    Called by the AI Agent to switch hardware modes.
    """
    command = command.lower()
    print(f"⚙️ Hardware Command: {command}")
    
    # 1. STOP / DISCONNECT
    if "stop" in command or "disconnect" in command:
        STATE.mode = "IDLE"
        STATE.camera_active = False
        print("🛑 Hardware Stopped (Camera Released).")

    # 2. MOUSE MODE
    elif "mouse" in command:
        if MOUSE_AVAILABLE:
            STATE.mode = "MOUSE"
            STATE.camera_active = True  # Python needs camera
            print("🖱️ Mouse Mode Active")
        else:
            print("⚠️ Mouse module missing.")

    # 3. SIGN MODE
    elif "sign" in command:
        if SIGN_AVAILABLE:
            STATE.mode = "SIGN"
            STATE.camera_active = True  # Python needs camera
            print("✌️ Sign Mode Active")
        else:
            print("⚠️ Sign module missing.")

    # 4. VISION MODE (THE FIX)
    elif "vision" in command or "camera" in command:
        STATE.mode = "VISION"
        STATE.camera_active = False  # <--- FALSE: Release camera for Browser
        print("👁️ Vision Mode: Camera released to Browser/Frontend.")

# --- CAMERA THREAD ---
def camera_loop():
    """
    Central loop that switches behavior based on STATE.mode
    """
    cap = None
    mouse = None
    sign_detector = None
    
    # Lazy Load Models
    if MOUSE_AVAILABLE:
        try: mouse = VirtualMouse()
        except: pass
        
    if SIGN_AVAILABLE:
        try: 
            sign_detector = SignDetector(
                model_path="sign_detection/Model/keras_model.h5", 
                labels_path="sign_detection/Model/labels.txt"
            )
        except: pass

    last_key_time = 0
    type_delay = 1.0

    while not STATE.stop_event.is_set():
        if STATE.camera_active:
            # Start Camera if needed
            if cap is None or not cap.isOpened():
                cap = cv2.VideoCapture(0)
                cap.set(3, 640)
                cap.set(4, 480)

            success, img = cap.read()
            if success:
                # NOTE: We DO NOT flip the image here so the Mouse works naturally.
                # img = cv2.flip(img, 1) 

                # --- A. MOUSE MODE ---
                if STATE.mode == "MOUSE" and mouse:
                    try: 
                        img = mouse.process_frame(img)
                    except: pass
                
                # --- B. SIGN MODE ---
                elif STATE.mode == "SIGN" and sign_detector:
                    try:
                        result = sign_detector.predict(img)
                        text = None
                        conf = 1.0
                        
                        # Handle varied return types
                        if isinstance(result, tuple):
                            if len(result) == 3: text, conf, img = result
                            elif len(result) == 2: text, img = result

                        if text:
                            # Display detected sign
                            cv2.putText(img, f"Sign: {text}", (10, 50), cv2.FONT_HERSHEY_PLAIN, 2, (0, 255, 0), 2)
                            
                            # Typing Logic
                            if conf > 0.8 and (time.time() - last_key_time > type_delay):
                                key = text.lower().strip()
                                print(f"⌨️ Typing: {key}")
                                
                                if key == "space": pyautogui.press("space")
                                elif key == "enter": pyautogui.press("enter")
                                elif key == "backspace" or key == "delete": pyautogui.press("backspace")
                                elif len(key) == 1: pyautogui.write(key)
                                
                                last_key_time = time.time()

                    except Exception as e: 
                        print(f"Sign Error: {e}")
                
                # --- C. VISION MODE (Placeholder) ---
                elif STATE.mode == "VISION":
                    # This block rarely runs because active=False, but good for safety
                    cv2.putText(img, "Miro Vision Active", (10, 50), cv2.FONT_HERSHEY_PLAIN, 2, (0, 255, 255), 2)

                # Show Window
                cv2.imshow("Miro AI Hardware", img)
                
                # Press 'q' to stop manually
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    handle_command("stop")
        else:
            # --- RELEASE CAMERA ---
            if cap is not None:
                cap.release()
                cap = None
                cv2.destroyAllWindows()
            time.sleep(0.5)

# --- MAIN EXECUTION ---
def main():
    print("--- 🚀 MIRO SYSTEM INITIALIZING ---")
    
    # 1. Start Camera Thread
    cam_thread = threading.Thread(target=camera_loop, daemon=True)
    cam_thread.start()

    # 2. Start Server
    if AGENT_AVAILABLE and app:
        print("🔗 Linking Agent to Hardware...")
        set_system_state_callback(handle_command)
        
        # Mount Frontend
        if os.path.exists("frontend"):
            print("🌍 Hosting Frontend at http://localhost:8000")
            app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
        
        # Run Server
        uvicorn.run(app, host="0.0.0.0", port=8000, log_level="error")
    else:
        print("❌ Critical Error: Could not start Agent.")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        STATE.stop_event.set()
        sys.exit(0)