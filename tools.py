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
import pyautogui
import time
import re
from datetime import datetime
from typing import Optional, Union, List, Dict
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from duckduckgo_search import DDGS
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

logger = logging.getLogger("Tools")

# Global In-Memory state
class GlobalStore:
    cart: List[Dict] = []
    
STORE = GlobalStore()

# ==========================================
# 1. SYSTEM TOOLS (PRESERVED)
# ==========================================
async def set_volume(level: str) -> str:
    level = level.lower()
    def _perform_volume():
        if "up" in level:
            for _ in range(5): pyautogui.press("volumeup")
            return "Volume Up."
        elif "down" in level:
            for _ in range(5): pyautogui.press("volumedown")
            return "Volume Down."
        elif "mute" in level:
            pyautogui.press("volumemute")
            return "Muted."
        return "Unchanged."
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _perform_volume)

async def take_screenshot() -> str:
    def _perform_screenshot():
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        fn = f"screenshot_{ts}.png"
        pyautogui.screenshot(fn)
        return fn
    loop = asyncio.get_event_loop()
    fn = await loop.run_in_executor(None, _perform_screenshot)
    return f"Saved: {fn}"

async def minimize_windows() -> str:
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, lambda: pyautogui.hotkey('win', 'd'))
    return "Desktop visible."

async def open_application(app_name: str) -> str:
    app_name = app_name.lower().strip()
    app_map = {"chrome": "start chrome", "notepad": "notepad", "calc": "calc", "code": "code"}
    def _perform_open():
        if app_map.get(app_name):
            os.system(app_map[app_name])
            return f"Opened {app_name}"
        pyautogui.press("win"); time.sleep(0.2); pyautogui.write(app_name); time.sleep(0.2); pyautogui.press("enter")
        return f"Launched {app_name}"
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _perform_open)

# ==========================================
# 2. WEB & INFO TOOLS (PRESERVED)
# ==========================================
async def get_system_time() -> str:
    return datetime.now().strftime("%I:%M %p, %A %B %d")

async def get_weather(city: str) -> str:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://wttr.in/{city}?format=3", timeout=5) as resp:
                return (await resp.text()).strip() if resp.status == 200 else "Weather unavailable."
    except: return "Weather Error."

async def search_web(query: str) -> str:
    try:
        loop = asyncio.get_event_loop()
        res = await loop.run_in_executor(None, lambda: list(DDGS().text(query, max_results=3)))
        return "\n".join([f"- {r['title']}: {r['href']}" for r in res]) if res else "No results."
    except: return "Search failed."

async def send_email(
    to_email: str,
    subject: str,
    message: str,
    cc_email: Optional[str] = None
) -> str:
    """
    Send an email through Gmail using STARTTLS (Port 587).
    """
    print(f"\n📨 Sending email to {to_email}...")
    
    # 1. Define the Blocking Function
    def _send_blocking():
        try:
            # Gmail SMTP configuration
            smtp_server = "smtp.gmail.com"
            smtp_port = 587
            
            # Get credentials & CLEAN them
            gmail_user = os.getenv("GMAIL_USER")
            # Remove spaces from the app password just in case
            gmail_password = os.getenv("GMAIL_APP_PASSWORD", "").replace(" ", "").strip()
            
            if not gmail_user or not gmail_password:
                print("❌ Error: GMAIL_USER or GMAIL_APP_PASSWORD missing.")
                return "Email failed: Credentials missing."
            
            # Create message
            msg = MIMEMultipart()
            msg['From'] = gmail_user
            msg['To'] = to_email
            msg['Subject'] = subject
            
            recipients = [to_email]
            if cc_email:
                msg['Cc'] = cc_email
                recipients.append(cc_email)
            
            msg.attach(MIMEText(message, 'plain'))
            
            # Connect using STARTTLS (Port 587)
            server = smtplib.SMTP(smtp_server, smtp_port)
            # server.set_debuglevel(1) # Uncomment if you want to see deep server logs
            server.starttls()  # Enable Security
            server.login(gmail_user, gmail_password)
            
            # Send
            text = msg.as_string()
            server.sendmail(gmail_user, recipients, text)
            server.quit()
            
            print(f"✅ Email sent successfully to {to_email}")
            return f"Email sent successfully to {to_email}"
            
        except Exception as e:
            print(f"❌ Email Error: {e}")
            return f"Email failed: {str(e)}"

    # 2. Run in Background
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _send_blocking)

async def open_website(site: str, q: str = None) -> str:
    url = f"https://www.google.com/search?q={q}" if q else f"https://www.{site}.com"
    webbrowser.open(url)
    return f"Opened {url}"

async def manage_shopping(action: str, item: str="", price: float=0) -> str:
    if action == "add": STORE.cart.append({"name": item, "price": price}); return "Added."
    return str(STORE.cart)

async def book_ride(a: str, b: str) -> str: return "Ride booked."
async def search_product(p: str) -> str: return "Searched."

