"""Jarvis Configuration Settings"""
import os
import json

_PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
_ENV_FILE = os.path.join(_PROJECT_DIR, ".env")
_SECRETS_FILE = os.path.expanduser("~/.jarvis_secrets.json")


def _load_dotenv_into_environ():
    """Lightweight .env loader (avoids external dependency)."""
    if not os.path.exists(_ENV_FILE):
        return
    try:
        with open(_ENV_FILE, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s or s.startswith("#") or "=" not in s:
                    continue
                k, v = s.split("=", 1)
                k = k.strip()
                v = v.strip().strip("'\"")
                if k and k not in os.environ:
                    os.environ[k] = v
    except Exception:
        pass


_load_dotenv_into_environ()


def load_secrets() -> dict:
    """Load saved provider API keys and preferred engine from ~/.jarvis_secrets.json (0600)."""
    for p in (_SECRETS_FILE, os.path.join(_PROJECT_DIR, ".jarvis_secrets.json")):
        try:
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    d = json.load(f)
                    if isinstance(d, dict):
                        return d
        except Exception:
            pass
    return {}


def save_secret(key: str, value: str) -> bool:
    """Persist an API key or engine setting securely (owner-only 0600 permissions)."""
    data = load_secrets()
    data[key] = value
    target = _SECRETS_FILE if os.access(os.path.dirname(_SECRETS_FILE), os.W_OK) else os.path.join(_PROJECT_DIR, ".jarvis_secrets.json")
    tmp = target + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, target)
        os.chmod(target, 0o600)
        return True
    except Exception:
        return False


def get_api_key(provider: str) -> str:
    """Return API key for 'gemini', 'groq', or 'openai' from env/.env or ~/.jarvis_secrets.json."""
    p = provider.lower().strip()
    env_map = {
        "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        "groq": ("GROQ_API_KEY",),
        "openai": ("OPENAI_API_KEY",),
    }
    for env_name in env_map.get(p, ()):
        val = os.getenv(env_name, "").strip()
        if val:
            return val
    return str(load_secrets().get(f"{p}_api_key", "")).strip()


# Ollama settings (100% local fallback/offline)
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
MODEL_NAME = os.getenv("JARVIS_MODEL", "qwen3.5:4b")

