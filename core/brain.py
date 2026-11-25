"""Ollama LLM integration with tool calling, conversation memory, and persistence."""
import json
import re
import threading
import requests
from config import OLLAMA_BASE_URL, MODEL_NAME, JARVIS_SYSTEM_PROMPT
from core.tools import TOOL_DEFINITIONS, execute_tool
from core.memory import load_memory, save_memory, clear_memory

# Simple action/status tools whose return string is already a clean user reply on success
_DIRECT_CONFIRM_TOOLS = frozenset({
    "open_application",
    "close_application",
    "set_volume",
    "get_volume",
    "get_current_time",
    "set_clipboard_content",
    "take_note",
    "set_reminder",
    "open_in_browser",
    "control_youtube",
    "split_screen",
    "control_system",
    "start_ffcs_monitor",
    "stop_ffcs_monitor",
    "make_jarvis_live",
    "stop_live_session",
    "watch_screen",
    "stop_screen_watcher",
    "reply_message",
})
_ERROR_MARKERS = ("error", "could not", "failed", "invalid", "rejected", "unable", "unknown", "not found", "timed out")

_APP_ALIASES = {
    "safari": "Safari",
    "chrome": "Google Chrome",
    "google chrome": "Google Chrome",
    "spotify": "Spotify",
    "finder": "Finder",
    "notes": "Notes",
    "apple notes": "Notes",
    "terminal": "Terminal",
    "vscode": "Visual Studio Code",
    "vs code": "Visual Studio Code",
    "visual studio code": "Visual Studio Code",
    "calculator": "Calculator",
    "messages": "Messages",
    "whatsapp": "WhatsApp",
    "mail": "Mail",
    "calendar": "Calendar",
    "settings": "System Settings",
    "system settings": "System Settings",
    "music": "Music",
    "discord": "Discord",
    "slack": "Slack",
}

_NEGATION_RE = re.compile(r"\b(don't|do not|didn't|never|not|shouldn't|wouldn't|how do|how to|why did|can't|couldn't)\b", re.IGNORECASE)
_ACTION_START_RE = re.compile(
    r"^(?:please\s+|jarvis[,\s]+)*(?:open|close|quit|launch|play|set|change|mute|unmute|split|search|find|look up|watch|monitor|remind|take a note|create|write|run|execute|type|click|press|reply|send|turn on|turn off|toggle|lock|maximize)\b",
    re.IGNORECASE,
)
_HALLUCINATION_RE = re.compile(
    r"(?:got it!.*?\b(?:playing|opening|setting|watching|searching)|volume (?:is )?set to|playing [\"'*].*? on youtube|now playing|i['’]?m watching your screen|consider it done|arranged split)",
    re.IGNORECASE,
)


def _try_fast_action(user_input: str) -> tuple[str, dict] | None:
    """
    Match unambiguous single-step commands deterministically in <50ms,
    eliminating 4B model hallucination and LLM latency for common actions.
    """
    t = user_input.strip()
    tl = re.sub(r"^(?:hey\s+|hi\s+|please\s+|jarvis[,\s]+)+", "", t.lower()).strip()
    tl = re.sub(r"[.!]+$", "", tl).strip()

    if not tl or _NEGATION_RE.search(tl):
        return None

    # Ignore compound multi-step phrases ("open X and type Y") so LLM can chain steps
    is_split = tl.startswith("split screen")
    if not is_split and re.search(r"\b(?:and then|then|and)\b", tl):
        return None

    # 1. Play on YouTube: "play <song> on/in youtube"
    m_yt = re.match(r"^play\s+(.+?)\s+(?:on|in)\s+youtube(?:\s+please)?$", tl)
    if m_yt:
        song = m_yt.group(1).strip()
        if song:
            return ("play_youtube", {"query": song})

    # 2. Volume control: "set volume to 90%", "volume 50"
    m_vol = re.match(r"^(?:set\s+)?(?:the\s+)?volume\s+(?:to\s+)?(\d{1,3})\s*%?$", tl)
    if m_vol:
        return ("set_volume", {"level": max(0, min(100, int(m_vol.group(1))))})

    # 3. Mute / unmute
    if tl in ("mute", "mute audio", "mute sound", "mute mac"):
        return ("control_system", {"setting": "mute"})
    if tl in ("unmute", "unmute audio", "unmute sound", "unmute mac"):
        return ("control_system", {"setting": "unmute"})

    # 4. Current time
    if tl in ("what time is it", "whats the time", "what's the time", "current time", "tell me the time", "time"):
        return ("get_current_time", {})

    # 5. Open / close known Mac app
    m_open = re.match(r"^(?:open|launch|start)\s+(?:the\s+)?(.+?)(?:\s+app)?$", tl)
    if m_open and m_open.group(1).strip() in _APP_ALIASES:
        return ("open_application", {"app_name": _APP_ALIASES[m_open.group(1).strip()]})

    m_close = re.match(r"^(?:close|quit|exit)\s+(?:the\s+)?(.+?)(?:\s+app)?$", tl)
    if m_close and m_close.group(1).strip() in _APP_ALIASES:
        return ("close_application", {"app_name": _APP_ALIASES[m_close.group(1).strip()]})

    # 6. Reply to active chat / WhatsApp: "reply with done", "reply my whatsapp message with done"
    m_reply = re.match(
        r"^(?:reply(?:\s+to)?(?:\s+(?:the|my))?(?:\s+(?:whatsapp|instagram|slack|discord|telegram|chat|msg|message|messages))*\s+(?:with|saying)|send\s+(?:a\s+)?reply\s+(?:with|saying)|reply)\s+(.+?)(?:\s+message)?$",
        tl,
    )
    if m_reply:
        reply_txt = m_reply.group(1).strip(" '\"")
        if reply_txt:
            return ("reply_message", {"message": reply_txt})

    return None


