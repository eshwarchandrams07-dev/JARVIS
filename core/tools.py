"""Mac system tools and functions for Jarvis."""
import os
import shutil
import subprocess
import datetime
import json
from core.browser import BrowserController
from core.ffcs import FFCSMonitor
from core.live import LiveSessionManager, ScreenTriggerWatcher
from core.app_control import AppController

_browser_controller = BrowserController()
_ffcs_monitor = FFCSMonitor()
_live_manager = LiveSessionManager()
_screen_watcher = ScreenTriggerWatcher()
_app_controller = AppController()
_reminder_engine = None

def get_system_status() -> dict:
    """Check battery, CPU load, memory, and disk space on macOS."""
    status = {}
    
    # Battery info
    try:
        res = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True, check=False)
        lines = res.stdout.strip().split("\n")
        if len(lines) > 1:
            status["battery"] = lines[1].strip()
        else:
            status["battery"] = "AC Power / No Battery Info"
    except Exception as e:
        status["battery"] = f"Unavailable ({e})"

    # CPU Load
    try:
        load1, load5, load15 = os.getloadavg()
        cpu_count = os.cpu_count() or 1
        status["cpu_load"] = f"{load1:.2f} (1m), {load5:.2f} (5m), cores: {cpu_count}"
    except Exception as e:
        status["cpu_load"] = f"Unavailable ({e})"

    # Disk Space
    try:
        total, used, free = shutil.disk_usage("/")
        status["disk_free_gb"] = f"{free / (1024**3):.1f} GB free of {total / (1024**3):.1f} GB"
    except Exception as e:
        status["disk_free_gb"] = f"Unavailable ({e})"

    # Time & Date
    status["timestamp"] = datetime.datetime.now().strftime("%A, %B %d, %Y at %I:%M %p")
    return status

def _redact_secrets(text: str) -> str:
    """Mask common API keys, tokens, and private keys before returning tool output to an LLM."""
    if not text:
        return text
    import re as _re
    patterns = [
        (r'-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----', '[REDACTED_PRIVATE_KEY]'),
        (r'\b(AIza[0-9A-Za-z\-_]{20,}|sk-[A-Za-z0-9\-_]{20,}|gsk_[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9\-]{10,})\b', '[REDACTED_TOKEN]'),
        (r'(?i)\b(api_key|secret|password|passwd|token)\s*([=:])\s*\S+', r'\1\2 [REDACTED]'),
    ]
    out = text
    for pat, repl in patterns:
        out = _re.sub(pat, repl, out)
    return out


def get_clipboard_content() -> str:
    """Read the current text from the macOS clipboard (with confirmation if Strict/Cloud and secret redaction)."""
    from config import get_safe_mode
    mode = get_safe_mode()
    is_cloud = _screen_watcher.brain is not None and _screen_watcher.brain.active_provider() != "ollama"
    if mode == "strict" or (mode == "guarded" and is_cloud):
        if not _confirm_risky_action("read macOS clipboard", "Clipboard may contain copied passwords or sensitive data."):
            return "Action cancelled by user: clipboard was not read."
    try:
        res = subprocess.run(["pbpaste"], capture_output=True, text=True, check=False)
        content = res.stdout.strip()
        if not content:
            return "The clipboard is currently empty."
        return _redact_secrets(content)
    except Exception as e:
        return f"Error accessing clipboard: {e}"

def set_clipboard_content(text: str) -> str:
    """Copy text to the macOS clipboard."""
    try:
        subprocess.run(["pbcopy"], input=text, text=True, check=False)
        return "Content copied to clipboard successfully."
    except Exception as e:
        return f"Error setting clipboard: {e}"

def set_volume(level: int) -> str:
    """Set the Mac speaker volume (0 to 100)."""
    try:
        level = max(0, min(100, int(level)))  # already integer-safe; no string interpolation risk
        subprocess.run(["osascript", "-e", f"set volume output volume {level}"], check=False)
        return f"Speaker volume set to {level}%."
    except Exception as e:
        return f"Error setting volume: {e}"

def get_volume() -> str:
    """Get the current Mac speaker volume."""
    try:
        res = subprocess.run(["osascript", "-e", "output volume of (get volume settings)"], capture_output=True, text=True, check=False)
        return f"Current volume is {res.stdout.strip()}%."
    except Exception as e:
        return f"Error reading volume: {e}"

