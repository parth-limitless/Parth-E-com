@echo off
title Spice Nest 24x7 Telegram Bot
cd /d "%~dp0spice-nest-hub"
if exist venv\Scripts\python.exe (
    venv\Scripts\python.exe telegram_bot.py
) else (
    python telegram_bot.py
)
pause
