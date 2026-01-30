import os
import ssl
import smtplib
import urllib.parse
import asyncio
import platform
import subprocess
import aiohttp
import logging
import webbrowser
import pyautogui  # New: For System Control
import time       # New: For delays in automation
from datetime import datetime
from typing import Optional, Union, List, Dict
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from duckduckgo_search import DDGS

logger = logging.getLogger("Tools")

# Global In-Memory state
class GlobalStore:
    cart: List[Dict] = []
    
STORE = GlobalStore()

# --- 1. NEW SYSTEM AUTOMATION TOOLS ---

async def set_volume(level: str) -> str:
    """
    Controls system volume (up, down, mute).
    """
    level = level.lower()
    
    def _perform_volume():
        if "up" in level or "increase" in level:
            for _ in range(5): 
                pyautogui.press("volumeup")
            return " Volume increased."
        elif "down" in level or "decrease" in level:
            for _ in range(5): 
                pyautogui.press("volumedown")
            return " Volume decreased."
        elif "mute" in level or "silent" in level:
            pyautogui.press("volumemute")
            return " System muted."
        return "Volume unchanged."

    # Run in executor to prevent blocking the async loop
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _perform_volume)

async def take_screenshot() -> str:
    """
    Takes a screenshot and saves it to the current folder.
    """
    def _perform_screenshot():
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"screenshot_{timestamp}.png"
        pyautogui.screenshot(filename)
        return filename

    loop = asyncio.get_event_loop()
    filename = await loop.run_in_executor(None, _perform_screenshot)
    return f" Screenshot saved as {filename} "

async def minimize_windows() -> str:
    """
    Minimizes all windows to show the desktop.
    """
    def _perform_minimize():
        pyautogui.hotkey('win', 'd')
        return "Desktop visible."

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _perform_minimize)

async def open_application(app_name: str) -> str:
    """
    Opens common applications or searches for them using the Start menu.
    """
    app_name = app_name.lower().strip()
    
    # 1. Direct Command Map (Faster & More Reliable)
    app_map = {
        "notepad": "notepad",
        "calculator": "calc",
        "chrome": "start chrome",
        "vscode": "code",
        "code": "code",
        "settings": "start ms-settings:",
        "cmd": "start cmd",
        "terminal": "start cmd",
        "explorer": "explorer"
    }

    def _perform_open():
        # Try direct command first
        cmd = app_map.get(app_name)
        if cmd:
            os.system(cmd)
            return f"🚀 Opening {app_name}..."
        
        # 2. Fallback: "Iron Man" Style Search (Win Key + Type)
        pyautogui.press("win")
        time.sleep(0.5)
        pyautogui.write(app_name)
        time.sleep(0.5)
        pyautogui.press("enter")
        return f"🚀 Searching and launching {app_name}..."

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _perform_open)


# --- 2. EXISTING TOOLS (Preserved) ---

async def get_system_time() -> str:
    """Get the current real-time date and time."""
    now = datetime.now()
    return f"The current time is {now.strftime('%I:%M %p')} and the date is {now.strftime('%A, %B %d, %Y')}."

