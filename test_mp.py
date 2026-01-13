import cv2
import sys
# Make sure we can see the virtual_mouse folder
sys.path.append(".")

try:
    from virtual_mouse.HandTrackingModule import HandDetector
    print("✅ HandDetector imported successfully!")
    
    detector = HandDetector()
    print("✅ HandDetector initialized successfully!")
    
    print("Test passed. You can now run 'python main.py'")
    
except Exception as e:
    print(f"❌ Test Failed: {e}")