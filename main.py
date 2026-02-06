import cv2
import sys
import time
import math
import numpy as np
import pyautogui
import os

# --- DEPENDENCIES CHECK ---
try:
    from cvzone.HandTrackingModule import HandDetector
    from cvzone.ClassificationModule import Classifier
except ImportError:
    print("❌ CRITICAL: Missing libraries. Run 'pip install cvzone mediapipe'") 
    sys.exit()

# ==========================================
# 🖱️ VIRTUAL MOUSE LOGIC
# ==========================================
class VirtualMouse:
    def __init__(self):
        pyautogui.FAILSAFE = False 
        self.wScr, self.hScr = pyautogui.size()
        self.frameR = 100 # Frame Reduction
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
        
        # Draw Boundary Box
        cv2.rectangle(img, (self.frameR, self.frameR), (w - self.frameR, h - self.frameR), (255, 0, 255), 2)

        # 1. Moving Mode (Index Finger Up)
        if fingers[1] == 1 and fingers[2] == 0:
            x1, y1 = lmList[8][0], lmList[8][1]
            
            # Convert Coordinates
            x3 = np.interp(x1, (self.frameR, w - self.frameR), (0, self.wScr))
            y3 = np.interp(y1, (self.frameR, h - self.frameR), (0, self.hScr))
            
            # Smoothen Values
            self.clocX = self.plocX + (x3 - self.plocX) / self.smoothening
            self.clocY = self.plocY + (y3 - self.plocY) / self.smoothening
            
            # Move Mouse
            try: pyautogui.moveTo(self.wScr - self.clocX, self.clocY)
            except: pass
            
            cv2.circle(img, (x1, y1), 15, (255, 0, 255), cv2.FILLED)
            self.plocX, self.plocY = self.clocX, self.clocY

        # 2. Clicking Mode (Index + Middle Fingers Up)
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
        self.classifier = None
        self.labels = []
        try:
            self.classifier = Classifier("sign_detection/Model/keras_model.h5", "sign_detection/Model/labels.txt")
            print("✅ Sign Model Loaded.")
        except:
            print("⚠️ Sign Model not found. (Check 'sign_detection/Model' folder)")

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
# 🚀 MAIN LOOP (Original Style)
# ==========================================
def main():
    print("--- 🚀 MIRO VISION STARTING ---")
    print("Controls:")
    print("Press 'm' -> Virtual Mouse Mode")
    print("Press 's' -> Sign Language Mode")
    print("Press 'q' -> Quit")

    cap = cv2.VideoCapture(0)
    cap.set(3, 640)
    cap.set(4, 480)

    detector = HandDetector(maxHands=1)
    mouse_engine = VirtualMouse()
    sign_engine = SignDetector()
    
    mode = "MOUSE" # Default Mode

    while True:
        success, img = cap.read()
        if not success: break

        # 1. Detect Hands
        hands, img = detector.findHands(img, flipType=False)

        # 2. Logic based on Mode
        if mode == "MOUSE":
            img = mouse_engine.process(img, hands, detector)
            cv2.putText(img, "MODE: MOUSE (Press 's' for Sign)", (10, 30), cv2.FONT_HERSHEY_PLAIN, 2, (0, 255, 0), 2)
        
        elif mode == "SIGN":
            img, label = sign_engine.process(img, hands)
            cv2.putText(img, f"MODE: SIGN ({label if label else ''})", (10, 30), cv2.FONT_HERSHEY_PLAIN, 2, (0, 255, 0), 2)

        # 3. Display
        cv2.imshow("Miro Vision", img)
        
        # 4. Keyboard Controls
        key = cv2.waitKey(1)
        if key == ord('q'): # Quit
            break
        elif key == ord('m'): # Switch to Mouse
            mode = "MOUSE"
        elif key == ord('s'): # Switch to Sign
            mode = "SIGN"

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()