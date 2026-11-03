@echo off
title Spice Nest Hub - Meesho Login & Session Saver
cd /d "%~dp0"
echo ========================================================
echo    SPICE NEST HUB - MEESHO 1-CLICK SESSION SAVER
echo ========================================================
echo.
echo Browser open hoga, apna Meesho login / verification complete karein.
echo.
".\spice-nest-hub\venv\Scripts\python.exe" "spice-nest-hub\save_meesho_session.py"
echo.
pause
