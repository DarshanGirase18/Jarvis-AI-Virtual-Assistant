import datetime
import logging
import os
import subprocess
import time
import webbrowser
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Optional

try:
    import pyautogui
    PYAUTOGUI_IMPORT_ERROR = None
except Exception as error:  # pragma: no cover - environment-specific dependency issue
    pyautogui = None
    PYAUTOGUI_IMPORT_ERROR = error


class SystemController:
    """Collection of desktop and Windows-specific actions."""

    DEFAULT_APPS = {
        "chrome": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        "google chrome": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        "vs code": r"C:\Users\Admin\AppData\Local\Programs\Microsoft VS Code\Code.exe",
        "visual studio code": r"C:\Users\Admin\AppData\Local\Programs\Microsoft VS Code\Code.exe",
        "notepad": "notepad.exe",
        "calculator": "calc.exe",
        "whatsapp": r"C:\Users\Admin\AppData\Local\WhatsApp\WhatsApp.exe",
        "whatsapp desktop": r"C:\Users\Admin\AppData\Local\WhatsApp\WhatsApp.exe",
    }

    DEFAULT_SITES = {
        "google": "https://www.google.com",
        "youtube": "https://www.youtube.com",
        "gmail": "https://mail.google.com",
        "github": "https://github.com",
        "whatsapp": "https://web.whatsapp.com",
        "whatsapp web": "https://web.whatsapp.com",
    }

    APP_PROCESS_NAMES = {
        "chrome": "chrome.exe",
        "google chrome": "chrome.exe",
        "vs code": "Code.exe",
        "visual studio code": "Code.exe",
        "code": "Code.exe",
        "notepad": "notepad.exe",
        "calculator": "CalculatorApp.exe",
        "calc": "CalculatorApp.exe",
        "whatsapp": "WhatsApp.exe",
        "whatsapp desktop": "WhatsApp.exe",
    }

    SPECIAL_FOLDERS = {
        "desktop": Path.home() / "Desktop",
        "documents": Path.home() / "Documents",
        "downloads": Path.home() / "Downloads",
        "pictures": Path.home() / "Pictures",
        "videos": Path.home() / "Videos",
        "music": Path.home() / "Music",
    }

    def __init__(self) -> None:
        self.logger = logging.getLogger("jarvis")
        self._time_cache: tuple[float, str] = (0.0, "")
        self._date_cache: tuple[float, str] = (0.0, "")
        self._path_cache: dict[tuple[str, bool, bool], Optional[Path]] = {}

    @staticmethod
    def _ensure_pyautogui() -> Optional[str]:
        if pyautogui is None:
            details = f" Details: {PYAUTOGUI_IMPORT_ERROR}" if PYAUTOGUI_IMPORT_ERROR else ""
            return (
                "This action needs the optional pyautogui package, but it is not available."
                f"{details}"
            )
        return None

    def open_application(self, app_name: str) -> str:
        app_name = app_name.lower().strip()
        app_path = self._resolve_app_path(app_name)

        if app_name in {"whatsapp", "whatsapp desktop"}:
            if app_path and os.path.exists(app_path):
                try:
                    subprocess.Popen(app_path)
                    return "Opening WhatsApp."
                except Exception as error:
                    return f"Failed to open WhatsApp: {error}"
            webbrowser.open(self.DEFAULT_SITES["whatsapp"])
            return "Opening WhatsApp Web."

        if not app_path:
            return f"I do not have a shortcut configured for {app_name}."

        try:
            if app_path.endswith(".exe") and os.path.exists(app_path):
                subprocess.Popen(app_path)
            else:
                subprocess.Popen(app_path, shell=True)
            return f"Opening {app_name}."
        except Exception as error:
            return f"Failed to open {app_name}: {error}"

    def open_website(self, site_name: str) -> str:
        site_name = site_name.lower().strip()
        url = self.DEFAULT_SITES.get(site_name, site_name)

        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"

        webbrowser.open(url)
        return f"Opening {site_name}."

    def google_search(self, query: str) -> str:
        search_url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
        webbrowser.open(search_url)
        return f"Searching Google for {query}."

    def play_on_youtube(self, query: str) -> str:
        url = f"https://www.youtube.com/results?search_query={query.replace(' ', '+')}"
        webbrowser.open(url)
        return f"Playing {query} on YouTube."

    def get_time(self) -> str:
        now = time.time()
        if now - self._time_cache[0] < 1 and self._time_cache[1]:
            return self._time_cache[1]

        value = datetime.datetime.now().strftime("The time is %I:%M %p.")
        self._time_cache = (now, value)
        return value

    def get_date(self) -> str:
        now = time.time()
        if now - self._date_cache[0] < 30 and self._date_cache[1]:
            return self._date_cache[1]

        value = datetime.datetime.now().strftime("Today's date is %A, %d %B %Y.")
        self._date_cache = (now, value)
        return value

    def shutdown_pc(self) -> str:
        subprocess.Popen("shutdown /s /t 5", shell=True)
        return "Shutting down the computer in 5 seconds."

    def restart_pc(self) -> str:
        subprocess.Popen("shutdown /r /t 5", shell=True)
        return "Restarting the computer in 5 seconds."

    def sleep_pc(self) -> str:
        subprocess.Popen(
            r"rundll32.exe powrprof.dll,SetSuspendState 0,1,0",
            shell=True,
        )
        return "Putting the computer to sleep."

    def open_path(self, raw_path: str) -> str:
        cleaned = raw_path.strip().strip('"')
        path = Path(cleaned).expanduser()

        if not path.exists():
            return f"I could not find {cleaned}."

        os.startfile(str(path))
        return f"Opening {path.name}."

    def open_named_file(self, file_name: str) -> str:
        path = self._find_path_by_name(file_name=file_name, only_files=True)
        if not path:
            return f"I could not find a file named {file_name}."

        os.startfile(str(path))
        return f"Opening file {path.name}."

    def open_named_folder(self, folder_name: str) -> str:
        special_folder = self.SPECIAL_FOLDERS.get(folder_name.strip().strip('"').lower())
        if special_folder and special_folder.exists():
            os.startfile(str(special_folder))
            return f"Opening folder {special_folder.name}."

        path = self._find_path_by_name(file_name=folder_name, only_folders=True)
        if not path:
            return f"I could not find a folder named {folder_name}."

        os.startfile(str(path))
        return f"Opening folder {path.name}."

    def open_from_computer(self, name: str) -> str:
        path = self._find_path_by_name(file_name=name)
        if not path:
            return f"I could not find {name} on this computer."

        os.startfile(str(path))
        kind = "folder" if path.is_dir() else "file"
        return f"Opening {kind} {path.name}."

    def close_application(self, app_name: str) -> str:
        target = app_name.lower().strip()
        process_name = self.APP_PROCESS_NAMES.get(target)

        if not process_name:
            cleaned = target.replace('"', "").strip()
            process_name = cleaned if cleaned.endswith(".exe") else f"{cleaned}.exe"

        try:
            result = subprocess.run(
                ["taskkill", "/IM", process_name, "/F"],
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )

            if result.returncode == 0:
                return f"Closed {app_name}."

            error_text = (result.stdout or result.stderr or "").strip()
            if "not found" in error_text.lower() or "no running instance" in error_text.lower():
                return f"{app_name} is not running."
            return f"Could not close {app_name}: {error_text or 'unknown error'}"
        except Exception as error:
            return f"Failed to close {app_name}: {error}"

    def take_screenshot(self) -> str:
        dependency_error = self._ensure_pyautogui()
        if dependency_error:
            return dependency_error

        screenshot_dir = Path.cwd() / "screenshots"
        screenshot_dir.mkdir(exist_ok=True)
        filename = datetime.datetime.now().strftime("screenshot_%Y%m%d_%H%M%S.png")
        file_path = screenshot_dir / filename
        image = pyautogui.screenshot()
        image.save(file_path)
        return f"Screenshot saved to {file_path}."

    def volume_up(self) -> str:
        dependency_error = self._ensure_pyautogui()
        if dependency_error:
            return dependency_error

        for _ in range(5):
            pyautogui.press("volumeup")
        return "Volume increased."

    def volume_down(self) -> str:
        dependency_error = self._ensure_pyautogui()
        if dependency_error:
            return dependency_error

        for _ in range(5):
            pyautogui.press("volumedown")
        return "Volume decreased."

    def mute_volume(self) -> str:
        dependency_error = self._ensure_pyautogui()
        if dependency_error:
            return dependency_error

        pyautogui.press("volumemute")
        return "Volume toggled."

    def _find_path_by_name(
        self,
        file_name: str,
        only_files: bool = False,
        only_folders: bool = False,
    ) -> Optional[Path]:
        query = file_name.strip().strip('"').lower()
        if not query:
            return None

        cache_key = (query, only_files, only_folders)
        if cache_key in self._path_cache:
            cached = self._path_cache[cache_key]
            if cached and cached.exists():
                return cached
            if cached is None:
                return None

        exact_match = None
        partial_match = None

        for root in self._search_roots():
            try:
                if self._matches_query(root, query, only_files=only_files, only_folders=only_folders):
                    return root

                for path in root.rglob("*"):
                    if self._matches_query(path, query, only_files=only_files, only_folders=only_folders):
                        return path
                    stem = path.stem.lower() if path.is_file() else path.name.lower()
                    if exact_match is None and stem == query:
                        exact_match = path
                    elif partial_match is None and query in path.name.lower():
                        partial_match = path
            except (PermissionError, OSError):
                continue

        resolved = exact_match or partial_match
        self._path_cache[cache_key] = resolved
        return resolved

    @staticmethod
    @lru_cache(maxsize=32)
    def _resolve_app_path(app_name: str) -> Optional[str]:
        return SystemController.DEFAULT_APPS.get(app_name)

    @staticmethod
    def _matches_query(
        path: Path,
        query: str,
        only_files: bool = False,
        only_folders: bool = False,
    ) -> bool:
        if only_files and not path.is_file():
            return False
        if only_folders and not path.is_dir():
            return False
        return path.name.lower() == query

    @staticmethod
    def _search_roots() -> Iterable[Path]:
        home = Path.home()
        candidates = [
            home / "Desktop",
            home / "Documents",
            home / "Downloads",
            home / "Pictures",
            home / "Videos",
            home / "Music",
            home / "OneDrive" / "Desktop",
            home / "OneDrive" / "Documents",
            home / "OneDrive" / "Downloads",
        ]
        return [path for path in candidates if path.exists()]
