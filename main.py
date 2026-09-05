import logging
import queue
import re
import sys
import threading
import time

from ai_module import AIClient
from command_handler import CommandHandler
from gui import JarvisGUI
from voice_engine import VoiceEngine
from utils.config import BASE_DIR, SESSION_TIMEOUT_SECONDS
from utils.logger import configure_logging


class StreamSpeechBuffer:
    """Buffers streamed text and emits speakable chunks without waiting for the full answer."""

    SENTENCE_PATTERN = re.compile(r"(.+?[.!?])(?=\s|$)")

    def __init__(self, on_chunk) -> None:
        self.on_chunk = on_chunk
        self.buffer = ""
        self.seen_any = False
        self.lock = threading.Lock()

    def add(self, delta: str) -> None:
        if not delta:
            return

        with self.lock:
            self.seen_any = True
            self.buffer += delta
            for chunk in self._pop_ready_chunks():
                self.on_chunk(chunk)

    def flush(self) -> None:
        with self.lock:
            remaining = " ".join(self.buffer.split()).strip()
            self.buffer = ""
            if remaining:
                self.on_chunk(remaining)

    def _pop_ready_chunks(self) -> list[str]:
        chunks = []
        while True:
            match = self.SENTENCE_PATTERN.match(self.buffer)
            if match:
                chunk = " ".join(match.group(1).split()).strip()
                self.buffer = self.buffer[match.end() :].lstrip()
                if chunk:
                    chunks.append(chunk)
                continue

            compact = " ".join(self.buffer.split())
            if len(compact) >= 90:
                split_index = compact.rfind(" ", 0, 90)
                if split_index > 35:
                    chunk = compact[:split_index].strip()
                    remainder = compact[split_index + 1 :].lstrip()
                    self.buffer = remainder
                    if chunk:
                        chunks.append(chunk)
                break
            break
        return chunks


