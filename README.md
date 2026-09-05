# JARVIS Desktop Voice Assistant

A modular Windows desktop voice assistant built with Python, Tkinter, SpeechRecognition, and pyttsx3.

## Architecture

- `main.py`: starts the GUI and wires every module together.
- `wake_word.py`: runs continuous low-CPU wake-word listening for `"Jarvis"`.
- `voice_engine.py`: handles microphone input and text-to-speech.
- `command_handler.py`: maps spoken commands to built-in actions or AI fallback.
- `system_control.py`: Windows automation such as apps, websites, power, screenshots, and volume.
- `ai_module.py`: OpenAI or Gemini fallback with short memory.
- `gui.py`: dark themed desktop dashboard.
- `utils/`: reusable config/constants.

## Strict Wake Word Flow

1. Assistant stays silent until it hears `"Jarvis"`.
2. If `"Jarvis"` is detected, it immediately says `"Yes sir"`.
3. Only after that response does it listen for the real command.
4. If wake word is not present, it ignores the audio.

The wake-word loop uses short listening windows plus thread pausing to keep CPU usage low while still reacting quickly.

## Features

- Wake word detection: `"Jarvis"`
- Voice recognition with `SpeechRecognition`
- Text to speech with `pyttsx3`
- Continuous background listening
- Open apps and websites
- Google search and YouTube playback
- Time and date
- Shutdown, restart, sleep
- Open files and folders
- Take screenshots
- Volume controls
- AI fallback for unknown commands
- Short conversation memory
- Dark desktop GUI with listening indicator

## Setup

### 1. Create and activate a virtual environment

```powershell
python -m venv .venv
.\.venv\Scripts\activate
```

### 2. Install dependencies

```powershell
pip install -r requirements.txt
```

If `PyAudio` fails to install on Windows, try:

```powershell
pip install pipwin
pipwin install pyaudio
```

### 3. Configure AI API keys (optional)

For OpenAI:

```powershell
$env:OPENAI_API_KEY="your_openai_key"
$env:OPENAI_MODEL="gpt-4o-mini"
```

For Gemini:

```powershell
$env:GEMINI_API_KEY="your_gemini_key"
```

If no API key is set, Jarvis still works for built-in desktop commands.

## Run

```powershell
python main.py
```

## Usage Example

- User: `Jarvis`
- Assistant: `Yes sir`
- User: `Open YouTube`
- Assistant: opens YouTube in the browser

## Notes

- The VS Code path in `system_control.py` is set for the current Windows user profile. Update it if your installation path is different.
- Power commands execute immediately with a 5-second delay for shutdown/restart.
- Screenshots are saved inside the `screenshots/` folder.
- Closing the window hides it; the assistant can keep running in background mode until stopped.
