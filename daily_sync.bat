@echo off
title Spice Nest Hub - 24h Daily Auto Sync
cd /d "%~dp0"
echo Starting Spice Nest Hub 24h Auto Sync...
".\spice-nest-hub\venv\Scripts\python.exe" daily_sync.py
timeout /t 5