def open_application(app_name: str) -> str:
    """Open an installed macOS application (e.g., 'Safari', 'Spotify', 'Finder', 'Notes')."""
    try:
        res = subprocess.run(["open", "-a", app_name], capture_output=True, text=True, check=False)
        if res.returncode == 0:
            return f"Opened {app_name}."
        return f"Could not open {app_name}: {res.stderr.strip()}"
    except Exception as e:
        return f"Error opening application: {e}"

def get_current_time() -> str:
    """Get the exact local time and date."""
    now = datetime.datetime.now()
    return now.strftime("The current time is %I:%M %p on %A, %B %d, %Y.")

def _get_notes_path() -> str:
    """Return the private notes file path, falling back to workspace if ~ is unavailable."""
    primary = os.path.expanduser("~/Jarvis_Notes.txt")
    try:
        # Test if writable or existing
        if os.path.exists(primary):
            return primary
        with open(primary, "a", encoding="utf-8") as f:
            pass
        return primary
    except Exception:
        fallback = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Jarvis_Notes.txt")
        return fallback

def take_note(note_text: str) -> str:
    """Save a quick note to notes.txt."""
    notes_file = _get_notes_path()
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{timestamp}] {note_text}\n"
    try:
        is_new = not os.path.exists(notes_file)
        with open(notes_file, "a", encoding="utf-8") as f:
            f.write(entry)
        if is_new:
            try:
                os.chmod(notes_file, 0o600)  # Private to user only
            except Exception:
                pass
        return f"Note saved to {notes_file}: '{note_text}'"
    except Exception as e:
        return f"Error saving note: {e}"

def read_notes() -> str:
    """Read saved notes from notes.txt."""
    notes_file = _get_notes_path()
    if not os.path.exists(notes_file):
        return "No notes recorded yet."
    try:
        with open(notes_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
        recent = lines[-5:] if len(lines) > 5 else lines
        return "Recent notes:\n" + "".join(recent).strip()
    except Exception as e:
        return f"Error reading notes: {e}"

_READONLY_CMD_PREFIXES = (
    "ls", "pwd", "whoami", "uname", "date", "uptime", "df", "du", "ps",
    "git status", "git log", "git diff", "which", "echo", "pmset -g",
    "sw_vers", "diskutil list", "python --version", "python3 --version",
)
_READONLY_EXACT_CMDS = frozenset({
    "cat readme", "cat readme.md", "cat changelog", "cat changelog.md",
    "cat license", "cat license.md",
})


def _confirm_risky_action(action_label: str, detail: str) -> bool:
    """
    Show a native macOS confirmation dialog ('Cancel' vs 'Allow', defaulting to Cancel)
    before running risky shell writes/deletes or closing apps.
    Works safely from Terminal, Voice (Cmd+I), or background threads without stdin deadlocks.
    """
    import re as _re
    def _esc(s: str) -> str:
        s = _re.sub(r'[^\x20-\x7E]', ' ', str(s))[:220]
        return s.replace('\\', '\\\\').replace('"', '\\"')

    msg = f"Jarvis wants to {_esc(action_label)}:\\n\\n{_esc(detail)}\\n\\nAllow this action?"
    script = (
        f'display dialog "{msg}" with title "Jarvis Security Check" '
        'buttons {"Cancel", "Allow"} default button "Cancel" cancel button "Cancel" '
        'with icon caution giving up after 20'
    )
    try:
        res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=25)
        return res.returncode == 0 and "button returned:Allow" in res.stdout
    except Exception:
        return False


def _is_readonly_shell_command(command: str) -> bool:
    """Return True only for simple single read-only inspection commands (no pipes/redirects/chaining/env vars)."""
    cmd = command.strip()
    if any(op in cmd for op in (";", "&&", "||", "|", ">", "<", "`", "$(", "$")):
        return False
    cmd_norm = " ".join(cmd.lower().split())
    if cmd_norm in _READONLY_EXACT_CMDS:
        return True
    return any(cmd_norm == p or cmd_norm.startswith(p + " ") for p in _READONLY_CMD_PREFIXES)


