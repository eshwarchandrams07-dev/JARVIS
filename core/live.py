"""
Universal Live Watcher & Background Session Controller for Jarvis.
Allows Jarvis to stay live on ANY website or application, continuously monitoring,
preventing timeouts, or watching for triggers/changes until the user says stop.
"""
import os
import re
import time
import base64
import threading
import subprocess
from rich.console import Console

console = Console()

class LiveSessionManager:
    def __init__(self, voice_engine=None):
        self.voice = voice_engine
        self.active_session = None
        self.stop_event = threading.Event()
        self.worker_thread = None
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

    def chime_alert(self, message: str = "Trigger detected!"):
        """Play macOS system chime and send a native banner notification."""
        subprocess.run(["afplay", "/System/Library/Sounds/Glass.aiff"], check=False)
        try:
            from core.notify import notify
            notify("🟢 Jarvis Live Alert", message)
        except Exception:
            pass

    def start_live(self, target: str, condition: str = "keep_alive", interval: float = 5.0, browser: str = "Google Chrome") -> str:
        """
        Make Jarvis live on any website or application until the user says stop.
        - target: URL (e.g. 'https://...') or application name (e.g. 'Spotify', 'Slack')
        - condition: 'keep_alive' (stay live and prevent timeouts), 'change' (alert on page content changes),
                     or 'contains:<keyword>' (alert when specific text appears).
        """
        if self.active_session:
            return f"Jarvis is already live on: {self.active_session['target']}. Type /stop or say 'stop' first."

        self.stop_event.clear()
        is_web = target.startswith("http://") or target.startswith("https://") or "." in target and not target.endswith(".app")

        if is_web and not target.startswith("http://") and not target.startswith("https://"):
            target = "https://" + target

        self.active_session = {
            "target": target,
            "type": "web" if is_web else "app",
            "condition": condition,
            "interval": max(2.0, float(interval)),
            "start_time": time.time(),
            "browser": browser
        }

        self.worker_thread = threading.Thread(target=self._run_loop, daemon=True)
        self.worker_thread.start()

        msg = f"Jarvis is now LIVE on {target}. Standing guard until you say stop."
        self.speak(msg)
        console.print(f"\n[bold green]🟢 LIVE SESSION STARTED:[/bold green] [bold white]{target}[/bold white]")
        console.print(f"[dim cyan]Condition: {condition} | Interval: {interval}s | Type '/stop' or say 'stop' to halt.[/dim cyan]\n")
        return msg

    def stop_live(self) -> str:
        """Halt any active live session."""
        if not self.active_session:
            return "No live website or application is currently being monitored, sir."

        target = self.active_session["target"]
        self.stop_event.set()
        self.active_session = None
        
        msg = f"Live session for {target} has been terminated. Standing by."
        self.speak(msg)
        console.print(f"\n[bold yellow]🛑 {msg}[/bold yellow]\n")
        return msg

    def _run_loop(self):
        session = self.active_session
        if not session:
            return

        target = session["target"]
        session_type = session["type"]
        condition = session["condition"]
        interval = session["interval"]

        if session_type == "web":
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                try:
                    context = p.chromium.launch_persistent_context(
                        user_data_dir=self.profile_dir,
                        channel="chrome",
                        headless=False,
                        args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
                        viewport={"width": 1366, "height": 850}
                    )
                    page = context.pages[0] if context.pages else context.new_page()

                    if not page.url.startswith(target):
                        page.goto(target, wait_until="domcontentloaded", timeout=30000)

                    previous_content = ""
                    cycles = 0

                    while not self.stop_event.is_set():
                        cycles += 1
                        
                        try:
                            current_text = page.inner_text("body")
                        except Exception:
                            current_text = ""

                        # Check trigger conditions
                        if condition.startswith("contains:") or condition.startswith("text:"):
                            keyword = condition.split(":", 1)[1].strip().lower()
                            if keyword and keyword in current_text.lower():
                                alert = f"Keyword '{keyword}' detected on {target}!"
                                console.print(f"\n[bold red blink]🚨 TRIGGER DETECTED! 🚨[/bold red blink] [bold white]{alert}[/bold white]")
                                self.chime_alert(message=alert)
                                self.speak(alert)
                                # Bring window to front
                                page.bring_to_front()

                        elif condition == "change":
                            if previous_content and current_text != previous_content:
                                alert = f"Page content changed on {target}!"
                                console.print(f"\n[bold magenta]⚡ CHANGE DETECTED:[/bold magenta] [bold white]{alert}[/bold white]")
                                self.chime_alert(message=alert)
                                self.speak(alert)
                            previous_content = current_text

                        # Periodic keep-alive / refresh
                        self.stop_event.wait(interval)
                        if self.stop_event.is_set():
                            break

                        try:
                            # If page has a refresh or update button, prefer it, otherwise reload
                            reload_btn = page.query_selector("button:has-text('Refresh'), a:has-text('Refresh')")
                            if reload_btn and reload_btn.is_visible():
                                reload_btn.click()
                            else:
                                page.reload(wait_until="domcontentloaded", timeout=15000)
                        except Exception:
                            pass

                except Exception as e:
                    console.print(f"[red]Live web session error: {e}[/red]")
                finally:
                    self.active_session = None

        else:
            # Native Desktop Application Live Watcher
            # Keeps app open, frontmost, or monitors state via AppleScript
            subprocess.run(["open", "-a", target], check=False)
            
            while not self.stop_event.is_set():
                # Check if app is still alive
                check_script = f'tell application "System Events" to (name of processes) contains "{target}"'
                res = subprocess.run(["osascript", "-e", check_script], capture_output=True, text=True, check=False)
                
                is_running = "true" in res.stdout.strip().lower()
                if not is_running:
                    # Relaunch if requested
                    subprocess.run(["open", "-a", target], check=False)

                self.stop_event.wait(interval)
                if self.stop_event.is_set():
                    break


