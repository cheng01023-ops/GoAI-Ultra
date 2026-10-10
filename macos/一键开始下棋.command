#!/bin/bash
# KataGo 围棋人机对战 —— 一键开始
cd "$(dirname "$0")" || exit 1
PY="$(command -v python3 || echo /usr/bin/python3)"
if ! "$PY" -c "import tkinter" 2>/dev/null; then
  echo "缺少 tkinter: sudo apt install python3-tk  (Fedora: sudo dnf install python3-tkinter)"
  read -r -p "按回车键退出..." _
  exit 1
fi
if ! "$PY" -c "import go_ai, sys; ok, _ = go_ai.check_installation(); sys.exit(0 if ok else 1)" 2>/dev/null; then
  echo "正在准备 KataGo 引擎 (需要联网)..."
  if ! "$PY" setup_katago.py; then echo "准备失败"; read -r -p "按回车键退出..." _; exit 1; fi
fi
echo "开始下棋 (你执黑先行, 点击交叉点落子)"
"$PY" go_ai.py
STATUS=$?
if [ $STATUS -ne 0 ]; then echo "程序退出, 代码 $STATUS"; read -r -p "按回车键退出..." _; fi
