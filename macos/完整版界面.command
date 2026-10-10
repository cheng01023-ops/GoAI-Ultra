#!/bin/bash
# 完整版图形界面（9/13/19 路、让子、形势判断、SGF 棋谱导出）
cd "$(dirname "$0")" || exit 1
PY="$(command -v python3 || echo /usr/bin/python3)"
"$PY" play.py
STATUS=$?
if [ $STATUS -ne 0 ]; then echo "程序退出, 代码 $STATUS"; read -r -p "按回车键退出..." _; fi
