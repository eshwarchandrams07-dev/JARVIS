"""
Universal Application & macOS System Controller for Jarvis.
Enables Jarvis to control desktop applications, arrange windows (split screen),
and manage macOS system settings (dark mode, Do Not Disturb, mute, lock screen).
"""
import os
import re
import time
import subprocess
from rich.console import Console

console = Console()

# Mapping common user app names to (App Name, Process Name)
APP_PROCESS_MAP = {
    "code": ("Visual Studio Code", "Code"),
    "vscode": ("Visual Studio Code", "Code"),
    "vs code": ("Visual Studio Code", "Code"),
    "visual studio code": ("Visual Studio Code", "Code"),
    "terminal": ("Terminal", "Terminal"),
    "term": ("Terminal", "Terminal"),
    "chrome": ("Google Chrome", "Google Chrome"),
    "google chrome": ("Google Chrome", "Google Chrome"),
    "safari": ("Safari", "Safari"),
    "notes": ("Notes", "Notes"),
    "apple notes": ("Notes", "Notes"),
    "spotify": ("Spotify", "Spotify"),
    "finder": ("Finder", "Finder"),
    "slack": ("Slack", "Slack"),
    "discord": ("Discord", "Discord"),
}

class AppController:
    def __init__(self, voice_engine=None):
        self.voice = voice_engine

    def speak(self, text: str):
        if self.voice:
            self.voice.speak(text, wait=False)

    def _run_osascript(self, script: str) -> tuple[int, str, str]:
        """Safely execute an AppleScript snippet."""
        try:
            res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=8)
            return res.returncode, res.stdout.strip(), res.stderr.strip()
        except subprocess.TimeoutExpired:
            return -1, "", "AppleScript command timed out."
        except Exception as e:
            return -1, "", str(e)

    def _get_screen_dimensions(self) -> tuple[int, int]:
        """Get the main screen width and height using Cocoa NSScreen."""
        try:
            from Cocoa import NSScreen
            frame = NSScreen.mainScreen().frame()
            return int(frame.size.width), int(frame.size.height)
        except Exception:
            return 1440, 900  # standard fallback

    def split_screen(self, left_app: str, right_app: str = "Terminal") -> str:
        """
        Open two applications and position them side-by-side in split screen on macOS.
        Example: split_screen('Visual Studio Code', 'Terminal')
        """
        left_clean = left_app.lower().strip()
        right_clean = right_app.lower().strip()

        left_name, left_proc = APP_PROCESS_MAP.get(left_clean, (left_app, left_app))
        right_name, right_proc = APP_PROCESS_MAP.get(right_clean, (right_app, right_app))

        console.print(f"[bold cyan]🪟 Arranging Split Screen:[/bold cyan] {left_name} (Left) | {right_name} (Right)")

        # 1. Launch / activate both applications
        subprocess.run(["open", "-a", left_name], check=False)
        subprocess.run(["open", "-a", right_name], check=False)
        time.sleep(0.8)

        # 2. Get screen dimensions
        screen_w, screen_h = self._get_screen_dimensions()
        half_w = screen_w // 2

        # 3. Position left window {0, 0, half_w, screen_h} and right window {half_w, 0, half_w, screen_h}
        script = f'''
        tell application "System Events"
            try
                tell process "{left_proc}"
                    set position of window 1 to {{0, 0}}
                    set size of window 1 to {{{half_w}, {screen_h}}}
                end tell
            end try
            try
                tell process "{right_proc}"
                    set position of window 1 to {{{half_w}, 0}}
                    set size of window 1 to {{{half_w}, {screen_h}}}
                end tell
            end try
        end tell
        '''
        self._run_osascript(script)

        # Activate both so they are frontmost
        subprocess.run(["open", "-a", left_name], check=False)
        subprocess.run(["open", "-a", right_name], check=False)

        msg = f"Arranged split screen with {left_name} on the left and {right_name} on the right!"
        self.speak(msg)
        return msg

    def maximize_window(self, app_name: str) -> str:
        """Maximize the front window of an application to fill the screen."""
        clean = app_name.lower().strip()
        name, proc = APP_PROCESS_MAP.get(clean, (app_name, app_name))
        screen_w, screen_h = self._get_screen_dimensions()

        subprocess.run(["open", "-a", name], check=False)
        time.sleep(0.4)

        script = f'''
        tell application "System Events"
            try
                tell process "{proc}"
                    set position of window 1 to {{0, 0}}
                    set size of window 1 to {{{screen_w}, {screen_h}}}
                end tell
            end try
        end tell
        '''
        self._run_osascript(script)
        return f"Maximized {name} window to fill the screen."

    def control_system(self, setting: str) -> str:
        """
        Toggle or adjust macOS system features:
        - dark_mode: Toggles Dark Mode on/off
        - do_not_disturb / focus: Toggles Focus / Do Not Disturb
        - mute: Toggles audio mute
        - lock / sleep: Locks screen or puts display to sleep
        """
        setting_lower = setting.lower().strip()

        if "dark" in setting_lower or "appearance" in setting_lower:
            script = 'tell application "System Events" to tell appearance preferences to set dark mode to not dark mode'
            code, _, err = self._run_osascript(script)
            if code == 0:
                # Check current state
                _, out, _ = self._run_osascript('tell application "System Events" to tell appearance preferences to get dark mode')
                mode = "Dark Mode" if "true" in out.lower() else "Light Mode"
                msg = f"Switched Mac appearance to {mode}."
                self.speak(msg)
                return msg
            return f"Could not toggle Dark Mode: {err}"

        elif "disturb" in setting_lower or "focus" in setting_lower or "dnd" in setting_lower:
            # Toggle Focus / Do Not Disturb on modern macOS
            # Uses Shortcuts CLI or NotificationCenter shortcut if available, otherwise AppleScript
            script = '''
            tell application "System Events"
                try
                    tell process "ControlCenter"
                        click menu bar item "Focus" of menu bar 1
                    end tell
                    return "Toggled Focus mode via Control Center"
                on error
                    try
                        tell process "ControlCenter"
                            click menu bar item "Control Center" of menu bar 1
                        end tell
                    end try
                end try
            end tell
            '''
            code, out, _ = self._run_osascript(script)
            msg = "Toggled Do Not Disturb / Focus mode."
            self.speak(msg)
            return msg

        elif "mute" in setting_lower:
            script = 'set volume with output muted'
            self._run_osascript(script)
            return "Muted Mac audio."

        elif "unmute" in setting_lower:
            script = 'set volume without output muted'
            self._run_osascript(script)
            return "Unmuted Mac audio."

        elif "lock" in setting_lower or "sleep" in setting_lower:
            subprocess.run(["pmset", "displaysleepnow"], check=False)
            return "Display put to sleep / screen locked."

        return f"Unknown system setting: {setting}"

    def control_spotify(self, action: str, query: str = "") -> str:
        """
        Control Spotify playback, search, tracks, and status.
        Actions: play, pause, play_pause, next, previous, play_song, status, volume
        """
        action = action.lower().strip()

        if action in ("play", "pause", "play_pause", "toggle"):
            script = 'tell application "Spotify" to playpause'
            self._run_osascript(script)
            return "Toggled Spotify playback."

        elif action in ("next", "skip"):
            script = 'tell application "Spotify" to next track'
            self._run_osascript(script)
            return "Skipped to next track on Spotify."

        elif action in ("previous", "prev", "back"):
            script = 'tell application "Spotify" to previous track'
            self._run_osascript(script)
            return "Returned to previous track on Spotify."

        elif action in ("play_song", "play_track", "search"):
            if not query:
                return "Please specify what song or artist you'd like to play on Spotify."
            clean_query = re.sub(r'[^a-zA-Z0-9 ]', '', query).strip().replace(" ", "%20")
            uri = f"spotify:search:{clean_query}"
            subprocess.run(["open", uri], check=False)
            script = f'''
            tell application "Spotify"
                activate
                delay 0.5
                playpause
            end tell
            '''
            self._run_osascript(script)
            return f"Opened Spotify search for '{query}' and started playback."

        elif action in ("status", "current", "now_playing"):
            script = '''
            if application "Spotify" is running then
                tell application "Spotify"
                    set trackName to name of current track
                    set artistName to artist of current track
                    set playerState to player state as string
                    return playerState & ": " & trackName & " by " & artistName
                end tell
            else
                return "Spotify is not currently running"
            end if
            '''
            code, out, _ = self._run_osascript(script)
            return out if out else "Could not retrieve Spotify status."

        elif action == "volume":
            try:
                vol = int(re.sub(r'[^0-9]', '', query))
                vol = max(0, min(100, vol))
                script = f'tell application "Spotify" to set sound volume to {vol}'
                self._run_osascript(script)
                return f"Set Spotify volume to {vol}%."
            except Exception:
                return "Please specify a volume percentage between 0 and 100."

        return f"Unknown Spotify action: {action}"

    def control_notes(self, action: str, title: str = "", content: str = "") -> str:
        """Create or manage notes in Apple Notes."""
        action = action.lower().strip()
        if action in ("create", "new", "add", "write"):
            # Ensure Notes is open
            subprocess.run(["open", "-a", "Notes"], check=False)
            time.sleep(0.5)

            note_title = title or "Note from Jarvis"
            note_content = content or ""
            html_body = f"<div><b>{note_title}</b></div><div>{note_content}</div>"
            safe_body = html_body.replace('\\', '\\\\').replace('"', '\\"')

            script = f'''
            tell application "Notes"
                tell account 1
                    make new note with properties {{body:"{safe_body}"}}
                end tell
            end tell
            '''
            code, out, err = self._run_osascript(script)
            if code == 0:
                msg = f"Created new note '{note_title}' in Apple Notes!"
                self.speak(msg)
                return msg
            else:
                # Fallback to local Jarvis Notes
                from core.tools import take_note
                take_note(f"{note_title}: {note_content}")
                return f"Saved note to ~/Jarvis_Notes.txt: '{note_title}: {note_content}'"

        elif action in ("open", "show"):
            subprocess.run(["open", "-a", "Notes"], check=False)
            return "Opened Apple Notes."

        return f"Unknown Notes action: {action}"

    def control_finder(self, action: str, target: str = "") -> str:
        """Control Finder to open common folders or reveal files."""
        action = action.lower().strip()
        folder_map = {
            "downloads": "~/Downloads",
            "download": "~/Downloads",
            "desktop": "~/Desktop",
            "documents": "~/Documents",
            "document": "~/Documents",
            "home": "~",
            "applications": "/Applications",
            "apps": "/Applications",
            "trash": "~/.Trash",
        }
        folder_path = folder_map.get(target.lower().strip(), target)
        expanded_path = os.path.expanduser(folder_path)

        if action in ("open", "open_folder", "view"):
            if os.path.exists(expanded_path):
                subprocess.run(["open", expanded_path], check=False)
                return f"Opened {target.title() or folder_path} in Finder."
            subprocess.run(["open", "-a", "Finder"], check=False)
            return "Opened Finder."

        elif action in ("reveal", "show_file"):
            if os.path.exists(expanded_path):
                subprocess.run(["open", "-R", expanded_path], check=False)
                return f"Revealed {target} in Finder."
            return f"Path does not exist: {target}"

        return f"Unknown Finder action: {action}"

    @staticmethod
    def _sanitize_app(app_name: str) -> str:
        return re.sub(r"[^a-zA-Z0-9 .\-]", "", app_name).strip()

    def send_keystroke(self, text: str, app_name: str = "") -> str:
        """Type text into the frontmost or specified application window (uses paste for multiline/long text)."""
        safe_app = self._sanitize_app(app_name) if app_name else ""
        if safe_app:
            subprocess.run(["open", "-a", safe_app], check=False)
            time.sleep(0.35)

        # For long or multiline text, paste via clipboard (faster and preserves newlines/special chars)
        if len(text) > 25 or "\n" in text:
            try:
                subprocess.run(["pbcopy"], input=text, text=True, check=True)
                script = 'tell application "System Events" to keystroke "v" using {command down}'
                code, _, err = self._run_osascript(script)
                if code == 0:
                    target_str = f" into {safe_app}" if safe_app else ""
                    return f"Typed text{target_str}."
            except Exception:
                pass

        safe_text = text.replace('\\', '\\\\').replace('"', '\\"')
        script = f'tell application "System Events" to keystroke "{safe_text}"'
        code, _, err = self._run_osascript(script)
        if code == 0:
            target_str = f" into {safe_app}" if safe_app else ""
            return f"Typed '{text}'{target_str}."
        return f"Could not type keystroke: {err}"

    def press_shortcut(self, key_combination: str, app_name: str = "") -> str:
        """
        Press a keyboard shortcut in macOS (e.g. 'cmd+c', 'cmd+v', 'cmd+t', 'cmd+w', 'enter', 'space').
        """
        safe_app = self._sanitize_app(app_name) if app_name else ""
        combo = key_combination.lower().strip()
        modifiers = []
        if "cmd" in combo or "command" in combo:
            modifiers.append("command down")
        if "shift" in combo:
            modifiers.append("shift down")
        if "opt" in combo or "option" in combo or "alt" in combo:
            modifiers.append("option down")
        if "ctrl" in combo or "control" in combo:
            modifiers.append("control down")

        mod_str = f" using {{{', '.join(modifiers)}}}" if modifiers else ""

        base_key = combo.split("+")[-1].strip()
        special_keys = {
            "enter": "key code 36",
            "return": "key code 36",
            "tab": "key code 48",
            "space": "key code 49",
            "escape": "key code 53",
            "esc": "key code 53",
            "backspace": "key code 51",
            "delete": "key code 51",
            "up": "key code 126",
            "down": "key code 125",
            "left": "key code 123",
            "right": "key code 124",
        }

        if base_key in special_keys:
            key_cmd = f"{special_keys[base_key]}{mod_str}"
        else:
            safe_key = re.sub(r'[^a-zA-Z0-9]', '', base_key)[:1]
            if not safe_key:
                return f"Invalid shortcut key: '{key_combination}'"
            key_cmd = f'keystroke "{safe_key}"{mod_str}'

        if safe_app:
            script = f'''
            tell application "{safe_app}" to activate
            delay 0.15
            tell application "System Events"
                {key_cmd}
            end tell
            '''
        else:
            script = f'''
            tell application "System Events"
                {key_cmd}
            end tell
            '''

        code, _, err = self._run_osascript(script)
        if code == 0:
            target_str = f" in {safe_app}" if safe_app else ""
            return f"Pressed shortcut '{key_combination}'{target_str}."
        return f"Could not execute shortcut: {err}"

    def _detect_chat_target(self) -> str:
        """Detect the active chat target (WhatsApp Desktop, Chrome WhatsApp/chat tab, Messages, Slack, Discord)."""
        # 1. Check Google Chrome active tab URL first (works even without Apple Events JS enabled)
        _, chrome_url, _ = self._run_osascript(
            'tell application "System Events"\n'
            '  if (name of processes) contains "Google Chrome" then\n'
            '    tell application "Google Chrome" to if (count of windows) > 0 then return URL of active tab of front window\n'
            '  end if\n'
            'end tell'
        )
        cu = chrome_url.lower()
        if any(site in cu for site in ("whatsapp", "instagram", "discord", "slack", "telegram", "messages", "mail")):
            return "Google Chrome"

        # 2. Check running native messaging apps
        _, proc_out, _ = self._run_osascript('tell application "System Events" to get name of every process whose visible is true')
        procs = [p.strip() for p in proc_out.split(",") if p.strip()]
        for cand in ("WhatsApp", "Messages", "Slack", "Discord", "Telegram", "Google Chrome", "Safari"):
            if cand in procs:
                return cand
        return "WhatsApp"

    def reply_in_active_chat(self, message: str, app_name: str = "") -> str:
        """
        Type and send a reply in WhatsApp (Desktop or Chrome Web), Messages, Slack, or Discord.
        Works via Chrome JS if enabled, and cleanly falls back to macOS System Events paste + Enter.
        """
        msg = (message or "").strip()
        if not msg:
            return "Please specify the reply message text."

        target = self._sanitize_app(app_name) if app_name else self._detect_chat_target()

        # Fast Chrome JS path if targeting Google Chrome (e.g. web.whatsapp.com)
        if target == "Google Chrome":
            import json as _json
            js = f"""
            (() => {{
                const text = {_json.dumps(msg)};
                const box = document.querySelector('footer div[contenteditable="true"], div[contenteditable="true"][data-tab="10"], [role="textbox"][contenteditable="true"], textarea');
                if (!box) return '__NO_BOX__';
                box.focus();
                document.execCommand('insertText', false, text);
                return '__TYPED__';
            }})()
            """
            escaped_js = _json.dumps(js)
            script = (
                'tell application "Google Chrome"\n'
                '  activate\n'
                '  tell active tab of front window\n'
                f'    return execute javascript {escaped_js}\n'
                '  end tell\n'
                'end tell'
            )
            code, out, _ = self._run_osascript(script)
            if code == 0 and out == "__TYPED__":
                time.sleep(0.15)
                self._run_osascript('tell application "System Events" to key code 36')
                return f"Replied '{msg}' in {target}."

        # Native macOS app & fallback path (works for WhatsApp.app AND web.whatsapp.com without JS Apple Events!)
        subprocess.run(["open", "-a", target], check=False)
        time.sleep(0.35)

        # If WhatsApp Desktop is open, try focusing its compose text box via Accessibility if needed
        if target.lower() == "whatsapp":
            self._run_osascript(
                'tell application "System Events"\n'
                '  tell process "WhatsApp"\n'
                '    try\n'
                '      set focused of last text area of window 1 to true\n'
                '    end try\n'
                '  end tell\n'
                'end tell'
            )

        try:
            subprocess.run(["pbcopy"], input=msg, text=True, check=True)
            send_script = (
                'tell application "System Events"\n'
                '  keystroke "v" using {command down}\n'
                '  delay 0.15\n'
                '  key code 36\n'
                'end tell'
            )
            code, _, err = self._run_osascript(send_script)
            if code == 0:
                return f"Sent reply '{msg}' in {target}."
            return f"Could not send reply in {target}: {err}"
        except Exception as e:
            return f"Could not reply in {target}: {e}"

    def execute_app_command(self, app_name: str, action: str, details: str = "") -> str:
        """
        Main routing function for application automation across any app on macOS.
        """
        app_lower = app_name.lower().strip()
        action_lower = action.lower().strip()

        # Split screen request
        if action_lower in ("split_screen", "split", "tile", "side_by_side"):
            other_app = details or "Terminal"
            return self.split_screen(left_app=app_name, right_app=other_app)

        if action_lower in ("maximize", "fullscreen"):
            return self.maximize_window(app_name=app_name)

        if "spotify" in app_lower or "music" in app_lower:
            return self.control_spotify(action, query=details)

        elif "note" in app_lower:
            parts = details.split(":", 1) if ":" in details else (details, "")
            title = parts[0].strip()
            content = parts[1].strip() if len(parts) > 1 else ""
            return self.control_notes(action, title=title, content=content)

        elif "finder" in app_lower:
            return self.control_finder(action, target=details)

        elif action in ("type", "keystroke"):
            return self.send_keystroke(details, app_name=app_name)

        elif action in ("shortcut", "press", "key"):
            return self.press_shortcut(details, app_name=app_name)

        elif action in ("open", "launch", "activate", "focus"):
            res = subprocess.run(["open", "-a", app_name], capture_output=True, text=True, check=False)
            if res.returncode == 0:
                return f"Opened and brought {app_name} to the front."
            return f"Could not open {app_name}: {res.stderr.strip()}"

        elif action in ("close", "quit", "exit"):
            from core.tools import close_application
            return close_application(app_name)

        else:
            subprocess.run(["open", "-a", app_name], check=False)
            if details:
                return self.send_keystroke(details, app_name=app_name)
            return f"Activated {app_name}."
