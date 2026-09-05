import asyncio
import json
import logging
import os
import queue
import subprocess
import tempfile
import threading
import time
import zipfile
from pathlib import Path
from typing import Callable, Optional

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

try:
    import requests
    REQUESTS_IMPORT_ERROR = None
except Exception as error:  # pragma: no cover - environment-specific import
    requests = None
    REQUESTS_IMPORT_ERROR = error

try:
    import edge_tts
    EDGE_TTS_IMPORT_ERROR = None
except Exception as error:  # pragma: no cover - environment-specific import
    edge_tts = None
    EDGE_TTS_IMPORT_ERROR = error

try:
    import pygame
    PYGAME_IMPORT_ERROR = None
except Exception as error:  # pragma: no cover - environment-specific import
    pygame = None
    PYGAME_IMPORT_ERROR = error

try:
    import sounddevice as sd
    SOUNDDEVICE_IMPORT_ERROR = None
except Exception as error:  # pragma: no cover - environment-specific import
    sd = None
    SOUNDDEVICE_IMPORT_ERROR = error

try:
    from vosk import KaldiRecognizer, Model, SetLogLevel
    VOSK_IMPORT_ERROR = None
except Exception as error:  # pragma: no cover - environment-specific import
    KaldiRecognizer = None
    Model = None
    SetLogLevel = None
    VOSK_IMPORT_ERROR = error

from utils.config import MODEL_DIR, TTS_VOICE, VOSK_MODEL_NAME, VOSK_MODEL_URL


