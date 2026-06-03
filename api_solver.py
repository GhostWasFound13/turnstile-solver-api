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
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.align import Align
from rich import box



COLORS = {
    'MAGENTA': '\033[35m',
    'BLUE': '\033[34m',
    'GREEN': '\033[32m',
    'YELLOW': '\033[33m',
    'RED': '\033[31m',
    'RESET': '\033[0m',
}


class CustomLogger(logging.Logger):
    @staticmethod
    def format_message(level, color, message):
        timestamp = time.strftime('%H:%M:%S')
        return f"[{timestamp}] [{COLORS.get(color)}{level}{COLORS.get('RESET')}] -> {message}"

    def debug(self, message, *args, **kwargs):
        super().debug(self.format_message('DEBUG', 'MAGENTA', message), *args, **kwargs)

    def info(self, message, *args, **kwargs):
        super().info(self.format_message('INFO', 'BLUE', message), *args, **kwargs)

    def success(self, message, *args, **kwargs):
        super().info(self.format_message('SUCCESS', 'GREEN', message), *args, **kwargs)

    def warning(self, message, *args, **kwargs):
        super().warning(self.format_message('WARNING', 'YELLOW', message), *args, **kwargs)

    def error(self, message, *args, **kwargs):
        super().error(self.format_message('ERROR', 'RED', message), *args, **kwargs)


logging.setLoggerClass(CustomLogger)
logger = logging.getLogger("TurnstileAPIServer")
logger.setLevel(logging.DEBUG)
handler = logging.StreamHandler(sys.stdout)
logger.addHandler(handler)


# ============ JSON DATABASE WITH AUTO RESET EVERY 5 HOURS ============
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

async def get_pending_count() -> int:
    try:
        db = _load_db()
        count = 0
        for result in db.values():
            data = result.get("data", {})
            if isinstance(data, dict) and data.get("status") == "CAPTCHA_NOT_READY":
                count += 1
        return count
    except Exception as e:
        logger.error(f"Error getting pending count: {e}")
        return 0


# ============ BROWSER CONFIGURATION ============
def get_random_user_agent() -> str:
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
    ]
    return random.choice(user_agents)


