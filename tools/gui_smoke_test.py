#!/usr/bin/env python3
"""图形界面自动化冒烟测试 — 真正启动窗口与引擎, 模拟点击走完一个回合。

用法::

    python3 tools/gui_smoke_test.py            # 无头运行 (不会弹窗, 弹窗调用被替换成记录)
    python3 tools/gui_smoke_test.py --visits 100

检查项: 引擎加载 → 自动开局 → 人类落子 → AI 应手 → 胜率刷新 → 悔棋 → 形势判断。
退出码 0 表示全部通过。
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import tkinter as tk
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gogame import gui as gui_mod  # noqa: E402
from gogame.gui import GoGameApp  # noqa: E402

CALLS: list[tuple] = []


class RecordingMessageBox:
    """替代 tkinter.messagebox, 避免自动化测试被模态弹窗卡住。"""

    @staticmethod
    def showinfo(title, msg, **kw):
        CALLS.append(("info", title, str(msg)[:200]))

    @staticmethod
    def showerror(title, msg, **kw):
        CALLS.append(("error", title, str(msg)[:300]))

    @staticmethod
    def askyesno(title, msg, **kw):
        CALLS.append(("ask", title, str(msg)[:200]))
        return True

    @staticmethod
    def showwarning(title, msg, **kw):
        CALLS.append(("warn", title, str(msg)[:200]))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GUI 冒烟测试")
    parser.add_argument("--visits", type=int, default=200, help="测试用每手访问次数")
    parser.add_argument("--timeout", type=float, default=240.0, help="启动引擎的最长等待秒数")
    args = parser.parse_args(argv)

    gui_mod.messagebox = RecordingMessageBox
    root = tk.Tk()
    app = GoGameApp(root)
    app.difficulty_var.set("中级 · 每手 400 次")
    app.ai.set_visits(args.visits)

    failures: list[str] = []

    def pump(seconds: float, cond=None) -> bool:
        end = time.time() + seconds
        while time.time() < end:
            root.update()
            if cond and cond():
                return True
            time.sleep(0.02)
        return bool(cond and cond())

    def expect(name: str, cond: bool, detail: str = "") -> None:
        print(("  [通过] " if cond else "  [失败] ") + name + (f" — {detail}" if detail else ""),
              flush=True)
        if not cond:
            failures.append(name)

    print("== 图形界面冒烟测试 ==", flush=True)
    expect("引擎加载完成", pump(args.timeout, lambda: app.engine_ready), app.engine_status_var.get())
    if not app.engine_ready:
        print("引擎未就绪, 请先运行 python3 test_katago.py 排查", flush=True)
        app.on_close()
        return 1
    expect("自动开局", pump(60, lambda: "轮到你" in app.status_var.get() or "新局" in app.status_var.get()),
           app.status_var.get())

    row, col = app.board_size // 2, app.board_size // 2
    x, y = app._point(row, col)
    app.canvas.event_generate("<Button-1>", x=int(x), y=int(y))
    expect("人类落子生效", pump(30, lambda: len(app.moves) >= 1), f"moves={app.moves}")
    expect("AI 应手完成", pump(120, lambda: len(app.moves) >= 2),
           f"moves={app.moves} status={app.status_var.get()}")
    expect("胜率已刷新", app.black_winrate is not None,
           f"黑棋胜率={app.black_winrate} 面板={app.winrate_var.get()!r}")
    expect("AI 分析信息非空", app.info_var.get() != "AI 尚未落子",
           app.info_var.get().replace("\n", " | "))

    sgf = app._build_sgf()
    last_move_sgf = gui_mod.sgf_vertex(app.board, app.moves[-1][1])
    expect("SGF 棋谱可生成",
           sgf.startswith("(;") and sgf.rstrip().endswith(")")
           and "SZ[" in sgf and "KM[" in sgf and f"[{last_move_sgf}]" in sgf,
           sgf.replace("\n", " ")[:110])

    before = len(app.moves)
    app.undo()
    expect("悔棋回到人类回合", pump(60, lambda: len(app.moves) == max(0, before - 2)),
           f"{before} -> {len(app.moves)}")

    app.estimate()
    expect("形势判断返回", pump(90, lambda: any(c[0] == "info" and c[1] == "形势判断" for c in CALLS)),
           "; ".join(c[2].replace("\n", " | ") for c in CALLS if c[0] == "info")[:200])

    if app.moves:
        color, vertex = app.moves[-1]
        if vertex != "pass":
            r, c = app.board.from_gtp(vertex)
            app.canvas.event_generate("<Button-1>",
                                      x=int(app._point(r, c)[0]), y=int(app._point(r, c)[1]))
            pump(2)
            expect("重复落子被拒绝", "不能下在" in app.status_var.get(),
                   app.status_var.get())

    expect("无错误弹窗", not any(c[0] == "error" for c in CALLS),
           "; ".join(c[2] for c in CALLS if c[0] == "error"))

    print("== 结果 ==", flush=True)
    print(f"失败项: {failures if failures else '无'}", flush=True)
    print(f"棋盘 {app.board.size} 路, 手数 {len(app.moves)}, 提子 {app.board.captures}, "
          f"最后状态: {app.status_var.get()}", flush=True)
    app.on_close()
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