# ==========================================
# 3. 🛍️ SMART PRICE COMPARISON ENGINE
# ==========================================
class PersonalShopper:
    def __init__(self):
        self.driver = None

    def _get_driver(self):
        if self.driver:
            try: 
                self.driver.current_url
                return self.driver
            except: self.driver = None

        options = webdriver.ChromeOptions()
        options.add_argument("--start-maximized")
        options.add_experimental_option("detach", True)
        options.add_argument("--log-level=3")
        options.add_argument("--disable-blink-features=AutomationControlled")
        
        # Dedicated Bot Profile
        path = os.path.join(os.getcwd(), "bot_profile")
        options.add_argument(f"user-data-dir={path}")

        try: self.driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
        except: self.driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()))
        return self.driver

    def parse_price(self, price_text):
        """Converts '₹1,54,900' to integer 154900"""
        try:
            return int(re.sub(r'[^\d]', '', price_text))
        except:
            return 99999999 # Return high number if price not found

    def check_platform(self, driver, wait, platform, product):
        """Scrapes price and url from a specific platform."""
        data = {"platform": platform, "price": 99999999, "url": "", "title": ""}
        
        try:
            print(f"🔎 Checking {platform}...")
            if platform == "Amazon":
                driver.get("https://www.amazon.in")
                box = wait.until(EC.presence_of_element_located((By.ID, "twotabsearchtextbox")))
                box.clear(); box.send_keys(product); box.send_keys(Keys.RETURN)
                
                # Find Item - Try multiple selectors
                item = None
                selectors = ["div.s-result-item[data-component-type='s-search-result']", "div.s-product-image-container"]
                for sel in selectors:
                    try: 
                        item = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, sel)))
                        break
                    except: continue
                
                if not item: return data

                # Get Price
                try: 
                    price_elm = item.find_element(By.CSS_SELECTOR, ".a-price-whole")
                    data["price"] = self.parse_price(price_elm.text)
                except: pass
                
                # Get URL
                try:
                    link = item.find_element(By.TAG_NAME, "h2").find_element(By.TAG_NAME, "a")
                    data["url"] = link.get_attribute("href")
                    data["title"] = link.text
                except: 
                     # Fallback URL
                    try: data["url"] = item.find_element(By.TAG_NAME, "a").get_attribute("href")
                    except: pass

            elif platform == "Flipkart":
                driver.get("https://www.flipkart.com")
                try:
                    box = wait.until(EC.presence_of_element_located((By.NAME, "q")))
                    box.clear(); box.send_keys(product); box.send_keys(Keys.RETURN)
                except: return data 
                
                # Find Item & Price (Flipkart has variable classes)
                try:
                    # List View
                    container = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "a._1fQZEK")))
                    price_text = container.find_element(By.CSS_SELECTOR, "div._30jeq3").text
                    data["price"] = self.parse_price(price_text)
                    data["url"] = container.get_attribute("href")
                    data["title"] = container.find_element(By.CSS_SELECTOR, "div._4rR01T").text
                except:
                    # Grid View
                    try:
                        container = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div._4ddWZP a.s1Q9rs")))
                        price_text = driver.find_element(By.CSS_SELECTOR, "div._30jeq3").text
                        data["price"] = self.parse_price(price_text)
                        data["url"] = container.get_attribute("href")
                        data["title"] = container.get_attribute("title")
                    except: pass
                    
        except Exception as e: print(f"Error checking {platform}: {e}")
        return data

    def execute_shopping(self, product, forced_platform=None):
        driver = self._get_driver()
        wait = WebDriverWait(driver, 5)
        
        # 1. PRICE COMPARISON
        if forced_platform and forced_platform.lower() != "auto":
            best_deal = self.check_platform(driver, wait, forced_platform, product)
        else:
            amazon_deal = self.check_platform(driver, wait, "Amazon", product)
            flipkart_deal = self.check_platform(driver, wait, "Flipkart", product)
            
            # Print for debugging
            print(f"\n💰 COMPARE: Amazon [₹{amazon_deal['price']}] vs Flipkart [₹{flipkart_deal['price']}]")
            
            if amazon_deal['price'] == 99999999 and flipkart_deal['price'] == 99999999:
                 return f"❌ Could not find '{product}' on Amazon OR Flipkart."
            
            if flipkart_deal['price'] < amazon_deal['price']:
                best_deal = flipkart_deal
            else:
                best_deal = amazon_deal

        # 2. BUY EXECUTION
        if not best_deal["url"]:
            return f"❌ Could not find URL for '{product}'."

        print(f"🚀 Winning Deal: {best_deal['platform']} at ₹{best_deal['price']}. Opening...")
        driver.get(best_deal["url"])
        
        # Switch tab if needed
        if len(driver.window_handles) > 1: driver.switch_to.window(driver.window_handles[-1])

        status = f"✅ Best Price: ₹{best_deal['price']} on {best_deal['platform']}."
        
        # 3. CLICK BUY BUTTON
        try:
            print("💳 Clicking 'Buy' button...")
            if best_deal["platform"] == "Amazon":
                try: 
                    driver.find_element(By.ID, "buy-now-button").click()
                except: 
                    # Fallback: Add to Cart -> Checkout
                    driver.find_element(By.ID, "add-to-cart-button").click()
                    time.sleep(2)
                    driver.find_element(By.NAME, "proceedToRetailCheckout").click()
            else:
                # Flipkart Buy
                driver.find_element(By.XPATH, "//button[normalize-space()='Buy Now']").click()
        except:
            status += " (Item opened. 'Buy Now' button hidden/Login required)."

        return status

shopper = PersonalShopper()

async def shop_online(product_query: str, platform: str) -> str:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, shopper.execute_shopping, product_query, platform)

AVAILABLE_TOOLS = {
    "get_system_time": get_system_time,
    "get_weather": get_weather,
    "search_web": search_web,
    "send_email": send_email,
    "open_website": open_website,
    "manage_shopping": manage_shopping,
    "book_ride": book_ride,
    "search_product": search_product,
    "set_volume": set_volume,
    "take_screenshot": take_screenshot,
    "minimize_windows": minimize_windows,
    "open_application": open_application,
    "shop_online": shop_online 
}