async def get_weather(city: str) -> str:
    """Get current weather for a city."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://wttr.in/{city}?format=3", timeout=10) as resp:
                if resp.status == 200:
                    return (await resp.text()).strip()
                return f"Weather service unavailable for {city}."
    except Exception as e:
        return f"Error: {str(e)}"

async def search_web(query: str) -> str:
    """
    Search the web using DuckDuckGo (No API Key required).
    """
    try:
        loop = asyncio.get_event_loop()
        
        def _perform_search():
            return list(DDGS().text(query, max_results=5))

        results = await loop.run_in_executor(None, _perform_search)
        
        if not results:
            return f"No results found for search: {query}"
        
        formatted_list = []
        for r in results:
            formatted_list.append(f"- **{r.get('title')}**: {r.get('body')} (Link: {r.get('href')})")
            
        formatted = "\n".join(formatted_list)
        return f"Web Search Results for '{query}':\n{formatted}"

    except Exception as e:
        return f"Search failed: {str(e)}"

async def send_email(
    to_email: str,
    subject: str,
    message: str,
    cc_email: Optional[str] = None
) -> str:
    """
    Send an ACTUAL email through Gmail using SMTP_SSL (Port 465).
    """
    print(f"\n📨 STARTING EMAIL SEND PROCESS...")
    print(f"   To: {to_email}")
    print(f"   Subject: {subject}")

    try:
        # 1. Check Credentials
        gmail_user = os.getenv("GMAIL_USER")
        gmail_password = os.getenv("GMAIL_APP_PASSWORD")
        
        if not gmail_user or not gmail_password:
            error_msg = "❌ CRITICAL ERROR: GMAIL_USER or GMAIL_APP_PASSWORD is missing in .env file."
            print(error_msg)
            return error_msg
            
        print(f"   🔑 Credentials found for user: {gmail_user}")

        # 2. Create Message
        msg = MIMEMultipart()
        msg['From'] = gmail_user
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(message, 'plain'))
        
        if cc_email:
            msg['Cc'] = cc_email
            
        # 3. Connect via SSL (Port 465 - More Reliable)
        print("   🔌 Connecting to Gmail Server (smtp.gmail.com:465)...")
        context = ssl.create_default_context()
        
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
            print("   🔓 Logging in...")
            server.login(gmail_user, gmail_password)
            print("   🚀 Sending message...")
            server.send_message(msg)
            
        success_msg = f"✅ SUCCESS: Email sent to {to_email}"
        print(success_msg)
        return success_msg

    except smtplib.SMTPAuthenticationError:
        err = "❌ AUTHENTICATION ERROR: Your App Password or Email is incorrect."
        print(err)
        return err
    except Exception as e:
        err = f"❌ SENDING FAILED: {str(e)}"
        print(err)
        return err

async def open_website(site_name: str, search_query: Union[str, None] = None) -> str:
    """Universal browser opener."""
    site_name = site_name.lower().strip()
    url = ""
    
    if "youtube" in site_name:
        url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(search_query)}" if search_query else "https://www.youtube.com"
    elif "google" in site_name:
        url = f"https://www.google.com/search?q={urllib.parse.quote(search_query)}" if search_query else "https://www.google.com"
    elif "amazon" in site_name:
        url = f"https://www.amazon.in/s?k={urllib.parse.quote(search_query)}" if search_query else "https://www.amazon.in"
    else:
        clean = site_name.replace(' ', '').replace('http://', '').replace('https://', '')
        url = f"https://www.{clean}.com" if "." not in clean else f"https://{clean}"

    def _force_open():
        sys_os = platform.system().lower()
        try:
            if sys_os == "windows":
                subprocess.Popen(['cmd', '/c', 'start', '', url], shell=True, creationflags=0x00000008)
            elif sys_os == "darwin": subprocess.Popen(['open', url])
            else: subprocess.Popen(['xdg-open', url])
            return True
        except: return webbrowser.open(url)

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _force_open)
    return f"Opened {url} for you."

async def manage_shopping(action: str, item_name: str = "", price: float = 0.0) -> str:
    if action == "search":
        return f"Found {item_name} for ₹{price}. Add to cart?"
    elif action == "add":
        STORE.cart.append({"name": item_name, "price": price})
        return f"Added {item_name}. Total: {len(STORE.cart)} items."
    elif action == "view":
        if not STORE.cart: return "Cart is empty."
        items = "\n".join([f"- {i['name']}: ₹{i['price']}" for i in STORE.cart])
        return f"Cart:\n{items}\nTotal: ₹{sum(i['price'] for i in STORE.cart)}"
    return "Action failed."

async def book_ride(pickup: str, destination: str) -> str:
    return f"🚖 Ride confirmed from {pickup} to {destination}. Driver arriving in 3 mins."

async def search_product(product_name: str) -> str:
    url = f"https://www.amazon.in/s?k={urllib.parse.quote(product_name)}"
    webbrowser.open(url)
    return f"Opened Amazon search for '{product_name}'."

# --- TOOL REGISTRY ---
AVAILABLE_TOOLS = {
    "get_system_time": get_system_time,
    "get_weather": get_weather,
    "search_web": search_web,
    "send_email": send_email,
    "open_website": open_website,
    "manage_shopping": manage_shopping,
    "book_ride": book_ride,
    "search_product": search_product,
    # New System Tools
    "set_volume": set_volume,
    "take_screenshot": take_screenshot,
    "minimize_windows": minimize_windows,
    "open_application": open_application
}