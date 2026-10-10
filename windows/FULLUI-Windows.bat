@echo off
rem GoAI Ultra - full GUI (9/13/19 board, handicap, score estimate, SGF export)
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY goto :nopyt

echo.
echo [*] 启动完整版界面 (9/13/19 路、让子、形势判断、SGF 棋谱导出)
echo.
%PY% play.py
goto :done

:nopyt
echo [X] 没有找到 Python, 请先安装 Python 3.9+ 。

:done
chcp 936 >nul
pause
exit /b 0
