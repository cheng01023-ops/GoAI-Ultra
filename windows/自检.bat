@echo off
rem GoAI Ultra - environment self check (GTP / coordinates / rules / GUI)
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY goto :nopyt

echo.
echo [*] 环境自检: GTP 通信 / 坐标转换 / 围棋规则 / 图形界面
echo.
%PY% test_go_ai.py %*
goto :done

:nopyt
echo [X] 没有找到 Python, 请先安装 Python 3.9+ 。

:done
chcp 936 >nul
pause
exit /b 0