def run_shell_command(command: str) -> str:
    """Run a safe terminal command respecting Safe Mode ('strict' disables shell, 'guarded' confirms writes)."""
    from config import get_safe_mode
    if get_safe_mode() == "strict":
        return "Command blocked: Terminal execution is disabled in STRICT Safe Mode. Use '/safe on' or '/safe off' to allow."

    dangerous = [
        "rm -rf /", "rm -rf ~", "rm -rf *", "mkfs", "dd if=", ":(){ :|:& };:",
        "> /dev/sda", "chmod -R 777 /", "id_rsa", "id_ed25519", ".aws/credentials",
        ".bash_history", ".zsh_history", ".jarvis_memory", ".jarvis_secrets", ".env",
        "security find-", "| bash", "| sh",
        "/etc/passwd", "/etc/shadow", "/etc/sudoers", "pkill", "killall",
        "sudo ", "su -", "chown -R", "chmod 777", "nc -l", "ncat", "netcat",
        "curl http", "curl ftp", "wget http", "wget ftp",
    ]
    cmd_lower = command.lower()
    for d in dangerous:
        if d.lower() in cmd_lower:
            return f"Command rejected for security: restricted pattern '{d}' detected."

    if not _is_readonly_shell_command(command):
        if not _confirm_risky_action("run Terminal command", command):
            return f"Action cancelled by user: refused to run '{command}'."

    try:
        res = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=10)
        output = _redact_secrets((res.stdout + res.stderr).strip())
        if not output:
            return f"Command executed successfully with return code {res.returncode}."
        if len(output) > 800:
            output = output[:800] + "... [truncated]"
        return output
    except subprocess.TimeoutExpired:
        return "Command timed out after 10 seconds."
    except Exception as e:
        return f"Error executing command: {e}"

def search_web(query: str, max_results: int = 3) -> str:
    """Search the web for real-time information, answers, and news."""
    try:
        max_results = max(1, min(10, int(max_results)))
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS
        results = list(DDGS().text(query, max_results=max_results))
        if not results:
            return f"No web results found for query: '{query}'"
        formatted = []
        for i, r in enumerate(results, 1):
            title = r.get("title", "No Title")
            snippet = r.get("body", "No Snippet")
            url = r.get("href", "")
            formatted.append(f"[{i}] {title}\nSummary: {snippet}\nURL: {url}")
        return "\n\n".join(formatted)
    except Exception as e:
        return f"Error performing web search for '{query}': {e}"

def fetch_webpage(url: str) -> str:
    """Read and extract the main textual content from any website or URL."""
    try:
        import requests
        from bs4 import BeautifulSoup

        if not url.startswith("http://") and not url.startswith("https://"):
            url = "https://" + url

        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        resp = requests.get(url, headers=headers, timeout=12)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        title = soup.title.string.strip() if soup.title and soup.title.string else url

        # Remove irrelevant elements
        for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "aside", "svg"]):
            tag.decompose()

        text = " ".join(soup.stripped_strings)
        if len(text) > 2500:
            text = text[:2500] + "... [truncated]"

        return f"Page Title: {title}\nURL: {url}\n\nExtracted Content:\n{text}"
    except Exception as e:
        return f"Error reading webpage '{url}': {e}"

def open_in_browser(url: str, section: str = "") -> str:
    """Open a URL or website in the Mac's default web browser, optionally opening a specific section or search."""
    if section:
        return _browser_controller.interactive_website_task(url=url, action_description=section)
    try:
        if not url.startswith("http://") and not url.startswith("https://"):
            url = "https://" + url
        subprocess.run(["open", url], check=False)
        return f"Opened {url} in your default browser."
    except Exception as e:
        return f"Error opening browser for '{url}': {e}"

