@echo off
title MoneyPrinterTurbo Engine
echo Starting MoneyPrinterTurbo Core Engine...
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python main.py
pause
