# -*- coding: utf-8 -*-
"""
Miro Screen Reader — Background screenshot + OCR for "what am I looking at?" queries.
Uses PIL for screenshots and pytesseract for OCR.
"""

import asyncio
import time

try:
    from PIL import ImageGrab
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

try:
    import pytesseract
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False

# Latest screen capture data
_last_screen_text = ""
_last_capture_time = 0


async def capture_screen() -> str:
    """Captures screen and runs OCR. Returns extracted text."""
    global _last_screen_text, _last_capture_time
    
    if not PIL_AVAILABLE or not OCR_AVAILABLE:
        return "Screen reader unavailable. Install: pip install Pillow pytesseract"
    
    loop = asyncio.get_running_loop()
    
    def _capture():
        global _last_screen_text, _last_capture_time
        screenshot = ImageGrab.grab()
        # Resize for faster OCR
        screenshot = screenshot.resize((screenshot.width // 2, screenshot.height // 2))
        text = pytesseract.image_to_string(screenshot)
        _last_screen_text = text.strip()
        _last_capture_time = time.time()
        return _last_screen_text
    
    return await loop.run_in_executor(None, _capture)


def get_cached_screen(max_age_seconds=10) -> str:
    """Returns cached screen text if captured within max_age_seconds."""
    if time.time() - _last_capture_time < max_age_seconds and _last_screen_text:
        return _last_screen_text
    return ""


async def describe_screen() -> str:
    """Captures screen and returns a readout for the AI to analyze."""
    text = await capture_screen()
    if not text:
        return "I couldn't read anything from the screen."
    
    # Truncate to avoid overwhelming the LLM
    if len(text) > 3000:
        text = text[:3000] + "\n... (truncated)"
    
    return f"[SCREEN CONTENT]:\n{text}\n[END SCREEN]"