def play_youtube(query: str, browser: str = "Google Chrome") -> str:
    """Search YouTube for a verified, playable song or video and play it in the user's chosen browser."""
    import urllib.parse

    clean_query = query.strip()
    generic_queries = ["a song", "some song", "song", "music", "some music", "play something", "something"]
    if clean_query.lower() in generic_queries:
        clean_query = "lofi hip hop radio - beats to relax/study to"

    target_url = None
    video_title = clean_query
    other_options = []

    # Use yt-dlp to find verified playable video and alternatives
    try:
        import yt_dlp
        ydl_opts = {
            "quiet": True,
            "extract_flat": True,
            "skip_download": True,
            "no_warnings": True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            res = ydl.extract_info(f"ytsearch3:{clean_query}", download=False)
            if res and res.get("entries"):
                valid_entries = [e for e in res["entries"] if e and e.get("id")]
                if valid_entries:
                    top_entry = valid_entries[0]
                    vid_id = top_entry.get("id")
                    video_title = top_entry.get("title", clean_query)
                    target_url = f"https://www.youtube.com/watch?v={vid_id}"

                    for alt in valid_entries[1:3]:
                        alt_title = alt.get("title", "Alternative version")
                        alt_url = f"https://www.youtube.com/watch?v={alt.get('id')}"
                        other_options.append(f"• {alt_title}")
    except Exception:
        pass

    # Fallback to direct search URL if extractor fails
    if not target_url:
        target_url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(clean_query)

    # Open in user's chosen browser (Chrome, Safari, etc.)
    _browser_controller.open_in_browser(target_url, browser=browser)
    
    reply = f"Now playing the top match in {browser}: '{video_title}'.\nDirect Link: {target_url}"
    if other_options:
        reply += "\n\nOther popular versions found:\n" + "\n".join(other_options)
    return reply

def control_youtube(action: str = "play_pause") -> str:
    """Control active YouTube video in Chrome (play_pause, mute, fullscreen)."""
    action_map = {
        "play_pause": "document.querySelector('video') ? (document.querySelector('video').paused ? document.querySelector('video').play() : document.querySelector('video').pause()) : null",
        "mute": "document.querySelector('video') ? (document.querySelector('video').muted = !document.querySelector('video').muted) : null",
        "fullscreen": "document.querySelector('.ytp-fullscreen-button') ? document.querySelector('.ytp-fullscreen-button').click() : null",
    }
    js = action_map.get(action.lower(), action_map["play_pause"])
    script = f'''
    tell application "Google Chrome"
        if (count of windows) > 0 then
            tell active tab of front window
                execute javascript "{js}"
            end tell
        end if
    end tell
    '''
    try:
        subprocess.run(["osascript", "-e", script], check=False)
        return f"Executed YouTube {action} in Chrome."
    except Exception as e:
        return f"Could not control Chrome: {e}"

def close_application(app_name: str) -> str:
    """Close or quit a running macOS application (e.g. 'Google Chrome', 'Safari', 'Spotify', 'Notes')."""
    import re as _re
    if not app_name or _re.search(r'[;"\'/$`<>|&\\]', app_name):
        return f"Invalid application name: '{app_name}'"
    safe_name = _re.sub(r"[^a-zA-Z0-9 .\-]", "", app_name).strip()
    if not safe_name:
        return f"Invalid application name: '{app_name}'"
    if not _confirm_risky_action("close application", safe_name):
        return f"Action cancelled by user: kept {safe_name} open."
    try:
        script = f'tell application "{safe_name}" to quit'
        res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, check=False)
        if res.returncode == 0:
            return f"Closed {safe_name}."
        # Fallback: pkill using list form (no shell=True), safe
        subprocess.run(["pkill", "-x", safe_name], check=False)
        return f"Closed {safe_name}."
    except Exception as e:
        return f"Error closing {safe_name}: {e}"

def book_bus_redbus(source: str, destination: str, browser: str = "Google Chrome", wait_for_login: bool = False) -> str:
    """Search for buses and book tickets on RedBus in the specified browser (Chrome/Safari), pausing for login if needed without terminating."""
    return _browser_controller.search_redbus(source=source, destination=destination, browser=browser, wait_for_login=wait_for_login)

def browse_and_interact(task: str, url: str = "current", browser: str = "Google Chrome", wait_for_login: bool = False) -> str:
    """Automate actions on any website or on the currently open Chrome tab (pass url='current' to click/scroll/type/read on the active tab)."""
    from config import get_safe_mode
    task_l = task.lower()
    if get_safe_mode() in ("strict", "guarded") and any(k in task_l for k in ("click", "fill", "type", "enter", "submit", "tap", "press", "reply", "send")):
        if not _confirm_risky_action("interact with webpage", f"{url}: {task}"):
            return f"Action cancelled by user: did not perform '{task}' on webpage."
    return _browser_controller.interactive_website_task(url=url, action_description=task, browser=browser, wait_for_login=wait_for_login)

def control_app(app_name: str, action: str, details: str = "") -> str:
    """Control and automate actions in macOS applications (Spotify, Notes, Finder, Chrome/Safari, etc.)."""
    from config import get_safe_mode
    act_l = action.lower().strip()
    if get_safe_mode() in ("strict", "guarded") and act_l in ("type", "keystroke", "shortcut", "press", "key", "close", "quit", "exit"):
        if not _confirm_risky_action(f"perform '{action}' in {app_name}", details or app_name):
            return f"Action cancelled by user: did not execute '{action}' in {app_name}."
    return _app_controller.execute_app_command(app_name=app_name, action=action, details=details)

