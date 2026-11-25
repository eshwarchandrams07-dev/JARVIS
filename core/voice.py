"""Voice engine for Jarvis: Speech-to-Text and Text-to-Speech on macOS."""
import os
import re
import time
import subprocess
import threading
import numpy as np
import sounddevice as sd
import speech_recognition as sr
from rich.console import Console
from config import TTS_VOICE, TTS_RATE, AUDIO_SAMPLE_RATE

console = Console()

def check_microphone_permission() -> str:
    """
    Check macOS AVCaptureDevice microphone authorization status via swift.
    Returns: 'authorized', 'denied', 'restricted', 'not_determined', or 'unknown'.
    """
    try:
        res = subprocess.run(
            ["swift", "-e", "import AVFoundation; print(AVCaptureDevice.authorizationStatus(for: .audio).rawValue)"],
            capture_output=True, text=True, timeout=5
        )
        if res.returncode == 0:
            val = res.stdout.strip()
            # 0: notDetermined, 1: restricted, 2: denied, 3: authorized
            status_map = {"0": "not_determined", "1": "restricted", "2": "denied", "3": "authorized"}
            return status_map.get(val, "unknown")
    except Exception:
        pass
    return "unknown"

def find_builtin_microphone() -> int | None:
    """Find the index of the Mac's built-in microphone for reliable fallback."""
    try:
        devs = sd.query_devices()
        for idx, d in enumerate(devs):
            if d.get("max_input_channels", 0) > 0:
                name = d.get("name", "").lower()
                if "built-in" in name or "macbook" in name:
                    return idx
        for idx, d in enumerate(devs):
            if d.get("max_input_channels", 0) > 0:
                return idx
    except Exception:
        pass
    return None

def create_safe_input_stream(device=None, sample_rate=AUDIO_SAMPLE_RATE, channels=1, dtype="int16", blocksize=1024, callback=None):
    """
    Open an InputStream with automatic hardware fallback:
    1. Try target/default device with requested sample_rate
    2. Try target/default device with native default_samplerate (fixes -10851 AUHAL error)
    3. Try built-in MacBook microphone as fallback (fixes -9986 PortAudio error)
    Returns: (stream, actual_sample_rate, actual_device_name)
    """
    dev_candidates = []
    if device is not None:
        dev_candidates.append(device)
    else:
        try:
            def_in = sd.default.device[0]
            if def_in != -1:
                dev_candidates.append(def_in)
        except Exception:
            pass

    builtin = find_builtin_microphone()
    if builtin is not None and builtin not in dev_candidates:
        dev_candidates.append(builtin)

    last_error = None
    for cand in dev_candidates:
        try:
            cand_info = sd.query_devices(cand)
            cand_name = cand_info.get("name", f"Device {cand}")
            native_rate = int(cand_info.get("default_samplerate", sample_rate))
        except Exception:
            cand_name = f"Device {cand}"
            native_rate = sample_rate

        rates_to_try = [sample_rate]
        if native_rate not in rates_to_try:
            rates_to_try.append(native_rate)

        for rate in rates_to_try:
            kwargs = {
                "device": cand,
                "samplerate": rate,
                "channels": channels,
                "dtype": dtype,
                "blocksize": blocksize,
            }
            if callback:
                kwargs["callback"] = callback
            try:
                stream = sd.InputStream(**kwargs)
                stream.start()
                return stream, rate, cand_name
            except Exception as e:
                last_error = e
                continue

    raise last_error or RuntimeError("Could not open any audio input stream.")

