@echo off
setlocal
set PYTHONUTF8=1
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Install this checkout into .venv first. See docs\STUDIO_TERMINAL.md.
  pause
  exit /b 1
)
if "%~1"=="" (
  ".venv\Scripts\python.exe" -m cli.main workspace
) else (
  ".venv\Scripts\python.exe" -m cli.main %*
)
pause