def split_screen(left_app: str, right_app: str = "Terminal") -> str:
    """Open two applications side-by-side in split screen (e.g. Visual Studio Code on left, Terminal on right)."""
    return _app_controller.split_screen(left_app=left_app, right_app=right_app)

def control_system(setting: str) -> str:
    """Control macOS system settings: 'dark_mode' (toggle dark/light), 'do_not_disturb' (or 'focus'), 'mute', 'unmute', 'lock'."""
    if "lock" in setting.lower() or "sleep" in setting.lower():
        if not _confirm_risky_action("lock / sleep display", setting):
            return "Action cancelled by user: kept screen unlocked."
    return _app_controller.control_system(setting=setting)

def start_ffcs_monitor(portal_url: str, course_code: str, slot: str = None, interval: float = 4.0, auto_add: bool = True) -> str:
    """Start continuous live monitoring on a college FFCS/VTOP course registration page for dropped seats until the user says stop."""
    return _ffcs_monitor.start(portal_url=portal_url, course_code=course_code, slot=slot, interval=interval, auto_add=auto_add)

def stop_ffcs_monitor() -> str:
    """Stop the active live FFCS course monitor."""
    return _ffcs_monitor.stop()

def make_jarvis_live(target: str, condition: str = "keep_alive", interval: float = 5.0, browser: str = "Google Chrome") -> str:
    """Make Jarvis stay live on any website or application until the user says stop."""
    return _live_manager.start_live(target=target, condition=condition, interval=interval, browser=browser)

def stop_live_session() -> str:
    """Stop any active live website or application monitoring session."""
    return _live_manager.stop_live()

def look_at_screen(question: str = "Explain what is on the screen and identify any errors or key details.") -> str:
    """Capture a screenshot of the user's Mac display and analyze it visually using active Cloud/Local AI."""
    from config import get_safe_mode
    is_cloud = _screen_watcher.brain is not None and _screen_watcher.brain.active_provider() != "ollama"
    if is_cloud and get_safe_mode() == "strict":
        if not _confirm_risky_action("send screen capture to Cloud AI", f"Provider: {_screen_watcher.brain.active_provider()}"):
            return "Action cancelled by user: screen capture not sent in Strict Safe Mode."
    from core.live import capture_screen_b64
    b64_img = capture_screen_b64(max_dimension=1024, quality=70)

    if not b64_img:
        return "Unable to capture screen. Please check Screen Recording permissions in System Settings -> Privacy & Security."

    try:
        import re
        if _screen_watcher.brain is not None and _screen_watcher.brain.active_provider() != "ollama":
            data = _screen_watcher.brain._post_chat(
                [{
                    "role": "user",
                    "content": f"The user asked you to inspect their screen: {question}. Provide a clear, concise visual description.",
                    "images": [b64_img],
                }],
                use_tools=False,
                temperature=0.2,
                num_predict=220,
            )
        else:
            import requests
            from config import OLLAMA_BASE_URL, MODEL_NAME
            payload = {
                "model": MODEL_NAME,
                "messages": [{
                    "role": "user",
                    "content": f"The user asked you to inspect their screen: {question}. Provide a clear, concise visual description.",
                    "images": [b64_img],
                }],
                "think": False,
                "stream": False,
                "options": {"num_predict": 180},
            }
            resp = requests.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload, timeout=60)
            resp.raise_for_status()
            data = resp.json()
        analysis = data.get("message", {}).get("content", "I inspected your screen but could not extract a description.")
        clean_analysis = re.sub(r'<think>[\s\S]*?</think>', '', analysis).strip()
        return clean_analysis or analysis
    except Exception as e:
        return f"Error analyzing screen: {e}"

def watch_screen(trigger: str, action: str = "notify", interval: float = 3.0, repeat: bool = False) -> str:
    """
    Keep looking at the user's screen in the background, alert when a trigger condition
    (keyword, error, phrase, or screen change) occurs, and optionally execute follow-up work automatically.
    - trigger: Condition to watch for (e.g. 'Build Succeeded', 'Error 404', 'Download complete', or 'something changes')
    - action: Work or command to execute when triggered (e.g. 'open Finder', 'split screen with VS Code and Terminal', 'notify')
    - interval: Seconds between visual checks (default: 3.0)
    - repeat: Keep watching and alerting every time the condition happens until /stop (default: False)
    """
    return _screen_watcher.start_watch(trigger=trigger, action=action, interval=interval, repeat=repeat)

