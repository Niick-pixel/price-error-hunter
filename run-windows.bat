@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo First run - setting up a local Python environment...
    python -m venv .venv || goto :fail
    ".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
    ".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt || goto :fail
)

".venv\Scripts\python.exe" -m glitchguard
goto :eof

:fail
echo.
echo Setup failed. Make sure Python 3.9+ is installed and on your PATH.
pause
