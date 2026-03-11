# -*- coding: utf-8 -*-
"""
Miro Security Module — Central security utilities.
Provides input sanitization, rate limiting, security logging, and credential checking.
"""

import os
import re
import time
import hashlib
import base64
import logging
import datetime
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv(override=True)

# ─────────────────────────────────────────────────────────────────
# 1. CREDENTIAL CHECK (run on import)
# ─────────────────────────────────────────────────────────────────
REQUIRED_CREDENTIALS = [
    "MIRO_SECRET_TOKEN",
    "GOOGLE_API_KEY",
    "GMAIL_APP_PASSWORD",
]

def check_credentials():
    """Check that all required .env values exist. Print warnings for missing ones.
    NEVER logs or prints actual credential values."""
    missing = []
    for key in REQUIRED_CREDENTIALS:
        val = os.getenv(key)
        if not val or not val.strip():
            missing.append(key)
    if missing:
        print("=" * 60)
        print("⚠️  SECURITY WARNING — Missing required credentials:")
        for key in missing:
            print(f"   ❌ {key} is not set in .env")
        print("   Fix: Add these values to your .env file.")
        print("=" * 60)
    else:
        print("✅ All required credentials present in .env")
    return len(missing) == 0


# Run check on module import
_credentials_ok = check_credentials()


# ─────────────────────────────────────────────────────────────────
# 2. FERNET KEY DERIVATION (shared by memory + finance encryption)
# ─────────────────────────────────────────────────────────────────
def derive_fernet_key(secret: str = None) -> bytes:
    """Derives a Fernet-compatible key from MIRO_SECRET_TOKEN using SHA-256.
    Returns a url-safe base64-encoded 32-byte key."""
    if secret is None:
        secret = os.getenv("MIRO_SECRET_TOKEN", "")
    if not secret:
        raise ValueError("MIRO_SECRET_TOKEN is not set — cannot derive encryption key")
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


# ─────────────────────────────────────────────────────────────────
# 3. INPUT SANITIZER
# ─────────────────────────────────────────────────────────────────
# Dangerous shell metacharacters and path traversal sequences
_DANGEROUS_PATTERNS = [
    r';',           # command chaining
    r'&&',          # AND chaining
    r'\|\|',        # OR chaining
    r'\|',          # pipe
    r'\$\(',        # command substitution $(...)
    r'\$\{',        # variable expansion ${...}
    r'`',           # backtick command substitution
    r'\.\.\/',      # path traversal ../
    r'\.\.\/',      # path traversal ..\  (Windows)
]
_DANGEROUS_RE = re.compile('|'.join(_DANGEROUS_PATTERNS))


class InputSanitizer:
    """Validates and sanitizes all user input before processing."""

    @staticmethod
    def is_dangerous(text: str) -> bool:
        """Returns True if text contains shell injection or path traversal characters."""
        if not text:
            return False
        # Check compiled regex
        if _DANGEROUS_RE.search(text):
            return True
        # Also check for backslash-based traversal on Windows
        if '..\\'  in text:
            return True
        return False

    @staticmethod
    def sanitize(text: str) -> tuple[bool, str]:
        """Validate input. Returns (is_safe, cleaned_text_or_error_message).
        
        If safe: returns (True, original_text)
        If dangerous: returns (False, "Invalid input")
        """
        if not text:
            return True, text
        if InputSanitizer.is_dangerous(text):
            return False, "⚠️ Invalid input — contains blocked characters."
        return True, text


# ─────────────────────────────────────────────────────────────────
# 4. RATE LIMITER (in-memory, no extra libraries)
# ─────────────────────────────────────────────────────────────────
class RateLimiter:
    """Per-connection rate limiter. Max `max_requests` per `window_seconds`."""

    def __init__(self, max_requests: int = 30, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        # Key: connection id → list of timestamps
        self._requests: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, connection_id: str) -> bool:
        """Returns True if the connection is within rate limits."""
        now = time.time()
        cutoff = now - self.window_seconds
        # Prune old entries
        self._requests[connection_id] = [
            t for t in self._requests[connection_id] if t > cutoff
        ]
        if len(self._requests[connection_id]) >= self.max_requests:
            return False
        self._requests[connection_id].append(now)
        return True

    def cleanup(self, connection_id: str):
        """Remove tracking data for a disconnected connection."""
        self._requests.pop(connection_id, None)


# ─────────────────────────────────────────────────────────────────
# 5. SECURITY LOGGER
# ─────────────────────────────────────────────────────────────────
_LOG_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "miro_security.log")

# Configure dedicated security logger (separate from uvicorn)
_sec_logger = logging.getLogger("miro.security")
_sec_logger.setLevel(logging.INFO)
_sec_logger.propagate = False

# File handler — append mode
_fh = logging.FileHandler(_LOG_FILE, mode="a", encoding="utf-8")
_fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
_sec_logger.addHandler(_fh)


class SecurityLogger:
    """Logs security-relevant events. Never logs message content for privacy."""

    @staticmethod
    def log_connection(remote: str, result: str):
        """Log a WebSocket connection attempt.
        result should be 'ACCEPTED' or 'REJECTED:<reason>'
        """
        _sec_logger.info(f"CONNECTION | remote={remote} | result={result}")

    @staticmethod
    def log_disconnect(remote: str):
        _sec_logger.info(f"DISCONNECT | remote={remote}")

    @staticmethod
    def log_command(command_type: str, remote: str = "system"):
        """Log what type of command was executed (never the content)."""
        _sec_logger.info(f"COMMAND | type={command_type} | remote={remote}")

    @staticmethod
    def log_rate_limit(remote: str):
        _sec_logger.warning(f"RATE_LIMIT | remote={remote} | exceeded=30/min")

    @staticmethod
    def log_blocked_input(remote: str):
        _sec_logger.warning(f"BLOCKED_INPUT | remote={remote} | reason=dangerous_characters")

    @staticmethod
    def log_event(event: str):
        """Generic security event log."""
        _sec_logger.info(f"EVENT | {event}")


# ─────────────────────────────────────────────────────────────────
# 6. COMMAND WHITELIST
# ─────────────────────────────────────────────────────────────────
COMMAND_WHITELIST = {
    "notepad", "calc", "calculator", "chrome", "code", "vscode",
    "explorer", "cmd", "terminal", "settings", "powershell",
    "edge", "firefox", "brave", "spotify", "discord", "slack",
    "word", "excel", "powerpoint", "outlook",
}


def is_command_allowed(app_name: str) -> bool:
    """Check if an application name is in the whitelist."""
    return app_name.lower().strip() in COMMAND_WHITELIST


# ─────────────────────────────────────────────────────────────────
# 7. TOKEN VERIFICATION
# ─────────────────────────────────────────────────────────────────
def verify_token(token: str) -> bool:
    """Verify a WebSocket connection token against MIRO_SECRET_TOKEN."""
    expected = os.getenv("MIRO_SECRET_TOKEN", "")
    if not expected:
        # If no token is configured, warn but allow (so user can set it up)
        print("⚠️  MIRO_SECRET_TOKEN not set — WebSocket auth disabled (INSECURE)")
        return True
    return token == expected
