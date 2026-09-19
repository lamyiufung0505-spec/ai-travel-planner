@echo off
cd /d %~dp0

if not exist ".venv" (
    echo First run: creating venv and installing dependencies...
    python -m venv .venv
    call .venv\Scripts\activate.bat
    pip install -r requirements.txt
)

echo.
echo Backend starting at http://0.0.0.0:8000  (LAN accessible)
echo Health check: http://127.0.0.1:8000/health
echo To stop: close this window or press Ctrl+C
echo.

.venv\Scripts\python -m uvicorn main:app --host 0.0.0.0 --port 8000