def stop_screen_watcher() -> str:
    """Stop the active continuous visual screen trigger watcher."""
    return _screen_watcher.stop_watch()

def set_reminder(message: str, duration: str) -> str:
    """Schedule a real timed reminder with spoken alert + macOS Notification Center banner (e.g. duration='5m', '30s', '1h30m')."""
    global _reminder_engine
    if _reminder_engine is None:
        from core.notify import ReminderEngine
        _reminder_engine = ReminderEngine()
    return _reminder_engine.set_reminder(message=message, duration_text=duration)

def reply_message(message: str, app_name: str = "") -> str:
    """Reply to the currently active chat in WhatsApp (Desktop or Chrome Web), Messages, Slack, or Discord."""
    from config import get_safe_mode
    if get_safe_mode() in ("strict", "guarded"):
        target = app_name or "active chat"
        if not _confirm_risky_action(f"send message in {target}", message):
            return f"Action cancelled by user: message '{message}' was not sent."
    return _app_controller.reply_in_active_chat(message=message, app_name=app_name)

# Tool registry mapping tool name to python callable
TOOL_MAP = {
    "get_system_status": get_system_status,
    "get_clipboard_content": get_clipboard_content,
    "set_clipboard_content": set_clipboard_content,
    "set_volume": set_volume,
    "get_volume": get_volume,
    "open_application": open_application,
    "close_application": close_application,
    "get_current_time": get_current_time,
    "take_note": take_note,
    "read_notes": read_notes,
    "set_reminder": set_reminder,
    "reply_message": reply_message,
    "run_shell_command": run_shell_command,
    "search_web": search_web,
    "fetch_webpage": fetch_webpage,
    "open_in_browser": open_in_browser,
    "play_youtube": play_youtube,
    "control_youtube": control_youtube,
    "book_bus_redbus": book_bus_redbus,
    "browse_and_interact": browse_and_interact,
    "control_app": control_app,
    "split_screen": split_screen,
    "control_system": control_system,
    "start_ffcs_monitor": start_ffcs_monitor,
    "stop_ffcs_monitor": stop_ffcs_monitor,
    "make_jarvis_live": make_jarvis_live,
    "stop_live_session": stop_live_session,
    "look_at_screen": look_at_screen,
    "watch_screen": watch_screen,
    "stop_screen_watcher": stop_screen_watcher,
}

