@echo off
rem GoAI Ultra - SAFE launcher (pure ASCII). Use this if the Chinese text in
rem START-Windows.bat shows as garbage on your machine.
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY goto :nopyt

%PY% -c "import go_ai,sys; ok,_=go_ai.check_installation(); sys.exit(0 if ok else 1)" 2>nul
if not errorlevel 1 goto :play

echo [*] Preparing KataGo engine (needs internet) ...
%PY% setup_katago.py
if errorlevel 1 goto :setuperr

:play
echo [*] Starting the game ... (you play Black, click an intersection)
%PY% go_ai.py
goto :done

:setuperr
echo [X] Setup failed. Send the text above to the author.
goto :done

:nopyt
echo [X] Python not found. Install Python 3.9+ from https://www.python.org/downloads/

:done
pause
exit /b 0
