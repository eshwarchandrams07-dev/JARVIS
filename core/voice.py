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

KOKORO_VOICE_ALIASES = {
    "heart": "af_heart",
    "bella": "af_bella",
    "sky": "af_sky",
    "nova": "af_nova",
    "emma": "bf_emma",
    "michael": "am_michael",
    "fenrir": "am_fenrir",
    "george": "bm_george",
}
MACOS_FALLBACK_VOICE = "Karen"


def _find_kokoro_files() -> tuple[str, str] | None:
    """Locate local Kokoro v1.0 ONNX model & voice embedding files."""
    candidates = [
        os.path.expanduser("~/.jarvis_models/kokoro"),
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".jarvis_models", "kokoro"),
    ]
    for base in candidates:
        model_p = os.path.join(base, "kokoro-v1.0.onnx")
        voices_p = os.path.join(base, "voices-v1.0.bin")
        if os.path.exists(model_p) and os.path.exists(voices_p) and os.path.getsize(model_p) > 50_000_000:
            return model_p, voices_p
    return None


class VoiceEngine:
    def __init__(self, voice: str = TTS_VOICE, rate: int = TTS_RATE):
        self.voice = self.resolve_voice_name(voice)
        self.rate = rate
        self.is_speaking = False
        self.current_process = None
        self.recognizer = sr.Recognizer()
        self.muted = False
        self.input_device = None
        self._kokoro = None
        self._kokoro_failed = False
        self._kokoro_lock = threading.Lock()
        self._speech_gen = 0
        self._gen_lock = threading.Lock()

    @staticmethod
    def resolve_voice_name(name: str) -> str:
        """Map friendly aliases ('heart', 'bella', 'george') to Kokoro IDs, keeping macOS names intact."""
        clean = (name or TTS_VOICE).strip()
        return KOKORO_VOICE_ALIASES.get(clean.lower(), clean)

    def set_voice(self, name: str) -> str:
        self.voice = self.resolve_voice_name(name)
        return self.voice

    def _is_kokoro_voice(self) -> bool:
        v = self.voice.lower()
        return v in KOKORO_VOICE_ALIASES or re.match(r"^[ab][fm]_[a-z]+$", v) is not None

    def _get_kokoro(self):
        """Lazily load local Kokoro-82M ONNX engine (thread-safe, offline)."""
        if self._kokoro is not None:
            return self._kokoro
        if self._kokoro_failed:
            return None
        with self._kokoro_lock:
            if self._kokoro is not None:
                return self._kokoro
            paths = _find_kokoro_files()
            if not paths:
                return None
            try:
                from kokoro_onnx import Kokoro
                self._kokoro = Kokoro(paths[0], paths[1])
                return self._kokoro
            except Exception as e:
                self._kokoro_failed = True
                console.print(f"[dim yellow]Kokoro neural voice fallback to macOS say: {e}[/dim yellow]")
                return None

    def warmup_neural_tts(self):
        """Preload Kokoro ONNX in the background at startup so first spoken reply has zero load lag."""
        if not self._is_kokoro_voice() or not _find_kokoro_files():
            return
        threading.Thread(target=self._get_kokoro, daemon=True).start()

    def clean_text_for_speech(self, text: str) -> str:
        """Strip markdown, internal thinking, URLs, and code blocks while preserving natural prosody punctuation."""
        if not text:
            return ""
        text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
        text = re.sub(r'```[\s\S]*?```', 'Here is the requested code snippet.', text)
        text = re.sub(r'`([^`]+)`', r'\1', text)
        text = re.sub(r'#+\s*', '', text)
        text = re.sub(r'~~(.+?)~~', r'\1', text)
        text = re.sub(r'^\s*[-*•]\s+', '', text, flags=re.MULTILINE)
        text = re.sub(r'\n+', '. ', text)
        text = re.sub(r'https?://\S+', 'link', text)
        text = text.replace('_', ' ')
        # Keep ** and * briefly if caller passes raw, strip in plain cleaner
        text = re.sub(r'\*{1,3}([^*]+?)\*{1,3}', r'\1', text)
        text = re.sub(r'[^\w\s.,!?:;\'"/—-]', '', text)
        text = re.sub(r'\.{4,}', '...', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def _prepare_expressive_chunks(self, text: str) -> list[tuple[str, float, float]]:
        """
        Split text into natural human speech chunks: (chunk_text, speed_multiplier, pause_after_sec).
        Gives greetings/interjections and emphasized words warmer weight, while keeping follow-ups lively.
        """
        if not text:
            return []
        raw = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
        raw = re.sub(r'```[\s\S]*?```', 'Here is the requested code snippet.', raw)
        raw = re.sub(r'`([^`]+)`', r'\1', raw)
        raw = re.sub(r'#+\s*', '', raw)
        raw = re.sub(r'~~(.+?)~~', r'\1', raw)
        raw = re.sub(r'^\s*[-*•]\s+', '', raw, flags=re.MULTILINE)
        raw = re.sub(r'\n+', '. ', raw)
        raw = re.sub(r'https?://\S+', 'link', raw)
        raw = raw.replace('_', ' ')

        # Normalize stretched conversational letters cleanly so espeak never pronounces extra syllables ("heyy" -> "hey...")
        raw = re.sub(r'\b(hey)y+\b', r'\1...', raw, flags=re.IGNORECASE)
        raw = re.sub(r'\b(oh)h+\b', r'\1...', raw, flags=re.IGNORECASE)
        raw = re.sub(r'\b(yay+|ya+y+)\b', 'Yay!', raw, flags=re.IGNORECASE)
        raw = re.sub(r'([a-zA-Z])\1{2,}', r'\1\1', raw)

        # Split at sentence boundaries while keeping punctuation
        parts = [p.strip() for p in re.split(r'(?<=[.!?])\s+', raw) if p.strip()]
        chunks: list[tuple[str, float, float]] = []

        for idx, part in enumerate(parts):
            has_emphasis = bool(re.search(r'\*\*[^*]+\*\*', part))
            clean_part = re.sub(r'\*{1,3}([^*]+?)\*{1,3}', r'\1', part)
            clean_part = re.sub(r'[^\w\s.,!?:;\'"/—-]', '', clean_part)
            clean_part = re.sub(r'\.{4,}', '...', clean_part)
            clean_part = re.sub(r'\s+', ' ', clean_part).strip()
            if not clean_part or not re.search(r'[a-zA-Z0-9]', clean_part):
                continue

            word_count = len(clean_part.split())
            low = clean_part.lower()
            is_greeting_or_punch = (
                idx == 0 and word_count <= 4
                and re.search(r'\b(hey+|hi+|oh+|whoa|wait|boom|boss|got it|alright|ready)\b', low)
            )
            if is_greeting_or_punch:
                # Slower, warmer weight on opening greeting/interjection + natural breath pause
                chunks.append((clean_part, 0.88, 0.14))
            elif has_emphasis and word_count <= 10:
                chunks.append((clean_part, 0.94, 0.14))
            elif clean_part.endswith('?'):
                chunks.append((clean_part, 0.98, 0.20))
            elif clean_part.endswith('!'):
                chunks.append((clean_part, 1.03, 0.18))
            elif clean_part.endswith('.'):
                # Declarative full-stop sentence: gently relaxed pace + fuller breath pause
                chunks.append((clean_part, 0.95, 0.26))
            else:
                chunks.append((clean_part, 1.00, 0.16))

        return chunks

    @staticmethod
    def _shape_phrase_envelope(samples: np.ndarray, sr_hz: int, soft_ending: bool) -> np.ndarray:
        """
        Trim dead leading silence cleanly while keeping natural trailing breath,
        and apply a gentle cosine volume decrease before full stops ('.') instead of an abrupt cut.
        """
        if len(samples) == 0:
            return samples
        voiced = np.where(np.abs(samples) > 0.003)[0]
        if len(voiced) == 0:
            return samples

        lead_pad = int(0.012 * sr_hz)
        tail_pad = int(0.090 * sr_hz) if soft_ending else int(0.050 * sr_hz)
        start = max(0, int(voiced[0]) - lead_pad)
        end = min(len(samples), int(voiced[-1]) + tail_pad)
        out = samples[start:end].astype(np.float32, copy=True)

        # Tiny 8ms fade-in to avoid any start click
        fade_in_n = min(int(0.008 * sr_hz), len(out) // 4)
        if fade_in_n > 0:
            out[:fade_in_n] *= np.linspace(0.0, 1.0, fade_in_n, dtype=np.float32)

        if soft_ending and len(out) > int(0.30 * sr_hz):
            # Gradually decrease volume over the final ~260ms of speech + breath tail (1.0 -> 0.0)
            fade_n = min(int(0.26 * sr_hz), int(len(out) * 0.45))
            t = np.linspace(0.0, np.pi / 2.0, fade_n, dtype=np.float64)
            curve = (np.clip(np.cos(t), 0.0, 1.0) ** 1.4).astype(np.float32)
            out[-fade_n:] *= curve
        else:
            # Smooth 35ms micro-release so non-period chunks never hard-click
            fade_n = min(int(0.035 * sr_hz), len(out) // 4)
            if fade_n > 0:
                out[-fade_n:] *= np.linspace(1.0, 0.0, fade_n, dtype=np.float32)

        return out

    def _base_kokoro_speed(self) -> float:
        """Convert WPM-style or multiplier rate cleanly into Kokoro speed (0.65..1.45)."""
        r = float(self.rate)
        if r <= 3.0:
            return max(0.65, min(1.45, r))
        return max(0.65, min(1.45, r / 210.0))

    def _speak_kokoro(self, text: str, gen: int):
        kokoro = self._get_kokoro()
        if kokoro is None:
            return False

        voice_id = self.voice if self.voice in kokoro.voices else "af_heart"
        lang = "en-gb" if voice_id.startswith("b") else "en-us"
        chunks = self._prepare_expressive_chunks(text)
        if not chunks:
            return True

        base_speed = self._base_kokoro_speed()
        from concurrent.futures import ThreadPoolExecutor

        def _synth(idx: int):
            chunk_text, mult, pause_s = chunks[idx]
            spd = max(0.65, min(1.5, base_speed * mult))
            is_period = chunk_text.endswith(".") and not chunk_text.endswith("...")
            samples, sr_hz = kokoro.create(
                chunk_text,
                voice=voice_id,
                speed=spd,
                lang=lang,
                trim=False,
                sentence_pause=0.22,
                clause_pause=0.10,
            )
            samples = self._shape_phrase_envelope(samples, sr_hz, soft_ending=is_period)
            if pause_s > 0 and idx < len(chunks) - 1:
                silence = np.zeros(int(pause_s * sr_hz), dtype=samples.dtype)
                samples = np.concatenate([samples, silence])
            elif idx == len(chunks) - 1:
                # 60ms soft tail pad so macOS CoreAudio doesn't clip the final faded decay
                silence = np.zeros(int(0.06 * sr_hz), dtype=samples.dtype)
                samples = np.concatenate([samples, silence])
            return samples, sr_hz

        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                next_future = pool.submit(_synth, 0)
                stream = None
                try:
                    for idx in range(len(chunks)):
                        with self._gen_lock:
                            if gen != self._speech_gen:
                                return True
                        samples, sr_hz = next_future.result()
                        if idx + 1 < len(chunks):
                            next_future = pool.submit(_synth, idx + 1)
                        with self._gen_lock:
                            if gen != self._speech_gen:
                                return True
                        if stream is None:
                            stream = sd.OutputStream(samplerate=sr_hz, channels=1, dtype="float32")
                            stream.start()
                        # Write in 2048-sample slices so voice.stop() interrupts within ~85ms
                        pos = 0
                        while pos < len(samples):
                            with self._gen_lock:
                                if gen != self._speech_gen:
                                    stream.abort()
                                    return True
                            stream.write(samples[pos:pos + 2048].reshape(-1, 1))
                            pos += 2048
                finally:
                    if stream is not None:
                        try:
                            stream.stop()
                            stream.close()
                        except Exception:
                            pass
            return True
        except Exception:
            return False

    def speak(self, text: str, wait: bool = True):
        """Speak text aloud with expressive Kokoro neural TTS (falling back to macOS 'say' if needed)."""
        if self.muted:
            return

        if not self.clean_text_for_speech(text):
            return

        self.stop()
        with self._gen_lock:
            self._speech_gen += 1
            my_gen = self._speech_gen
        self.is_speaking = True

        use_kokoro = self._is_kokoro_voice() and (_find_kokoro_files() is not None) and not self._kokoro_failed

        def _deliver():
            try:
                if use_kokoro and self._speak_kokoro(text, my_gen):
                    return
                # Fallback: macOS 'say' with expressive prosody rate tags
                mac_voice = MACOS_FALLBACK_VOICE if self._is_kokoro_voice() else self.voice
                mac_rate = int(self.rate * 210) if self.rate <= 3.0 else int(self.rate)
                clean = self.clean_text_for_speech(text)
                if not clean:
                    return
                with self._gen_lock:
                    if my_gen != self._speech_gen:
                        return
                cmd = ["say", "-v", mac_voice, "-r", str(mac_rate), clean]
                if wait:
                    subprocess.run(cmd, check=False)
                else:
                    self.current_process = subprocess.Popen(cmd)
                    self.current_process.wait()
            finally:
                with self._gen_lock:
                    if my_gen == self._speech_gen:
                        self.is_speaking = False
                        self.current_process = None

        if wait:
            _deliver()
        else:
            threading.Thread(target=_deliver, daemon=True).start()

    def stop(self):
        """Interrupt any ongoing speech (both Kokoro sounddevice and macOS say)."""
        with self._gen_lock:
            self._speech_gen += 1
        try:
            sd.stop()
        except Exception:
            pass
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
