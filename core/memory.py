"""
Persistent Conversation Memory for Jarvis.
Saves and restores the last N conversation turns across restarts
so Jarvis always remembers your previous context.
"""
import os
import json
import datetime

_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_HOME_FILE   = os.path.expanduser("~/.jarvis_memory.json")
_LOCAL_FILE  = os.path.join(_PROJECT_DIR, ".jarvis_memory.json")
MAX_TURNS         = 30   # Keep last 30 turns on disk
MAX_CONTEXT_TURNS = 6    # Inject last 6 turns into active LLM context (fast + high tool accuracy)


def _get_memory_file() -> str:
    """Return the best available memory file path (home preferred, project fallback)."""
    # Try home dir first
    try:
        parent = os.path.dirname(_HOME_FILE)
        if os.access(parent, os.W_OK):
            return _HOME_FILE
    except Exception:
        pass
    return _LOCAL_FILE


MEMORY_FILE = _get_memory_file()


# ─── private helpers ───────────────────────────────────────────────────────────

def _load_raw() -> dict:
    """Load raw memory dict from disk; return empty structure on any error."""
    for path in (_HOME_FILE, _LOCAL_FILE):
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        return data
        except Exception:
            pass
    return {"messages": [], "last_saved": None}


def _save_raw(data: dict):
    """Atomically write memory dict to disk with owner-only permissions."""
    target = _get_memory_file()
    tmp = target + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, target)
        try:
            os.chmod(target, 0o600)
        except Exception:
            pass
    except Exception:
        pass


# ─── public API ────────────────────────────────────────────────────────────────

def _strip_live_tag(text: str) -> str:
    return text.replace("[Live Screen View Attached] ", "").replace("[Live Screen View Attached]", "").strip()


def _group_turns(messages: list[dict]) -> list[list[dict]]:
    """
    Group raw messages into cohesive turns starting strictly with a 'user' message.
    Drops any leading orphaned 'assistant' or 'tool' messages and prevents invalid role order.
    """
    turns: list[list[dict]] = []
    current: list[dict] = []
    for m in messages:
        role = m.get("role")
        if role == "user":
            content = m.get("content", "")
            if isinstance(content, str):
                clean_text = _strip_live_tag(content)
                if clean_text:
                    # Only close previous turn if it has at least one assistant reply
                    if current and any(x.get("role") == "assistant" for x in current):
                        turns.append(current)
                    current = [{"role": "user", "content": clean_text}]
        elif role == "assistant" and current:
            tool_calls = m.get("tool_calls")
            content = m.get("content", "")
            entry: dict = {"role": "assistant", "content": content.strip() if isinstance(content, str) else ""}
            if tool_calls and isinstance(tool_calls, list):
                entry["tool_calls"] = tool_calls
                current.append(entry)
            elif entry["content"]:
                current.append(entry)
        elif role == "tool" and current and any("tool_calls" in x for x in current):
            content = str(m.get("content", ""))
            if len(content) > 300:
                content = content[:300] + "... [truncated]"
            current.append({"role": "tool", "content": content})

    if current and any(x.get("role") == "assistant" for x in current):
        turns.append(current)
    return turns


def load_memory(system_prompt: str) -> list[dict]:
    """
    Return a clean messages list ready to inject into JarvisBrain.
    Always starts with system prompt, then appends recent cohesive user->assistant turns
    (including genuine tool_calls examples so the model never forgets tool calling).
    """
    data   = _load_raw()
    stored = data.get("messages", [])
    turns  = _group_turns(stored)
    recent = turns[-MAX_CONTEXT_TURNS:]
    history = [msg for turn in recent for msg in turn]
    return [{"role": "system", "content": system_prompt}] + history


def save_memory(messages: list[dict]):
    """Persist cohesive conversation turns cleanly to disk (preserving tool_calls context)."""
    turns = _group_turns([m for m in messages if m.get("role") != "system"])
    if len(turns) > MAX_TURNS:
        turns = turns[-MAX_TURNS:]
    clean_to_save = [msg for turn in turns for msg in turn]
    _save_raw({
        "messages":   clean_to_save,
        "last_saved": datetime.datetime.now().isoformat(),
    })


def clear_memory():
    """Wipe persisted memory from disk."""
    for path in (_HOME_FILE, _LOCAL_FILE):
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass
    return "Memory wiped. Fresh start, boss!"


def memory_summary() -> str:
    """Return a one-line human-readable summary of stored memory."""
    data  = _load_raw()
    turns = len([m for m in data.get("messages", []) if m.get("role") == "user"])
    saved = data.get("last_saved") or "never"
    return f"{turns} conversation turn(s) remembered | last saved: {saved}"

