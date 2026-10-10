@echo off
rem GoAI Ultra - Go / Weiqi game vs KataGo AI  (double-click to play)
rem NOTE: keep this file ASCII-only, otherwise cmd.exe shows mojibake.
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
  echo [X] Python not found.
  echo     Please install Python 3.9+ from https://www.python.org/downloads/
  echo     During installation, check "Add Python to PATH".
  pause
  exit /b 1
)

%PY% -c "import go_ai,sys; ok,_=go_ai.check_installation(); sys.exit(0 if ok else 1)" 2>nul
if errorlevel 1 (
  echo [*] Preparing KataGo engine ^(needs internet^) ...
  %PY% setup_katago.py
  if errorlevel 1 ( echo [X] Setup failed. Send the text above to the author. & pause & exit /b 1 )
)

echo [*] Starting the game ... ^(you play Black, click an intersection^)
%PY% go_ai.py
if errorlevel 1 ( echo Program exited with an error. Try CHECK-Windows.bat to diagnose. & pause )
