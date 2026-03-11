# -*- coding: utf-8 -*-
"""
Miro Screen Reader — Explicit activation only.
- Only activates on explicit voice/text command (never passive)
- Auto-stops after 60 seconds of inactivity
- Uses PIL for screenshots and pytesseract for OCR
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

# --- SECURITY: Screen reader state ---
_active = False           # Only True when explicitly triggered
_last_screen_text = ""
_last_capture_time = 0
_INACTIVITY_TIMEOUT = 60  # Auto-stop after 60 seconds


def is_active() -> bool:
    """Check if screen reader is currently active and within timeout."""
    global _active
    if _active and (time.time() - _last_capture_time > _INACTIVITY_TIMEOUT):
        _active = False  # Auto-stop after 60s inactivity
    return _active


async def capture_screen() -> str:
    """Captures screen and runs OCR. Returns extracted text.
    SECURITY: Only runs when explicitly called — never passively."""
    global _last_screen_text, _last_capture_time, _active
    
    if not PIL_AVAILABLE or not OCR_AVAILABLE:
        return "Screen reader unavailable. Install: pip install Pillow pytesseract"
    
    # Activate on explicit call
    _active = True
    
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
    
    result = await loop.run_in_executor(None, _capture)
    return result


def get_cached_screen(max_age_seconds=10) -> str:
    """Returns cached screen text if captured within max_age_seconds.
    SECURITY: Returns empty if screen reader auto-stopped (>60s)."""
    if not is_active():
        return ""
    if time.time() - _last_capture_time < max_age_seconds and _last_screen_text:
        return _last_screen_text
    return ""


def stop_screen_reader():
    """Explicitly stop the screen reader."""
    global _active
    _active = False


async def describe_screen() -> str:
    """Captures screen and returns a readout for the AI to analyze.
    SECURITY: Only runs on explicit command — never background."""
    text = await capture_screen()
    if not text:
        return "I couldn't read anything from the screen."
    
    # Truncate to avoid overwhelming the LLM
    if len(text) > 3000:
        text = text[:3000] + "\n... (truncated)"
    
    return f"[SCREEN CONTENT]:\n{text}\n[END SCREEN]"
