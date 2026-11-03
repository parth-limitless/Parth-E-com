@echo off
title Spice Nest - 24H Meesho Buyer Monitor Daemon
echo =====================================================================
echo  SPICE NEST IMPEX - 24-HOUR AUTONOMOUS MEESHO BUYER PRICE MONITOR
echo =====================================================================
echo.
echo [INFO] Working Directory: %~dp0
echo [INFO] Python Virtual Environment: %~dp0venv\Scripts\python.exe
echo [INFO] Scheduler Timezone: Asia/Kolkata (IST = UTC+5:30)
echo [INFO] Interval: Exactly 24 hours between cycles
echo.

cd /d "%~dp0"
"%~dp0venv\Scripts\python.exe" app.py

pause
