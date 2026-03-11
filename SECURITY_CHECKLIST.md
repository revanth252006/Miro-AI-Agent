# 🛡️ MIRO AI Agent — Security Checklist

Every protection applied and how to verify it is working.

---

## 1. Lock to Localhost

**What:** Server only listens on `127.0.0.1`, not `0.0.0.0`.

**Files:** `main.py`, `agent/assistant.py`

**Verify:**
```bash
# Start the server, then from another PC on the same network:
curl http://<YOUR_IP>:8000
# Should FAIL / refuse connection
```

---

## 2. WebSocket Token Authentication

**What:** Every WebSocket connection must include `?token=MIRO_SECRET_TOKEN`. Rejected with code `1008` otherwise.

**Files:** `agent/assistant.py`, `agent/security.py`, `frontend/index.html`

**Verify:**
```javascript
// In browser console:
new WebSocket('ws://localhost:8000/ws')
// Should close with code 1008

new WebSocket('ws://localhost:8000/ws?token=YOUR_TOKEN')
// Should connect successfully
```

---

## 3. Whitelist System Commands

**What:** Only pre-approved apps can be launched: `notepad`, `calc`, `chrome`, `code`, `explorer`, `cmd`, `terminal`, `settings`, etc. Uses `subprocess.Popen()` instead of `os.system()`.

**Files:** `tools.py`

**Verify:**
```
User: "open notepad"     → ✅ Opens notepad
User: "open malware.exe" → ⚠️ Blocked message
User: "open rm"          → ⚠️ Blocked message
```

---

## 4. Sanitize All User Inputs

**What:** Blocks `;`, `&&`, `|`, `$()`, backticks, `../` in all messages. Returns "Invalid input" immediately.

**Files:** `agent/security.py`, `agent/assistant.py`

**Verify:**
```
Send: "hello; rm -rf /"       → ⚠️ Invalid input
Send: "$(whoami)"              → ⚠️ Invalid input
Send: "../../../../etc/passwd" → ⚠️ Invalid input
Send: "what is python"         → ✅ Normal response
```

---

## 5. Rate Limiting

**What:** Max 30 messages per 60-second window per connection. In-memory counter, no extra libraries.

**Files:** `agent/security.py`, `agent/assistant.py`

**Verify:**
```javascript
// In browser console, send 31 rapid messages:
for (let i = 0; i < 31; i++) ws.send("test " + i);
// 31st message should return: "Rate limit exceeded"
```

---

## 6. Startup Credential Check

**What:** On startup, server checks `.env` for `MIRO_SECRET_TOKEN`, `GOOGLE_API_KEY`, `GMAIL_APP_PASSWORD`. Prints warning (never the value) if missing.

**Files:** `agent/security.py`, `agent/assistant.py`

**Verify:**
```bash
# Remove MIRO_SECRET_TOKEN from .env, start server:
python main.py
# Terminal should show:
# ⚠️ SECURITY WARNING — Missing required credentials:
#    ❌ MIRO_SECRET_TOKEN is not set in .env
```

---

## 7. Security Logging

**What:** All connection attempts (accepted/rejected), command types, rate limit events, and blocked inputs are logged to `miro_security.log` with timestamps. Message content is never logged.

**Files:** `agent/security.py`, `agent/assistant.py`

**Verify:**
```bash
# After connecting and sending some messages:
cat miro_security.log
# Should show entries like:
# 2026-03-11 09:30:00 | INFO | CONNECTION | remote=... | result=ACCEPTED
# 2026-03-11 09:30:05 | WARNING | BLOCKED_INPUT | remote=...
```

---

## 8. Encrypt brain.json

**What:** Memory file is encrypted using `cryptography.fernet.Fernet` with `MIRO_SECRET_TOKEN` as key (SHA-256 + base64 derivation). Decrypted on read, encrypted on write.

**Files:** `agent/memory.py`, `agent/security.py`

**Verify:**
```bash
# After starting the server and having a conversation:
cat agent/brain.json
# Should show encrypted binary data, NOT readable JSON

# Legacy migration: If brain.json was plain JSON before,
# it will be automatically re-saved as encrypted.
```

---

## 9. Screen Reader Protection

**What:** Screen reader only activates on explicit voice/text command (`"read my screen"`, `"what's on my screen"`). Never runs passively. Auto-stops after 60 seconds of inactivity.

**Files:** `agent/screen_reader.py`

**Verify:**
1. Start server — screen reader should NOT be active
2. Say "read my screen" — should capture and analyze
3. Wait 60 seconds — `is_active()` should return `False`

---

## 10. Finance Data Protection

**What:** SQLite finance database is encrypted at rest using Fernet. Decrypted to a temp file only while the agent is running. Re-encrypted on shutdown. Legacy unencrypted DB is migrated automatically.

**Files:** `agent/finance_tracker.py`, `agent/security.py`

**Verify:**
```bash
# After logging an expense and stopping the server:
file agent/miro_finance.db.enc
# Should exist as encrypted binary

ls agent/miro_finance.db
# Should NOT exist (migrated to .enc)
```

---

## Required pip Package

```bash
pip install cryptography
```

---

## Files Modified

| File | Changes |
|------|---------|
| `agent/security.py` | **NEW** — Central security module |
| `agent/assistant.py` | Token auth, rate limiting, input sanitization, CORS, localhost, security logging |
| `main.py` | Localhost lock (`127.0.0.1`) |
| `tools.py` | Command whitelist, `subprocess.Popen()` replaces `os.system()` |
| `agent/memory.py` | Fernet encryption for `brain.json` |
| `agent/screen_reader.py` | Explicit activation only, 60s auto-stop |
| `agent/finance_tracker.py` | Encrypted SQLite at rest |
| `frontend/index.html` | Token auth via `localStorage` |
| `.env.template` | **NEW** — Complete env template |
| `.gitignore` | Updated with all sensitive files |
| `SECURITY_CHECKLIST.md` | **NEW** — This file |
