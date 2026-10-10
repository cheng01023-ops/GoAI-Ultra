@echo off
rem GoAI Ultra - one click start (Windows). Do not reorder the lines below.
rem UTF-8 + CRLF + chcp 65001 before any Chinese text; labels instead of ( ) blocks.
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY goto :nopyt

%PY% -c "import go_ai,sys; ok,_=go_ai.check_installation(); sys.exit(0 if ok else 1)" 2>nul
if not errorlevel 1 goto :play

echo.
echo [*] 首次运行: 正在准备 KataGo 引擎与神经网络权重 (需要联网) ...
echo.
%PY% setup_katago.py
if errorlevel 1 goto :setuperr

:play
echo.
echo [*] 开始下棋: 你执黑先行, 鼠标点击交叉点落子
echo.
%PY% go_ai.py
if errorlevel 1 goto :apperr
goto :done

:apperr
echo.
echo [X] 程序异常退出。可双击 CHECK-Windows.bat 查看诊断信息。
goto :done

:setuperr
echo.
echo [X] 准备失败, 请把上面的信息发给分享给你的人。
goto :done

:nopyt
echo [X] 没有找到 Python。
echo     请先安装 Python 3.9+ : https://www.python.org/downloads/
echo     安装时务必勾选 "Add Python to PATH"

:done
chcp 936 >nul
pause
exit /b 0
