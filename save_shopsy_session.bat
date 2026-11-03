@echo off
title Spice Nest Hub - Shopsy / Flipkart Session Saver
cd /d "%~dp0"
echo ========================================================
echo    SPICE NEST HUB - SHOPSY 1-CLICK SESSION SAVER
echo ========================================================
echo.
echo Browser open hoga, apna Shopsy login / verification complete karein.
echo.
".\spice-nest-hub\venv\Scripts\python.exe" "spice-nest-hub\save_shopsy_session.py"
echo.
pause
