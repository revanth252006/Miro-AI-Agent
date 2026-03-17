# -*- coding: utf-8 -*-
"""
Miro Screen Reader — F9: Background thread with cached OCR.
- Background thread captures screen every 10 seconds (optional)
- Explicit commands get immediate fresh capture
- Auto-stops background thread after 5 minutes of no queries
- Uses PIL for screenshots and pytesseract for OCR
"""

import asyncio
import threading
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

# --- State ---
_active = False           # True when explicitly triggered or background running
_background_running = False
_last_screen_text = ""
_last_capture_time = 0
_last_query_time = 0
_INACTIVITY_TIMEOUT = 300  # Auto-stop background after 5 minutes of no queries
_CAPTURE_INTERVAL = 10     # Capture every 10 seconds in background mode
_lock = threading.Lock()
_bg_thread = None


def is_active() -> bool:
    """Check if screen reader is currently active."""
    global _active, _background_running
    if _background_running and (time.time() - _last_query_time > _INACTIVITY_TIMEOUT):
        _background_running = False
        _active = False
    return _active or _background_running


def _do_capture() -> str:
    """Synchronous screen capture + OCR. Thread-safe."""
    global _last_screen_text, _last_capture_time
    if not PIL_AVAILABLE or not OCR_AVAILABLE:
        return ""
    try:
        screenshot = ImageGrab.grab()
        screenshot = screenshot.resize((screenshot.width // 2, screenshot.height // 2))
        text = pytesseract.image_to_string(screenshot).strip()
        with _lock:
            _last_screen_text = text
            _last_capture_time = time.time()
        return text
    except Exception as e:
        print(f"🖥️ Screen capture error: {e}")
        return ""


def _background_loop():
    """Background thread: captures screen every CAPTURE_INTERVAL seconds."""
    global _background_running
    print("🖥️ Screen reader background thread started")
    while _background_running:
        _do_capture()
        # Sleep in small chunks so we can stop quickly
        for _ in range(int(_CAPTURE_INTERVAL * 2)):
            if not _background_running:
                break
            time.sleep(0.5)
    print("🖥️ Screen reader background thread stopped")


def start_background_reader():
    """Start the background screen reader thread (F9)."""
    global _background_running, _active, _last_query_time, _bg_thread
    if not PIL_AVAILABLE or not OCR_AVAILABLE:
        print("⚠️ Screen reader unavailable: missing PIL or pytesseract")
        return False
    if _background_running:
        return True  # Already running
    
    _background_running = True
    _active = True
    _last_query_time = time.time()
    _bg_thread = threading.Thread(target=_background_loop, daemon=True, name="ScreenReader")
    _bg_thread.start()
    return True


def stop_background_reader():
    """Stop the background screen reader thread."""
    global _background_running, _active
    _background_running = False
    _active = False


async def capture_screen() -> str:
    """Captures screen and runs OCR. Returns extracted text."""
    global _last_query_time, _active
    
    if not PIL_AVAILABLE or not OCR_AVAILABLE:
        return "Screen reader unavailable. Install: pip install Pillow pytesseract"
    
    _active = True
    _last_query_time = time.time()
    
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, _do_capture)
    return result


def get_cached_screen(max_age_seconds=15) -> str:
    """Returns cached screen text if captured within max_age_seconds."""
    global _last_query_time
    if not is_active():
        return ""
    _last_query_time = time.time()  # Reset inactivity timer
    with _lock:
        if time.time() - _last_capture_time < max_age_seconds and _last_screen_text:
            return _last_screen_text
    return ""


def stop_screen_reader():
    """Explicitly stop the screen reader (both explicit and background)."""
    stop_background_reader()


async def describe_screen() -> str:
    """Captures screen and returns a readout for the AI to analyze.
    Uses cached text if recent enough (F9), otherwise fresh capture."""
    global _last_query_time
    _last_query_time = time.time()
    
    # Try cached text first (from background thread)
    cached = get_cached_screen(max_age_seconds=15)
    if cached:
        text = cached
    else:
        text = await capture_screen()
    
    if not text:
        return "I couldn't read anything from the screen."
    
    # Truncate to avoid overwhelming the LLM
    if len(text) > 3000:
        text = text[:3000] + "\n... (truncated)"
    
    return f"[SCREEN CONTENT]:\n{text}\n[END SCREEN]"
