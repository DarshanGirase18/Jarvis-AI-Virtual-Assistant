import logging
import re
from functools import lru_cache
from typing import Callable, Optional

from system_control import SystemController


class CommandHandler:
    """Routes spoken commands to local actions first, with AI fallback for the rest."""

    SPLIT_PATTERN = re.compile(
        r"\s*(?:,|;|\band then\b|\bthen\b|\band\b)\s+(?=(?:open|close|search|google|play|"
        r"what|who|tell|explain|take|mute|volume|increase|decrease|turn|shutdown|restart|"
        r"sleep|find|launch|start|browse|visit|go)\b)",
        re.IGNORECASE,
    )

    LEADING_FILLERS = (
        "jarvis ",
        "please ",
        "can you ",
        "could you ",
        "would you ",
        "will you ",
        "hey jarvis ",
        "jarvis please ",
        "jarvis can you ",
        "jarvis could you ",
        "jarvis would you ",
        "jarvis will you ",
    )

    TRAILING_FILLERS = (
        " please",
        " for me",
        " right now",
        " if you can",
    )

    def __init__(self, ai_client) -> None:
        self.ai_client = ai_client
        self.system = SystemController()
        self.logger = logging.getLogger("jarvis")

    def handle_command(
        self,
        command: str,
        ai_stream_callback: Optional[Callable[[str], None]] = None,
    ) -> str:
        responses = []
        for part in self.split_compound_commands(command):
            response = self._handle_single_command(part, ai_stream_callback=ai_stream_callback)
            if response:
                responses.append(response)
        return " ".join(responses).strip()

    @classmethod
    @lru_cache(maxsize=128)
    def split_compound_commands(cls, command: str) -> tuple[str, ...]:
        normalized = " ".join((command or "").strip().split())
        if not normalized:
            return tuple()

        parts = [segment.strip() for segment in cls.SPLIT_PATTERN.split(normalized) if segment.strip()]
        return tuple(parts) if parts else (normalized,)

    def detect_intent(self, command: str) -> str:
        return "system" if self.extract_local_command(command) else "ai"

    def _handle_single_command(
        self,
        command: str,
        ai_stream_callback: Optional[Callable[[str], None]] = None,
    ) -> str:
        normalized = self._normalize_for_routing(command)
        if not normalized:
            return ""

        local_command = self.extract_local_command(normalized)
        intent = "system" if local_command else "ai"
        routed_command = local_command or normalized
        self.logger.info("Intent routed to %s: %s", intent, routed_command)
        if local_command:
            return self._handle_local_command(local_command, ai_stream_callback=ai_stream_callback)
        return self.ai_client.ask_stream(normalized, on_delta=ai_stream_callback)

    def _handle_local_command(
        self,
        command: str,
        ai_stream_callback: Optional[Callable[[str], None]] = None,
    ) -> str:
        if command.startswith("close "):
            target = command.replace("close ", "", 1).strip()
            if target.startswith("app "):
                target = target.replace("app ", "", 1).strip()
            if target.startswith("application "):
                target = target.replace("application ", "", 1).strip()
            return self.system.close_application(target)

        if command.startswith("open "):
            return self._handle_open(command)

        if command.startswith("search google for "):
            query = command.replace("search google for ", "", 1).strip()
            return self.system.google_search(query)

        if command.startswith("google search "):
            query = command.replace("google search ", "", 1).strip()
            return self.system.google_search(query)

        if command.startswith("search "):
            query = command.replace("search ", "", 1).strip()
            return self.system.google_search(query)

        if command.startswith("play ") and "youtube" in command:
            query = command.replace("play ", "", 1).replace(" on youtube", "").strip()
            return self.system.play_on_youtube(query)

        if command.startswith("play "):
            query = command.replace("play ", "", 1).strip()
            return self.system.play_on_youtube(query)

        if "time" in command:
            return self.system.get_time()

        if "date" in command or "day" in command:
            return self.system.get_date()

        if "shutdown" in command:
            return self.system.shutdown_pc()

        if "restart" in command:
            return self.system.restart_pc()

        if "sleep" in command:
            return self.system.sleep_pc()

        if "screenshot" in command or "screen shot" in command:
            return self.system.take_screenshot()

        if "volume up" in command or "increase volume" in command:
            return self.system.volume_up()

        if "volume down" in command or "decrease volume" in command:
            return self.system.volume_down()

        if "mute" in command:
            return self.system.mute_volume()

        if command.startswith("open file "):
            target = command.replace("open file ", "", 1).strip()
            if self._looks_like_path(target):
                return self.system.open_path(target)
            return self.system.open_named_file(target)

        if command.startswith("open folder "):
            target = command.replace("open folder ", "", 1).strip()
            if self._looks_like_path(target):
                return self.system.open_path(target)
            return self.system.open_named_folder(target)

        if command.startswith("find file "):
            return self.system.open_named_file(command.replace("find file ", "", 1).strip())

        if command.startswith("find folder "):
            return self.system.open_named_folder(command.replace("find folder ", "", 1).strip())

        if command in {"stop", "cancel", "never mind"}:
            return "Command cancelled."

        return self.ai_client.ask_stream(command, on_delta=ai_stream_callback)

    def _handle_open(self, command: str) -> str:
        target = command.replace("open ", "", 1).strip()

        if target in {"google", "youtube", "gmail", "github"}:
            return self.system.open_website(target)

        if target.startswith("http"):
            return self.system.open_website(target)

        if target.startswith("website "):
            site = target.replace("website ", "", 1).strip()
            return self.system.open_website(site)

        if target.startswith("file "):
            file_target = target.replace("file ", "", 1).strip()
            if self._looks_like_path(file_target):
                return self.system.open_path(file_target)
            return self.system.open_named_file(file_target)

        if target.startswith("folder "):
            folder_target = target.replace("folder ", "", 1).strip()
            if self._looks_like_path(folder_target):
                return self.system.open_path(folder_target)
            return self.system.open_named_folder(folder_target)

        app_response = self.system.open_application(target)
        if "shortcut configured" in app_response.lower():
            return self.system.open_from_computer(target)
        return app_response

    @staticmethod
    def should_speak_response(response: str) -> bool:
        lowered = response.lower()
        return "saved to" not in lowered

    def extract_local_command(self, command: str) -> Optional[str]:
        normalized = self._normalize_for_routing(command)
        if not normalized:
            return None

        simple_matches = (
            (r"^(?:what(?:'s| is)?(?: the)? time|tell me(?: the)? time|current time|time now)$", "what is the time"),
            (r"^(?:what(?:'s| is)?(?: the)? date|tell me(?: the)? date|what day is it|today(?:'s| is) date)$", "what is the date"),
            (r"^(?:take|capture) (?:a )?(?:screen ?shot|screenshot)$", "take screenshot"),
            (r"^(?:increase|raise|turn up) (?:the )?volume$", "volume up"),
            (r"^(?:decrease|lower|turn down) (?:the )?volume$", "volume down"),
            (r"^(?:mute|silence) (?:the )?(?:volume|sound|audio)$", "mute volume"),
            (r"^(?:shutdown|shut down|power off) (?:the )?(?:pc|computer|system)?$", "shutdown pc"),
            (r"^(?:restart|reboot) (?:the )?(?:pc|computer|system)?$", "restart pc"),
            (r"^(?:sleep|lock) (?:the )?(?:pc|computer|system)?$", "sleep pc"),
        )
        for pattern, resolved in simple_matches:
            if re.fullmatch(pattern, normalized):
                return resolved

        dynamic_patterns = (
            (
                r"^(?:open|launch|start|run) (.+)$",
                lambda match: f"open {self._clean_target(match.group(1))}",
            ),
            (
                r"^(?:go to|visit|browse to) (.+)$",
                lambda match: f"open {self._clean_target(match.group(1))}",
            ),
            (
                r"^(?:close|quit|exit) (.+)$",
                lambda match: f"close {self._clean_target(match.group(1))}",
            ),
            (
                r"^(?:search(?: google)? for|google search|look up) (.+)$",
                lambda match: f"search google for {self._clean_target(match.group(1))}",
            ),
            (
                r"^(?:search youtube for|find on youtube|play) (.+?)(?: on youtube)?$",
                lambda match: f"play {self._clean_target(match.group(1))} on youtube",
            ),
            (
                r"^(?:open|find) (?:the )?file (.+)$",
                lambda match: f"open file {self._clean_target(match.group(1))}",
            ),
            (
                r"^(?:open|find) (?:the )?folder (.+)$",
                lambda match: f"open folder {self._clean_target(match.group(1))}",
            ),
        )
        for pattern, resolver in dynamic_patterns:
            match = re.fullmatch(pattern, normalized)
            if match:
                resolved = resolver(match)
                return resolved.strip() if resolved.strip() else None

        if normalized in {"stop", "cancel", "never mind"}:
            return normalized
        return None

    @staticmethod
    def _looks_like_path(target: str) -> bool:
        return (
            ":" in target
            or "\\" in target
            or "/" in target
            or target.startswith(".")
            or target.startswith("~")
        )

    def _normalize_for_routing(self, command: str) -> str:
        normalized = " ".join((command or "").strip().split()).lower()
        normalized = normalized.strip(" .!?")

        changed = True
        while changed and normalized:
            changed = False
            for prefix in self.LEADING_FILLERS:
                if normalized.startswith(prefix):
                    normalized = normalized[len(prefix) :].strip()
                    changed = True
            for suffix in self.TRAILING_FILLERS:
                if normalized.endswith(suffix):
                    normalized = normalized[: -len(suffix)].strip()
                    changed = True

        normalized = normalized.replace("screen shot", "screenshot")
        normalized = normalized.replace("whats ", "what's ")
        return normalized

    @staticmethod
    def _clean_target(target: str) -> str:
        cleaned = " ".join(target.split()).strip(" .!?\"'")
        cleaned = re.sub(r"^(?:the|a|an)\s+", "", cleaned)
        cleaned = re.sub(r"\s+(?:please|for me|right now)$", "", cleaned)
        return cleaned.strip()
