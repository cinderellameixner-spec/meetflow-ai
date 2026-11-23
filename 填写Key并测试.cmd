@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" app.py --setup --port 7862
) else (
    python app.py --setup --port 7862
)
if errorlevel 1 pause

