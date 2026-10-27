@echo off
cd /d %~dp0
if not exist venv (
  python -m venv venv
  call venv\Scripts\activate
  pip install -r requirements.txt
  playwright install chromium
) else (
  call venv\Scripts\activate
)
start "" cmd /c "ping -n 6 127.0.0.1 >nul & start http://localhost:5000"
python app.py
pause
