@echo off
title MoneyPrinterTurbo Launcher
echo ========================================================
echo   Launching MoneyPrinterTurbo and Telegram Bot Studio   
echo ========================================================
cd /d "%~dp0"

echo [1/2] Starting MoneyPrinterTurbo Core Engine...
start "MoneyPrinterTurbo Engine" cmd /k "cd /d ""%~dp0"" && call .venv\Scripts\activate.bat && python main.py"

echo Waiting 5 seconds for the engine to initialize...
timeout /t 5 /nobreak >nul

echo [2/2] Starting Telegram Bot...
start "MoneyPrinterTurbo Telegram Bot" cmd /k "cd /d ""%~dp0"" && call .venv\Scripts\activate.bat && python -m telegram_bot.bot"

echo ========================================================
echo  Both processes launched in dedicated windows!
echo  You can now open Telegram and send /start to your bot.
echo ========================================================
pause