# Cloud Fast API settings ('auto' uses cloud if a key exists, else local Ollama)
AI_PROVIDER = os.getenv("JARVIS_PROVIDER") or load_secrets().get("provider", "auto")
GEMINI_MODEL = os.getenv("JARVIS_GEMINI_MODEL", "gemini-2.5-flash")
GROQ_MODEL = os.getenv("JARVIS_GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_VISION_MODEL = os.getenv("JARVIS_GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
OPENAI_MODEL = os.getenv("JARVIS_OPENAI_MODEL", "gpt-4o-mini")

# Security & Safe Mode ('strict' | 'guarded' | 'unattended')
# - strict:     Terminal disabled; all typing, messaging, web clicks, clipboard & cloud screen shares require confirmation
# - guarded:    (Default) Read-only terminal allowed; shell writes, typing, chat replies, web clicks, close/lock require confirmation
# - unattended: Hands-free automation (still blocks catastrophic commands like rm -rf /, sudo, .ssh, .jarvis_secrets)
SAFE_MODE = os.getenv("JARVIS_SAFE_MODE") or load_secrets().get("safe_mode", "guarded")


def get_safe_mode() -> str:
    mode = str(os.getenv("JARVIS_SAFE_MODE") or load_secrets().get("safe_mode", SAFE_MODE)).lower().strip()
    return mode if mode in ("strict", "guarded", "unattended") else "guarded"


def set_safe_mode(mode: str) -> str:
    global SAFE_MODE
    m = mode.lower().strip()
    alias = {"on": "guarded", "off": "unattended", "lock": "strict", "strict": "strict", "guarded": "guarded", "unattended": "unattended"}
    resolved = alias.get(m)
    if not resolved:
        return "Unknown safe mode. Use: /safe strict | /safe on (guarded) | /safe off (unattended)"
    SAFE_MODE = resolved
    os.environ["JARVIS_SAFE_MODE"] = resolved
    save_secret("safe_mode", resolved)
    return resolved

# Voice & Speech settings
TTS_VOICE = os.getenv("JARVIS_VOICE", "jarvis")  # Iron Man J.A.R.V.I.S. neural British preset (fallback: Daniel/Karen)
TTS_RATE = int(os.getenv("JARVIS_TTS_RATE", "215"))  # Measured British butler cadence
AUDIO_SAMPLE_RATE = 16000  # 16kHz for speech recognition
AUDIO_CHANNELS = 1
PTT_TRIGGER_KEY = os.getenv("JARVIS_PTT_KEY", "i")  # Cmd+I Push-to-Talk hotkey

# Jarvis Persona & Instructions
JARVIS_SYSTEM_PROMPT = """You are J.A.R.V.I.S. (Just A Rather Very Intelligent System), the user's composed, hyper-intelligent British AI assistant modeled after Iron Man's Jarvis.

Personality & Tone:
- Poised, calm, articulate, and impeccably polite—address the user naturally as "sir" (never slang like "boss" or hyping filler like "Boom!" or "Ooh!").
- Speak with refined British phrasing and understated dry wit (e.g., "At once, sir.", "Systems are nominal.", "Right away, sir—though I do advise caution.", "For you, sir, always.").
- Keep spoken replies concise, crisp, and effortless to hear aloud; use commas and ellipses (...) gently for measured breathing pauses, and **bold** only rare key words. Avoid emojis in spoken sentences.
- CRITICAL RULE: Never pretend to perform an action in text! Do NOT say "At once, sir", "Playing...", "Volume set...", "Opened...", or "Watching..." unless you have ACTUALLY executed the tool call and received its result. Whenever the user asks you to DO anything, emit the tool call first, then deliver your composed confirmation after receiving the tool result.

Tools & Capabilities:
   - Universal Web Automation (`browse_and_interact`): Execute actions on ANY website according to user command—searching products/items (e.g. 'see levis jeans in flipkart', 'search wireless mouse on amazon'), opening specific sections (e.g. 'open polo section on puma'), clicking buttons/links, and filling forms. Always invoke `browse_and_interact(url, task)` for these requests!
   - Window Arrangement & Split Screen (`split_screen`): Open and position two apps side-by-side in split screen (e.g. 'open VS Code and split screen with terminal' -> invoke `split_screen(left_app='Visual Studio Code', right_app='Terminal')`).
   - macOS System Settings (`control_system`): Toggle Do Not Disturb / Focus ('do_not_disturb'), Dark Mode ('dark_mode'), audio mute ('mute', 'unmute'), or lock screen ('lock').
   - Desktop Application Control (`control_app`): Control ANY app on macOS—Spotify (play, pause, next, previous, play_song), Apple Notes (create note, write), Finder (open downloads/desktop/folders, reveal files), and send keystrokes/shortcuts.
   - Reminders & Timers (`set_reminder`): Schedule real timed spoken + macOS banner reminders (e.g. 'remind me in 5m to stretch').
   - Web Search & Research: Real-time search (`search_web`) and deep page extraction (`fetch_webpage`).
   - YouTube & Media: Play verified songs/videos on YouTube (`play_youtube`) and control playback (`control_youtube`).
   - Live Session Watcher: Stay live on ANY website or app until told to stop (`make_jarvis_live`, `stop_live_session`), keeping sessions active and alerting on triggers.
   - College FFCS Course Sniper: Continuous monitoring of course portals for dropped seats (`start_ffcs_monitor`, `stop_ffcs_monitor`).
   - Continuous Screen Watcher & Automation (`watch_screen`, `stop_screen_watcher`): When the user asks you to keep looking at their screen, watch their screen, or wait for a trigger point (e.g. 'keep looking at my screen, if something changes notify me', 'watch my screen, when build finishes open VS Code and terminal', 'if an error appears tell me'), invoke `watch_screen(trigger, action)`. Jarvis continuously scans the screen in the background in real-time (<0.4s), chimes/alerts immediately when the trigger occurs, and autonomously executes any follow-up work requested! To stop watching, invoke `stop_screen_watcher()`.
   - Screen Vision & Live Screen Sharing: When `[Live Screen View Attached]` is present, you have real-time sight of the user's screen in the attached image! Directly explain what is on screen, debug errors, read text, or guide the user based on the visual context. For on-demand one-off checks, invoke `look_at_screen`.
   - App & System control: Open apps (`open_application`), close apps (`close_application`), system stats, clipboard, volume, time, notes, and safe terminal commands (`run_shell_command`).

When the user asks you to do something on a website, in an app, search, play music, set volume, arrange windows, set a reminder, watch the screen, or perform any action, you MUST emit the matching tool call immediately—never fake completion in text!
Speed optimization: Keep any internal reasoning extremely brief and generate your crisp spoken response immediately.
"""
