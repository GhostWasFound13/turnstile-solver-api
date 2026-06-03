import os
import sys
import time
import uuid
import random
import logging
import asyncio
import json
from typing import Optional, Union, Dict, Any
import argparse
from urllib.parse import urlparse, unquote
from datetime import datetime, timedelta
from quart import Quart, request, jsonify
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service

# Remove rich - too heavy
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] [%(levelname)s] -> %(message)s', datefmt='%H:%M:%S')
logger = logging.getLogger("TurnstileAPIServer")

# ============ JSON DATABASE ============
DB_PATH = "results.json"

def _get_current_time():
    return datetime.now()

def _load_db() -> Dict:
    try:
        if os.path.exists(DB_PATH):
            with open(DB_PATH, 'r') as f:
                return json.load(f)
        return {}
    except Exception as e:
        logger.error(f"Error loading database: {e}")
        return {}

def _save_db(data: Dict) -> None:
    try:
        with open(DB_PATH, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving database: {e}")

async def init_db():
    if not os.path.exists(DB_PATH):
        _save_db({})
        logger.info(f"Database initialized: {DB_PATH}")
    asyncio.create_task(_auto_cleanup_loop())

async def _auto_cleanup_loop():
    while True:
        try:
            await asyncio.sleep(18000)
            await cleanup_old_results(hours=5)
        except Exception as e:
            logger.error(f"Auto cleanup error: {e}")

async def save_result(task_id: str, task_type: str, data: Union[Dict[str, Any], str]) -> None:
    try:
        db = _load_db()
        db[task_id] = {
            "type": task_type,
            "data": data if isinstance(data, dict) else {"value": data},
            "created_at": _get_current_time().isoformat()
        }
        _save_db(db)
    except Exception as e:
        logger.error(f"Error saving result {task_id}: {e}")

async def load_result(task_id: str) -> Optional[Union[Dict[str, Any], str]]:
    try:
        db = _load_db()
        if task_id in db:
            return db[task_id].get("data")
        return None
    except Exception as e:
        logger.error(f"Error loading result {task_id}: {e}")
        return None

async def cleanup_old_results(hours: int = 5) -> int:
    try:
        db = _load_db()
        cutoff_time = _get_current_time() - timedelta(hours=hours)
        deleted_count = 0
        to_delete = []
        
        for task_id, result in db.items():
            created_at = datetime.fromisoformat(result.get("created_at", "2000-01-01T00:00:00"))
            if created_at < cutoff_time:
                to_delete.append(task_id)
        
        for task_id in to_delete:
            del db[task_id]
            deleted_count += 1
        
        if deleted_count > 0:
            _save_db(db)
            logger.info(f"Cleaned up {deleted_count} old results")
        
        return deleted_count
    except Exception as e:
        logger.error(f"Error cleaning up: {e}")
        return 0


def get_random_user_agent() -> str:
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
    ]
    return random.choice(user_agents)


def parse_proxy_config(proxy: str) -> dict:
    raw_proxy = (proxy or "").strip()
    if not raw_proxy:
        raise ValueError("Invalid proxy format")

    if "://" in raw_proxy:
        parsed = urlparse(raw_proxy)
        if not parsed.scheme or not parsed.hostname or not parsed.port:
            raise ValueError("Invalid proxy format")

        config = {"server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"}
        if parsed.username is not None:
            config["username"] = unquote(parsed.username)
        if parsed.password is not None:
            config["password"] = unquote(parsed.password)
        return config

    parts = raw_proxy.split(":")
    if len(parts) == 2:
        host, port = parts
        if not host or not port:
            raise ValueError("Invalid proxy format")
        return {"server": f"http://{host}:{port}"}

    if len(parts) == 4:
        host, port, username, password = parts
        if not host or not port or not username:
            raise ValueError("Invalid proxy format")
        return {
            "server": f"http://{host}:{port}",
            "username": username,
            "password": password,
        }

    raise ValueError("Invalid proxy format")


