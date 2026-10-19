@echo off
setlocal
cd /d "%~dp0"
title MoneyPrinterTurbo - Stop Services

echo ============================================================
echo           MoneyPrinterTurbo - Stopping Services
echo ============================================================
echo.

:: Stop Core Engine on Port 8080 if active
echo [*] Checking for Core Engine on port 8080...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$conn = Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue; if ($conn) { foreach ($p in $conn.OwningProcess | Select-Object -Unique) { try { Stop-Process -Id $p -Force -ErrorAction SilentlyContinue; Write-Output \"    Stopped Core Engine (PID: $p)\" } catch {} } } else { Write-Output '    No Core Engine found running on port 8080.' }"

:: Stop any running Telegram Bot python processes
echo.
echo [*] Checking for Telegram Bot process...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$procs = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'telegram_bot\.bot' }; if ($procs) { foreach ($p in $procs) { try { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue; Write-Output \"    Stopped Telegram Bot (PID: $($p.ProcessId))\" } catch {} } } else { Write-Output '    No Telegram Bot process found.' }"

:: Stop Streamlit WebUI on Port 8501 if active
echo.
echo [*] Checking for WebUI on port 8501...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$conn = Get-NetTCPConnection -LocalPort 8501 -State Listen -ErrorAction SilentlyContinue; if ($conn) { foreach ($p in $conn.OwningProcess | Select-Object -Unique) { try { Stop-Process -Id $p -Force -ErrorAction SilentlyContinue; Write-Output \"    Stopped WebUI (PID: $p)\" } catch {} } } else { Write-Output '    No WebUI found running on port 8501.' }"

echo.
echo ============================================================
echo Services stop routine complete.
echo ============================================================
echo.
if /i not "%~1"=="--silent" pause
