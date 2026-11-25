"""
Interactive Browser & Web Automation Controller for Jarvis.
Uses Playwright with Google Chrome and persistent profiles to execute real user commands
on any website: opening sections/categories, searching, clicking buttons, filling forms, and reading dynamic results.
"""
import os
import re
import time
import urllib.parse
import subprocess
import requests
from bs4 import BeautifulSoup
from rich.console import Console

console = Console()

class BrowserController:
    def __init__(self, voice_engine=None):
        self.voice = voice_engine
        self.profile_dir = os.path.expanduser("~/.jarvis_chrome_profile")
        try:
            os.makedirs(self.profile_dir, exist_ok=True)
            os.chmod(self.profile_dir, 0o700)
        except Exception:
            self.profile_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".jarvis_chrome_profile")
            try:
                os.makedirs(self.profile_dir, exist_ok=True)
                os.chmod(self.profile_dir, 0o700)
            except Exception:
                pass

    def speak(self, text: str):
        if self.voice:
            self.voice.speak(text, wait=False)

    def open_in_browser(self, url: str, browser: str = "Google Chrome") -> str:
        """Open a website in the specified or default browser and keep it open."""
        if not url.startswith("http://") and not url.startswith("https://"):
            url = "https://" + url

        browser_map = {
            "chrome": "Google Chrome",
            "google chrome": "Google Chrome",
            "safari": "Safari",
            "firefox": "Firefox",
            "edge": "Microsoft Edge",
            "arc": "Arc",
        }
        # Resolve to known app name from allowlist — prevents injection via browser argument
        target_app = browser_map.get(browser.lower(), None)
        if target_app is None:
            # Default to Chrome if unrecognised (never use user string directly in osascript)
            target_app = "Google Chrome"

        app_path = f"/Applications/{target_app}.app"
        if os.path.exists(app_path):
            subprocess.run(["open", "-a", target_app, url], check=False)
            # target_app is from our controlled allowlist, not raw user input
            subprocess.run(["osascript", "-e", f'tell application "{target_app}" to activate'], check=False)
            return f"Opened {url} in {target_app}."
        else:
            subprocess.run(["open", url], check=False)
            return f"Opened {url} in your default browser."

    def wait_for_login(self, service_name: str = "the service") -> bool:
        """
        Gracefully pause without terminating so the user can log in or enter an OTP in the browser.
        Resumes immediately once the user confirms.
        """
        notice = f"Please log in to {service_name} in your browser window, boss. I'll wait right here until you're logged in."
        console.print(f"\n[bold yellow]🔒 USER LOGIN REQUIRED:[/bold yellow] [bold white]{notice}[/bold white]")
        
        self.speak(notice)

        console.print("[dim cyan]👉 Press [Enter] here once you have finished logging in (or type 'cancel'): [/dim cyan]", end="")
        try:
            user_confirm = input().strip()
            if user_confirm.lower() in ("cancel", "abort", "exit"):
                return False
        except (KeyboardInterrupt, EOFError):
            return False

        resumed_msg = f"Verified login for {service_name}! Resuming your request now."
        console.print(f"[bold green]✔ {resumed_msg}[/bold green]\n")
        self.speak(resumed_msg)
        return True

    def _extract_section_query(self, command: str) -> str:
        """Extract the target category/section/item from user phrasing."""
        cmd = command.lower().strip()
        # Strip trailing site specifiers like 'on puma', 'in flipkart', 'on amazon', 'in chrome'
        cmd = re.sub(r'\s+(?:on|in|at|from)\s+[a-zA-Z0-9_\.-]+$', '', cmd).strip()
        patterns = [
            r'^(?:open|go to|navigate to|show me|show|view|find|search for|search|look for|look up|see for|see)\s+(?:the\s+)?(.*?)(?:\s+section|\s+category|\s+tab|\s+page)?$',
            r'^(.*?)(?:\s+section|\s+category|\s+tab|\s+page)$'
        ]
        for p in patterns:
            m = re.match(p, cmd)
            if m:
                extracted = m.group(1).strip()
                extracted = re.sub(r'^(?:the|a)\s+', '', extracted)
                extracted = re.sub(r'\s+(?:section|category|page|tab)$', '', extracted)
                if extracted:
                    return extracted
        return cmd

    def _resolve_section_url(self, base_url: str, section_query: str) -> str:
        """
        Resolves the exact direct category or search URL for any e-commerce or content domain.
        Handles Puma, Amazon, Flipkart, Myntra, Nike, YouTube, GitHub, RedBus, Wikipedia, etc.
        """
        clean_query = urllib.parse.quote_plus(section_query.strip())
        domain = base_url.lower()

        # If base_url already contains a deep path (e.g. /bus-tickets/... or /watch?v=...) preserve it!
        parsed = urllib.parse.urlparse(base_url)
        path = parsed.path.strip("/")
        if path and path not in ("search", "s", "w", "results"):
            if not section_query or any(part in section_query.lower() for part in path.split("/")):
                return base_url

        if "puma" in domain:
            if not section_query or section_query == "puma":
                return "https://in.puma.com"
            if "in.puma" in domain or ".in" in domain:
                return f"https://in.puma.com/in/en/search?q={clean_query}"
            return f"https://puma.com/search?q={clean_query}"
        elif "amazon" in domain:
            if not section_query or section_query == "amazon":
                return "https://www.amazon.in" if ".in" in domain else "https://www.amazon.com"
            if ".in" in domain:
                return f"https://www.amazon.in/s?k={clean_query}"
            return f"https://www.amazon.com/s?k={clean_query}"
        elif "flipkart" in domain:
            if not section_query or section_query == "flipkart":
                return "https://www.flipkart.com"
            return f"https://www.flipkart.com/search?q={clean_query}"
        elif "redbus" in domain:
            if "/bus-tickets/" in base_url:
                return base_url
            return f"https://www.redbus.in/bus-tickets/{clean_query}"
        elif "myntra" in domain:
            return f"https://www.myntra.com/{clean_query}"
        elif "nike" in domain:
            return f"https://www.nike.com/in/w?q={clean_query}"
        elif "youtube" in domain:
            return f"https://www.youtube.com/results?search_query={clean_query}"
        elif "github" in domain:
            return f"https://github.com/search?q={clean_query}"
        elif "wikipedia" in domain:
            return f"https://en.wikipedia.org/wiki/Special:Search?search={clean_query}"
        elif "reddit" in domain:
            return f"https://www.reddit.com/search/?q={clean_query}"
        else:
            # Generic search/section endpoint
            scheme = parsed.scheme or "https"
            netloc = parsed.netloc or parsed.path.split("/")[0]
            if not section_query:
                return f"{scheme}://{netloc}"
            return f"{scheme}://{netloc}/search?q={clean_query}"

    def _run_chrome_js(self, js_code: str) -> tuple[int, str, str]:
        """Execute JavaScript in Google Chrome's active tab via AppleScript."""
        import json as _json
        escaped_js = _json.dumps(js_code)
        script = (
            'tell application "Google Chrome"\n'
            '    if (count of windows) = 0 then return "__NO_WINDOW__"\n'
            '    tell active tab of front window\n'
            f'        return execute javascript {escaped_js}\n'
            '    end tell\n'
            'end tell'
        )
        try:
            res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=8)
            return res.returncode, res.stdout.strip(), res.stderr.strip()
        except Exception as e:
            return -1, "", str(e)

    def _get_active_chrome_url(self) -> str:
        """Return the URL of Google Chrome's front active tab, or empty string."""
        script = (
            'tell application "Google Chrome"\n'
            '    if (count of windows) > 0 then return URL of active tab of front window\n'
            'end tell'
        )
        try:
            res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=4)
            if res.returncode == 0:
                return res.stdout.strip()
        except Exception:
            pass
        return ""

    def act_on_active_tab(self, command: str) -> str:
        """Click, scroll, fill forms, or read content directly inside the currently open Google Chrome tab."""
        import json as _json
        cmd = command.strip()
        cmd_lower = cmd.lower()

        subprocess.run(["osascript", "-e", 'tell application "Google Chrome" to activate'], check=False)

        # 1. Scroll
        if "scroll" in cmd_lower:
            if "top" in cmd_lower:
                js = "window.scrollTo({top: 0, behavior: 'smooth'}); 'Scrolled to top.'"
            elif "bottom" in cmd_lower:
                js = "window.scrollTo({top: document.body.scrollHeight, behavior: 'smooth'}); 'Scrolled to bottom.'"
            elif "up" in cmd_lower:
                js = "window.scrollBy({top: -550, behavior: 'smooth'}); 'Scrolled up.'"
            else:
                js = "window.scrollBy({top: 550, behavior: 'smooth'}); 'Scrolled down.'"
            code, out, err = self._run_chrome_js(js)

        # 2. Reply to active web chat (e.g. WhatsApp Web)
        if re.match(r"^(?:reply|send reply|send message|respond)\b", cmd_lower):
            m_rep = re.match(r"^(?:reply(?:\s+(?:my\s+)?(?:whatsapp|chat|message|msg))?\s+(?:with|saying)?|reply|send reply(?:\s+with)?|send message)\s+(.+?)(?:\s+message)?$", cmd, re.IGNORECASE)
            reply_text = m_rep.group(1).strip(" '\"") if m_rep else cmd
            from core.app_control import AppController
            return AppController().reply_in_active_chat(reply_text, app_name="Google Chrome")

        # 3. Fill / Type into field
        elif any(w in cmd_lower for w in ("fill ", "type ", "enter ")):
            m = re.search(r'(?:type|fill|enter)\s+[\'"]?([^\'"]+)[\'"]?\s+(?:into|in|to)\s+[\'"]?([^\'"]+)[\'"]?', cmd, re.IGNORECASE)
            if m:
                val, field_name = m.group(1).strip(), m.group(2).strip()
            else:
                val = re.sub(r'^(?:type|fill|enter)\s+', '', cmd, flags=re.IGNORECASE).strip()
                field_name = ""
            js = f"""
            (() => {{
                const q = {_json.dumps(field_name.lower())};
                const val = {_json.dumps(val)};
                const inputs = Array.from(document.querySelectorAll('input, textarea'));
                const visible = inputs.filter(el => el.offsetParent !== null && !el.disabled && el.type !== 'hidden');
                let target = visible.find(el => {{
                    const meta = ((el.placeholder||'') + ' ' + (el.name||'') + ' ' + (el.id||'') + ' ' + (el.getAttribute('aria-label')||'')).toLowerCase();
                    return q ? meta.includes(q) : true;
                }});
                if (!target && visible.length) target = visible[0];
                if (!target) return '__NOT_FOUND__';
                target.focus();
                const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set
                            || Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value')?.set;
                if (setter) setter.call(target, val); else target.value = val;
                target.dispatchEvent(new Event('input', {{ bubbles: true }}));
                target.dispatchEvent(new Event('change', {{ bubbles: true }}));
                return 'Typed into ' + (target.placeholder || target.name || target.id || 'input field');
            }})()
            """
            code, out, err = self._run_chrome_js(js)

        # 3. Click button / link
        elif any(w in cmd_lower for w in ("click", "press", "select", "tap")):
            m = re.search(r'(?:click on|click|press|select|tap)\s+(?:the\s+)?[\'"]?([^\'"]+?)[\'"]?(?:\s+button|\s+link)?$', cmd, re.IGNORECASE)
            target_name = m.group(1).strip() if m else cmd_lower
            js = f"""
            (() => {{
                const q = {_json.dumps(target_name.lower())};
                const els = Array.from(document.querySelectorAll('button, a, [role="button"], input[type="submit"], [aria-label]'));
                const visible = els.filter(el => el.offsetParent !== null);
                let match = visible.find(el => (el.innerText || el.value || el.getAttribute('aria-label') || '').trim().toLowerCase() === q);
                if (!match) match = visible.find(el => (el.innerText || el.value || el.getAttribute('aria-label') || el.title || '').toLowerCase().includes(q));
                if (!match) return '__NOT_FOUND__';
                match.scrollIntoView({{block: 'center'}});
                match.click();
                return 'Clicked: ' + (match.innerText || match.value || match.getAttribute('aria-label') || q).trim().slice(0, 60);
            }})()
            """
            code, out, err = self._run_chrome_js(js)

        # 4. Read / inspect active tab
        else:
            js = """
            (() => {
                const title = document.title || '';
                const url = location.href || '';
                const text = (document.body?.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 2000);
                return 'Title: ' + title + '\\nURL: ' + url + '\\nContent: ' + text;
            })()
            """
            code, out, err = self._run_chrome_js(js)

        if out == "__NO_WINDOW__":
            return "No Google Chrome window is open right now."
        if out == "__NOT_FOUND__":
            return f"Could not find matching element for '{cmd}' on the active Chrome tab."
        if code != 0 and "JavaScript through AppleScript" in err or "Allow JavaScript from Apple Events" in err:
            return (
                "Chrome blocked JavaScript control. In Chrome's top menu, enable: "
                "View -> Developer -> Allow JavaScript from Apple Events, then try again."
            )
        if code != 0:
            return f"Could not interact with Chrome tab: {err or 'unknown error'}"
        return out or f"Executed '{cmd}' on active Chrome tab."

    def automate_web(self, url: str, command: str, wait_for_login: bool = False, browser: str = "Google Chrome") -> str:
        """
        Executes real web actions on ANY website according to a natural language command:
        - Active Tab Control: Clicks, scrolls, fills forms, or reads the currently open Chrome tab.
        - Section/Category Navigation: E.g. 'open polo section' -> Opens exact section in Chrome!
        - Playwright Fallback: Automates background page flows when needed.
        """
        url_clean = (url or "").strip()
        if not url_clean or url_clean.lower() in ("current", "active", "this page", "open tab", "chrome", "current tab"):
            return self.act_on_active_tab(command)

        if not url_clean.startswith("http://") and not url_clean.startswith("https://"):
            url = "https://" + url_clean
        else:
            url = url_clean

        console.print(f"\n[bold cyan]🌐 Jarvis Web Automation:[/bold cyan] Navigating to [bold white]{url}[/bold white]")
        console.print(f"[dim yellow]Command:[/dim yellow] '{command}'")

        cmd_lower = command.lower().strip()
        domain = url.split("//")[-1].split("/")[0].replace("www.", "")

        # ── Scenario A: Active-tab DOM interaction if user already has this site open in Chrome ──
        is_dom_action = any(k in cmd_lower for k in [
            "click", "scroll", "fill ", "type ", "enter ", "submit", "press button", "read page", "summarize page"
        ])
        if is_dom_action and browser.lower() in ("chrome", "google chrome"):
            active_url = self._get_active_chrome_url().lower()
            if domain and domain in active_url:
                return self.act_on_active_tab(command)

        # ── Scenario B: User wants a specific section, category, or search item ──
        search_triggers = ["search", "find", "look", "show", "open", "see", "view", "section", "category", "get", "buy", "check"]
        is_search_or_section = not is_dom_action and (any(k in cmd_lower for k in search_triggers) or len(cmd_lower.split()) <= 5)

        if is_search_or_section:
            section_query = self._extract_section_query(command)
            target_section_url = self._resolve_section_url(url, section_query)
            console.print(f"[dim cyan]🎯 Resolved Target Section URL:[/dim cyan] [bold white]{target_section_url}[/bold white]")

            # Open directly in the user's Chrome and bring to front
            self.open_in_browser(target_section_url, browser=browser)

            msg = f"Opened {domain.title()} with your search for '{section_query}' in {browser}!\nURL: {target_section_url}"
            console.print(f"[bold green]✔ {msg}[/bold green]\n")
            return msg

        # ── Scenario B: Interactive DOM Automation (Click / Fill / Playwright) ──
        from playwright.sync_api import sync_playwright

        try:
            with sync_playwright() as p:
                try:
                    context = p.chromium.launch_persistent_context(
                        user_data_dir=self.profile_dir,
                        channel="chrome",
                        headless=False,
                        args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
                        viewport={"width": 1366, "height": 850}
                    )
                except Exception:
                    browser_instance = p.chromium.launch(channel="chrome", headless=False)
                    context = browser_instance.new_context(viewport={"width": 1366, "height": 850})

                page = context.pages[0] if context.pages else context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                time.sleep(1.0)

                if wait_for_login or "/login" in page.url or "/signin" in page.url or "/auth" in page.url:
                    ok = self.wait_for_login(domain)
                    if not ok:
                        return f"Navigated to {url}, but paused on login request."

                # Action: Click
                if "click" in cmd_lower or "select" in cmd_lower or "press" in cmd_lower:
                    target_match = re.search(r'(?:click on|click|select|press)\s+[\'"]?([^\'"]+)[\'"]?', cmd_lower)
                    target_name = target_match.group(1).strip() if target_match else cmd_lower.replace("click", "").strip()
                    console.print(f"[dim cyan]🖱️ Clicking:[/dim cyan] '{target_name}'")

                    clicked = False
                    for selector in [
                        f"button:has-text('{target_name}')",
                        f"a:has-text('{target_name}')",
                        f"input[value*='{target_name}' i]",
                        f"[role='button']:has-text('{target_name}')",
                    ]:
                        btn = page.query_selector(selector)
                        if btn and btn.is_visible():
                            btn.click()
                            clicked = True
                            time.sleep(1.5)
                            break

                    if not clicked:
                        elements = page.query_selector_all("button, a, [role='button']")
                        for el in elements:
                            if target_name in el.inner_text().lower() and el.is_visible():
                                el.click()
                                clicked = True
                                time.sleep(1.5)
                                break

                    current_url = page.url
                    # Also ensure user has the resulting page open in their regular browser window
                    self.open_in_browser(current_url, browser=browser)
                    if clicked:
                        return f"Clicked '{target_name}' on {domain}. Now at: {page.title()} ({current_url})"
                    return f"Could not find clickable element '{target_name}' on {url}."

                # Action: Fill / Form
                elif "fill" in cmd_lower or "type" in cmd_lower or "enter" in cmd_lower:
                    fill_match = re.search(r'(?:type|fill|enter)\s+[\'"]?([^\'"]+)[\'"]?\s+(?:into|in|to)\s+[\'"]?([^\'"]+)[\'"]?', cmd_lower)
                    if fill_match:
                        val = fill_match.group(1).strip()
                        field_name = fill_match.group(2).strip()
                    else:
                        val = command
                        field_name = "input"

                    field = (
                        page.query_selector(f"input[name*='{field_name}' i]") or
                        page.query_selector(f"input[id*='{field_name}' i]") or
                        page.query_selector(f"input[placeholder*='{field_name}' i]") or
                        page.query_selector("input[type='text']")
                    )
                    if field:
                        field.fill(val)
                        return f"Filled '{val}' into {field_name} field on {url}."
                    return f"Could not locate field '{field_name}' on {url}."

                # Generic Fallback: Open URL in user's browser and summarize
                self.open_in_browser(url, browser=browser)
                title = page.title()
                return f"Opened {url} ({title}) in {browser}."

        except Exception as e:
            # Fallback to direct browser launch
            self.open_in_browser(url, browser=browser)
            return f"Opened {url} in {browser}. Task: {command} (Automator note: {e})"

    def interactive_website_task(self, url: str, action_description: str, browser: str = "Google Chrome", wait_for_login: bool = False) -> str:
        """Executes real web actions on any website, opening sections or automating DOM."""
        return self.automate_web(url=url, command=action_description, wait_for_login=wait_for_login, browser=browser)

    def search_redbus(self, source: str, destination: str, browser: str = "Google Chrome", wait_for_login: bool = False) -> str:
        """Search for buses on RedBus, display available options, open the page in browser."""
        src = re.sub(r'[^a-zA-Z0-9]', '', source.strip().lower())
        dst = re.sub(r'[^a-zA-Z0-9]', '', destination.strip().lower())
        target_url = f"https://www.redbus.in/bus-tickets/{src}-to-{dst}"
        return self.interactive_website_task(
            url=target_url,
            action_description=f"search buses from {source} to {destination}",
            browser=browser,
            wait_for_login=wait_for_login
        )
