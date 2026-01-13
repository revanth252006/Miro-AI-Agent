import cv2
import numpy as np
import math
import os
import time
import pyautogui  # <--- Added for typing
from cvzone.HandTrackingModule import HandDetector
from cvzone.ClassificationModule import Classifier

class SignDetector:
    def __init__(self, model_path="sign_detection/Model/keras_model.h5", labels_path="sign_detection/Model/labels.txt"):
        self.active = False
        
        # Check if files exist (Handle paths relative to main.py or direct run)
        if not os.path.exists(model_path):
            # Try local path if running directly inside folder
            model_path = "Model/keras_model.h5"
            labels_path = "Model/labels.txt"

        if not os.path.exists(model_path) or not os.path.exists(labels_path):
            print(f"⚠️ WARNING: Sign Model not found at {model_path}.")
            return

        self.classifier = Classifier(model_path, labels_path)
        self.detector = HandDetector(maxHands=1)
        
        self.offset = 20
        self.imgSize = 300
        
        # Load labels
        with open(labels_path, 'r') as f:
            self.labels = [line.strip() for line in f.readlines()]
        
        self.active = True
        self.last_key_time = 0  # Timer to prevent spamming keys
        print("✅ Sign Detection Model Loaded.")

    def predict(self, img):
        if not self.active:
            return None, img

        imgOutput = img.copy()
        hands, img = self.detector.findHands(img, draw=False)

        prediction_text = None
        confidence = 0

        if hands:
            hand = hands[0]
            x, y, w, h = hand['bbox']

            h_img, w_img = img.shape[:2]
            
            x1 = max(0, x - self.offset)
            y1 = max(0, y - self.offset)
            x2 = min(w_img, x + w + self.offset)
            y2 = min(h_img, y + h + self.offset)

            imgCrop = img[y1:y2, x1:x2]

            if imgCrop.size != 0:
                imgWhite = np.ones((self.imgSize, self.imgSize, 3), np.uint8) * 255
                aspectRatio = h / w

                try:
                    if aspectRatio > 1:
                        k = self.imgSize / h
                        wCal = math.ceil(k * w)
                        imgResize = cv2.resize(imgCrop, (wCal, self.imgSize))
                        wGap = math.ceil((self.imgSize - wCal) / 2)
                        imgWhite[:, wGap:wCal + wGap] = imgResize
                    else:
                        k = self.imgSize / w
                        hCal = math.ceil(k * h)
                        imgResize = cv2.resize(imgCrop, (self.imgSize, hCal))
                        hGap = math.ceil((self.imgSize - hCal) / 2)
                        imgWhite[hGap:hCal + hGap, :] = imgResize

                    # Get Prediction
                    prediction, index = self.classifier.getPrediction(imgWhite, draw=False)
                    prediction_text = self.labels[index]
                    confidence = prediction[index]
                    
                    # Draw UI
                    cv2.rectangle(imgOutput, (x - self.offset, y - self.offset - 50), 
                                (x - self.offset + 90, y - self.offset - 50 + 50), (255, 0, 255), cv2.FILLED)
                    cv2.putText(imgOutput, prediction_text, (x, y - 26), cv2.FONT_HERSHEY_COMPLEX, 1.7, (255, 255, 255), 2)
                    cv2.rectangle(imgOutput, (x - self.offset, y - self.offset), 
                                (x + w + self.offset, y + h + self.offset), (255, 0, 255), 4)
                    
                except Exception:
                    pass

        return prediction_text, confidence, imgOutput

# --- MAIN LOOP (Runs when 'Activate Sign' is called) ---
def run_detection():
    cap = cv2.VideoCapture(0)
    detector = SignDetector()
    
    if not detector.active:
        print("❌ Could not load model. Exiting.")
        return

    print("✌️ Sign Detection Running... (Press 'q' to quit)")
    
    last_typed_time = 0
    type_delay = 1.5  # Seconds to wait before typing same letter again

    while True:
        success, img = cap.read()
        if not success: break

        # 1. Flip Image (Mirror Effect)
        img = cv2.flip(img, 1)

        # 2. Get Prediction
        char_detected, conf, imgOutput = detector.predict(img)

        # 3. Typing Logic (High Confidence Only)
        if char_detected and conf > 0.85:
            current_time = time.time()
            if current_time - last_typed_time > type_delay:
                print(f"⌨️ Typing: {char_detected}")
                
                # Handle Special Keys if your model has them
                if char_detected.lower() == "space":
                    pyautogui.press("space")
                elif char_detected.lower() == "enter":
                    pyautogui.press("enter")
                elif char_detected.lower() == "backspace":
                    pyautogui.press("backspace")
                else:
                    # Type normal letters (A, B, C...)
                    pyautogui.write(char_detected.lower())
                
                last_typed_time = current_time

        # 4. Show Display
        cv2.imshow("Miro Sign Detection", imgOutput)
        
        # Quit on 'q'
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    run_detection()