# Ollama / OpenAI Tool Definitions
TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "get_system_status",
            "description": "Get current Mac system status including battery percentage, CPU load, free disk space, and timestamp.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_clipboard_content",
            "description": "Read whatever text or code the user currently has copied on their macOS clipboard.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_clipboard_content",
            "description": "Copy text to the macOS clipboard.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "The text to copy to the clipboard"}
                },
                "required": ["text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_volume",
            "description": "Adjust Mac master audio volume (percentage 0 to 100).",
            "parameters": {
                "type": "object",
                "properties": {
                    "level": {"type": "integer", "description": "Volume percentage from 0 to 100"}
                },
                "required": ["level"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_volume",
            "description": "Get current Mac audio output volume.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "open_application",
            "description": "Launch or open a macOS app by name, e.g., 'Safari', 'Spotify', 'Finder', 'Notes', 'Visual Studio Code'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "app_name": {"type": "string", "description": "Name of application to open"}
                },
                "required": ["app_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "Get the current time, day, and date.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "take_note",
            "description": "Save a quick note or reminder for the user.",
            "parameters": {
                "type": "object",
                "properties": {
                    "note_text": {"type": "string", "description": "Content of the note"}
                },
                "required": ["note_text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_notes",
            "description": "Read recent notes saved by the user.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_shell_command",
            "description": "Execute a shell command on macOS (e.g. 'git status', 'ls -la', 'uptime').",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The shell command to execute"}
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "Search the live internet for news, real-time information, documentation, or answers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search keywords or query"},
                    "max_results": {"type": "integer", "description": "Maximum number of search results to return (1-10, default 3)"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_webpage",
            "description": "Fetch, read, and extract the text content from any website or URL to summarize or analyze it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "The full website URL (e.g., 'https://en.wikipedia.org/wiki/Artificial_intelligence')"}
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "open_in_browser",
            "description": "Open a website in the Mac's browser, optionally opening a specific category, section, or search on that site.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "The website URL to open (e.g., 'https://in.puma.com', 'https://amazon.in')"},
                    "section": {"type": "string", "description": "Optional section, category, or search query to open on that site (e.g. 'polo', 'running shoes', 'laptops')"}
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "play_youtube",
            "description": "Search YouTube and immediately play any song, artist, video, or playlist in any browser (Google Chrome, Safari, etc.).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The song name, video title, or artist to play on YouTube"},
                    "browser": {"type": "string", "description": "Target browser (e.g. 'Google Chrome', 'Safari'). Defaults to 'Google Chrome'."}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "book_bus_redbus",
            "description": "Search for bus tickets on RedBus between two cities in the user's browser, pausing without terminating if the user needs to log in.",
            "parameters": {
                "type": "object",
                "properties": {
                    "source": {"type": "string", "description": "Departure city (e.g., 'Bangalore', 'Chennai', 'Hyderabad')"},
                    "destination": {"type": "string", "description": "Destination city (e.g., 'Chennai', 'Mumbai', 'Coimbatore')"},
                    "browser": {"type": "string", "description": "Browser to use ('Google Chrome', 'Safari'). Defaults to 'Google Chrome'."},
                    "wait_for_login": {"type": "boolean", "description": "Whether to pause and wait for the user to log in before proceeding. Defaults to false."}
                },
                "required": ["source", "destination"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browse_and_interact",
            "description": "Automate any website OR interact with the currently open Chrome tab (click buttons/links, scroll, fill forms, read page content). Omit url or pass 'current' to act on the active Chrome tab.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "The exact action, section, or command to perform (e.g. 'click Sign In', 'scroll down', 'type iphone into search', 'open polo section', 'read this page')"},
                    "url": {"type": "string", "description": "Website URL, or 'current' (default) to interact with the already-open active Chrome tab."},
                    "browser": {"type": "string", "description": "Target browser ('Google Chrome'). Defaults to 'Google Chrome'."},
                    "wait_for_login": {"type": "boolean", "description": "Set to true if user needs to log in or enter an OTP first."}
                },
                "required": ["task"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "control_app",
            "description": "Control desktop applications on macOS: Spotify (play, pause, next, previous, play_song, status), Apple Notes (create note, open), Finder (open downloads/desktop/folder, reveal file), or send keystrokes/shortcuts to active apps.",
            "parameters": {
                "type": "object",
                "properties": {
                    "app_name": {"type": "string", "description": "Target application name (e.g., 'Spotify', 'Notes', 'Finder', 'Google Chrome')"},
                    "action": {"type": "string", "description": "Action to perform: 'play', 'pause', 'next', 'previous', 'play_song', 'create', 'open_folder', 'type', 'shortcut', 'focus', 'quit'"},
                    "details": {"type": "string", "description": "Details for the action (e.g. song/artist name, note text 'Title: Content', folder name like 'Downloads', keystroke text, or shortcut like 'cmd+c')"}
                },
                "required": ["app_name", "action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "split_screen",
            "description": "Open and arrange two macOS applications side-by-side in split screen (e.g. VS Code on the left, Terminal on the right).",
            "parameters": {
                "type": "object",
                "properties": {
                    "left_app": {"type": "string", "description": "Application to place on the left half (e.g. 'Visual Studio Code', 'Google Chrome', 'Notes')"},
                    "right_app": {"type": "string", "description": "Application to place on the right half (e.g. 'Terminal', 'Google Chrome', 'Notes'). Defaults to 'Terminal'."}
                },
                "required": ["left_app"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "control_system",
            "description": "Toggle or control macOS system settings: 'dark_mode' (toggle dark/light mode), 'do_not_disturb' (toggle Focus mode), 'mute', 'unmute', 'lock' (lock screen).",
            "parameters": {
                "type": "object",
                "properties": {
                    "setting": {
                        "type": "string",
                        "enum": ["dark_mode", "do_not_disturb", "mute", "unmute", "lock"],
                        "description": "The system setting to toggle or set"
                    }
                },
                "required": ["setting"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "control_youtube",
            "description": "Control playback of the currently active YouTube video in Chrome (play_pause, mute, fullscreen).",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["play_pause", "mute", "fullscreen"],
                        "description": "The playback action to perform"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "close_application",
            "description": "Quit or close a running macOS application (e.g., 'Google Chrome', 'Safari', 'Spotify', 'Notes').",
            "parameters": {
                "type": "object",
                "properties": {
                    "app_name": {"type": "string", "description": "The name of the app to close"}
                },
                "required": ["app_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "start_ffcs_monitor",
            "description": "Start live, continuous monitoring on college FFCS/VTOP portal for dropped course seats. Runs continuously until the user says stop, and automatically alerts or clicks add when a seat opens.",
            "parameters": {
                "type": "object",
                "properties": {
                    "portal_url": {"type": "string", "description": "URL of the FFCS / college portal page"},
                    "course_code": {"type": "string", "description": "Target course code to monitor (e.g. 'CSE1001', 'MAT2001')"},
                    "slot": {"type": "string", "description": "Optional slot or faculty to filter (e.g. 'A1', 'L1+L2')"},
                    "interval": {"type": "number", "description": "Refresh polling interval in seconds. Defaults to 4.0."},
                    "auto_add": {"type": "boolean", "description": "Whether to automatically click add/register the moment a seat opens. Defaults to true."}
                },
                "required": ["portal_url", "course_code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "stop_ffcs_monitor",
            "description": "Stop the live FFCS course monitor.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "make_jarvis_live",
            "description": "Make Jarvis stay live on any website or application until the user says stop. Can monitor for page changes, specific text/keywords, or prevent session timeouts.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "Website URL (e.g. 'https://...') or application name (e.g. 'Spotify', 'Slack')"},
                    "condition": {"type": "string", "description": "'keep_alive' (prevent timeouts), 'change' (alert on change), or 'contains:<keyword>' (alert when text appears). Defaults to 'keep_alive'."},
                    "interval": {"type": "number", "description": "Check/refresh interval in seconds. Defaults to 5.0."},
                    "browser": {"type": "string", "description": "Browser to use ('Google Chrome', 'Safari'). Defaults to 'Google Chrome'."}
                },
                "required": ["target"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "stop_live_session",
            "description": "Stop any active live website or application monitoring session.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "look_at_screen",
            "description": "Capture a screenshot of the user's Mac display and analyze it visually to answer questions, explain code/errors, or summarize windows.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "Specific question or request about what is on screen"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "watch_screen",
            "description": "Keep looking at the user's screen in the background until a trigger point happens (a keyword/phrase appears, an error shows up, or screen content changes), notify the user with a chime and banner, and optionally execute follow-up automated work/actions immediately.",
            "parameters": {
                "type": "object",
                "properties": {
                    "trigger": {
                        "type": "string",
                        "description": "Trigger condition to watch for (e.g. 'something changes', 'Build Succeeded', 'Error 404', 'Download finished', 'verification code')"
                    },
                    "action": {
                        "type": "string",
                        "description": "Follow-up automated work to execute immediately when triggered (e.g. 'open VS Code and Terminal in split screen', 'open Downloads in Finder', 'search error on Google', 'notify'). Defaults to 'notify'."
                    },
                    "interval": {
                        "type": "number",
                        "description": "Seconds between visual screen checks. Defaults to 3.0."
                    },
                    "repeat": {
                        "type": "boolean",
                        "description": "Set true ONLY if user explicitly asks for 'every time' or 'continuously'; otherwise MUST be false."
                    }
                },
                "required": ["trigger"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "stop_screen_watcher",
            "description": "Stop the continuous visual screen trigger watcher.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_reminder",
            "description": "Set a real countdown timer reminder that chimes, shows a macOS banner, and speaks aloud after a duration (e.g. '30s', '5m', '1h30m').",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "What to remind the user about"},
                    "duration": {"type": "string", "description": "Time delay like '30s', '5m', '2h', '1h30m'"}
                },
                "required": ["message", "duration"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "reply_message",
            "description": "Reply to the currently active WhatsApp, Messages, Slack, or Discord chat (works in both WhatsApp Desktop app and Chrome Web).",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "The reply text to type and send (e.g. 'done', 'on my way')"},
                    "app_name": {"type": "string", "description": "Optional app override ('WhatsApp', 'Google Chrome', 'Messages'). Leave empty to auto-detect."}
                },
                "required": ["message"]
            }
        }
    }
]

def execute_tool(name: str, arguments: dict | None = None) -> str:
    """Execute a tool by name and return string representation of result."""
    func = TOOL_MAP.get(name)
    if not func:
        return f"Unknown tool: {name}"
    
    arguments = arguments or {}
    try:
        res = func(**arguments)
        if isinstance(res, (dict, list)):
            return json.dumps(res, indent=2)
        return str(res)
    except Exception as e:
        return f"Tool '{name}' execution error: {e}"
