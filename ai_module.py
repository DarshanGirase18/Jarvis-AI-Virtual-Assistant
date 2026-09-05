import logging
import os
import re
from collections import deque
from datetime import datetime
from typing import Callable, Deque, Dict, List, Optional


class AIClient:
    """AI fallback client with streaming support and short-term memory."""

    def __init__(self, memory_size: int = 8) -> None:
        self.memory: Deque[Dict[str, str]] = deque(maxlen=memory_size)
        self.provider = self._detect_provider()
        self.openai_client = None
        self.gemini_model = None
        self.logger = logging.getLogger("jarvis")
        self.saved_notes: Deque[str] = deque(maxlen=5)
        self._setup_client()

    def _detect_provider(self) -> str:
        if os.getenv("OPENAI_API_KEY"):
            return "openai"
        if os.getenv("GEMINI_API_KEY"):
            return "gemini"
        return "none"

    def _setup_client(self) -> None:
        try:
            if self.provider == "openai":
                from openai import OpenAI

                self.openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            elif self.provider == "gemini":
                import google.generativeai as genai

                genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
                self.gemini_model = genai.GenerativeModel("gemini-1.5-flash")
        except Exception as error:
            self.logger.warning("AI provider setup failed: %s", error)
            self.provider = "none"

    def ask(self, user_message: str) -> str:
        return self.ask_stream(user_message=user_message)

    def ask_stream(
        self,
        user_message: str,
        on_delta: Optional[Callable[[str], None]] = None,
    ) -> str:
        cleaned_message = " ".join((user_message or "").split()).strip()
        self.memory.append({"role": "user", "content": cleaned_message})

        try:
            if self.provider == "openai" and self.openai_client:
                reply = self._ask_openai_stream(on_delta=on_delta)
            elif self.provider == "gemini" and self.gemini_model:
                reply = self._ask_gemini(on_delta=on_delta)
            else:
                reply = self._offline_reply(cleaned_message)
                if on_delta and reply:
                    on_delta(reply)
        except Exception as error:
            self.logger.warning("AI request failed, using offline assistant: %s", error)
            reply = self._offline_reply(cleaned_message)
            if on_delta and reply:
                on_delta(reply)

        self.memory.append({"role": "assistant", "content": reply})
        return reply

    def _system_prompt(self) -> str:
        return (
            "You are Jarvis, a fast Windows desktop voice assistant. "
            "Reply clearly, naturally, and with low-latency voice delivery in mind. "
            "Keep answers concise unless the user asks for depth. "
            "When helpful, use short sentences that can be spoken smoothly."
        )

    def _messages(self) -> List[Dict[str, str]]:
        messages: List[Dict[str, str]] = [{"role": "system", "content": self._system_prompt()}]
        messages.extend(list(self.memory))
        return messages

    def _ask_openai_stream(self, on_delta: Optional[Callable[[str], None]] = None) -> str:
        stream = self.openai_client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            messages=self._messages(),
            temperature=0.4,
            stream=True,
        )

        parts: List[str] = []
        for chunk in stream:
            delta = chunk.choices[0].delta.content or ""
            if not delta:
                continue
            parts.append(delta)
            if on_delta:
                on_delta(delta)

        return "".join(parts).strip()

    def _ask_gemini(self, on_delta: Optional[Callable[[str], None]] = None) -> str:
        prompt_lines = [self._system_prompt(), ""]
        for item in self.memory:
            prompt_lines.append(f"{item['role'].title()}: {item['content']}")

        prompt_lines.append("Assistant:")
        response = self.gemini_model.generate_content("\n".join(prompt_lines))
        text = response.text.strip()
        if on_delta and text:
            on_delta(text)
        return text

    def _offline_reply(self, user_message: str) -> str:
        lowered = user_message.lower().strip()
        if not lowered:
            return "I'm listening."

        remembered = self._handle_memory_request(lowered)
        if remembered:
            return remembered

        if re.search(r"\b(hello|hi|hey)\b", lowered):
            return "Hello sir. I'm ready."

        if "how are you" in lowered:
            return "I'm operating normally and ready to help."

        if any(phrase in lowered for phrase in ("who are you", "what are you", "your name")):
            return "I'm Jarvis, your desktop assistant for voice commands, apps, files, and quick help."

        if "what can you do" in lowered or re.search(r"\b(help|capabilities)\b", lowered):
            return (
                "I can open apps and websites, search Google, play on YouTube, manage files and folders, "
                "take screenshots, control volume, and answer simple chat locally. "
                "For full AI conversations, add OPENAI_API_KEY or GEMINI_API_KEY."
            )

        if re.search(r"\btime\b", lowered):
            return datetime.now().strftime("It is %I:%M %p.")

        if re.search(r"\b(date|day)\b", lowered):
            return datetime.now().strftime("Today is %A, %d %B %Y.")

        if any(phrase in lowered for phrase in ("thank you", "thanks", "good job")):
            return "Anytime."

        if "current events" in lowered or re.search(r"\b(weather|news|latest)\b", lowered):
            return "I can open a browser search for that. Say search Google for what you want."

        return (
            "I can handle desktop actions right now, and I also have a local fallback for basic chat. "
            "If you want richer AI answers, add OPENAI_API_KEY or GEMINI_API_KEY."
        )

    def _handle_memory_request(self, lowered_message: str) -> str:
        remember_match = re.search(r"\bremember(?: that)?\s+(.+)", lowered_message)
        if remember_match:
            note = remember_match.group(1).strip(" .")
            if note:
                self.saved_notes.append(note)
                return f"I'll remember that: {note}."

        if "what do you remember" in lowered_message or "what did i ask you to remember" in lowered_message:
            if not self.saved_notes:
                return "You have not asked me to remember anything yet."
            notes = "; ".join(self.saved_notes)
            return f"Here is what I remember: {notes}."

        if "forget everything" in lowered_message or "clear memory" in lowered_message:
            self.saved_notes.clear()
            return "Memory cleared."

        return ""
