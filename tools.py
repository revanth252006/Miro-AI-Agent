import os
import smtplib
import urllib.parse
import asyncio
import platform
import subprocess
import aiohttp
import logging
import webbrowser
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

# --- TOOLS ---

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

# --- EMAIL LOGIC (SMTP) ---
async def send_email(
    to_email: str,
    subject: str,
    message: str,
    cc_email: Optional[str] = None
) -> str:
    """
    Send an ACTUAL email through Gmail using SMTP.
    """
    try:
        # Gmail SMTP configuration
        smtp_server = "smtp.gmail.com"
        smtp_port = 587
        
        # Get credentials from environment variables
        gmail_user = os.getenv("GMAIL_USER")
        gmail_password = os.getenv("GMAIL_APP_PASSWORD")  # Use App Password!
        
        if not gmail_user or not gmail_password:
            logging.error("Gmail credentials not found in environment variables")
            return "Email failed: GMAIL_USER or GMAIL_APP_PASSWORD not set in .env file."
        
        # Create message
        msg = MIMEMultipart()
        msg['From'] = gmail_user
        msg['To'] = to_email
        msg['Subject'] = subject
        
        # Add CC if provided
        recipients = [to_email]
        if cc_email:
            msg['Cc'] = cc_email
            recipients.append(cc_email)
        
        # Attach message body
        msg.attach(MIMEText(message, 'plain'))
        
        # Connect to Gmail SMTP server
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()  # Enable TLS encryption
        server.login(gmail_user, gmail_password)
        
        # Send email
        text = msg.as_string()
        server.sendmail(gmail_user, recipients, text)
        server.quit()
        
        logging.info(f"Email sent successfully to {to_email}")
        return f"✅ Email sent successfully to {to_email}"
        
    except smtplib.SMTPAuthenticationError:
        logging.error("Gmail authentication failed")
        return "Email failed: Authentication error. Check your App Password."
    except Exception as e:
        logging.error(f"Error sending email: {e}")
        return f"Email failed: {str(e)}"

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
    "search_product": search_product
}