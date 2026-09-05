@echo off
setlocal

set "ROOT=%~dp0"
set "PYTHON=%ROOT%.venv\Scripts\python.exe"

if not exist "%PYTHON%" (
    echo Creating virtual environment...
    py -3.12 -m venv "%ROOT%.venv"
    if errorlevel 1 goto :fail
)

echo Installing dependencies...
"%PYTHON%" -m pip install -r "%ROOT%requirements.txt"
if errorlevel 1 goto :fail

echo Starting Jarvice...
"%PYTHON%" "%ROOT%main.py"
goto :eof

:fail
echo Jarvice could not start. Check the messages above.
pause