class JarvisBrain:
    def __init__(self, base_url: str = OLLAMA_BASE_URL, model: str = MODEL_NAME):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.chat_url = f"{self.base_url}/api/chat"
        self.session = requests.Session()
        self._lock = threading.Lock()
        # Load persisted memory from disk (keeps last 6 turns cleanly with tool_calls)
        self.messages = load_memory(JARVIS_SYSTEM_PROMPT)

    def reset(self):
        """Reset conversation memory (in-memory AND on disk)."""
        with self._lock:
            self.messages = [
                {"role": "system", "content": JARVIS_SYSTEM_PROMPT}
            ]
            clear_memory()

    def _strip_thinking(self, text: str) -> str:
        """Strip <think>...</think> blocks from text."""
        if not text:
            return ""
        return re.sub(r'<think>[\s\S]*?</think>', '', text).strip()

    def _post_chat(self, messages: list[dict], use_tools: bool = True, temperature: float = 0.15, num_predict: int = 180) -> dict:
        payload = {
            "model": self.model,
            "messages": messages,
            "think": False,
            "stream": False,
            "options": {
                "temperature": temperature,
                "top_p": 0.85,
                "num_predict": num_predict,
            },
        }
        if use_tools:
            payload["tools"] = TOOL_DEFINITIONS
        resp = self.session.post(self.chat_url, json=payload, timeout=60)
        resp.raise_for_status()
        return resp.json()

    def chat(self, user_input: str, on_tool_call=None, image_b64: str | None = None) -> str:
        """
        Send user message to Ollama model, handle multi-step tool calling reliably,
        guard against hallucinated text-only actions, and return final assistant response.
        """
        with self._lock:
            # 1. Ultra-fast deterministic path for unambiguous commands (only when no live image Q&A)
            if not image_b64:
                fast = _try_fast_action(user_input)
                if fast:
                    name, args = fast
                    if on_tool_call:
                        on_tool_call(name, args)
                    result = execute_tool(name, args)
                    # Record authentic tool_calls turn so history reinforces real tool use
                    self.messages.append({"role": "user", "content": user_input})
                    self.messages.append({
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [{"function": {"name": name, "arguments": args}}],
                    })
                    self.messages.append({"role": "tool", "content": result})
                    self.messages.append({"role": "assistant", "content": result})
                    save_memory(self.messages)
                    return result

            user_msg = {"role": "user", "content": user_input}
            if image_b64:
                user_msg["images"] = [image_b64]
                user_msg["content"] = f"[Live Screen View Attached] {user_input}"

            self.messages.append(user_msg)
            is_compound = bool(re.search(r"\b(?:and then|then|and)\b", user_input, re.IGNORECASE))

            try:
                data = self._post_chat(self.messages, use_tools=True, temperature=0.15, num_predict=180)
            except requests.exceptions.RequestException as e:
                # Roll back dangling user message on network failure to keep history aligned
                if self.messages and self.messages[-1] is user_msg:
                    self.messages.pop()
                return f"My apologies, sir. I encountered a communication error with the local model: {e}"

            msg = data.get("message", {})
            tool_calls = msg.get("tool_calls")

            # 2. Anti-Hallucination Retry Guard:
            # If the model skipped calling tools on an action request or pretended it ran one, force 1 strict retry.
            if not tool_calls:
                raw_text = self._strip_thinking(msg.get("content", ""))
                looks_action = bool(_ACTION_START_RE.search(user_input.strip())) and not _NEGATION_RE.search(user_input)
                looks_fake = bool(_HALLUCINATION_RE.search(raw_text))
                if (looks_action or looks_fake) and not image_b64:
                    enforce_msgs = self.messages + [{
                        "role": "system",
                        "content": "CORRECTION: Do NOT reply in plain text or claim the task is done. Invoke the matching function tool_call NOW.",
                    }]
                    try:
                        retry_data = self._post_chat(enforce_msgs, use_tools=True, temperature=0.0, num_predict=180)
                        retry_msg = retry_data.get("message", {})
                        if retry_msg.get("tool_calls"):
                            msg = retry_msg
                            tool_calls = retry_msg.get("tool_calls")
                    except Exception:
                        pass

            # 3. Multi-step tool execution loop (up to 4 steps for compound commands)
            if tool_calls:
                result = ""
                max_steps = 4
                for step in range(max_steps):
                    self.messages.append(msg)
                    last_tool_name = ""
                    for call in tool_calls:
                        func_info = call.get("function", {})
                        name = func_info.get("name", "")
                        last_tool_name = name
                        args = func_info.get("arguments", {})
                        if isinstance(args, str):
                            try:
                                args = json.loads(args)
                            except Exception:
                                args = {}

                        if on_tool_call:
                            on_tool_call(name, args)

                        result = execute_tool(name, args)
                        self.messages.append({"role": "tool", "content": result})

                    res_lower = result.lower()
                    has_err = any(err in res_lower for err in _ERROR_MARKERS)

                    # Fast exit on single clean direct-confirmation action (saves 2nd LLM round-trip)
                    if (
                        step == 0
                        and not is_compound
                        and len(tool_calls) == 1
                        and last_tool_name in _DIRECT_CONFIRM_TOOLS
                        and result
                        and not has_err
                    ):
                        final_clean = result
                        break

                    # For compound tasks with steps remaining, steer model to finish any remaining sub-task
                    keep_tools = is_compound and (step < max_steps - 1) and not has_err
                    req_messages = self.messages
                    if keep_tools:
                        req_messages = self.messages + [{
                            "role": "system",
                            "content": f"Check user's full request: '{user_input}'. If another part (like typing, clicking, searching, or a second action) is not done yet, call the next tool NOW. Otherwise answer concisely.",
                        }]
                    try:
                        data2 = self._post_chat(
                            req_messages,
                            use_tools=keep_tools,
                            temperature=0.15 if keep_tools else 0.5,
                            num_predict=140,
                        )
                        msg2 = data2.get("message", {})
                    except Exception as e:
                        final_clean = f"I executed the requested action, sir, but encountered an error summarizing: {e}"
                        break

                    if msg2.get("tool_calls"):
                        msg = msg2
                        tool_calls = msg2["tool_calls"]
                        continue

                    final_clean = self._strip_thinking(msg2.get("content", ""))
                    if not final_clean:
                        final_clean = f"I completed the action, sir. Here is the result:\n{result}"
                    break
                else:
                    final_clean = result or "Completed your requested steps, boss!"

                self.messages.append({"role": "assistant", "content": final_clean})
                if "images" in user_msg:
                    user_msg.pop("images", None)
                save_memory(self.messages)
                return final_clean

            # 4. Direct conversational reply (no tools needed)
            content = msg.get("content", "")
            clean_content = self._strip_thinking(content)
            if not clean_content and content:
                clean_content = content.strip()

            self.messages.append({"role": "assistant", "content": clean_content})
            if "images" in user_msg:
                user_msg.pop("images", None)
            save_memory(self.messages)
            return clean_content
