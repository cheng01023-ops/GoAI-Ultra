@echo off
rem GoAI Ultra - environment self check (GTP / coordinates / rules / GUI)
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY ( echo [X] Python not found. Install Python 3.9+ first. & pause & exit /b 1 )
%PY% test_go_ai.py %*
pause
