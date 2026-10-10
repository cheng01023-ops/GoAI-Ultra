#!/bin/bash
# 环境自检: GTP 通信 / 坐标转换 / 围棋规则 / 图形界面
cd "$(dirname "$0")" || exit 1
PY="$(command -v python3 || echo /usr/bin/python3)"
"$PY" test_go_ai.py "$@"
echo
read -r -p "按回车键关闭窗口..." _
