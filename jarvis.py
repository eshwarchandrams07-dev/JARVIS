#!/usr/bin/env python3
"""
J.A.R.V.I.S. - Just A Rather Very Intelligent System
Voice-enabled personal assistant powered by local Ollama (qwen3.5:4b) and macOS.
"""
import sys
import os
import re
import threading
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.prompt import Prompt

from config import MODEL_NAME, TTS_VOICE, TTS_RATE, PTT_TRIGGER_KEY
from core.brain import JarvisBrain
from core.voice import VoiceEngine
from core.tools import get_system_status
from core.memory import memory_summary, clear_memory
from core.notify import ReminderEngine, build_daily_briefing, notify

console = Console()

BANNER = """
   ╔═══════════════════════════════════════════════════════════╗
   ║     ██╗ █████╗ ██████╗ ██╗   ██╗██╗███████╗               ║
   ║     ██║██╔══██╗██╔══██╗██║   ██║██║██╔════╝               ║
   ║     ██║███████║██████╔╝██║   ██║██║███████╗               ║
   ║██   ██║██╔══██║██╔══██╗╚██╗ ██╔╝██║╚════██║               ║
   ║╚█████╔╝██║  ██║██║  ██║ ╚████╔╝ ██║███████║               ║
   ║ ╚════╝ ╚═╝  ╚═╝╚═╝  ╚═╝  ╚═══╝  ╚═╝╚══════╝               ║
   ║      Just A Rather Very Intelligent System                ║
   ╚═══════════════════════════════════════════════════════════╝
"""

def print_welcome(voice_name=TTS_VOICE, voice_speed=TTS_RATE):
    console.print(f"[bold cyan]{BANNER}[/bold cyan]")
    mem = memory_summary()
    status = (
        f"[bold green]● Model:[/bold green] {MODEL_NAME} (local via Ollama)\n"
        f"[bold green]● Voice:[/bold green] {voice_name} @ {voice_speed} WPM\n"
        f"[bold green]● Memory:[/bold green] {mem}\n"
        f"[bold green]● Mic Trigger:[/bold green] Hold [bold yellow]Cmd+{PTT_TRIGGER_KEY.upper()}[/bold yellow] anywhere on your Mac to speak!\n"
        f"[bold green]● Live Screen:[/bold green] Press [bold yellow]Shift+L[/bold yellow] anywhere to share screen live!\n"
        f"[bold green]● Commands:[/bold green] "
        f"[yellow]/watch[/yellow] [yellow]/screen[/yellow] [yellow]/mode[/yellow] [yellow]/live[/yellow] [yellow]/stop[/yellow] "
        f"[yellow]/remind[/yellow] [yellow]/briefing[/yellow] [yellow]/memory[/yellow] "
        f"[yellow]/voice[/yellow] [yellow]/speed[/yellow] [yellow]/voices[/yellow] "
        f"[yellow]/status[/yellow] [yellow]/clear[/yellow] [yellow]/exit[/yellow]"
    )
    console.print(Panel(status, title="[bold white]System Diagnostic[/bold white]", border_style="cyan"))

