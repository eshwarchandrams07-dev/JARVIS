"""
FFCS Live Course Monitor & Auto-Registrar for Jarvis.
Continuously monitors college course registration portals (e.g. VTOP / FFCS)
for dropped seats and automatically reserves/adds them the instant they open.
"""
import os
import re
import time
import threading
import subprocess
from rich.console import Console

console = Console()

class FFCSMonitor:
    def __init__(self, voice_engine=None):
        self.voice = voice_engine
        self.is_running = False
        self.stop_event = threading.Event()
        self.thread = None
        self.target_course = None
        self.target_slot = None
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

    def speak(self, message: str):
        if self.voice:
            self.voice.speak(message, wait=False)

    def chime_alert(self, course_code: str = ""):
        """Play macOS system alert sounds and send a native banner notification."""
        subprocess.run(["afplay", "/System/Library/Sounds/Glass.aiff"], check=False)
        try:
            from core.notify import notify
            notify("🎓 FFCS Seat Available!", f"Seat opened for {course_code or 'your course'}! Registering now…")
        except Exception:
            pass

    def start(self, portal_url: str, course_code: str, slot: str = None, interval: float = 4.0, auto_add: bool = True):
        """Start the live monitoring loop in a background thread."""
        if self.is_running:
            return "FFCS monitor is already actively running, sir."

        self.target_course = course_code.strip().upper()
        self.target_slot = slot.strip().upper() if slot else None
        self.stop_event.clear()
        self.is_running = True

        self.thread = threading.Thread(
            target=self._monitor_loop,
            args=(portal_url, self.target_course, self.target_slot, interval, auto_add),
            daemon=True
        )
        self.thread.start()

        msg = f"FFCS live monitor activated for course {self.target_course}"
        if self.target_slot:
            msg += f" in slot {self.target_slot}"
        msg += f". Refreshing every {interval}s until you say stop."

        self.speak(msg)
        return msg

    def stop(self) -> str:
        """Stop the live monitoring loop."""
        if not self.is_running:
            return "FFCS monitor is not currently running, sir."

        self.stop_event.set()
        self.is_running = False
        msg = f"FFCS monitoring stopped for {self.target_course}. Systems standing by."
        self.speak(msg)
        console.print(f"\n[bold yellow]🛑 {msg}[/bold yellow]\n")
        return msg

    def _monitor_loop(self, portal_url: str, course_code: str, slot: str, interval: float, auto_add: bool):
        from playwright.sync_api import sync_playwright

        console.print(f"\n[bold cyan]🚀 Launching Chrome for FFCS Monitoring on:[/bold cyan] {portal_url}")
        console.print(f"[bold green]🎯 Target Course:[/bold green] [bold white]{course_code}[/bold white]" + (f" | [bold green]Slot:[/bold green] [bold white]{slot}[/bold white]" if slot else ""))
        console.print("[dim yellow]Note: If you need to log in or solve captcha, please do so in the open Chrome window. The monitor will track the course live.[/dim yellow]")

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

                # Navigate if not already on the portal
                if not page.url.startswith(portal_url):
                    page.goto(portal_url, wait_until="domcontentloaded", timeout=30000)

                attempt = 0
                course_found = False

                while not self.stop_event.is_set():
                    attempt += 1

                    # Look for target course rows in any table or card
                    # Look for course code in page content
                    content = page.content()
                    
                    if course_code in content:
                        # Course code is present on current view
                        # Look for row or container containing course code
                        course_rows = page.query_selector_all(f"tr:has-text('{course_code}'), div:has-text('{course_code}')")
                        
                        for row in course_rows:
                            row_text = row.inner_text()
                            
                            # If specific slot requested, check slot
                            if slot and slot not in row_text.upper():
                                continue

                            # Check for available seats (> 0) or Register / Add button enabled
                            # Common patterns: "Available: X", "Seats: X", positive integers, or enabled register buttons
                            seats_match = re.search(r'(?:seats|available|vacancy|vacant)[\s:]*([0-9]+)', row_text, re.IGNORECASE)
                            has_seats = False
                            
                            if seats_match:
                                seats_count = int(seats_match.group(1))
                                if seats_count > 0:
                                    has_seats = True
                            
                            # Also check if an 'Add' or 'Register' button or radio button is enabled
                            action_btn = row.query_selector("button:has-text('Add'), button:has-text('Register'), input[type='radio'], input[type='checkbox']")
                            if action_btn and action_btn.is_enabled():
                                has_seats = True

                            if has_seats:
                                # SEAT FOUND!
                                alert_msg = f"Seat available for {course_code}" + (f" slot {slot}" if slot else "") + "! Attempting to register immediately!"
                                console.print(f"\n[bold red blink]🚨 SEAT DETECTED! 🚨[/bold red blink] [bold white]{alert_msg}[/bold white]")
                                self.chime_alert(course_code=course_code)
                                self.speak(alert_msg)

                                if auto_add and action_btn:
                                    try:
                                        action_btn.click()
                                        console.print("[bold green]✔ Clicked Add/Register button![/bold green]")
                                        # Look for submit/confirm button if any
                                        time.sleep(0.5)
                                        confirm_btn = page.query_selector("button:has-text('Confirm'), button:has-text('Submit'), input[value*='Confirm']")
                                        if confirm_btn and confirm_btn.is_enabled():
                                            confirm_btn.click()
                                            console.print("[bold green]✔ Clicked Confirm/Submit registration![/bold green]")
                                    except Exception as e:
                                        console.print(f"[red]Error during auto-click: {e}[/red]")

                                success_msg = f"Course {course_code} has been selected! Please review your portal screen to confirm."
                                self.speak(success_msg)
                                console.print(f"[bold green]🎉 {success_msg}[/bold green]\n")
                                
                                # Auto-stop on success
                                self.is_running = False
                                return

                    if attempt % 5 == 0:
                        console.print(f"[dim cyan]● Polling attempt #{attempt}: Monitoring {course_code}... (Press /stop to halt)[/dim cyan]")

                    # Wait before next refresh
                    self.stop_event.wait(interval)
                    if self.stop_event.is_set():
                        break

                    # Refresh course view
                    try:
                        # Try to click a refresh or search button if exists, otherwise reload page
                        refresh_btn = page.query_selector("button:has-text('Refresh'), button:has-text('Search'), a:has-text('Refresh')")
                        if refresh_btn and refresh_btn.is_visible():
                            refresh_btn.click()
                        else:
                            page.reload(wait_until="domcontentloaded", timeout=15000)
                    except Exception:
                        pass

            except Exception as e:
                console.print(f"\n[bold red]FFCS Monitor Encountered Exception:[/bold red] {e}")
            finally:
                self.is_running = False
                console.print("[dim]FFCS browser session closed or stopped.[/dim]")