def capture_screen_b64(max_dimension: int = 1024, quality: int = 70) -> str | None:
    """Capture the macOS screen, resize using native sips, and return JPEG base64 string."""
    raw_path = f"/tmp/jarvis_screen_raw_{os.getpid()}.png"
    jpg_path = f"/tmp/jarvis_screen_{os.getpid()}.jpg"
    b64_data = None
    try:
        subprocess.run(["screencapture", "-x", raw_path], check=False)
        if not os.path.exists(raw_path):
            return None
        subprocess.run([
            "sips", "-s", "format", "jpeg",
            "-s", "formatOptions", str(quality),
            "-Z", str(max_dimension),
            raw_path, "--out", jpg_path
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)

        target = jpg_path if os.path.exists(jpg_path) else raw_path
        with open(target, "rb") as f:
            b64_data = base64.b64encode(f.read()).decode("utf-8")
    except Exception:
        pass
    finally:
        for p in (raw_path, jpg_path):
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass
    return b64_data


class LiveScreenManager:
    """
    Manages interactive live screen sharing session.
    Toggled on/off with Shift+L (globally) or /screen (in terminal).
    When active:
    - Jarvis watches the user's screen in real-time.
    - Every user command (voice or text) receives live visual screen context.
    - Jarvis directly answers questions about what is on screen and acts on commands.
    """
    def __init__(self, voice_engine=None):
        self.voice = voice_engine
        self.is_live = False
        self.start_time = None
        self._lock = threading.Lock()

    def speak(self, text: str):
        if self.voice:
            self.voice.speak(text, wait=False)

    def toggle(self) -> bool:
        """Toggle live screen sharing session on or off. Returns new active state."""
        with self._lock:
            if not self.is_live:
                self.is_live = True
                self.start_time = time.time()
                subprocess.Popen(["afplay", "/System/Library/Sounds/Glass.aiff"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                try:
                    from core.notify import notify
                    notify("🔴 Live Screen Sharing Active", "Jarvis is watching your screen. Press Shift+L to stop.")
                except Exception:
                    pass
                msg = "Live screen sharing active! I can see your screen now, boss. Ask me anything or tell me what to do!"
                console.print(f"\n[bold red blink]🔴 LIVE SCREEN SHARING ACTIVE:[/bold red blink] [bold white]I can see your screen in real-time![/bold white]")
                console.print("[dim cyan]Press [bold yellow]Shift+L[/bold yellow] anywhere or type [bold yellow]/screen[/bold yellow] to stop sharing.[/dim cyan]\n")
                self.speak(msg)
                return True
            else:
                self.is_live = False
                self.start_time = None
                subprocess.Popen(["afplay", "/System/Library/Sounds/Pop.aiff"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                msg = "Live screen sharing stopped. Back to normal mode!"
                console.print(f"\n[bold green]⚪ LIVE SCREEN SHARING STOPPED:[/bold green] [bold white]{msg}[/bold white]\n")
                self.speak(msg)
                return False

    def get_screen_frame(self) -> str | None:
        """Capture the current screen and return compressed JPEG base64 string."""
        if not self.is_live:
            return None
        return capture_screen_b64(max_dimension=1024, quality=70)


def parse_screen_watch_intent(text: str, is_screen_live: bool = False) -> tuple[str, str, bool] | None:
    """
    Parse a user prompt to detect screen-watching intent, trigger condition, follow-up action, and repeat mode.
    Handles both 'when <trigger>, <action>' and '<action> when/if <trigger>' phrasing.
    Returns (trigger, action, repeat) or None.
    """
    t = text.strip()
    explicit_screen_watch = (
        re.search(r'\b(watch|keep looking at|keep watching|monitor|look at)\s+(?:my\s+|the\s+)?screen\b', t, re.IGNORECASE)
        or re.search(r'\bif something changes\b', t, re.IGNORECASE)
        or re.search(r'\bwhen (?:something|anything) changes\b', t, re.IGNORECASE)
    )
    conditional_alert_watch = (
        re.search(r'\b(?:if|when|whenever|every time|each time)\s+(?:(?:you|u)\s+)?(?:see|spot|notice|find|detect)\b.*\b(?:notify|alert|tell|let me know|run|open|split|reply|send|type|click)\b', t, re.IGNORECASE)
        and (is_screen_live or re.search(r'\b(?:new message|new notification|appears|appeared|changes|arrives|finishes|completes|succeeds|fails)\b', t, re.IGNORECASE))
    ) or bool(
        re.search(r'\b(?:if|when|whenever|every time|each time)\s+.+?\b(?:appears|appeared|changes|changed|arrives|arrived|finishes|completes|succeeds|fails)\b', t, re.IGNORECASE)
        and re.search(r'\b(?:notify|alert|tell|let me know|open|split|run|reply|send|type|click)\b', t, re.IGNORECASE)
    )
    if not (explicit_screen_watch or conditional_alert_watch):
        return None

    repeat = bool(re.search(r'\b(every time|each time|keep notifying|keep alerting|continuously)\b', t, re.IGNORECASE))

    # Case A: Action appears BEFORE 'when/if' (e.g. "reply my whatsapp message with done when new message appeared")
    m_before = re.match(r'^(.+?)\s+\b(?:when|if|whenever|every time|each time)\s+(?:(?:you|u)\s+)?(?:see\s+)?(.+)$', t, re.IGNORECASE)
    if m_before and re.search(r'\b(?:reply|send|notify|alert|tell|open|split|run|type|click)\b', m_before.group(1), re.IGNORECASE) and not re.search(r'\b(?:watch|monitor|look at)\s+(?:my\s+|the\s+)?screen\b', m_before.group(1), re.IGNORECASE):
        raw_action = m_before.group(1).strip(" ,:.")
        raw_trig = m_before.group(2).strip(" ,:.")
        if re.search(r'\b(something changes|screen changes|anything changes|page changes|new messages?|new notifications?|any updates?|appeared|appears)\b', raw_trig, re.IGNORECASE):
            trigger = 'something changes'
        else:
            trigger = raw_trig or 'something changes'
        return trigger, (raw_action or 'notify'), repeat

    # Case B: Trigger appears first ("watch screen / if new message appears, reply with done")
    if re.search(r'\b(something changes|screen changes|anything changes|page changes|new messages?|new notifications?|any updates?)\b', t, re.IGNORECASE):
        trigger = 'something changes'
    else:
        m = re.search(r'\b(?:when|if|whenever|for|detect|see)\s+(?:(?:you|u)\s+)?(?:see\s+)?(.+?)(?:\s+(?:then|and\s+then)\s+|\s*,\s*(?=(?:notify|split|open|run|tell|alert|close|search|start|copy|reply|send|type|click)\b)|\s*:\s*|$)', t, re.IGNORECASE)
        if m:
            trigger = m.group(1).strip()
        else:
            trigger = 'something changes'

    action = 'notify'
    m_then = re.search(r'\b(?:then|and then)\s+(.+)$', t, re.IGNORECASE)
    if m_then:
        action = m_then.group(1).strip()
    else:
        m_comma = re.search(r',\s*(?:and\s+)?((?:notify|split|open|run|tell|alert|close|search|start|copy|reply|send|type|click)\b.+)$', t, re.IGNORECASE)
        if m_comma:
            action = m_comma.group(1).strip()
        else:
            m_notify = re.search(r'\b(?:notify me|alert me|tell me)\s+(?:and\s+)?(.*)$', t, re.IGNORECASE)
            if m_notify and m_notify.group(1).strip():
                action = m_notify.group(1).strip()
            else:
                m_tail_act = re.search(r'\b(?:appears|appeared|changes|arrives|finishes|completes)\s+((?:reply|send|open|split|run|type|click)\b.+)$', t, re.IGNORECASE)
                if m_tail_act:
                    action = m_tail_act.group(1).strip()
                elif 'notify' in t.lower() or 'alert' in t.lower():
                    action = 'notify'

    trigger = re.sub(r'\b(notify|alert|tell)\s+me\b.*', '', trigger, flags=re.IGNORECASE).strip()
    trigger = re.sub(r'[\'\"\.,]+', '', trigger).strip()
    if not trigger:
        trigger = 'something changes'

    return trigger, action, repeat


class ScreenTriggerWatcher:
    """
    Continuous visual screen watcher that monitors the Mac display in real time,
    detects visual/pixel or textual trigger conditions, alerts the user, and
    autonomously executes follow-up actions (one-shot or continuous repeat mode).
    """
    def __init__(self, voice_engine=None, brain=None):
        self.voice = voice_engine
        self.brain = brain
        self.active_watch = None
        self.stop_event = threading.Event()
        self.worker_thread = None
        self._lock = threading.Lock()
        self.ocr_binary = os.path.join(os.path.dirname(os.path.abspath(__file__)), "screen_ocr")

    def speak(self, text: str):
        if self.voice:
            self.voice.speak(text, wait=False)

    def start_watch(self, trigger: str, action: str = "notify", interval: float = 3.0, repeat: bool = False) -> str:
        with self._lock:
            if self.active_watch:
                return f"Jarvis is already watching the screen for '{self.active_watch['trigger']}'. Type /stop to cancel first."

            self.stop_event.clear()
            clean_trigger = trigger.strip()
            clean_action = action.strip() if action else "notify"

            self.active_watch = {
                "trigger": clean_trigger,
                "action": clean_action,
                "interval": max(1.5, float(interval)),
                "repeat": bool(repeat),
                "start_time": time.time(),
                "baseline_text": None,
            }
            self.worker_thread = threading.Thread(target=self._watch_loop, daemon=True)
            self.worker_thread.start()

            mode_label = "continuously (repeat mode)" if repeat else "for trigger"
            msg = f"Watching your screen {mode_label}: '{clean_trigger}'. I will notify you and execute work when it happens!"
            self.speak(msg)
            console.print(f"\n[bold red blink]👁️ SCREEN TRIGGER WATCHER ENGAGED:[/bold red blink] [bold white]Watching {mode_label}: '{clean_trigger}'[/bold white]")
            console.print(f"[dim cyan]Follow-up action: '{clean_action}' | Interval: {interval}s | Type '/stop' to cancel.[/dim cyan]\n")
            return msg

    def stop_watch(self) -> str:
        with self._lock:
            if not self.active_watch:
                return "No screen watcher is currently active, sir."
            trig = self.active_watch["trigger"]
            self.stop_event.set()
            self.active_watch = None
            msg = f"Stopped watching screen for '{trig}'."
            self.speak(msg)
            console.print(f"\n[bold yellow]🛑 {msg}[/bold yellow]\n")
            return msg

    @staticmethod
    def _normalize_ocr_text(text: str) -> str:
        """Strip macOS menu bar clock/battery noise and Jarvis's own alert banners from OCR diffing."""
        if not text:
            return ""
        cleaned = re.sub(r'\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+\d{1,2}\s+[A-Za-z]{3}(?:\s+\d{1,2}:\d{2}\s*(?:AM|PM)?)?', '', text, flags=re.IGNORECASE)
        cleaned = re.sub(r'\b\d{1,2}:\d{2}\s*(?:AM|PM)?\b', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\b\d{1,3}%', '', cleaned)
        # Strip Jarvis's own status/notification lines so Jarvis never triggers on its own output
        for own_phrase in (
            r'Jarvis Trigger Detected[^\n]*',
            r'SCREEN TRIGGER WATCHER ENGAGED[^\n]*',
            r'TRIGGER FIRED![^\n]*',
            r'Executing requested action:[^\n]*',
            r'Follow-up action:[^\n]*',
        ):
            cleaned = re.sub(own_phrase, '', cleaned, flags=re.IGNORECASE)
        return re.sub(r'\s+', ' ', cleaned).strip()

    @staticmethod
    def _get_screen_thumb_bytes() -> bytes | None:
        """Capture tiny 64px uncompressed BMP thumbnail bytes (skipping top 22% menu bar + banner area)."""
        raw_path = f"/tmp/jarvis_thumb_{os.getpid()}.png"
        bmp_path = f"/tmp/jarvis_thumb_{os.getpid()}.bmp"
        try:
            subprocess.run(["screencapture", "-x", raw_path], check=False)
            if not os.path.exists(raw_path):
                return None
            subprocess.run(
                ["sips", "-s", "format", "bmp", "-Z", "64", raw_path, "--out", bmp_path],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
            )
            if os.path.exists(bmp_path):
                with open(bmp_path, "rb") as f:
                    data = f.read()
                body = data[54:]
                # Skip top ~22% (menu bar clock + macOS top-right notification banners!)
                skip_top = (len(body) * 22) // 100
                return body[skip_top:]
        except Exception:
            pass
        finally:
            for p in (raw_path, bmp_path):
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except Exception:
                        pass
        return None

    def get_screen_text(self) -> str:
        """Extract all visible screen text using Apple Neural Engine OCR in 0.3s."""
        if os.path.exists(self.ocr_binary):
            try:
                res = subprocess.run([self.ocr_binary], capture_output=True, text=True, timeout=5)
                if res.returncode == 0:
                    return res.stdout.strip()
            except Exception:
                pass
        return ""

    def _watch_loop(self):
        watch = self.active_watch
        if not watch:
            return

        trigger = watch["trigger"].lower()
        action = watch["action"]
        interval = watch["interval"]
        repeat = watch.get("repeat", False)
        is_change_trigger = any(w in trigger for w in (
            "change", "update", "different", "modify", "something changes",
            "new message", "new notification", "appears", "arrives", "pops up",
        ))

        baseline = self._normalize_ocr_text(self.get_screen_text())
        baseline_thumb = self._get_screen_thumb_bytes() if is_change_trigger else None
        watch["baseline_text"] = baseline

        while not self.stop_event.is_set():
            self.stop_event.wait(interval)
            if self.stop_event.is_set():
                break

            raw_text = self.get_screen_text()
            current_text = self._normalize_ocr_text(raw_text)
            matched = False
            trigger_reason = ""

            if is_change_trigger:
                if baseline and current_text and current_text != baseline:
                    diff_len = abs(len(current_text) - len(baseline))
                    if diff_len > 15 or current_text[:80] != baseline[:80]:
                        matched = True
                        trigger_reason = "Screen content changed!"
                if not matched and baseline_thumb:
                    cur_thumb = self._get_screen_thumb_bytes()
                    if cur_thumb and len(cur_thumb) == len(baseline_thumb):
                        diff_sum = sum(abs(a - b) for a, b in zip(cur_thumb, baseline_thumb))
                        if (diff_sum / len(cur_thumb)) > 8.0:
                            matched = True
                            trigger_reason = "Visual screen change detected!"
            else:
                clean_trig = re.sub(r'^(when|if|whenever|after|for|see|detect)\s+', '', trigger).strip()
                clean_trig = re.sub(r'\s+(appears|shows up|happens|is on screen|appears on screen)$', '', clean_trig).strip()

                if clean_trig and clean_trig in raw_text.lower():
                    matched = True
                    trigger_reason = f"Detected '{clean_trig}' on screen!"
                else:
                    words = [w for w in clean_trig.split() if len(w) > 3]
                    if len(words) >= 2 and all(w in raw_text.lower() for w in words):
                        matched = True
                        trigger_reason = f"Detected phrase '{clean_trig}' on screen!"

            if matched:
                console.print(f"\n[bold red blink]🚨 TRIGGER FIRED! 🚨[/bold red blink] [bold white]{trigger_reason}[/bold white]")
                subprocess.Popen(["afplay", "/System/Library/Sounds/Glass.aiff"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                try:
                    from core.notify import notify
                    notify("🎯 Jarvis Trigger Detected", f"{trigger_reason}\nAction: {action}")
                except Exception:
                    pass

                has_action = bool(action and action.lower() not in ("notify", "alert", "tell me", "nothing", "none"))
                action_failed = False
                if has_action:
                    self.speak(f"Boss! Trigger fired: {trigger_reason} Executing {action}!")
                    console.print(f"[bold green]⚙ Executing requested action:[/bold green] [bold white]{action}[/bold white]")
                    if self.brain:
                        try:
                            # Run synchronously BEFORE refreshing baseline so our own typing/window focus never self-triggers!
                            res = self.brain.chat(action)
                            console.print(f"\n[bold cyan]Jarvis:[/bold cyan] {res}\n")
                            self.speak(res)
                            res_l = str(res).lower()
                            if any(err in res_l for err in ("blocked", "error", "could not", "cancelled", "failed")):
                                action_failed = True
                        except Exception as e:
                            console.print(f"[red]Error executing action: {e}[/red]")
                            action_failed = True
                else:
                    self.speak(f"Boss! Trigger fired: {trigger_reason}")

                if repeat and not action_failed:
                    # Wait for banner/UI animations to settle, then snapshot a clean post-action baseline
                    self.stop_event.wait(3.0)
                    if self.stop_event.is_set():
                        break
                    baseline = self._normalize_ocr_text(self.get_screen_text())
                    if is_change_trigger:
                        baseline_thumb = self._get_screen_thumb_bytes()
                    continue

                with self._lock:
                    self.active_watch = None
                break
