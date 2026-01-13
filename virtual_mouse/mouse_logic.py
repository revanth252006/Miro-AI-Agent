import cv2
import numpy as np
import time
import autopy
import pyautogui

from . import HandTrackingModule as htm

class VirtualMouse:
    def __init__(self):
        # --- TUNING SETTINGS ---
        self.wCam, self.hCam = 640, 480
        self.frameR = 100     # Frame Reduction (Padding)
        self.smoothening = 5  # Lower = Snappier, Higher = Smoother (but laggier)
        self.scrollSpeed = 15 # Lower this if scrolling is still too fast
        # -----------------------
        
        self.pTime = 0
        self.plocX, self.plocY = 0, 0
        self.clocX, self.clocY = 0, 0
        
        self.detector = htm.handDetector(maxHands=1)
        
        try:
            self.wScr, self.hScr = autopy.screen.size()
        except:
            self.wScr, self.hScr = pyautogui.size()

    def process_frame(self, img):
        # 1. Find Hand Landmarks
        img = self.detector.findHands(img)
        lmList, bbox = self.detector.findPosition(img)

        # 2. Check if hand exists
        if len(lmList) != 0:
            x1, y1 = lmList[8][1:]   # Index finger tip
            x2, y2 = lmList[12][1:]  # Middle finger tip

            # Check which fingers are up
            fingers = self.detector.fingersUp()
            
            # Draw Control Region (Visual Guide)
            cv2.rectangle(img, (self.frameR, self.frameR), 
                         (self.wCam - self.frameR, self.hCam - self.frameR),
                         (255, 0, 255), 2)

            # --- MODE 1: MOVING MOUSE (Only Index Finger Up) ---
            if fingers[1] == 1 and fingers[2] == 0:
                # Convert Coordinates to Screen Size
                x3 = np.interp(x1, (self.frameR, self.wCam - self.frameR), (0, self.wScr))
                y3 = np.interp(y1, (self.frameR, self.hCam - self.frameR), (0, self.hScr))

                # Smoothen the values to remove jitter
                self.clocX = self.plocX + (x3 - self.plocX) / self.smoothening
                self.clocY = self.plocY + (y3 - self.plocY) / self.smoothening

                # Move Mouse
                try:
                    # autopy is smoother than pyautogui
                    autopy.mouse.move(self.wScr - self.clocX, self.clocY)
                except:
                    pass

                # Visual Feedback
                cv2.circle(img, (x1, y1), 15, (255, 0, 255), cv2.FILLED)
                self.plocX, self.plocY = self.clocX, self.clocY

            # --- MODE 2: CLICKING (Index + Middle Up AND Close Together) ---
            if fingers[1] == 1 and fingers[2] == 1:
                # Find distance between fingers
                length, img, lineInfo = self.detector.findDistance(8, 12, img)
                
                # If distance is short -> CLICK
                if length < 40:
                    cv2.circle(img, (lineInfo[4], lineInfo[5]), 15, (0, 255, 0), cv2.FILLED)
                    try:
                        autopy.mouse.click()
                    except:
                        pyautogui.click()
                    
                    # Small delay to prevent double-clicking too easily
                    # time.sleep(0.1) 

            # --- MODE 3: SCROLLING (Index + Middle Up AND Far Apart) ---
            if fingers[1] == 1 and fingers[2] == 1:
                # Calculate distance again to ensure we aren't clicking
                length, _, _ = self.detector.findDistance(8, 12, img, draw=False)
                
                if length > 40: # Only scroll if fingers are apart
                    
                    # LOGIC:
                    # Top 30% of screen = Scroll UP
                    # Bottom 30% of screen = Scroll DOWN
                    # Middle 40% = DO NOTHING (Neutral Zone)
                    
                    header = self.hCam * 0.3  # Top boundary
                    footer = self.hCam * 0.7  # Bottom boundary
                    
                    # Visual lines for scroll zones
                    cv2.line(img, (0, int(header)), (self.wCam, int(header)), (0, 255, 255), 2)
                    cv2.line(img, (0, int(footer)), (self.wCam, int(footer)), (0, 255, 255), 2)

                    if y1 < header:
                        # Hand is in Top Zone -> Scroll UP
                        pyautogui.scroll(self.scrollSpeed)
                        cv2.putText(img, "SCROLL UP", (20, 50), cv2.FONT_HERSHEY_PLAIN, 2, (0, 255, 255), 2)
                        
                    elif y1 > footer:
                        # Hand is in Bottom Zone -> Scroll DOWN
                        pyautogui.scroll(-self.scrollSpeed)
                        cv2.putText(img, "SCROLL DOWN", (20, 50), cv2.FONT_HERSHEY_PLAIN, 2, (0, 255, 255), 2)
                    else:
                        # Hand is in Middle -> Neutral
                        cv2.putText(img, "NEUTRAL", (20, 50), cv2.FONT_HERSHEY_PLAIN, 2, (200, 200, 200), 2)

        return img