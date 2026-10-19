@echo off
setlocal

:: ============================================================
:: MoneyPrinterTurbo - Unified Service Launcher for Windows
:: ============================================================

:: Switch to script directory
cd /d "%~dp0"
set "PROJECT_DIR=%CD%"
set "PYTHONPATH=%PROJECT_DIR%"

:: ------------------------------------------------------------
:: Internal Subprocess Handlers (Invoked in child windows)
:: ------------------------------------------------------------
if "%~1"=="_engine" goto :RUN_ENGINE_INTERNAL
if "%~1"=="_bot"    goto :RUN_BOT_INTERNAL
if "%~1"=="_webui"  goto :RUN_WEBUI_INTERNAL

:: ------------------------------------------------------------
:: Locate Python Executable
:: ------------------------------------------------------------
set "PYTHON_EXE="
if exist "%PROJECT_DIR%\.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%PROJECT_DIR%\.venv\Scripts\python.exe"
) else if exist "%PROJECT_DIR%\lib\python\python.exe" (
    set "PYTHON_EXE=%PROJECT_DIR%\lib\python\python.exe"
) else (
    where python >nul 2>nul
    if not errorlevel 1 set "PYTHON_EXE=python"
)

if not defined PYTHON_EXE (
    where uv >nul 2>nul
    if not errorlevel 1 (
        set "PYTHON_EXE=uv run python"
    )
)

if not defined PYTHON_EXE (
    echo.
    echo ============================================================
    echo [ERROR] Python environment not found!
    echo ============================================================
    echo Please ensure dependencies are installed in .venv or Python is on PATH.
    echo ============================================================
    echo.
    pause
    exit /b 1
)

:: Ensure basic configuration files exist
if not exist "%PROJECT_DIR%\config.toml" (
    if exist "%PROJECT_DIR%\config.example.toml" (
        echo [INFO] config.toml not found. Creating from config.example.toml...
        copy "%PROJECT_DIR%\config.example.toml" "%PROJECT_DIR%\config.toml" >nul
    )
)

:: ------------------------------------------------------------
:: Command Line Arguments Support
:: ------------------------------------------------------------
if /i "%~1"=="bot"      goto :START_BOT_AND_ENGINE
if /i "%~1"=="webui"    goto :START_WEBUI
if /i "%~1"=="all"      goto :START_ALL
if /i "%~1"=="engine"   goto :START_ENGINE_ONLY
if /i "%~1"=="bot-only" goto :START_BOT_ONLY
if /i "%~1"=="stop"     goto :STOP_SERVICES
if /i "%~1"=="check"    goto :CHECK_DIAGNOSTICS

