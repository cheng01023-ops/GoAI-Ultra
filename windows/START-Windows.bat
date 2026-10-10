@echo off
rem KataGo 围棋人机对战 —— Windows 一键开始 (双击本文件)
chcp 65001 >nul
cd /d "%~dp0"

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
  echo [X] 没有找到 Python。
  echo     请先安装 Python 3.9+ : https://www.python.org/downloads/
  echo     安装时务必勾选 "Add Python to PATH"
  pause
  exit /b 1
)

%PY% -c "import go_ai,sys; ok,_=go_ai.check_installation(); sys.exit(0 if ok else 1)" 2>nul
if errorlevel 1 (
  echo [*] 正在准备 KataGo 引擎 ^(需要联网^) ...
  %PY% setup_katago.py
  if errorlevel 1 ( echo [X] 准备失败, 请把上面的信息发给分享给你的人。 & pause & exit /b 1 )
)

echo [*] 开始下棋 ^(你执黑先行, 鼠标点击交叉点落子^)
%PY% go_ai.py
if errorlevel 1 ( echo 程序退出, 可运行 自检.bat 查看诊断。 & pause )
