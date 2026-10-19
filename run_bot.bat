@echo off
title MoneyPrinterTurbo Telegram Bot
echo Starting MoneyPrinterTurbo Telegram Bot...
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python -m telegram_bot.bot
pause
