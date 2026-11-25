"""
Global Push-to-Talk (PTT) Controller for Jarvis.
Listens for Cmd+I (held down) anywhere on macOS to record speech,
and transcribes it immediately upon release.
"""
import time
import threading
import subprocess
import numpy as np
import sounddevice as sd
import speech_recognition as sr
from pynput import keyboard
from rich.console import Console
from config import AUDIO_SAMPLE_RATE

console = Console()

def check_accessibility(prompt=False) -> bool:
    """Check if macOS Accessibility permission is granted to this process."""
    try:
        from ApplicationServices import AXIsProcessTrusted, AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt
        if prompt:
            return AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True})
        return AXIsProcessTrusted()
    except Exception:
        return True

class PushToTalkListener:
    def __init__(self, on_speech_callback=None, on_screen_share_callback=None, sample_rate=AUDIO_SAMPLE_RATE, trigger_key="i", input_device=None):
        self.on_speech_callback = on_speech_callback
        self.on_screen_share_callback = on_screen_share_callback
        self.sample_rate = sample_rate
        self.trigger_key = trigger_key.lower()
        self.recognizer = sr.Recognizer()
        self.input_device = input_device
        
        self.cmd_held = False
        self.key_held = False
        self.shift_held = False
        self.last_shift_l_toggle = 0.0
        self.is_recording = False
        self.audio_frames = []
        self.stream = None
        self.keyboard_listener = None
        self.lock = threading.Lock()

    def play_sound(self, sound_name: str):
        """Play a subtle macOS UI sound."""
        sound_path = f"/System/Library/Sounds/{sound_name}.aiff"
        subprocess.Popen(["afplay", sound_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _audio_callback(self, indata, frames, time_info, status):
        """Sounddevice stream callback collecting audio while held."""
        if self.is_recording:
            self.audio_frames.append(indata.copy())

    def _start_recording(self):
        with self.lock:
            if self.is_recording:
                return
            self.is_recording = True
            self.audio_frames = []

        self.play_sound("Tink")
        console.print(f"\n[bold green]🎙️ [Cmd+{self.trigger_key.upper()} Held] Recording speech... Speak now![/bold green]")

        try:
            from core.voice import create_safe_input_stream
            self.stream, self.actual_sample_rate, dev_name = create_safe_input_stream(
                device=self.input_device,
                sample_rate=self.sample_rate,
                channels=1,
                dtype="int16",
                callback=self._audio_callback
            )
        except Exception as e:
            console.print(f"[red]Microphone stream error: {e}[/red]")
            self.is_recording = False

    def _stop_recording_and_process(self):
        with self.lock:
            if not self.is_recording:
                return
            self.is_recording = False

        if self.stream:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
            self.stream = None

        self.play_sound("Pop")
        console.print("[dim cyan]Processing speech...[/dim cyan]")

        if not self.audio_frames:
            return

        raw_bytes = np.concatenate(self.audio_frames, axis=0).tobytes()
        audio_array = np.frombuffer(raw_bytes, dtype=np.int16)

        # Check for pure zero silence (TCC permission blocked)
        if len(audio_array) > 0 and np.all(audio_array == 0):
            console.print("\n[bold red]⚠️ Microphone Blocked by macOS:[/bold red] [white]Audio captured was 100% silent (pure zeros).[/white]")
            console.print("[yellow]Your terminal or IDE does not have permission to access the microphone.[/yellow]")
            console.print("[white]👉 Opening System Settings -> Privacy & Security -> Microphone. Please toggle this app ON.[/white]\n")
            subprocess.run(["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone"], check=False)
            return

        actual_rate = getattr(self, "actual_sample_rate", self.sample_rate)
        audio_data = sr.AudioData(raw_bytes, actual_rate, 2)

        def _transcribe():
            try:
                text = self.recognizer.recognize_google(audio_data).strip()
                if text:
                    console.print(f"\n[bold white]You (Cmd+{self.trigger_key.upper()} Voice):[/bold white] {text}")
                    if self.on_speech_callback:
                        self.on_speech_callback(text)
                else:
                    console.print("[dim yellow]No clear speech recognized.[/dim yellow]")
            except sr.UnknownValueError:
                console.print("[dim yellow]Speech unintelligible. Try again.[/dim yellow]")
            except Exception as e:
                console.print(f"[red]Speech recognition error: {e}[/red]")

        # Process transcription in worker thread so hotkey loop never blocks
        threading.Thread(target=_transcribe, daemon=True).start()

    def _on_press(self, key):
        # Detect Shift key
        if key in (keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r):
            self.shift_held = True

        # Check for 'L' key for Shift+L Live Screen Sharing toggle
        is_l = False
        try:
            if hasattr(key, "char") and key.char and key.char.lower() == "l":
                is_l = True
            elif hasattr(key, "vk") and key.vk in (37, 0x25):  # macOS vk for 'l'
                is_l = True
        except Exception:
            pass

        if self.shift_held and is_l:
            now = time.time()
            if now - self.last_shift_l_toggle > 0.8:
                self.last_shift_l_toggle = now
                if self.on_screen_share_callback:
                    threading.Thread(target=self.on_screen_share_callback, daemon=True).start()

        # Check if key is trigger ('i' or virtual keycode 34)
        is_trigger = False
        try:
            if hasattr(key, "char") and key.char and key.char.lower() == self.trigger_key:
                is_trigger = True
            elif hasattr(key, "vk") and key.vk in (34, 0x22):  # macOS vk for 'i'
                is_trigger = True
        except Exception:
            pass

        if is_trigger:
            self.key_held = True

        # Detect Cmd key
        if key in (keyboard.Key.cmd, keyboard.Key.cmd_l, keyboard.Key.cmd_r):
            self.cmd_held = True

        # If both Cmd and trigger key are held down, start recording
        if self.cmd_held and self.key_held and not self.is_recording:
            self._start_recording()

    def _on_release(self, key):
        # Detect Shift release
        if key in (keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r):
            self.shift_held = False

        # Check if key released is trigger ('i' or virtual keycode 34)
        is_trigger = False
        try:
            if hasattr(key, "char") and key.char and key.char.lower() == self.trigger_key:
                is_trigger = True
            elif hasattr(key, "vk") and key.vk in (34, 0x22):
                is_trigger = True
        except Exception:
            pass

        if is_trigger:
            self.key_held = False

        # Detect Cmd release
        if key in (keyboard.Key.cmd, keyboard.Key.cmd_l, keyboard.Key.cmd_r):
            self.cmd_held = False

        # If either was released while recording, stop recording and process!
        if self.is_recording and (not self.cmd_held or not self.key_held):
            self._stop_recording_and_process()

    def start(self):
        """Start listening for Cmd+I globally."""
        trusted = check_accessibility(prompt=False)
        if not trusted:
            console.print("\n[bold yellow]⚠️ macOS Security Note:[/bold yellow] [bold white]Accessibility permission is required for global hotkeys (Cmd+I to speak, Shift+L for live screen) outside the terminal.[/bold white]")
            console.print("[dim]To enable: System Settings -> Privacy & Security -> Accessibility -> Toggle Terminal / your IDE ON.[/dim]")
            console.print("[bold green]Tip: Inside the terminal, type 'i' to speak or '/screen' to share screen anytime![/bold green]\n")

        if self.keyboard_listener:
            return
        try:
            self.keyboard_listener = keyboard.Listener(
                on_press=self._on_press,
                on_release=self._on_release
            )
            self.keyboard_listener.daemon = True
            self.keyboard_listener.start()
        except Exception as e:
            console.print(f"[dim yellow]Could not start background key listener: {e}[/dim yellow]")

    def stop(self):
        """Stop global hotkey listener."""
        if self.keyboard_listener:
            self.keyboard_listener.stop()
            self.keyboard_listener = None
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None
