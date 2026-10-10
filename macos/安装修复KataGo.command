#!/bin/bash
# 安装 / 修复 KataGo 引擎与权重
cd "$(dirname "$0")" || exit 1
PY="$(command -v python3 || echo /usr/bin/python3)"
"$PY" setup_katago.py "$@"
echo
read -r -p "按回车键关闭窗口..." _