:: ------------------------------------------------------------
:: Interactive Menu
:: ------------------------------------------------------------
:MENU
title MoneyPrinterTurbo Launcher
cls
echo ============================================================
echo           MoneyPrinterTurbo - Service Launcher
echo ============================================================
echo   Project Directory: %PROJECT_DIR%
echo   Python:            %PYTHON_EXE%
echo ============================================================
echo.
echo   [1] Telegram Bot + API Engine (Recommended for Telegram)
echo       ^> Launches FastAPI Engine in background window and Bot here
echo.
echo   [2] WebUI Interface
echo       ^> Launches Streamlit WebUI in your default browser
echo.
echo   [3] Full Suite (API Engine + WebUI + Telegram Bot)
echo       ^> Launches Engine and WebUI in background, Bot here
echo.
echo   [4] Core Engine Only
echo       ^> Runs FastAPI backend (http://127.0.0.1:8080)
echo.
echo   [5] Telegram Bot Only
echo       ^> Runs Telegram Bot only (requires Engine already running)
echo.
echo   [6] Diagnostics and Environment Check
echo       ^> Verify Python, FFmpeg, .env, and ports
echo.
echo   [7] Stop Running Services
echo       ^> Terminates Engine, Bot, and WebUI processes
echo.
echo   [0] Exit
echo.
echo ============================================================
set "CHOICE=1"
set /p "CHOICE=Select an option [0-7] (Default: 1): "

if "%CHOICE%"=="1" goto :START_BOT_AND_ENGINE
if "%CHOICE%"=="2" goto :START_WEBUI
if "%CHOICE%"=="3" goto :START_ALL
if "%CHOICE%"=="4" goto :START_ENGINE_ONLY
if "%CHOICE%"=="5" goto :START_BOT_ONLY
if "%CHOICE%"=="6" goto :CHECK_DIAGNOSTICS
if "%CHOICE%"=="7" goto :STOP_SERVICES
if "%CHOICE%"=="0" exit /b 0

echo Invalid choice '%CHOICE%'. Please choose a number from 0 to 7.
ping 127.0.0.1 -n 3 >nul 2>&1
goto :MENU

:: ------------------------------------------------------------
:: Option 1: Start Telegram Bot + Core Engine
:: ------------------------------------------------------------
:START_BOT_AND_ENGINE
call :CHECK_ENV_FILE
title MoneyPrinterTurbo - Telegram Bot
echo.
echo ============================================================
echo [1/2] Launching MoneyPrinterTurbo Core Engine in background...
echo ============================================================
start "MoneyPrinterTurbo - Core Engine" cmd /k ""%~f0" _engine"

echo Waiting for API Engine to initialize on port 8080...
ping 127.0.0.1 -n 5 >nul 2>&1

echo.
echo ============================================================
echo [2/2] Starting Telegram Bot in this window...
echo Press Ctrl+C at any time to stop the bot.
echo ============================================================
echo.
"%PYTHON_EXE%" -m telegram_bot.bot
echo.
echo ============================================================
echo Telegram Bot process ended.
echo ============================================================
pause
exit /b 0

:: ------------------------------------------------------------
:: Option 2: Start WebUI
:: ------------------------------------------------------------
:START_WEBUI
title MoneyPrinterTurbo - WebUI
if exist "%PROJECT_DIR%\webui.bat" (
    call "%PROJECT_DIR%\webui.bat"
) else (
    echo [ERROR] webui.bat not found in %PROJECT_DIR%
    pause
)
exit /b 0

:: ------------------------------------------------------------
:: Option 3: Start Full Suite (Engine + WebUI + Bot)
:: ------------------------------------------------------------
:START_ALL
call :CHECK_ENV_FILE
title MoneyPrinterTurbo - Telegram Bot
echo.
echo ============================================================
echo [1/3] Launching MoneyPrinterTurbo Core Engine...
echo ============================================================
start "MoneyPrinterTurbo - Core Engine" cmd /k ""%~f0" _engine"

echo.
echo ============================================================
echo [2/3] Launching Streamlit WebUI...
echo ============================================================
start "MoneyPrinterTurbo - WebUI" cmd /k ""%~f0" _webui"

echo Waiting for services to initialize...
ping 127.0.0.1 -n 5 >nul 2>&1

echo.
echo ============================================================
echo [3/3] Starting Telegram Bot in this window...
echo ============================================================
echo.
"%PYTHON_EXE%" -m telegram_bot.bot
echo.
echo Bot process ended.
pause
exit /b 0

:: ------------------------------------------------------------
:: Option 4: Core Engine Only
:: ------------------------------------------------------------
:START_ENGINE_ONLY
title MoneyPrinterTurbo - Core Engine
echo.
echo Starting MoneyPrinterTurbo Core Engine on port 8080...
"%PYTHON_EXE%" main.py
echo.
echo Core Engine stopped.
pause
exit /b 0

:: ------------------------------------------------------------
:: Option 5: Telegram Bot Only
:: ------------------------------------------------------------
:START_BOT_ONLY
call :CHECK_ENV_FILE
title MoneyPrinterTurbo - Telegram Bot
echo.
echo Starting Telegram Bot...
"%PYTHON_EXE%" -m telegram_bot.bot
echo.
echo Bot process ended.
pause
exit /b 0

:: ------------------------------------------------------------
:: Option 6: Diagnostics & Environment Check
:: ------------------------------------------------------------
:CHECK_DIAGNOSTICS
if /i not "%~1"=="check" cls
title MoneyPrinterTurbo - Diagnostics Check
echo ============================================================
echo             MoneyPrinterTurbo - System Check
echo ============================================================
echo.
echo [1/5] Checking Python Environment...
if defined PYTHON_EXE (
    echo       Python Runner: %PYTHON_EXE%
    "%PYTHON_EXE%" --version
) else (
    echo       [FAIL] Python not detected.
)
echo.
echo [2/5] Checking FFmpeg (required for video rendering)...
where ffmpeg >nul 2>nul
if not errorlevel 1 (
    for /f "tokens=*" %%v in ('ffmpeg -version 2^>^&1 ^| findstr /i "ffmpeg version"') do echo       %%v
    echo       [OK] FFmpeg found in PATH.
) else (
    echo       [WARNING] FFmpeg not found in PATH!
    echo       Video generation will fail without FFmpeg.
)
echo.
echo [3/5] Checking Configuration Files...
if exist "%PROJECT_DIR%\config.toml" (
    echo       [OK] config.toml exists.
) else (
    echo       [WARNING] config.toml missing.
)
if exist "%PROJECT_DIR%\.env" (
    echo       [OK] .env exists.
    findstr /i "TELEGRAM_BOT_TOKEN=" "%PROJECT_DIR%\.env" | findstr /v "your_bot_token_here" >nul 2>nul
    if not errorlevel 1 (
        echo       [OK] TELEGRAM_BOT_TOKEN appears to be configured.
    ) else (
        echo       [NOTICE] Please ensure TELEGRAM_BOT_TOKEN in .env is set.
    )
) else (
    echo       [WARNING] .env missing. Copy .env.example to .env.
)
echo.
echo [4/5] Checking Directory Permissions and Storage...
if not exist "%PROJECT_DIR%\storage" (
    mkdir "%PROJECT_DIR%\storage" 2>nul
)
if exist "%PROJECT_DIR%\storage" (
    echo       [OK] storage folder exists.
) else (
    echo       [FAIL] Could not create storage directory.
)
echo.
echo [5/5] Checking Core Engine Port 8080...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$c=New-Object System.Net.Sockets.TcpClient; try { $c.Connect('127.0.0.1', 8080); Write-Output '      [INFO] Port 8080 is currently in use (Core Engine might already be running).' } catch { Write-Output '      [OK] Port 8080 is available for Core Engine.' } finally { $c.Dispose() }"
echo.
echo ============================================================
echo Diagnostics check complete.
echo ============================================================
echo.
if /i "%~1"=="check" exit /b 0
pause
goto :MENU

:: ------------------------------------------------------------
:: Option 7: Stop Services
:: ------------------------------------------------------------
:STOP_SERVICES
if exist "%PROJECT_DIR%\stop.bat" (
    call "%PROJECT_DIR%\stop.bat"
) else (
    echo [ERROR] stop.bat not found in %PROJECT_DIR%
    pause
)
if /i "%~1"=="stop" exit /b 0
goto :MENU

:: ------------------------------------------------------------
:: Helper: Check .env file
:: ------------------------------------------------------------
:CHECK_ENV_FILE
if not exist "%PROJECT_DIR%\.env" (
    if exist "%PROJECT_DIR%\.env.example" (
        echo [INFO] .env file not found. Copying template from .env.example...
        copy "%PROJECT_DIR%\.env.example" "%PROJECT_DIR%\.env" >nul
        echo [WARNING] Please make sure to configure TELEGRAM_BOT_TOKEN in .env!
        echo.
    )
)
exit /b 0

:: ------------------------------------------------------------
:: Internal Subprocess Targets
:: ------------------------------------------------------------
:RUN_ENGINE_INTERNAL
title MoneyPrinterTurbo - Core Engine
cd /d "%PROJECT_DIR%"
set "PYTHONPATH=%PROJECT_DIR%"
echo ============================================================
echo MoneyPrinterTurbo Core Engine (FastAPI)
echo Directory: %PROJECT_DIR%
echo ============================================================
if exist "%PROJECT_DIR%\.venv\Scripts\python.exe" (
    set "P_RUN=%PROJECT_DIR%\.venv\Scripts\python.exe"
) else (
    set "P_RUN=python"
)
"%P_RUN%" main.py
echo.
echo ============================================================
echo [WARNING] MoneyPrinterTurbo Engine process has terminated.
echo ============================================================
pause
exit /b 0

:RUN_WEBUI_INTERNAL
title MoneyPrinterTurbo - WebUI
cd /d "%PROJECT_DIR%"
if exist "%PROJECT_DIR%\webui.bat" (
    call "%PROJECT_DIR%\webui.bat"
) else (
    echo [ERROR] webui.bat not found.
)
pause
exit /b 0

:RUN_BOT_INTERNAL
title MoneyPrinterTurbo - Telegram Bot
cd /d "%PROJECT_DIR%"
set "PYTHONPATH=%PROJECT_DIR%"
if exist "%PROJECT_DIR%\.venv\Scripts\python.exe" (
    set "P_RUN=%PROJECT_DIR%\.venv\Scripts\python.exe"
) else (
    set "P_RUN=python"
)
"%P_RUN%" -m telegram_bot.bot
pause
exit /b 0
