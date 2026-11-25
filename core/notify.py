"""
macOS Notification Center & Reminder Engine for Jarvis.
Delivers native banner alerts (even when terminal is hidden)
and spoken voice reminders on a timer.
"""
import os
import re
import time
import threading
import subprocess
from rich.console import Console

console = Console()


# ─── macOS native notification ─────────────────────────────────────────────────

def notify(title: str, message: str, sound: bool = True):
    """
    Show a native macOS Notification Center banner instantly.
    Works even when the terminal is behind other windows.
    All user-provided content is escaped before passing to osascript.
    """
    # Sanitize: strip non-printable characters, then escape quotes for AppleScript string safety
    def _esc(s: str) -> str:
        s = re.sub(r'[^\x20-\x7E\u00A0-\uFFFF]', '', str(s))  # remove control chars
        return s.replace('\\', '\\\\').replace('"', '\\"')

    safe_title   = _esc(title)
    safe_message = _esc(message)

    script = f'display notification "{safe_message}" with title "{safe_title}"'
    if sound:
        script += ' sound name "Glass"'
    try:
        subprocess.run(["osascript", "-e", script], check=False,
                       capture_output=True, timeout=5)
    except Exception:
        pass   # Never crash Jarvis over a notification failure


# ─── reminder engine ───────────────────────────────────────────────────────────

class ReminderEngine:
    """Background timer-based reminder: speaks aloud + shows macOS banner."""

    def __init__(self, voice_engine=None):
        self.voice   = voice_engine
        self._timers: list[threading.Timer] = []
        self._lock   = threading.Lock()

    # ── parsing ───────────────────────────────────────────────────────────────

    @staticmethod
    def parse_duration(text: str) -> float | None:
        """
        Parse a human duration string into seconds.
        Examples:
          "30s" / "30 seconds"  → 30.0
          "5m" / "5 minutes"    → 300.0
          "2h" / "2 hours"      → 7200.0
          "1h30m"               → 5400.0
        Returns None if unparseable.
        """
        text = text.strip().lower()
        total = 0.0
        found = False

        patterns = [
            (r"(\d+(?:\.\d+)?)\s*h(?:ours?)?", 3600),
            (r"(\d+(?:\.\d+)?)\s*m(?:in(?:utes?)?)?", 60),
            (r"(\d+(?:\.\d+)?)\s*s(?:ec(?:onds?)?)?", 1),
        ]
        for pattern, multiplier in patterns:
            m = re.search(pattern, text)
            if m:
                total += float(m.group(1)) * multiplier
                found  = True

        return total if found else None

    # ── public API ────────────────────────────────────────────────────────────

    def set_reminder(self, message: str, duration_text: str) -> str:
        """
        Schedule a reminder.
        Args:
            message:       What to remind about.
            duration_text: e.g. "5m", "30 seconds", "1h30m"
        Returns a confirmation string.
        """
        seconds = self.parse_duration(duration_text)
        if seconds is None or seconds <= 0:
            return (
                f"Couldn't parse '{duration_text}' as a duration. "
                "Try something like '5m', '30s', or '1h30m'."
            )

        def _fire():
            alert = f"⏰ Reminder: {message}"
            notify("Jarvis Reminder", message, sound=True)
            console.print(f"\n[bold yellow]{alert}[/bold yellow]\n")
            if self.voice:
                self.voice.speak(f"Hey boss! Reminder: {message}", wait=False)

        t = threading.Timer(seconds, _fire)
        t.daemon = True
        t.start()
        with self._lock:
            self._timers.append(t)

        human = self._human_duration(seconds)
        return f"Reminder set! I'll buzz you in {human}: '{message}'"

    def cancel_all(self):
        """Cancel all pending reminders."""
        with self._lock:
            for t in self._timers:
                t.cancel()
            self._timers.clear()
        return "All pending reminders cancelled."

    @staticmethod
    def _human_duration(seconds: float) -> str:
        """Convert seconds back to human-readable string."""
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        parts = []
        if h: parts.append(f"{h}h")
        if m: parts.append(f"{m}m")
        if s or not parts: parts.append(f"{s}s")
        return " ".join(parts)


# ─── daily briefing ───────────────────────────────────────────────────────────

def build_daily_briefing(voice_engine=None) -> str:
    """
    Compose and optionally speak a morning briefing:
    current time, system health, and recent notes.
    Returns the briefing text.
    """
    import datetime
    from core.tools import get_system_status, read_notes

    now   = datetime.datetime.now()
    tod   = "morning" if now.hour < 12 else ("afternoon" if now.hour < 17 else "evening")
    time_ = now.strftime("%I:%M %p on %A, %B %d")

    status = get_system_status()
    batt   = status.get("battery", "unknown")
    cpu    = status.get("cpu_load", "unknown")
    disk   = status.get("disk_free_gb", "unknown")

    notes  = read_notes()
    notes_line = "No notes on record." if "No notes" in notes else notes

    briefing = (
        f"Good {tod}, boss! It's {time_}. "
        f"Battery: {batt}. CPU load: {cpu}. Disk: {disk}. "
        f"Your recent notes: {notes_line}"
    )
    return briefing
