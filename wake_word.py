import threading
import time
from typing import Callable, Optional


class WakeWordListener:
    """Continuously listens for the wake word using short audio windows."""

    def __init__(
        self,
        voice_engine,
        wake_word: str,
        on_wake_word: Callable[[], None],
        status_callback: Callable[[str], None],
        heard_callback: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.voice_engine = voice_engine
        self.wake_word = wake_word.lower().strip()
        self.on_wake_word = on_wake_word
        self.status_callback = status_callback
        self.heard_callback = heard_callback or (lambda _text: None)
        self._running = threading.Event()
        self._paused = threading.Event()
        self._thread = None
        self._aliases = {
            self.wake_word,
            "jarvis.",
            "jarvis?",
            "jarvis!",
        }

    def start_listening(self) -> None:
        if self._thread and self._thread.is_alive():
            return

        self._running.set()
        self._paused.clear()
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()

    def stop_listening(self) -> None:
        self._running.clear()
        self._paused.clear()

    def pause(self) -> None:
        self._paused.set()

    def resume(self) -> None:
        self._paused.clear()

    def _listen_loop(self) -> None:
        try:
            self.voice_engine.prepare_microphone()
        except Exception as error:
            self.heard_callback(f"Wake listener error: {error}")
            self.status_callback("Mic Error")
            return

        while self._running.is_set():
            if self._paused.is_set():
                time.sleep(0.1)
                continue

            try:
                self.status_callback("Armed")
                text = self.voice_engine.listen_for_wake_word(
                    timeout=0.7,
                    phrase_time_limit=1.5,
                )

                if not text:
                    continue

                normalized = text.lower().strip()
                self.heard_callback(f"Wake listener heard: {text}")

                if self._is_wake_match(normalized):
                    self.on_wake_word()
                    time.sleep(0.2)
            except Exception:
                # Sleep briefly so repeated microphone errors do not spin the CPU.
                time.sleep(0.5)

    def _is_wake_match(self, text: str) -> bool:
        if text in self._aliases:
            return True

        words = [word.strip(".,!? ") for word in text.split()]
        return any(word in self._aliases for word in words)
