#!/usr/bin/env python3
"""KataGo 人机对战 — 启动入口 (tkinter 图形界面)。

用法::

    python3 play.py            # 直接开始 (缺少引擎时自动提示安装)
    python3 play.py --setup    # 先运行安装器再启动
    python3 play.py --check    # 只做安装与自检, 不开界面
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gogame import paths  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="KataGo 人机对战 (tkinter 图形界面)")
    parser.add_argument("--setup", action="store_true", help="启动前先运行安装/修复流程")
    parser.add_argument("--check", action="store_true", help="只运行安装与自检, 不打开界面")
    parser.add_argument("--model", default=None, help="指定权重文件 (默认自动选择)")
    parser.add_argument("--visits", type=int, default=None, help="每手访问次数")
    parser.add_argument("--threads", type=int, default=None, help="搜索线程数")
    args = parser.parse_args(argv)

    if args.setup or not paths.is_installed():
        from gogame.installer import Installer

        if not paths.is_installed():
            print("未检测到完整的 KataGo 安装, 开始自动安装 (需要联网) …")
        ok = Installer(model_key="b10c128", log=print).run()
        if not ok:
            print("\n安装未完成。可重试: python3 setup_katago.py")
            return 1
        if args.check:
            return 0
        if args.setup:
            return 0

    if args.check:
        from gogame.installer import Installer

        return 0 if Installer(log=print).verify() else 1

    try:
        import tkinter  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        print("无法导入 tkinter: %s" % exc)
        print("· Windows/macOS: 请使用 python.org 官方安装包 (自带 tkinter)")
        print("· Ubuntu/Debian: sudo apt install python3-tk")
        print("· Fedora: sudo dnf install python3-tkinter")
        return 1

    from gogame.gui import GoGameApp
    import tkinter as tk

    root = tk.Tk()
    GoGameApp(root, visits=args.visits, threads=args.threads)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