def _mask_secret(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    if len(value) <= 2:
        return "**"
    return f"{value[:1]}***{value[-1:]}"


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

    if len(parts) == 5:
        scheme, host, port, username, password = parts
        if not scheme or not host or not port or not username:
            raise ValueError("Invalid proxy format")
        return {
            "server": f"{scheme}://{host}:{port}",
            "username": username,
            "password": password,
        }

    raise ValueError("Invalid proxy format")


def redact_proxy_config(proxy_config: Optional[dict]) -> str:
    if not proxy_config:
        return "none"
    username = proxy_config.get("username")
    if username:
        return f"{proxy_config.get('server')} (auth: {_mask_secret(username)}:***)"
    return str(proxy_config.get("server"))


class TurnstileAPIServer:

    def __init__(self, headless: bool, useragent: Optional[str], debug: bool, browser_type: str, thread: int, proxy_support: bool, use_random_config: bool = False, browser_name: Optional[str] = None, browser_version: Optional[str] = None):
        self.app = Quart(__name__)
        self.debug = debug
        self.browser_type = "firefox"
        self.headless = headless
        self.thread_count = min(thread, 1)
        self.proxy_support = proxy_support
        self.driver_pool = asyncio.Queue()
        self.use_random_config = use_random_config
        self.browser_name = browser_name or "firefox"
        self.browser_version = browser_version or "120"
        self.console = Console()
        self.login_address = os.getenv("TURNSTILE_LOGIN_ADDRESS", "").strip()
        self.active_tasks = set()
        self.semaphore = asyncio.Semaphore(1)
        
        self.useragent = useragent if useragent else get_random_user_agent()

        self._setup_routes()

    def display_welcome(self):
        self.console.clear()
        
        combined_text = Text()
        combined_text.append("\nTurnstile Solver API - Firefox Edition", style="bold white")
        combined_text.append(f"\nRuntime: Quart + Selenium/GeckoDriver (Threads: {self.thread_count})", style="cyan")
        combined_text.append("\nStorage: JSON (Auto-reset every 5 hours)", style="cyan")
        combined_text.append("\n")

        info_panel = Panel(
            Align.left(combined_text),
            title="[bold blue]Turnstile Solver API[/bold blue]",
            subtitle="[bold magenta]Firefox Only Build[/bold magenta]",
            box=box.ROUNDED,
            border_style="bright_blue",
            padding=(0, 1),
            width=50
        )

        self.console.print(info_panel)
        self.console.print()

    def _setup_routes(self) -> None:
        self.app.before_serving(self._startup)
        self.app.after_serving(self._shutdown)
        self.app.route('/turnstile', methods=['GET'])(self.process_turnstile)
        self.app.route('/result', methods=['GET'])(self.get_result)
        self.app.route('/')(self.index)
        self.app.route('/docs')(self.index)
        self.app.route('/docs/')(self.index)

    async def _startup(self) -> None:
        self.display_welcome()
        logger.info(f"Starting GeckoDriver initialization with {self.thread_count} driver(s)")
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
        firefox_options.set_preference("dom.webdriver.enabled", False)
        firefox_options.set_preference("useAutomationExtension", False)
        firefox_options.set_preference("media.navigator.enabled", False)
        firefox_options.set_preference("javascript.enabled", True)
        firefox_options.set_preference("permissions.default.image", 2)
        firefox_options.set_preference("dom.ipc.processCount", 1)
        firefox_options.set_preference("browser.tabs.remote.autostart", False)
        firefox_options.set_preference("browser.tabs.remote.autostart.2", False)
        firefox_options.set_preference("browser.tabs.remote.separatePrivilegedContentProcess", False)
        firefox_options.set_preference("browser.tabs.remote.separatePrivilegedMozillaWebContentProcess", False)
        firefox_options.set_preference("browser.tabs.remote.separateFileUriProcess", False)
        firefox_options.set_preference("browser.tabs.remote.separatePrivilegedContentProcess", False)
        firefox_options.binary_location = "/usr/bin/firefox-esr"
        
        if self.useragent:
            firefox_options.set_preference("general.useragent.override", self.useragent)
        
        # Setup service
        geckodriver_paths = [
            "/usr/local/bin/geckodriver",
            "/usr/bin/geckodriver",
            "/snap/bin/geckodriver"
        ]
        
        service = None
        for path in geckodriver_paths:
            if os.path.exists(path):
                logger.info(f"Using GeckoDriver: {path}")
                service = Service(executable_path=path)
                break
        
        if not service:
            service = Service()
        
        for i in range(self.thread_count):
            try:
                driver = webdriver.Firefox(options=firefox_options, service=service)
                await self.driver_pool.put((i+1, driver))
                if self.debug:
                    logger.info(f"GeckoDriver {i + 1} initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize GeckoDriver {i+1}: {e}")
                continue
        
        logger.info(f"GeckoDriver pool initialized with {self.driver_pool.qsize()} drivers")

    async def _find_and_click_checkbox(self, driver, index: int):
        try:
            iframe_selectors = [
                'iframe[src*="challenges.cloudflare.com"]',
                'iframe[src*="turnstile"]',
                'iframe[title*="widget"]'
            ]
            
            for selector in iframe_selectors:
                try:
                    iframes = driver.find_elements(By.CSS_SELECTOR, selector)
                    if iframes:
                        iframe = iframes[0]
                        driver.switch_to.frame(iframe)
                        
                        checkbox_selectors = [
                            'input[type="checkbox"]',
                            '.cb-lb input[type="checkbox"]',
                            'label input[type="checkbox"]'
                        ]
                        
                        for cb_selector in checkbox_selectors:
                            try:
                                checkbox = WebDriverWait(driver, 2).until(
                                    EC.element_to_be_clickable((By.CSS_SELECTOR, cb_selector))
                                )
                                checkbox.click()
                                driver.switch_to.default_content()
                                if self.debug:
                                    logger.debug(f"Browser {index}: Successfully clicked checkbox in iframe")
                                return True
                            except:
                                continue
                        
                        driver.switch_to.default_content()
                except Exception as e:
                    if self.debug:
                        logger.debug(f"Browser {index}: Iframe selector '{selector}' failed: {str(e)}")
                    continue
        except Exception as e:
            if self.debug:
                logger.debug(f"Browser {index}: General iframe search failed: {str(e)}")
        
        return False

    async def _try_click_strategies(self, driver, index: int):
        strategies = [
            ('checkbox_click', lambda: self._find_and_click_checkbox(driver, index)),
            ('direct_widget', lambda: self._safe_click(driver, '.cf-turnstile', index)),
            ('iframe_click', lambda: self._safe_click(driver, 'iframe[src*="turnstile"]', index)),
            ('js_click', lambda: driver.execute_script("document.querySelector('.cf-turnstile')?.click()")),
            ('sitekey_attr', lambda: self._safe_click(driver, '[data-sitekey]', index)),
            ('any_turnstile', lambda: self._safe_click(driver, '*[class*="turnstile"]', index)),
            ('xpath_click', lambda: self._safe_click(driver, "//div[@class='cf-turnstile']", index))
        ]
        
        for strategy_name, strategy_func in strategies:
            try:
                result = await strategy_func() if asyncio.iscoroutinefunction(strategy_func) else strategy_func()
                if result is True or result is None:
                    if self.debug:
                        logger.debug(f"Browser {index}: Click strategy '{strategy_name}' succeeded")
                    return True
            except Exception as e:
                if self.debug:
                    logger.debug(f"Browser {index}: Click strategy '{strategy_name}' failed: {str(e)}")
                continue
        
        return False

    async def _safe_click(self, driver, selector: str, index: int):
        try:
            element = WebDriverWait(driver, 2).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
            )
            element.click()
            return True
        except Exception:
            return False

    async def _load_captcha_overlay(self, driver, websiteKey: str, action: str = '', index: int = 0):
        script = f"""
        const existing = document.querySelector('#captcha-overlay');
        if (existing) existing.remove();

        const overlay = document.createElement('div');
        overlay.id = 'captcha-overlay';
        overlay.style.position = 'absolute';
        overlay.style.top = '0';
        overlay.style.left = '0';
        overlay.style.width = '100vw';
        overlay.style.height = '100vh';
        overlay.style.backgroundColor = 'rgba(0, 0, 0, 0.5)';
        overlay.style.display = 'block';
        overlay.style.justifyContent = 'center';
        overlay.style.alignItems = 'center';
        overlay.style.zIndex = '1000';

        const captchaDiv = document.createElement('div');
        captchaDiv.className = 'cf-turnstile';
        captchaDiv.setAttribute('data-sitekey', '{websiteKey}');
        captchaDiv.setAttribute('data-callback', 'onCaptchaSuccess');
        captchaDiv.setAttribute('data-action', '{action}');

        overlay.appendChild(captchaDiv);
        document.body.appendChild(overlay);

        const script = document.createElement('script');
        script.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js';
        script.async = true;
        script.defer = true;
        document.head.appendChild(script);
        """
        driver.execute_script(script)
        if self.debug:
            logger.debug(f"Browser {index}: Created CAPTCHA overlay with sitekey: {websiteKey}")

    async def _solve_turnstile(self, task_id: str, url: str, sitekey: str, action: Optional[str] = None, cdata: Optional[str] = None, request_proxy: Optional[str] = None):
        async with self.semaphore:
            proxy = None

            try:
                index, driver = await asyncio.wait_for(self.driver_pool.get(), timeout=30.0)
            except asyncio.TimeoutError:
                logger.error(f"Task {task_id}: Timeout waiting for driver")
                await save_result(task_id, "turnstile", {"value": "CAPTCHA_FAIL", "elapsed_time": 0})
                return

            start_time = time.time()
            proxy_file_path = os.path.join(os.getcwd(), "proxies.txt")

            try:
                if request_proxy:
                    proxy = request_proxy.strip()
                    if self.debug:
                        logger.debug(f"Browser {index}: Using request-level proxy override")
                elif self.proxy_support:
                    try:
                        with open(proxy_file_path) as proxy_file:
                            proxies = [line.strip() for line in proxy_file if line.strip()]
                        proxy = random.choice(proxies) if proxies else None
                        if self.debug and proxy:
                            logger.debug(f"Browser {index}: Selected proxy from file")
                    except FileNotFoundError:
                        logger.warning(f"Proxy file not found: {proxy_file_path}")
                        proxy = None
                    except Exception as e:
                        logger.error(f"Error reading proxy file: {str(e)}")
                        proxy = None

            except Exception as e:
                elapsed_time = round(time.time() - start_time, 3)
                await save_result(task_id, "turnstile", {"value": "CAPTCHA_FAIL", "elapsed_time": elapsed_time})
                logger.error(f"Browser {index}: Failed to setup: {str(e)}")
                await self.driver_pool.put((index, driver))
                return

            try:
                if self.debug:
                    logger.debug(f"Browser {index}: Starting Turnstile solve for URL: {url} with Sitekey: {sitekey}")

                driver.get(url)

                try:
                    login_input = driver.find_elements(By.CSS_SELECTOR, 'input[name="address"]')
                    if self.login_address and login_input:
                        if self.debug:
                            logger.debug(f"Browser {index}: Login page detected, submitting configured TURNSTILE_LOGIN_ADDRESS")
                        
                        login_input[0].send_keys(self.login_address)
                        time.sleep(0.5)
                        
                        submit_btn = driver.find_elements(By.CSS_SELECTOR, 'button[type="submit"]')
                        if submit_btn:
                            submit_btn[0].click()
                        
                        if self.debug:
                            logger.debug(f"Browser {index}: Login submitted, waiting for verification page")
                        time.sleep(2)
                except Exception as e:
                    if self.debug:
                        logger.debug(f"Browser {index}: Optional login flow info: {e}")

                try:
                    buttons = [
                        '#load-turnstile-btn',
                        'button:has-text("Load Security Verification")',
                        'button:has-text("Click to verify")',
                        '.btn-primary-modern:has-text("Security")'
                    ]
                    
                    for btn in buttons:
                        try:
                            btn_css = btn.replace(':has-text', '').replace('("', '').replace('")', '')
                            elements = driver.find_elements(By.CSS_SELECTOR, btn_css)
                            if elements and elements[0].is_displayed():
                                if self.debug:
                                    logger.debug(f"Browser {index}: Verification trigger found, clicking...")
                                elements[0].click()
                                time.sleep(2)
                                break
                        except:
                            continue
                except Exception as e:
                    if self.debug:
                        logger.debug(f"Browser {index}: Optional click flow info: {e}")

                time.sleep(2)

                max_attempts = 15
                
                for attempt in range(max_attempts):
                    try:
                        token_elements = driver.find_elements(By.CSS_SELECTOR, 'input[name="cf-turnstile-response"]')
                        
                        if not token_elements:
                            if self.debug:
                                logger.debug(f"Browser {index}: No token elements found on attempt {attempt + 1}")
                        else:
                            for token_elem in token_elements:
                                token = token_elem.get_attribute('value')
                                if token:
                                    elapsed_time = round(time.time() - start_time, 3)
                                    logger.success(f"Browser {index}: Successfully solved captcha - {COLORS.get('MAGENTA')}{token[:10]}{COLORS.get('RESET')} in {COLORS.get('GREEN')}{elapsed_time}{COLORS.get('RESET')} Seconds")
                                    await save_result(task_id, "turnstile", {"value": token, "elapsed_time": elapsed_time})
                                    await self.driver_pool.put((index, driver))
                                    return
                        
                        if attempt > 2 and attempt % 3 == 0:
                            click_success = await self._try_click_strategies(driver, index)
                            if not click_success and self.debug:
                                logger.debug(f"Browser {index}: All click strategies failed on attempt {attempt + 1}")
                        
                        if attempt == 10:
                            try:
                                if not token_elements:
                                    if self.debug:
                                        logger.debug(f"Browser {index}: Creating overlay as fallback strategy")
                                    await self._load_captcha_overlay(driver, sitekey, action or '', index)
                                    time.sleep(2)
                            except Exception as e:
                                if self.debug:
                                    logger.debug(f"Browser {index}: Fallback overlay creation failed: {str(e)}")
                        
                        wait_time = min(0.5 + (attempt * 0.05), 1.5)
                        time.sleep(wait_time)
                        
                        if self.debug and attempt % 5 == 0:
                            logger.debug(f"Browser {index}: Attempt {attempt + 1}/{max_attempts} - No valid token yet")
                            
                    except Exception as e:
                        if self.debug:
                            logger.debug(f"Browser {index}: Attempt {attempt + 1} error: {str(e)}")
                        continue
                
                elapsed_time = round(time.time() - start_time, 3)
                await save_result(task_id, "turnstile", {"value": "CAPTCHA_FAIL", "elapsed_time": elapsed_time})
                if self.debug:
                    logger.error(f"Browser {index}: Error solving Turnstile in {COLORS.get('RED')}{elapsed_time}{COLORS.get('RESET')} Seconds")
            except Exception as e:
                elapsed_time = round(time.time() - start_time, 3)
                await save_result(task_id, "turnstile", {"value": "CAPTCHA_FAIL", "elapsed_time": elapsed_time})
                if self.debug:
                    logger.error(f"Browser {index}: Error solving Turnstile: {str(e)}")
            finally:
                try:
                    await self.driver_pool.put((index, driver))
                    if self.debug:
                        logger.debug(f"Browser {index}: Driver returned to pool")
                except Exception as e:
                    if self.debug:
                        logger.warning(f"Browser {index}: Error returning driver to pool: {str(e)}")

    async def process_turnstile(self):
        url = request.args.get('url')
        sitekey = request.args.get('sitekey')
        action = request.args.get('action')
        cdata = request.args.get('cdata')
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
            "createTime": int(time.time()),
            "url": url,
            "sitekey": sitekey,
            "action": action,
            "cdata": cdata,
            "proxy": "provided" if request_proxy else None
        })

        try:
            asyncio.create_task(self._solve_turnstile(task_id=task_id, url=url, sitekey=sitekey, action=action, cdata=cdata, request_proxy=request_proxy))

            if self.debug:
                logger.debug(f"Request completed with taskid {task_id}.")
            return jsonify({
                "errorId": 0,
                "taskId": task_id
            }), 200
        except Exception as e:
            logger.error(f"Unexpected error processing request: {str(e)}")
            return jsonify({
                "errorId": 1,
                "errorCode": "ERROR_UNKNOWN",
                "errorDescription": str(e)
            }), 200

    async def get_result(self):
        task_id = request.args.get('id')

        if not task_id:
            return jsonify({
                "errorId": 1,
                "errorCode": "ERROR_WRONG_CAPTCHA_ID",
                "errorDescription": "Invalid task ID/Request parameter"
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
                "errorDescription": "Workers could not solve the Captcha"
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
                "errorDescription": "Workers could not solve the Captcha"
            }), 200

    @staticmethod
    async def index():
        return """
            <!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>Turnstile Solver API</title>
                <script src="https://cdn.tailwindcss.com"></script>
            </head>
            <body class="bg-gray-900 text-gray-200 min-h-screen flex items-center justify-center">
                <div class="bg-gray-800 p-8 rounded-lg shadow-md max-w-2xl w-full border border-red-500">
                    <h1 class="text-3xl font-bold mb-6 text-center text-red-500">Welcome to Turnstile Solver API</h1>
                    <p class="mb-4 text-gray-300">To use the turnstile service, send a GET request to 
                       <code class="bg-red-700 text-white px-2 py-1 rounded">/turnstile</code> with the following query parameters:</p>
                    <ul class="list-disc pl-6 mb-6 text-gray-300">
                        <li><strong>url</strong>: The URL where Turnstile is to be validated</li>
                        <li><strong>sitekey</strong>: The site key for Turnstile</li>
                    </ul>
                    <div class="bg-gray-700 p-4 rounded-lg mb-6 border border-red-500">
                        <p class="font-semibold mb-2 text-red-400">Example usage:</p>
                        <code class="text-sm break-all text-red-300">/turnstile?url=https://example.com&sitekey=sitekey</code>
                    </div>
                    <div class="bg-gray-700 p-4 rounded-lg mb-6">
                        <p class="text-gray-200 font-semibold mb-3">Deployment notes</p>
                        <div class="space-y-2 text-sm text-gray-300">
                            <p>Use <code class="bg-gray-800 px-2 py-1 rounded">/turnstile</code> to create a solve task and <code class="bg-gray-800 px-2 py-1 rounded">/result</code> to poll its status.</p>
                            <p>If your target page requires an address/email field before the widget appears, set <code class="bg-gray-800 px-2 py-1 rounded">TURNSTILE_LOGIN_ADDRESS</code>.</p>
                            <p>Run behind a reverse proxy or tunnel if you need public access.</p>
                        </div>
                    </div>
                </div>
            </body>
            </html>
        """


