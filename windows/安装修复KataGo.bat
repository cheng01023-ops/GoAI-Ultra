@echo off
rem 安装 / 修复 KataGo 引擎与权重
chcp 65001 >nul
cd /d "%~dp0"
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY ( echo 没有找到 Python, 请先安装 Python 3.9+ & pause & exit /b 1 )
%PY% setup_katago.py %*
pause