def main():
    brain   = JarvisBrain()
    voice   = VoiceEngine()
    reminders = ReminderEngine(voice_engine=voice)

    from core.live import LiveScreenManager, parse_screen_watch_intent
    live_screen = LiveScreenManager(voice_engine=voice)

    from core.tools import _browser_controller, _ffcs_monitor, _live_manager, _app_controller, _screen_watcher
    import core.tools as _tools_mod
    _browser_controller.voice = voice
    _ffcs_monitor.voice       = voice
    _live_manager.voice       = voice
    _app_controller.voice     = voice
    _screen_watcher.voice     = voice
    _screen_watcher.brain     = brain
    _tools_mod._reminder_engine = reminders

    print_welcome(voice.voice, voice.rate)

    # Check microphone permission asynchronously so startup stays instant
    from core.voice import check_microphone_permission
    def _bg_mic_check():
        if check_microphone_permission() == "denied":
            notify(
                "Jarvis: Microphone Blocked",
                "Enable Microphone in System Settings -> Privacy & Security.",
                sound=False,
            )
            console.print(Panel(
                "[bold red]⚠️  MICROPHONE ACCESS IS BLOCKED BY MACOS[/bold red]\n\n"
                "macOS has marked Microphone permission as [bold red]Denied[/bold red] for this terminal/app.\n"
                "Until enabled, voice commands will receive pure silence.\n\n"
                "[bold white]To fix this in 10 seconds:[/bold white]\n"
                "1. Open [bold cyan]System Settings -> Privacy & Security -> Microphone[/bold cyan]\n"
                "2. Turn the toggle [bold green]ON[/bold green] for [bold cyan]Antigravity IDE[/bold cyan], [bold cyan]Terminal[/bold cyan], or [bold cyan]Python[/bold cyan]\n"
                "3. Restart Jarvis, and you're all set!\n\n"
                "[dim yellow](We have opened the System Settings pane for you!)[/dim yellow]",
                title="[bold yellow]Voice Input Notice[/bold yellow]",
                border_style="yellow"
            ))
    threading.Thread(target=_bg_mic_check, daemon=True).start()

    # Boot greeting — mention memory if any turns loaded
    history_turns = len([m for m in brain.messages if m.get("role") == "user"])
    if history_turns > 0:
        greeting = f"Welcome back, boss! I remember our last {history_turns} conversation turn{'s' if history_turns != 1 else ''}. What are we smashing today?"
    else:
        greeting = "Systems online, boss! What fun or mischief are we getting into today?"

    console.print(f"\n[bold cyan]Jarvis:[/bold cyan] {greeting}\n")
    voice.speak(greeting, wait=False)

    mode = "text"

    def on_tool_call(name, args):
        args_str = f" with {args}" if args else ""
        console.print(f"[bold yellow]⚙ Executing tool:[/bold yellow] [bold]{name}[/bold]{args_str}...")

    def on_voice_recognized(user_input):
        if not user_input:
            return
        # Direct screen watch intent check
        intent = parse_screen_watch_intent(user_input, is_screen_live=live_screen.is_live)
        if intent:
            trigger, action, repeat = intent
            msg = _screen_watcher.start_watch(trigger=trigger, action=action, repeat=repeat)
            console.print(f"\n[bold cyan]Jarvis:[/bold cyan] {msg}\n")
            voice.speak(msg, wait=False)
            return

        image_b64 = live_screen.get_screen_frame()
        if image_b64:
            console.print("[dim cyan]📸 [Live Screen] Inspecting your screen to respond...[/dim cyan]")
        with console.status("[bold cyan]Jarvis is thinking...[/bold cyan]", spinner="dots"):
            response = brain.chat(user_input, on_tool_call=on_tool_call, image_b64=image_b64)
        console.print(f"\n[bold cyan]Jarvis:[/bold cyan] {response}\n")
        voice.speak(response, wait=False)

    from core.hotkey import PushToTalkListener
    ptt = PushToTalkListener(
        on_speech_callback=on_voice_recognized,
        on_screen_share_callback=live_screen.toggle,
        trigger_key=PTT_TRIGGER_KEY
    )
    try:
        ptt.start()
    except Exception as e:
        console.print(f"[dim yellow]Notice on Push-to-Talk listener: {e}[/dim yellow]")

    while True:
        try:
            if mode == "voice":
                console.print("\n[dim cyan]Press Enter to speak (or type /mode to switch to text):[/dim cyan] ", end="")
                user_key = input().strip()
                if user_key == "/mode":
                    mode = "text"
                    console.print("[green]Switched to Text Mode.[/green]")
                    continue
                elif user_key in ("/exit", "exit", "quit"):
                    break

                console.print("[bold green]🎙 Listening... (speak now)[/bold green]")
                user_input = voice.listen(timeout=6.0)

                if not user_input:
                    console.print("[dim red]No speech detected. Try again or type /mode.[/dim red]")
                    continue

                console.print(f"\n[bold white]You (Voice):[/bold white] {user_input}")

            else:
                user_input = Prompt.ask("\n[bold white]You[/bold white]").strip()

            if not user_input:
                continue

            # ── Command routing ───────────────────────────────────────────────
            cmd = user_input.lower()

            # Inline mic trigger or device switch
            if cmd.startswith("/mic ") or cmd.startswith("mic "):
                target_arg = user_input.split(maxsplit=1)[1].strip()
                res = voice.set_input_device(target_arg)
                console.print(f"[bold cyan]{res}[/bold cyan]")
                if ptt:
                    ptt.input_device = voice.input_device
                continue
            elif cmd in ("i", "/mic", "mic"):
                console.print("\n[bold green]🎙️ Listening... (speak now)[/bold green]")
                spoken = voice.listen(timeout=7.0)
                if not spoken:
                    console.print("[dim red]No speech detected. Please try again.[/dim red]")
                    continue
                console.print(f"[bold white]You (Voice):[/bold white] {spoken}")
                user_input = spoken
                cmd = user_input.lower()

            # ── Exit ──────────────────────────────────────────────────────────
            if cmd in ("/exit", "exit", "quit", "goodbye"):
                farewell = "Powering down! Catch you later, boss—stay awesome!"
                console.print(f"\n[bold cyan]Jarvis:[/bold cyan] {farewell}\n")
                voice.speak(farewell, wait=True)
                break

            # ── Mode toggle ───────────────────────────────────────────────────
            elif cmd == "/mode":
                mode = "voice" if mode == "text" else "text"
                console.print(f"[green]Switched to [bold]{mode.upper()}[/bold] mode.[/green]")
                continue

            # ── Mute ─────────────────────────────────────────────────────────
            elif cmd == "/mute":
                voice.muted = not voice.muted
                state = "muted" if voice.muted else "unmuted"
                console.print(f"[yellow]Voice speech is now {state}.[/yellow]")
                continue

            # ── Live Screen Sharing Toggle ────────────────────────────────────
            elif cmd in ("/screen", "screen", "live screen", "shift+l", "shift l"):
                live_screen.toggle()
                continue

            # ── Stop all watchers ─────────────────────────────────────────────
            elif cmd in ("/stop", "stop", "stop watching", "stop watching screen"):
                stopped_any = False
                if live_screen.is_live:
                    live_screen.toggle()
                    stopped_any = True
                if _ffcs_monitor.is_running:
                    msg = _ffcs_monitor.stop()
                    console.print(f"[yellow]{msg}[/yellow]")
                    stopped_any = True
                if _live_manager.active_session:
                    msg = _live_manager.stop_live()
                    console.print(f"[yellow]{msg}[/yellow]")
                    stopped_any = True
                if _screen_watcher.active_watch:
                    msg = _screen_watcher.stop_watch()
                    console.print(f"[yellow]{msg}[/yellow]")
                    stopped_any = True
                if not stopped_any:
                    console.print("[dim]No active live monitor or screen share to stop, sir.[/dim]")
                continue

            # ── Screen Trigger Watcher ─────────────────────────────────────────
            elif cmd.startswith("/watch"):
                raw_arg = user_input.split(maxsplit=1)[1].strip() if len(user_input.split()) > 1 else ""
                if not raw_arg:
                    console.print("[yellow]Usage: /watch <trigger> [then <action>][/yellow]\n"
                                  "  e.g.  /watch build succeeded then notify\n"
                                  "  e.g.  /watch something changes then open Finder\n"
                                  "  e.g.  /watch error 404 then split screen with Terminal and Chrome")
                    continue
                if " then " in raw_arg.lower():
                    trig_part, act_part = re.split(r'\s+then\s+', raw_arg, maxsplit=1, flags=re.IGNORECASE)
                else:
                    trig_part, act_part = raw_arg, "notify"
                res = _screen_watcher.start_watch(trigger=trig_part, action=act_part)
                continue

            # ── Live watcher ──────────────────────────────────────────────────
            elif cmd.startswith("/live"):
                parts = user_input.split(maxsplit=2)
                if len(parts) > 1:
                    target    = parts[1]
                    condition = parts[2] if len(parts) > 2 else "keep_alive"
                    msg = _live_manager.start_live(target=target, condition=condition)
                else:
                    console.print("[yellow]Usage: /live <url or app> [contains:<keyword> | change | keep_alive][/yellow]")
                continue

            # ── Reminder ─────────────────────────────────────────────────────
            elif cmd.startswith("/remind"):
                # /remind <duration> <message>  e.g. /remind 5m check FFCS
                parts = user_input.split(maxsplit=2)
                if len(parts) >= 3:
                    duration_text = parts[1]
                    reminder_msg  = parts[2]
                    result = reminders.set_reminder(reminder_msg, duration_text)
                    console.print(f"[bold green]⏰ {result}[/bold green]")
                    voice.speak(result, wait=False)
                elif len(parts) == 2:
                    console.print("[yellow]Usage: /remind <time> <message>  e.g. /remind 5m submit assignment[/yellow]")
                else:
                    console.print("[yellow]Usage: /remind <time> <message>  e.g. /remind 30s check phone[/yellow]")
                continue

            # ── Daily briefing ────────────────────────────────────────────────
            elif cmd in ("/briefing", "/brief", "/morning"):
                with console.status("[bold cyan]Preparing your briefing...[/bold cyan]", spinner="dots"):
                    briefing = build_daily_briefing(voice_engine=voice)
                console.print(Panel(briefing, title="[bold cyan]📋 Daily Briefing[/bold cyan]", border_style="cyan"))
                voice.speak(briefing, wait=False)
                continue

            # ── Memory ───────────────────────────────────────────────────────
            elif cmd in ("/memory", "/mem"):
                summary = memory_summary()
                console.print(Panel(summary, title="[bold cyan]🧠 Persistent Memory[/bold cyan]", border_style="cyan"))
                continue

            # ── Clear (memory + in-session) ───────────────────────────────────
            elif cmd == "/clear":
                brain.reset()
                console.print("[green]Conversation memory cleared (session + disk).[/green]")
                continue

            # ── Voice ─────────────────────────────────────────────────────────
            elif cmd.startswith("/voice"):
                parts = user_input.split(maxsplit=1)
                if len(parts) > 1:
                    new_voice = parts[1].strip()
                    voice.voice = new_voice
                    msg = f"Voice tone updated to {new_voice}."
                    console.print(f"[green]{msg}[/green]")
                    voice.speak(msg, wait=False)
                else:
                    console.print(f"[yellow]Current voice: {voice.voice}. Usage: /voice <name> (e.g. /voice Daniel, /voice Samantha, /voice Rishi)[/yellow]")
                continue

            # ── Speed ─────────────────────────────────────────────────────────
            elif cmd.startswith("/speed"):
                parts = user_input.split(maxsplit=1)
                if len(parts) > 1:
                    try:
                        new_rate = int(parts[1].strip())
                        voice.rate = new_rate
                        msg = f"Voice speed set to {new_rate} words per minute."
                        console.print(f"[green]{msg}[/green]")
                        voice.speak(msg, wait=False)
                    except ValueError:
                        console.print("[red]Please specify speed as a number (e.g., /speed 230).[/red]")
                else:
                    console.print(f"[yellow]Current speed: {voice.rate} WPM. Usage: /speed <number>[/yellow]")
                continue

            # ── Voices list ───────────────────────────────────────────────────
            elif cmd == "/voices":
                console.print(Panel(
                    "• [bold cyan]Samantha[/bold cyan] (en_US) - Modern, crisp, Siri/assistant tone\n"
                    "• [bold cyan]Daniel[/bold cyan]   (en_GB) - Classic British butler Jarvis tone\n"
                    "• [bold cyan]Rishi[/bold cyan]    (en_IN) - Indian English tone\n"
                    "• [bold cyan]Karen[/bold cyan]    (en_AU) - Cheeky Sidekick — current active voice ★\n"
                    "• [bold cyan]Moira[/bold cyan]    (en_IE) - Irish English tone\n"
                    "• [bold cyan]Tessa[/bold cyan]    (en_ZA) - South African English tone\n"
                    "\nChange with: [yellow]/voice <name>[/yellow] (e.g. [bold]/voice Daniel[/bold])",
                    title="Popular English Voices",
                    border_style="cyan"
                ))
                continue

            # ── Status ────────────────────────────────────────────────────────
            elif cmd == "/status":
                stats = get_system_status()
                console.print(Panel(str(stats), title="System Health", border_style="green"))
                continue

            # ── Devices & Microphones ─────────────────────────────────────────
            elif cmd in ("/devices", "/audio", "devices"):
                devs = voice.list_audio_devices()
                lines = []
                for d in devs:
                    tag = ""
                    if d["is_default_input"]:
                        tag += " [green][Default Mic][/green]"
                    if d["is_default_output"]:
                        tag += " [cyan][Default Speaker][/cyan]"
                    if d["inputs"] > 0:
                        lines.append(f"  [bold cyan][{d['index']}][/bold cyan] {d['name']} ({d['inputs']} in){tag}")
                    elif d["outputs"] > 0:
                        lines.append(f"  [dim][{d['index']}][/dim] {d['name']} ({d['outputs']} out){tag}")

                mic_status = check_microphone_permission()
                perm_str = "[green]Authorized[/green]" if mic_status == "authorized" else f"[red]{mic_status.upper()}[/red]"

                active_mic = f"[{voice.input_device}]" if voice.input_device is not None else "System Default"
                content = (
                    f"[bold white]macOS Microphone Permission:[/bold white] {perm_str}\n"
                    f"[bold white]Active Input Device:[/bold white] {active_mic}\n\n"
                    "[bold yellow]Detected Audio Devices:[/bold yellow]\n" + "\n".join(lines) +
                    "\n\n[dim]To switch microphone: [yellow]/mic <index or name>[/yellow] (e.g. /mic 2 or /mic airpods)[/dim]"
                )
                console.print(Panel(content, title="Audio & Microphone Devices", border_style="cyan"))
                continue

            # ── Help ──────────────────────────────────────────────────────────
            elif cmd in ("/help", "help", "?"):
                console.print(Panel(
                    "[bold cyan]Automation Commands:[/bold cyan]\n"
                    "  [yellow]/remind <time> <msg>[/yellow]  — set a timed spoken+banner reminder\n"
                    "    e.g.  /remind 5m check FFCS portal\n"
                    "    e.g.  /remind 1h30m submit lab report\n"
                    "  [yellow]/briefing[/yellow]              — speak today's morning briefing (time, battery, notes)\n"
                    "  [yellow]/memory[/yellow]                — show how many conversation turns are remembered\n"
                    "  [yellow]/clear[/yellow]                 — wipe memory (session + disk)\n\n"
                    "[bold cyan]Live Screen Sharing & Automation:[/bold cyan]\n"
                    "  [yellow]/watch <trigger> [then <action>][/yellow] — watch screen continuously; alert & execute work on trigger\n"
                    "    e.g.  /watch build succeeded then notify\n"
                    "    e.g.  /watch something changes then split screen with VS Code\n"
                    "  Press [bold yellow]Shift+L[/bold yellow] anywhere to share screen live (and Shift+L to stop)\n"
                    "  [yellow]/screen[/yellow]                 — toggle live screen sharing in terminal\n\n"
                    "[bold cyan]Live Monitoring:[/bold cyan]\n"
                    "  [yellow]/live <url> [condition][/yellow] — watch a website until /stop\n"
                    "  [yellow]/stop[/yellow]                  — halt all live watchers\n\n"
                    "[bold cyan]Voice & Audio:[/bold cyan]\n"
                    "  [yellow]/mode[/yellow]   [yellow]/voice <name>[/yellow]   [yellow]/speed <wpm>[/yellow]   [yellow]/voices[/yellow]   [yellow]/mute[/yellow]\n"
                    "  [yellow]/devices[/yellow]          — list all audio input/output devices\n"
                    "  [yellow]/mic <index>[/yellow]      — switch microphone (e.g. /mic 2 for MacBook Mic)\n"
                    "  Hold [bold yellow]Cmd+I[/bold yellow] anywhere to speak • Type [bold yellow]i[/bold yellow]+Enter in terminal\n\n"
                    "[bold cyan]System:[/bold cyan]\n"
                    "  [yellow]/status[/yellow]   [yellow]/exit[/yellow]",
                    title="[bold white]Jarvis Command Reference[/bold white]",
                    border_style="cyan"
                ))
                continue

            # ── Direct Screen Watch Intent ────────────────────────────────────
            intent = parse_screen_watch_intent(user_input, is_screen_live=live_screen.is_live)
            if intent:
                trigger, action, repeat = intent
                msg = _screen_watcher.start_watch(trigger=trigger, action=action, repeat=repeat)
                console.print(f"\n[bold cyan]Jarvis:[/bold cyan] {msg}\n")
                voice.speak(msg, wait=False)
                continue

            # ── Send to Brain ─────────────────────────────────────────────────
            image_b64 = live_screen.get_screen_frame()
            if image_b64:
                console.print("[dim cyan]📸 [Live Screen] Inspecting your screen to respond...[/dim cyan]")
            with console.status("[bold cyan]Jarvis is thinking...[/bold cyan]", spinner="dots"):
                response = brain.chat(user_input, on_tool_call=on_tool_call, image_b64=image_b64)

            console.print(f"\n[bold cyan]Jarvis:[/bold cyan] {response}\n")
            voice.speak(response, wait=False)

        except (KeyboardInterrupt, EOFError):
            console.print("\n[yellow]Interrupted by user. Shutting down.[/yellow]")
            break
        except Exception as e:
            console.print(f"\n[bold red]Error:[/bold red] {e}")

    ptt.stop()

if __name__ == "__main__":
    main()