def parse_args():
    parser = argparse.ArgumentParser(description="Turnstile API Server")
    parser.add_argument('--no-headless', action='store_true', help='Run the browser with GUI')
    parser.add_argument('--useragent', type=str, help='User-Agent string')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')
    parser.add_argument('--browser_type', type=str, default='firefox', help='Browser type')
    parser.add_argument('--thread', type=int, default=1, help='Number of browser threads')
    parser.add_argument('--proxy', action='store_true', help='Enable proxy support')
    parser.add_argument('--random', action='store_true', help='Use random User-Agent')
    parser.add_argument('--browser', type=str, default='firefox', help='Browser name')
    parser.add_argument('--version', type=str, default='120', help='Browser version')
    parser.add_argument('--host', type=str, default='0.0.0.0', help='Host to run on')
    parser.add_argument('--port', type=str, default='8000', help='Port to run on')
    return parser.parse_args()


def create_app(headless: bool, useragent: str, debug: bool, browser_type: str, thread: int, proxy_support: bool, use_random_config: bool, browser_name: str, browser_version: str) -> Quart:
    server = TurnstileAPIServer(headless=headless, useragent=useragent, debug=debug, browser_type=browser_type, thread=thread, proxy_support=proxy_support, use_random_config=use_random_config, browser_name=browser_name, browser_version=browser_version)
    return server.app


if __name__ == '__main__':
    args = parse_args()
    
    if args.thread > 1:
        logger.warning(f"Thread count reduced from {args.thread} to 1")
        args.thread = 1
        
    app = create_app(
        headless=not args.no_headless, 
        debug=args.debug, 
        useragent=args.useragent, 
        browser_type="firefox", 
        thread=args.thread, 
        proxy_support=args.proxy,
        use_random_config=args.random,
        browser_name="firefox",
        browser_version=args.version
    )
    app.run(host=args.host, port=int(args.port))