class VoiceEngine:
    """Low-latency audio pipeline with continuous Vosk listening and async Edge TTS."""

    WAKE_WORD_VARIANTS = {"jarvis", "jarvice", "jervis", "jarviss"}

    def __init__(
        self,
        status_callback: Optional[Callable[[str], None]] = None,
        on_wake_word: Optional[Callable[[], None]] = None,
        on_command: Optional[Callable[[str], None]] = None,
        on_heard_text: Optional[Callable[[str], None]] = None,
        session_active: Optional[Callable[[], bool]] = None,
        can_accept_command: Optional[Callable[[], bool]] = None,
    ) -> None:
        self.status_callback = status_callback or (lambda _status: None)
        self.on_wake_word = on_wake_word or (lambda: None)
        self.on_command = on_command or (lambda _text: None)
        self.on_heard_text = on_heard_text or (lambda _text: None)
        self.session_active = session_active or (lambda: False)
        self.can_accept_command = can_accept_command or (lambda: True)
        self.logger = logging.getLogger("jarvis")

        self._ensure_dependencies()
        self.model_path = self._ensure_vosk_model()
        if SetLogLevel is not None:
            SetLogLevel(-1)
        self.model = Model(str(self.model_path))

        self.input_device_index, self.microphone_name, self.sample_rate = self._resolve_input_device()
        self.available_microphones = self.list_microphones()

        self._running = threading.Event()
        self._stream = None
        self._audio_queue: "queue.Queue[bytes]" = queue.Queue(maxsize=80)
        self._speech_queue: "queue.Queue[str]" = queue.Queue()
        self._stream_thread = None
        self._tts_thread = None
        self._speaking = threading.Event()
        self._wake_cooldown_until = 0.0
        self._wake_seen_in_current_utterance = False
        self._suppress_next_nonwake_final = False
        self._latest_partial = ""
        self._last_command = ""
        self._last_command_at = 0.0
        self._pygame_ready = False

        self._start_tts_worker()

    @staticmethod
    def _ensure_dependencies() -> None:
        if VOSK_IMPORT_ERROR is not None:
            raise RuntimeError(
                "Vosk is not available. Install the requirements again to enable fast speech recognition."
            ) from VOSK_IMPORT_ERROR
        if SOUNDDEVICE_IMPORT_ERROR is not None:
            raise RuntimeError(
                "sounddevice is not available. Install the requirements again to enable microphone streaming."
            ) from SOUNDDEVICE_IMPORT_ERROR

    @staticmethod
    def list_microphones() -> list[str]:
        if sd is None:
            return []

        microphones = []
        try:
            for index, device in enumerate(sd.query_devices()):
                if device.get("max_input_channels", 0) > 0:
                    microphones.append(VoiceEngine._device_label(index, device["name"]))
        except Exception:
            return []
        return microphones

    @staticmethod
    def _device_label(device_index: Optional[int], name: str) -> str:
        if device_index is None:
            return name
        return f"[{device_index}] {name}"

    @staticmethod
    def _get_device_sample_rate(device_index: Optional[int]) -> int:
        if sd is None:
            return 16000
        try:
            if device_index is None:
                device = sd.query_devices(kind="input")
            else:
                device = sd.query_devices(device_index)
            return int(device.get("default_samplerate") or 16000)
        except Exception:
            return 16000

    @staticmethod
    def _normalize_device_name(name: str) -> str:
        return " ".join((name or "").strip().split()).lower()

    @staticmethod
    def _extract_device_index(label: str) -> Optional[int]:
        if not label:
            return None
        stripped = label.strip()
        if not stripped.startswith("["):
            return None
        closing = stripped.find("]")
        if closing <= 1:
            return None
        try:
            return int(stripped[1:closing])
        except ValueError:
            return None

    def _get_microphone_name(self, device_index: Optional[int]) -> str:
        if sd is None:
            return "Unavailable"
        try:
            if device_index is None:
                device = sd.query_devices(kind="input")
                return str(device["name"])
            else:
                device = sd.query_devices(device_index)
                return self._device_label(device_index, str(device["name"]))
        except Exception:
            return "Default microphone"

    def _select_input_device(self) -> Optional[int]:
        resolved_index, _, _ = self._resolve_input_device()
        return resolved_index

    def _resolve_input_device(
        self,
        preferred_index: Optional[int] = None,
        preferred_name: Optional[str] = None,
    ) -> tuple[Optional[int], str, int]:
        if sd is None:
            return None, "Unavailable", 16000

        ranked_matches = []
        try:
            devices = sd.query_devices()
        except Exception:
            return None, "Default microphone", 16000

        for index, device in enumerate(devices):
            if device.get("max_input_channels", 0) <= 0:
                continue

            lowered = self._normalize_device_name(device["name"])
            if any(bad in lowered for bad in ("stereo mix", "output", "speaker", "loopback")):
                continue

            score = 0
            if "microphone array" in lowered:
                score += 5
            if lowered.startswith("microphone"):
                score += 4
            if "microphone" in lowered:
                score += 3
            if "input" in lowered:
                score += 1
            if "usb" in lowered:
                score += 1

            ranked_matches.append((score, index))

        candidate_indexes: list[int] = []
        if preferred_index is not None:
            candidate_indexes.append(preferred_index)

        if preferred_name:
            normalized_target = self._normalize_device_name(preferred_name)
            for index, device in enumerate(devices):
                if device.get("max_input_channels", 0) <= 0:
                    continue
                if self._normalize_device_name(device["name"]) == normalized_target:
                    candidate_indexes.append(index)

        ranked_matches.sort(reverse=True)
        candidate_indexes.extend(index for _score, index in ranked_matches)

        seen: set[int] = set()
        for index in candidate_indexes:
            if index in seen:
                continue
            seen.add(index)
            config = self._find_supported_input_config(index)
            if config is None:
                continue
            sample_rate = config["sample_rate"]
            name = self._device_label(index, str(devices[index]["name"]))
            return index, name, sample_rate

        default_name = self._get_microphone_name(None)
        return None, default_name, self._get_device_sample_rate(None)

    def _find_supported_input_config(self, device_index: Optional[int]) -> Optional[dict[str, int]]:
        if sd is None:
            return None

        try:
            device = sd.query_devices(device_index if device_index is not None else None)
        except Exception:
            return None

        channels = 1
        for sample_rate in self._candidate_sample_rates(device_index):
            try:
                probe = self._build_stream(device_index, sample_rate)
                probe.close()
                return {"channels": channels, "sample_rate": sample_rate}
            except Exception:
                continue
        return None

    def _candidate_sample_rates(self, device_index: Optional[int]) -> list[int]:
        device_default = self._get_device_sample_rate(device_index)
        candidates = [16000, device_default, 48000, 44100, 32000]
        unique: list[int] = []
        for rate in candidates:
            rate = int(rate)
            if rate > 0 and rate not in unique:
                unique.append(rate)
        return unique

    def set_input_device_by_name(self, target_name: str) -> bool:
        if sd is None:
            return False

        explicit_index = self._extract_device_index(target_name)
        resolved_index, resolved_name, resolved_rate = self._resolve_input_device(
            preferred_index=explicit_index,
            preferred_name=target_name,
        )
        if resolved_name in {"Unavailable", "Default microphone"} and resolved_index is None:
            return False

        was_running = self._running.is_set()
        if was_running:
            self.stop_stream()

        self.input_device_index = resolved_index
        self.microphone_name = resolved_name
        self.sample_rate = resolved_rate
        self.available_microphones = self.list_microphones()
        self._clear_audio_queue()

        if was_running:
            self.start_stream()
        return True

    def get_microphone_details(self) -> str:
        return f"Using microphone: {self.microphone_name} @ {self.sample_rate} Hz"

    def prepare_microphone(self) -> None:
        if not self._running.is_set():
            self.start_stream()

    def start_stream(self) -> None:
        if self._running.is_set():
            return

        self._running.set()
        self._clear_audio_queue()
        self._stream_thread = threading.Thread(
            target=self._recognition_loop,
            name="jarvis-listener",
            daemon=True,
        )
        self._stream_thread.start()
        self._open_stream()
        self.logger.info("Audio stream started on %s", self.microphone_name)

    def stop_stream(self) -> None:
        self._running.clear()
        self._close_stream()
        self._clear_audio_queue()
        self.logger.info("Audio stream stopped")

    def speak(self, text: str) -> None:
        cleaned = " ".join((text or "").split())
        if cleaned:
            self._speech_queue.put(cleaned)

    def speak_wake_response(self, text: str = "Yes sir") -> None:
        self.speak(text)

    def is_speaking(self) -> bool:
        return self._speaking.is_set()

    def test_microphone(self) -> str:
        return self.get_microphone_details()

    def listen_for_wake_word(self, timeout: int = 1, phrase_time_limit: int = 2) -> str:
        return ""

    def listen_for_command(self, timeout: int = 6, phrase_time_limit: int = 8) -> str:
        return ""

    def _open_stream(self) -> None:
        if sd is None:
            raise RuntimeError("sounddevice is unavailable.")

        try:
            self._stream = self._build_stream(self.input_device_index, self.sample_rate)
            self._stream.start()
        except Exception as error:
            self.logger.warning(
                "Primary microphone open failed for %s: %s",
                self.microphone_name,
                error,
            )
            fallback_index, fallback_name, fallback_rate = self._resolve_input_device()
            if (
                fallback_index != self.input_device_index
                or fallback_rate != self.sample_rate
                or fallback_name != self.microphone_name
            ):
                try:
                    self.input_device_index = fallback_index
                    self.microphone_name = fallback_name
                    self.sample_rate = fallback_rate
                    self._stream = self._build_stream(self.input_device_index, self.sample_rate)
                    self._stream.start()
                    self.logger.info("Fell back to microphone %s", self.microphone_name)
                    return
                except Exception as fallback_error:
                    error = fallback_error

            self._running.clear()
            raise RuntimeError(f"Could not open microphone stream for {self.microphone_name}: {error}") from error

    def _build_stream(self, device_index: Optional[int], sample_rate: int):
        return sd.RawInputStream(
            samplerate=sample_rate,
            blocksize=0,
            device=device_index,
            dtype="int16",
            channels=1,
            latency="low",
            callback=self._audio_callback,
        )

    def _close_stream(self) -> None:
        stream = self._stream
        self._stream = None
        if stream is None:
            return

        try:
            stream.stop()
        except Exception:
            pass
        try:
            stream.close()
        except Exception:
            pass

    def _audio_callback(self, indata, frames, time_info, status) -> None:  # pragma: no cover - callback
        del frames, time_info
        if status:
            self.logger.warning("Audio callback status: %s", status)

        if not self._running.is_set():
            return

        try:
            self._audio_queue.put_nowait(bytes(indata))
        except queue.Full:
            try:
                self._audio_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._audio_queue.put_nowait(bytes(indata))
            except queue.Full:
                pass

    def _recognition_loop(self) -> None:
        recognizer = self._new_recognizer()

        while self._running.is_set():
            try:
                data = self._audio_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            if self._speaking.is_set():
                recognizer = self._new_recognizer()
                continue

            try:
                if recognizer.AcceptWaveform(data):
                    payload = json.loads(recognizer.Result())
                    text = payload.get("text", "").strip()
                    if text:
                        self._handle_final_text(text)
                    self._latest_partial = ""
                    self._wake_seen_in_current_utterance = False
                else:
                    payload = json.loads(recognizer.PartialResult())
                    partial = payload.get("partial", "").strip()
                    if partial:
                        self._handle_partial_text(partial)
            except Exception as error:
                self.logger.warning("Recognition loop error: %s", error)
                recognizer = self._new_recognizer()

    def _new_recognizer(self):
        recognizer = KaldiRecognizer(self.model, self.sample_rate)
        recognizer.SetWords(False)
        return recognizer

    def _handle_partial_text(self, partial: str) -> None:
        normalized = partial.lower().strip()
        if not normalized or normalized == self._latest_partial:
            return

        self._latest_partial = normalized
        if self.session_active():
            return

        if time.time() < self._wake_cooldown_until:
            return

        if self._looks_like_wake_phrase(normalized):
            self._wake_seen_in_current_utterance = True
            self._suppress_next_nonwake_final = True
            self._wake_cooldown_until = time.time() + 1.2
            self.logger.info("Wake detected from partial transcript: %s", partial)
            self.on_wake_word()

    def _handle_final_text(self, text: str) -> None:
        normalized = text.lower().strip()
        self.on_heard_text(text)

        contains_wake = self._contains_wake_word(normalized)

        if self._wake_seen_in_current_utterance and not contains_wake:
            self.logger.info("Ignoring trailing wake transcript: %s", text)
            self._wake_seen_in_current_utterance = False
            self._suppress_next_nonwake_final = False
            return

        if contains_wake:
            if time.time() >= self._wake_cooldown_until:
                self.logger.info("Wake detected from final transcript: %s", text)
                self.on_wake_word()
            self._wake_cooldown_until = time.time() + 1.2
            self._wake_seen_in_current_utterance = False
            self._suppress_next_nonwake_final = False
            stripped = self._strip_wake_word(normalized)
            if stripped:
                self._emit_command(stripped)
            return

        if self.session_active():
            self._emit_command(normalized)

    def _emit_command(self, command: str) -> None:
        cleaned = " ".join(command.split())
        if not cleaned:
            return

        if not self.can_accept_command():
            self.logger.info("Ignoring command while busy: %s", cleaned)
            return

        now = time.time()
        if cleaned == self._last_command and now - self._last_command_at < 2.5:
            return

        self._last_command = cleaned
        self._last_command_at = now
        self.logger.info("Command transcript received: %s", cleaned)
        self.on_command(cleaned)

    @staticmethod
    def _contains_wake_word(text: str) -> bool:
        words = [word.strip(".,!? ") for word in text.split()]
        return any(word in VoiceEngine.WAKE_WORD_VARIANTS for word in words)

    @staticmethod
    def _looks_like_wake_phrase(text: str) -> bool:
        words = [word.strip(".,!? ") for word in text.split() if word.strip(".,!? ")]
        if not words or len(words) > 3:
            return False
        return any(word in VoiceEngine.WAKE_WORD_VARIANTS for word in words)

    @staticmethod
    def _strip_wake_word(text: str) -> str:
        words = [word.strip(".,!? ") for word in text.split()]
        if not words:
            return ""

        if words[0] in VoiceEngine.WAKE_WORD_VARIANTS:
            return " ".join(words[1:]).strip()
        for index, word in enumerate(words):
            if word in VoiceEngine.WAKE_WORD_VARIANTS:
                return " ".join(words[index + 1 :]).strip()
        return text.strip()

    def _start_tts_worker(self) -> None:
        self._tts_thread = threading.Thread(
            target=self._tts_worker,
            name="jarvis-tts",
            daemon=True,
        )
        self._tts_thread.start()

    def _tts_worker(self) -> None:
        while True:
            text = self._speech_queue.get()
            try:
                self._speaking.set()
                self.status_callback("Speaking")
                if edge_tts is not None:
                    self._speak_with_edge_tts(text)
                else:
                    self._speak_with_windows_voice(text)
            except Exception as error:
                self.logger.warning("Edge TTS failed, falling back to Windows voice: %s", error)
                try:
                    self._speak_with_windows_voice(text)
                except Exception as fallback_error:
                    self.logger.error("Windows voice fallback failed: %s", fallback_error)
            finally:
                self._speaking.clear()
                self._speech_queue.task_done()

    def _speak_with_edge_tts(self, text: str) -> None:
        if edge_tts is None:
            raise RuntimeError(f"edge-tts is unavailable: {EDGE_TTS_IMPORT_ERROR}")

        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as temp_file:
            temp_path = Path(temp_file.name)

        try:
            asyncio.run(self._render_edge_tts(text, temp_path))
            self._play_audio_file(temp_path)
        finally:
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:
                pass

    async def _render_edge_tts(self, text: str, target_path: Path) -> None:
        voice_name = os.getenv("JARVIS_VOICE", TTS_VOICE)
        communicate = edge_tts.Communicate(text=text, voice=voice_name)
        await communicate.save(str(target_path))

    def _play_audio_file(self, audio_path: Path) -> None:
        if pygame is None:
            raise RuntimeError(f"pygame is unavailable: {PYGAME_IMPORT_ERROR}")

        if not self._pygame_ready:
            pygame.mixer.init()
            self._pygame_ready = True

        pygame.mixer.music.load(str(audio_path))
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            time.sleep(0.03)

    def _speak_with_windows_voice(self, text: str) -> None:
        escaped_text = text.replace("'", "''")
        script = (
            "Add-Type -AssemblyName System.Speech; "
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            "$voice = $s.GetInstalledVoices() | "
            "ForEach-Object { $_.VoiceInfo.Name } | "
            "Where-Object { $_ -match 'Guy|David|Mark|Male' } | "
            "Select-Object -First 1; "
            "if ($voice) { $s.SelectVoice($voice) }; "
            "$s.Rate = 1; "
            "$s.Volume = 100; "
            f"$s.Speak('{escaped_text}')"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            check=True,
            timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    def _ensure_vosk_model(self) -> Path:
        MODEL_DIR.mkdir(exist_ok=True)
        target_dir = MODEL_DIR / VOSK_MODEL_NAME
        if target_dir.exists():
            return target_dir

        if requests is None:
            raise RuntimeError(
                "The Vosk model is missing and the requests package is not available to download it."
            ) from REQUESTS_IMPORT_ERROR

        self.status_callback("Loading Model")
        self.logger.info("Downloading Vosk model from %s", VOSK_MODEL_URL)
        archive_path = MODEL_DIR / f"{VOSK_MODEL_NAME}.zip"

        with requests.get(VOSK_MODEL_URL, stream=True, timeout=60) as response:
            response.raise_for_status()
            with archive_path.open("wb") as archive_file:
                for chunk in response.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        archive_file.write(chunk)

        with zipfile.ZipFile(archive_path, "r") as archive:
            archive.extractall(MODEL_DIR)

        archive_path.unlink(missing_ok=True)
        return target_dir

    def _clear_audio_queue(self) -> None:
        while not self._audio_queue.empty():
            try:
                self._audio_queue.get_nowait()
            except queue.Empty:
                break