class JarvisAssistant:
    """Queue-driven controller that keeps wake listening, command routing, and speech non-blocking."""

    def __init__(self) -> None:
        self.log_path = configure_logging(BASE_DIR)
        self.logger = logging.getLogger("jarvis")

        self.gui = JarvisGUI(
            on_start=self.start,
            on_stop=self.stop,
            on_hide=self.hide_window,
            on_show=self.show_window,
            on_test_mic=self.test_microphone,
            on_select_mic=self.select_microphone,
            on_test_voice=self.test_voice,
            on_wake_test=self.wake_test,
        )
        self.startup_error = None
        self.started = False

        self.command_queue: "queue.Queue[str]" = queue.Queue()
        self.output_queue: "queue.Queue[dict[str, object]]" = queue.Queue()
        self._shutdown = threading.Event()
        self._processing_command = threading.Event()
        self._session_deadline = 0.0
        self._session_lock = threading.Lock()

        self.ai_client = AIClient()
        self.command_handler = CommandHandler(self.ai_client)
        self.voice_engine = None

        try:
            self.voice_engine = VoiceEngine(
                status_callback=self.gui.set_status,
                on_wake_word=self._on_wake_word,
                on_command=self._on_voice_command,
                on_heard_text=self._on_heard_text,
                session_active=self.session_active,
                can_accept_command=self._can_accept_command,
            )
        except Exception as error:
            self.startup_error = str(error)
            self.gui.set_status("Startup Error")
            self.gui.append_response("Voice engine could not start.")
            self.gui.append_response(f"Details: {error}")
            self.gui.append_response(f"Python: {sys.executable}")
            self.gui.append_response(
                "If you launched from an IDE, make sure it is using .venv\\Scripts\\python.exe "
                "or start Jarvis with run_jarvice.bat."
            )
            self.logger.error("Startup error: %s", error)

        if self.voice_engine:
            self.gui.set_microphones(self.voice_engine.available_microphones)
            self.gui.set_selected_microphone(self.voice_engine.microphone_name)

        self._start_background_workers()
        self.gui.append_response(f"Logs: {self.log_path}")
        if not self.startup_error:
            self.gui.root.after(500, self.start)

    def _start_background_workers(self) -> None:
        threading.Thread(target=self._command_worker, name="jarvis-command", daemon=True).start()
        threading.Thread(target=self._output_worker, name="jarvis-output", daemon=True).start()
        threading.Thread(target=self._session_monitor, name="jarvis-session", daemon=True).start()

    def start(self) -> None:
        if self.started:
            return

        if self.startup_error or not self.voice_engine:
            self.gui.set_status("Startup Error")
            self.gui.append_response("Jarvis cannot start until the voice stack is fixed.")
            return

        self.voice_engine.start_stream()
        self.started = True
        self.gui.set_mode("WAKE MODE // ARMED")
        self.gui.append_response(self.voice_engine.get_microphone_details())
        self.gui.append_response("Jarvis is live. Say 'Jarvis' once, then keep talking naturally.")
        self.logger.info("Assistant started")

    def stop(self) -> None:
        if not self.started and not self.voice_engine:
            return

        self.started = False
        self._clear_session()
        if self.voice_engine:
            self.voice_engine.stop_stream()
        self.gui.set_mode("WAKE MODE // STANDBY")
        self.gui.set_status("Stopped")
        self.gui.append_response("Assistant stopped.")
        self.logger.info("Assistant stopped")

    def hide_window(self) -> None:
        self.gui.hide_window()
        self.gui.append_response("GUI hidden. Jarvis is still running in background mode.")

    def show_window(self) -> None:
        self.gui.show_window()

    def select_microphone(self, microphone_name: str) -> None:
        if not self.voice_engine:
            return
        if self.voice_engine.set_input_device_by_name(microphone_name):
            self.gui.append_response(f"Selected microphone: {microphone_name}")
            self.gui.set_selected_microphone(microphone_name)
        else:
            self.gui.append_response(f"Could not select microphone: {microphone_name}")

    def test_microphone(self) -> None:
        if not self.voice_engine:
            self.gui.append_response("Voice engine is not available.")
            return
        self.gui.append_response(self.voice_engine.test_microphone())

    def test_voice(self) -> None:
        self.output_queue.put(
            {
                "display": "Voice test: Jarvis voice pipeline is online.",
                "speech": "Jarvis voice pipeline is online.",
            }
        )

    def wake_test(self) -> None:
        self._activate_session(announce=True)

    def session_active(self) -> bool:
        with self._session_lock:
            return self._session_deadline > time.time()

    def _activate_session(self, announce: bool = True) -> None:
        was_active = self.session_active()
        with self._session_lock:
            self._session_deadline = time.time() + SESSION_TIMEOUT_SECONDS

        if announce and not was_active:
            self.logger.info("Wake detected")
            self.output_queue.put({"display": "Wake word detected.", "speech": "Yes sir"})

    def _extend_session(self) -> None:
        with self._session_lock:
            self._session_deadline = time.time() + SESSION_TIMEOUT_SECONDS

    def _clear_session(self) -> None:
        with self._session_lock:
            self._session_deadline = 0.0

    def _on_wake_word(self) -> None:
        if not self.started:
            return
        self._activate_session(announce=True)

    def _on_heard_text(self, text: str) -> None:
        if self.started and text:
            self.logger.info("Heard text: %s", text)
            self.output_queue.put({"display": f"Heard: {text}", "speech": None})

    def _on_voice_command(self, command: str) -> None:
        if not self.started:
            return

        if not self._can_accept_command():
            self.logger.info("Assistant busy, dropping command: %s", command)
            return

        self._extend_session()
        self.gui.set_command(command)
        self.output_queue.put({"display": f"You: {command}", "speech": None})
        self.command_queue.put(command)

    def _can_accept_command(self) -> bool:
        if not self.started:
            return False
        if self._processing_command.is_set():
            return False
        if self.voice_engine and self.voice_engine.is_speaking():
            return False
        return True

    def _command_worker(self) -> None:
        while not self._shutdown.is_set():
            try:
                command = self.command_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            start = time.perf_counter()
            self._processing_command.set()
            self.gui.set_status("Processing")
            self.logger.info("Command received: %s", command)

            stream_buffer = StreamSpeechBuffer(
                on_chunk=lambda chunk: self.output_queue.put({"display": None, "speech": chunk})
            )

            try:
                response = self.command_handler.handle_command(
                    command,
                    ai_stream_callback=stream_buffer.add,
                )
                stream_buffer.flush()
                if response:
                    should_speak = not stream_buffer.seen_any and self.command_handler.should_speak_response(response)
                    self.output_queue.put(
                        {
                            "display": f"Jarvis: {response}",
                            "speech": response if should_speak else None,
                        }
                    )
            except Exception as error:
                self.logger.exception("Command execution failed")
                self.output_queue.put(
                    {
                        "display": f"Jarvis: Something went wrong while processing that request. {error}",
                        "speech": "Something went wrong while processing that request.",
                    }
                )
            finally:
                latency = time.perf_counter() - start
                self.logger.info("Response time %.2fs | command=%s", latency, command)
                self._extend_session()
                self._processing_command.clear()
                self.command_queue.task_done()

    def _output_worker(self) -> None:
        while not self._shutdown.is_set():
            try:
                payload = self.output_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            display = payload.get("display")
            speech = payload.get("speech")

            if display:
                self.gui.append_response(str(display))
            if speech and self.voice_engine:
                self.voice_engine.speak(str(speech))

            self.output_queue.task_done()

    def _session_monitor(self) -> None:
        last_mode = None
        last_status = None

        while not self._shutdown.is_set():
            if not self.started:
                mode = "WAKE MODE // STANDBY"
                status = "Stopped" if not self.startup_error else "Startup Error"
            elif self.session_active():
                remaining = max(0, int(self._session_deadline - time.time()))
                mode = f"SMART SESSION // {remaining:02d}s"
                if self._processing_command.is_set():
                    status = "Processing"
                elif self.voice_engine and self.voice_engine.is_speaking():
                    status = "Speaking"
                else:
                    status = "Listening"
            else:
                mode = "WAKE MODE // ARMED"
                if self.voice_engine and self.voice_engine.is_speaking():
                    status = "Speaking"
                else:
                    status = "Armed"

            if mode != last_mode:
                self.gui.set_mode(mode)
                last_mode = mode
            if status != last_status:
                self.gui.set_status(status)
                last_status = status

            time.sleep(0.25)

    def run(self) -> None:
        try:
            self.gui.run()
        finally:
            self._shutdown.set()
            self.stop()


if __name__ == "__main__":
    assistant = JarvisAssistant()
    assistant.run()
