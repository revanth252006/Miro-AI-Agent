import cv2
from cvzone.HandTrackingModule import HandDetector
from cvzone.ClassificationModule import Classifier
import numpy as np
import math
import os
import time
import pyautogui

# --- 1. CONFIGURATION ---
model_path = "sign_detection/Model/keras_model.h5"
labels_path = "sign_detection/Model/labels.txt"
offset = 20
imgSize = 300
typing_delay = 1.0  # Seconds to wait before typing same letter again

# --- 2. INIT SYSTEM ---
cap = cv2.VideoCapture(0)
detector = HandDetector(maxHands=1)

# Check paths (Robust check)
if not os.path.exists(model_path):
    # Fallback for different folder structures
    model_path = "Model/keras_model.h5"
    labels_path = "Model/labels.txt"

if not os.path.exists(model_path) or not os.path.exists(labels_path):
    print(f"❌ Error: Model files not found at {model_path}")
    print("Please make sure your folder structure is correct.")
    exit()

print("✅ Loading Model...")
classifier = Classifier(model_path, labels_path)

# FIX: Load ACTUAL labels from the file, don't guess A-Z
with open(labels_path, 'r') as f:
    labels = [line.strip() for line in f.readlines()]
print(f"Labels Loaded: {labels}")

# --- 3. MAIN LOOP ---
last_key_time = 0

print("✌️ Sign Detection Started. Click on a text box to type!")

while True:
    success, img = cap.read()
    if not success: break

    imgOutput = img.copy()
    hands, img = detector.findHands(img)

    if hands:
        hand = hands[0]
        x, y, w, h = hand['bbox']

        h_img, w_img = img.shape[:2]
        
        # Robust Cropping (Prevents crash at edge of screen)
        x1 = max(0, x - offset)
        y1 = max(0, y - offset)
        x2 = min(w_img, x + w + offset)
        y2 = min(h_img, y + h + offset)

        imgCrop = img[y1:y2, x1:x2]

        if imgCrop.size != 0:
            imgWhite = np.ones((imgSize, imgSize, 3), np.uint8) * 255
            aspectRatio = h / w

            if aspectRatio > 1:
                k = imgSize / h
                wCal = math.ceil(k * w)
                imgResize = cv2.resize(imgCrop, (wCal, imgSize))
                wGap = math.ceil((imgSize - wCal) / 2)
                imgWhite[:, wGap:wCal + wGap] = imgResize
            else:
                k = imgSize / w
                hCal = math.ceil(k * h)
                imgResize = cv2.resize(imgCrop, (imgSize, hCal))
                hGap = math.ceil((imgSize - hCal) / 2)
                imgWhite[hGap:hCal + hGap, :] = imgResize

            # --- PREDICTION ---
            prediction, index = classifier.getPrediction(imgWhite, draw=False)
            
            # Safe label access
            if index < len(labels):
                detected_char = labels[index]
                confidence = prediction[index]
            else:
                detected_char = "?"
                confidence = 0

            # --- VISUALS ---
            cv2.rectangle(imgOutput, (x - offset, y - offset - 50),
                          (x - offset + 90, y - offset - 50 + 50), (255, 0, 255), cv2.FILLED)
            cv2.putText(imgOutput, detected_char, (x, y - 26), cv2.FONT_HERSHEY_COMPLEX, 1.7, (255, 255, 255), 2)
            cv2.rectangle(imgOutput, (x - offset, y - offset),
                          (x + w + offset, y + h + offset), (255, 0, 255), 4)

            # --- TYPING LOGIC (Added) ---
            # Only type if confidence is high (> 80%)
            if confidence > 0.8:
                current_time = time.time()
                if current_time - last_key_time > typing_delay:
                    
                    key = detected_char.lower()
                    print(f"⌨️ Typing: {key}")

                    if key == "space":
                        pyautogui.press("space")
                    elif key == "delete" or key == "backspace":
                        pyautogui.press("backspace")
                    elif key == "enter":
                        pyautogui.press("enter")
                    else:
                        # Only type if it's a valid single letter
                        if len(key) == 1:
                            pyautogui.write(key)
                    
                    last_key_time = current_time

    cv2.imshow("Miro Sign Typer", imgOutput)
    
    # Press 'q' to quit
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()