class TurnstileAPIServer:

    def __init__(self, headless: bool, useragent: Optional[str], debug: bool, browser_type: str, thread: int, proxy_support: bool, use_random_config: bool = False, browser_name: Optional[str] = None, browser_version: Optional[str] = None):
        self.app = Quart(__name__)
        self.debug = debug
        self.headless = headless
        self.thread_count = 1  # Force 1 thread
        self.proxy_support = proxy_support
        self.driver_pool = asyncio.Queue()
        self.login_address = os.getenv("TURNSTILE_LOGIN_ADDRESS", "").strip()
        self.semaphore = asyncio.Semaphore(1)
        self.useragent = useragent if useragent else get_random_user_agent()
        self._setup_routes()

    def _setup_routes(self) -> None:
        self.app.before_serving(self._startup)
        self.app.after_serving(self._shutdown)
        self.app.route('/turnstile', methods=['GET'])(self.process_turnstile)
        self.app.route('/result', methods=['GET'])(self.get_result)
        self.app.route('/')(self.index)

    async def _startup(self) -> None:
        logger.info("Starting GeckoDriver initialization...")
        try:
            await init_db()
            await self._initialize_drivers()
        except Exception as e:
            logger.error(f"Failed to initialize GeckoDriver: {str(e)}")
            raise

    async def _shutdown(self) -> None:
        logger.info("Shutting down driver pool...")
        while not self.driver_pool.empty():
            try:
                index, driver = await self.driver_pool.get()
                driver.quit()
            except:
                pass
        logger.info("Shutdown complete")

    async def _initialize_drivers(self) -> None:
        firefox_options = Options()
        
        if self.headless:
            firefox_options.add_argument("--headless")
        
        firefox_options.add_argument("--no-sandbox")
        firefox_options.add_argument("--disable-dev-shm-usage")
        
        # MAXIMUM MEMORY OPTIMIZATION
        firefox_options.set_preference("javascript.enabled", True)
        firefox_options.set_preference("permissions.default.image", 2)  # Block images
        firefox_options.set_preference("dom.ipc.processCount", 1)
        firefox_options.set_preference("browser.tabs.remote.autostart", False)
        firefox_options.set_preference("browser.cache.memory.enable", False)
        firefox_options.set_preference("browser.cache.disk.enable", False)
        firefox_options.set_preference("network.http.max-connections", 6)
        firefox_options.set_preference("extensions.enabled", False)
        firefox_options.set_preference("browser.privatebrowsing.autostart", True)
        
        firefox_options.binary_location = "/usr/bin/firefox-esr"
        
        if self.useragent:
            firefox_options.set_preference("general.useragent.override", self.useragent)
        
        service = Service(executable_path="/usr/local/bin/geckodriver", log_output=os.devnull)
        
        try:
            driver = webdriver.Firefox(options=firefox_options, service=service)
            driver.set_page_load_timeout(30)
            await self.driver_pool.put((1, driver))
            logger.info("GeckoDriver initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize GeckoDriver: {e}")
            return
        
        logger.info(f"GeckoDriver pool initialized with 1 driver")

    def _click_turnstile(self, driver):
        """Simple click strategy"""
        try:
            # Try to find and click iframe
            iframes = driver.find_elements(By.CSS_SELECTOR, 'iframe[src*="turnstile"], iframe[src*="challenges.cloudflare.com"]')
            if iframes:
                driver.switch_to.frame(iframes[0])
                checkbox = driver.find_elements(By.CSS_SELECTOR, 'input[type="checkbox"]')
                if checkbox:
                    checkbox[0].click()
                    driver.switch_to.default_content()
                    return True
                driver.switch_to.default_content()
            
            # Try direct click
            widget = driver.find_elements(By.CSS_SELECTOR, '.cf-turnstile, [data-sitekey]')
            if widget:
                widget[0].click()
                return True
        except:
            pass
        return False

    async def _solve_turnstile(self, task_id: str, url: str, sitekey: str, action: Optional[str] = None, cdata: Optional[str] = None, request_proxy: Optional[str] = None):
        logger.info(f"SOLVER STARTED for task {task_id}")
        async with self.semaphore:
            try:
                index, driver = await asyncio.wait_for(self.driver_pool.get(), timeout=30.0)
            except asyncio.TimeoutError:
                logger.error(f"Task {task_id}: Timeout waiting for driver")
                await save_result(task_id, "turnstile", {"value": "CAPTCHA_FAIL"})
                return

            start_time = time.time()
            proxy = None

            try:
                if request_proxy:
                    proxy = request_proxy.strip()
                elif self.proxy_support:
                    proxy_file_path = os.path.join(os.getcwd(), "proxies.txt")
                    try:
                        with open(proxy_file_path) as proxy_file:
                            proxies = [line.strip() for line in proxy_file if line.strip()]
                        proxy = random.choice(proxies) if proxies else None
                    except:
                        pass
            except Exception as e:
                logger.error(f"Proxy setup error: {e}")

            try:
                logger.info(f"Loading URL: {url}")
                driver.get(url)
                
                # Wait for page to load
                time.sleep(3)
                
                # Try to click if needed
                self._click_turnstile(driver)
                
                max_attempts = 20
                
                for attempt in range(max_attempts):
                    try:
                        # Check for token
                        token_elements = driver.find_elements(By.CSS_SELECTOR, 'input[name="cf-turnstile-response"]')
                        
                        for token_elem in token_elements:
                            token = token_elem.get_attribute('value')
                            if token and len(token) > 10:
                                elapsed_time = round(time.time() - start_time, 3)
                                logger.info(f"SOLVED! Token: {token[:30]}... in {elapsed_time}s")
                                await save_result(task_id, "turnstile", {"value": token})
                                await self.driver_pool.put((index, driver))
                                return
                        
                        # Try clicking every 5 attempts
                        if attempt > 0 and attempt % 5 == 0:
                            self._click_turnstile(driver)
                        
                        time.sleep(2)
                            
                    except Exception as e:
                        if self.debug:
                            logger.debug(f"Attempt error: {str(e)}")
                        continue
                
                elapsed_time = round(time.time() - start_time, 3)
                await save_result(task_id, "turnstile", {"value": "CAPTCHA_FAIL"})
                logger.error(f"FAILED to solve in {elapsed_time}s")
                
            except Exception as e:
                elapsed_time = round(time.time() - start_time, 3)
                await save_result(task_id, "turnstile", {"value": "CAPTCHA_FAIL"})
                logger.error(f"Error: {str(e)}")
            finally:
                try:
                    await self.driver_pool.put((index, driver))
                except:
                    pass

    async def process_turnstile(self):
        url = request.args.get('url')
        sitekey = request.args.get('sitekey')
        action = request.args.get('action')
        request_proxy = request.args.get('proxy')

        if not url or not sitekey:
            return jsonify({
                "errorId": 1,
                "errorCode": "ERROR_WRONG_PAGEURL",
                "errorDescription": "Both 'url' and 'sitekey' are required"
            }), 200

        task_id = str(uuid.uuid4())
        await save_result(task_id, "turnstile", {
            "status": "CAPTCHA_NOT_READY",
            "createTime": int(time.time())
        })

        logger.info(f"Created task {task_id} for {url}")
        asyncio.create_task(self._solve_turnstile(task_id=task_id, url=url, sitekey=sitekey, action=action, request_proxy=request_proxy))

        return jsonify({
            "errorId": 0,
            "taskId": task_id
        }), 200

    async def get_result(self):
        task_id = request.args.get('id')

        if not task_id:
            return jsonify({
                "errorId": 1,
                "errorCode": "ERROR_WRONG_CAPTCHA_ID",
                "errorDescription": "Invalid task ID"
            }), 200

        result = await load_result(task_id)
        if not result:
            return jsonify({
                "errorId": 1,
                "errorCode": "ERROR_CAPTCHA_UNSOLVABLE",
                "errorDescription": "Task not found"
            }), 200

        if result == "CAPTCHA_NOT_READY" or (isinstance(result, dict) and result.get("status") == "CAPTCHA_NOT_READY"):
            return jsonify({"status": "processing"}), 200

        if isinstance(result, dict) and result.get("value") == "CAPTCHA_FAIL":
            return jsonify({
                "errorId": 1,
                "errorCode": "ERROR_CAPTCHA_UNSOLVABLE",
                "errorDescription": "Could not solve"
            }), 200

        if isinstance(result, dict) and result.get("value") and result.get("value") != "CAPTCHA_FAIL":
            return jsonify({
                "errorId": 0,
                "status": "ready",
                "solution": {
                    "token": result["value"]
                }
            }), 200
        else:
            return jsonify({
                "errorId": 1,
                "errorCode": "ERROR_CAPTCHA_UNSOLVABLE",
                "errorDescription": "Could not solve"
            }), 200

    @staticmethod
    async def index():
        return "Turnstile Solver API - Running"


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-headless', action='store_true')
    parser.add_argument('--useragent', type=str)
    parser.add_argument('--debug', action='store_true')
    parser.add_argument('--browser_type', type=str, default='firefox')
    parser.add_argument('--thread', type=int, default=1)
    parser.add_argument('--proxy', action='store_true')
    parser.add_argument('--random', action='store_true')
    parser.add_argument('--browser', type=str, default='firefox')
    parser.add_argument('--version', type=str, default='120')
    parser.add_argument('--host', type=str, default='0.0.0.0')
    parser.add_argument('--port', type=str, default='8000')
    return parser.parse_args()


if __name__ == '__main__':
    args = parse_args()
    
    server = TurnstileAPIServer(
        headless=not args.no_headless, 
        debug=args.debug, 
        useragent=args.useragent, 
        browser_type="firefox", 
        thread=1, 
        proxy_support=args.proxy,
        use_random_config=args.random,
        browser_name="firefox",
        browser_version=args.version
    )
    server.app.run(host=args.host, port=int(args.port))