class VoiceEngine:
    def __init__(self, voice: str = TTS_VOICE, rate: int = TTS_RATE):
        self.voice = voice
        self.rate = rate
        self.is_speaking = False
        self.current_process = None
        self.recognizer = sr.Recognizer()
        self.muted = False
        self.input_device = None

    def clean_text_for_speech(self, text: str) -> str:
        """Strip markdown, internal thinking, URLs, and code blocks for clean speech output."""
        if not text:
            return ""
        # Remove thinking blocks if present
        text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
        # Remove code blocks
        text = re.sub(r'```[\s\S]*?```', 'Here is the requested code snippet.', text)
        # Remove inline code (strip backticks, keep content)
        text = re.sub(r'`([^`]+)`', r'\1', text)
        # Remove markdown headers
        text = re.sub(r'#+\s*', '', text)
        # Remove bold/italic markers (* and **)
        text = re.sub(r'\*{1,3}([^*]+?)\*{1,3}', r'\1', text)
        text = re.sub(r'~~(.+?)~~', r'\1', text)
        # Bullet points at start of line
        text = re.sub(r'^\s*[-*•]\s+', '', text, flags=re.MULTILINE)
        # Newlines converted to pauses
        text = re.sub(r'\n+', '. ', text)
        # Remove URLs
        text = re.sub(r'https?://\S+', 'link', text)
        # Replace underscores with spaces so TTS speaks words naturally instead of saying 'underscore'
        text = text.replace('_', ' ')
        # Remove remaining stray symbols except standard punctuation and hyphens
        text = re.sub(r'[^\w\s.,!?:;\'"/-]', '', text)
        # Clean up repeated periods and excess whitespace
        text = re.sub(r'\.{2,}', '.', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def speak(self, text: str, wait: bool = True):
        """Speak text aloud using macOS built-in 'say' command."""
        if self.muted:
            return

        clean = self.clean_text_for_speech(text)
        if not clean:
            return

        self.stop()
        self.is_speaking = True

        cmd = ["say", "-v", self.voice, "-r", str(self.rate), clean]

        if wait:
            try:
                subprocess.run(cmd, check=False)
            finally:
                self.is_speaking = False
        else:
            def _run():
                try:
                    self.current_process = subprocess.Popen(cmd)
                    self.current_process.wait()
                finally:
                    self.is_speaking = False
                    self.current_process = None

            t = threading.Thread(target=_run, daemon=True)
            t.start()

    def stop(self):
        """Interrupt any ongoing speech."""
        if self.current_process and self.current_process.poll() is None:
            self.current_process.terminate()
            self.current_process = None
        self.is_speaking = False

    def list_audio_devices(self) -> list[dict]:
        """List all available audio input and output devices."""
        devices = []
        try:
            raw_devs = sd.query_devices()
            default_in, default_out = sd.default.device
            for idx, d in enumerate(raw_devs):
                devices.append({
                    "index": idx,
                    "name": d.get("name", "Unknown"),
                    "inputs": d.get("max_input_channels", 0),
                    "outputs": d.get("max_output_channels", 0),
                    "is_default_input": (idx == default_in),
                    "is_default_output": (idx == default_out),
                })
        except Exception as e:
            console.print(f"[dim yellow]Could not query audio devices: {e}[/dim yellow]")
        return devices

    def set_input_device(self, device_id_or_name) -> str:
        """Set the active input microphone by index or partial name."""
        try:
            if isinstance(device_id_or_name, str) and device_id_or_name.strip().isdigit():
                idx = int(device_id_or_name.strip())
            elif isinstance(device_id_or_name, int):
                idx = device_id_or_name
            else:
                # Search by name
                query = str(device_id_or_name).lower().strip()
                matched = None
                for d in self.list_audio_devices():
                    if d["inputs"] > 0 and query in d["name"].lower():
                        matched = d["index"]
                        break
                if matched is None:
                    return f"No input device found matching '{device_id_or_name}'."
                idx = matched

            info = sd.query_devices(idx, "input")
            self.input_device = idx
            return f"Switched microphone to [{idx}] {info.get('name')}."
        except Exception as e:
            return f"Failed to set input device: {e}"

    def listen(self, timeout: float = 8.0, silence_duration: float = 0.8, device: int | None = None) -> str | None:
        """
        Listen to the microphone using sounddevice with automatic
        Voice Activity Detection (energy thresholding), then transcribe via SpeechRecognition.
        """
        target_device = device if device is not None else self.input_device
        sample_rate = AUDIO_SAMPLE_RATE
        block_size = 1024
        channels = 1

        try:
            # First, check if devices exist
            devices = sd.query_devices()
            if not devices:
                console.print("[dim red]No audio devices found on system.[/dim red]")
                return None
        except Exception:
            return None

        # Energy threshold calibration
        buffer = []
        is_speaking = False
        silence_start = None
        start_time = time.time()

        # Calibration
        calibration_frames = int(sample_rate * 0.4 / block_size)
        ambient_energies = []
        zero_frames = 0

        try:
            stream, actual_rate, dev_name = create_safe_input_stream(
                device=target_device,
                sample_rate=sample_rate,
                channels=channels,
                dtype="int16",
                blocksize=block_size
            )
        except Exception as e:
            console.print(f"[dim red]Microphone stream error: {e}[/dim red]")
            return None

        try:
            # Calibrate ambient noise
            for _ in range(calibration_frames):
                data, _ = stream.read(block_size)
                rms = np.sqrt(np.mean(data.astype(np.float32) ** 2))
                ambient_energies.append(rms)
                if np.all(data == 0):
                    zero_frames += 1

            # If 100% of calibration audio is pure zeroes, macOS TCC is blocking microphone access!
            if zero_frames >= calibration_frames:
                console.print("\n[bold red]⚠️ Microphone Blocked by macOS:[/bold red] [white]Audio stream returned 0 dB silence (pure zeros).[/white]")
                console.print("[yellow]Your terminal or IDE does not have permission to access the microphone.[/yellow]")
                console.print("[white]👉 Opening System Settings -> Privacy & Security -> Microphone. Please toggle this app ON.[/white]\n")
                subprocess.run(["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone"], check=False)
                return None

            ambient_level = max(float(np.mean(ambient_energies)), 150.0)
            speech_threshold = ambient_level * 1.8 + 250.0

            while True:
                # Timeout check before speech starts
                if not is_speaking and (time.time() - start_time) > timeout:
                    return None

                data, _ = stream.read(block_size)
                rms = np.sqrt(np.mean(data.astype(np.float32) ** 2))

                if rms > speech_threshold:
                    if not is_speaking:
                        is_speaking = True
                    silence_start = None
                    buffer.append(data.tobytes())
                elif is_speaking:
                    buffer.append(data.tobytes())
                    if silence_start is None:
                        silence_start = time.time()
                    elif time.time() - silence_start > silence_duration:
                        # User stopped speaking
                        break
                time.sleep(0.001)

        except Exception as e:
            console.print(f"[dim red]Microphone stream error: {e}[/dim red]")
            return None
        finally:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass

        if not buffer or not is_speaking:
            return None

        raw_audio_bytes = b"".join(buffer)
        audio_data = sr.AudioData(raw_audio_bytes, actual_rate, 2)

        try:
            text = self.recognizer.recognize_google(audio_data)
            return text.strip()
        except sr.UnknownValueError:
            console.print("[dim yellow]Speech unintelligible. Try speaking a bit louder or closer.[/dim yellow]")
            return None
        except sr.RequestError as e:
            console.print(f"[dim red]Speech recognition network error: {e}[/dim red]")
            return None
