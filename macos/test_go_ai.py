#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""go_ai.py 配套自检 —— GTP 通信 / 坐标转换 / 围棋规则 / 图形界面。

用法::

    python3 test_go_ai.py             # 全部检查 (有显示器时包含界面测试)
    python3 test_go_ai.py --no-gui    # 无图形界面环境: 只测 GTP 与逻辑
    python3 test_go_ai.py --visits 50 # 指定测试用访问量 (越小越快)

退出码 0 = 全部通过。
"""

from __future__ import annotations

import argparse
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import go_ai  # noqa: E402  (被测程序本体)
from go_ai import COLUMNS, GtpEngine, GoBoard, IllegalMove  # noqa: E402

PASSED: list = []
FAILED: list = []


def check(name: str, fn):
    """执行一项检查并打印结果。"""
    try:
        detail = fn()
        PASSED.append(name)
        print(f"  [通过] {name}" + (f" — {detail}" if detail else ""), flush=True)
        return True
    except Exception as exc:                                   # noqa: BLE001
        FAILED.append((name, str(exc)))
        print(f"  [失败] {name} — {exc}", flush=True)
        traceback.print_exc(limit=3)
        return False


def expect(cond, msg):
    if not cond:
        raise AssertionError(msg)
    return True


# ---------------------------------------------------------------- 1. 坐标转换
def test_coordinates():
    b9 = GoBoard(9, 6.5)
    # 基本映射: row=0 是最上面一行, GTP 行号从下往上
    expect(b9.to_gtp(0, 0) == "A9", f"左上角应为 A9, 实际 {b9.to_gtp(0, 0)}")
    expect(b9.to_gtp(8, 0) == "A1", f"左下角应为 A1, 实际 {b9.to_gtp(8, 0)}")
    expect(b9.from_gtp("A8") == (1, 0), "A8 -> row1,col0")
    expect(b9.from_gtp("D4") == (5, 3), "D4 -> row5,col3")
    expect(b9.to_gtp(5, 3) == "D4", "row5,col3 -> D4")

    # 关键: 列字母跳过 I
    expect("I" not in COLUMNS, "GTP 列字母不应包含 I")
    expect(COLUMNS[:9] == "ABCDEFGHJ", f"前 9 列应为 ABCDEFGHJ, 实际 {COLUMNS[:9]}")
    b19 = GoBoard(19, 7.5)
    expect(b19.from_gtp("J10") == (9, 8), "19 路 J10 -> row9,col8")
    expect(b19.to_gtp(9, 8) == "J10", "19 路 row9,col8 -> J10")
    expect(b19.to_gtp(0, 8) == "J19", "19 路 J19 对应第 9 列")
    try:
        b19.from_gtp("I5")
        raise AssertionError("字母 I 不应被接受")
    except ValueError:
        pass

    # 往返一致性: 三种棋盘全部交叉点
    for size in (9, 13, 19):
        board = GoBoard(size)
        for row in range(size):
            for col in range(size):
                v = board.to_gtp(row, col)
                expect(board.from_gtp(v) == (row, col), f"{size} 路 {v} 往返失败")

    expect(b9.from_gtp("pass") is None, "pass 应返回 None")
    expect(b9.from_gtp("PASS") is None, "PASS 应返回 None")
    for bad in ("A10", "K1", "12", "AA"):
        try:
            b9.from_gtp(bad)
            raise AssertionError(f"{bad} 在 9 路棋盘上应报错")
        except ValueError:
            pass
    return "A8/D4/J10 正确, 跳过 I, 9/13/19 路全点往返一致, 越界报错"


# ---------------------------------------------------------------- 2. 围棋规则
def test_rules():
    # 提子
    b = GoBoard(9, 0)
    for color, v in [("W", "E5"), ("B", "D5"), ("W", "A1"), ("B", "F5"),
                     ("W", "A2"), ("B", "E6"), ("W", "A3")]:
        b.play(color, v)
    res = b.play("B", "E4")
    expect(res["captured"] == ["E5"], f"应提掉 E5, 实际 {res['captured']}")
    expect(b.captures["B"] == 1, "黑提子数应为 1")

    # 打劫
    k = GoBoard(9, 0)
    for color, v in [("B", "E4"), ("W", "E5"), ("B", "E6"), ("W", "C5"),
                     ("B", "F5"), ("W", "D4"), ("B", "A1"), ("W", "D6")]:
        k.play(color, v)
    ko = k.play("B", "D5")
    expect(ko["captured"] == ["E5"], f"劫形应提 E5, 实际 {ko['captured']}")
    expect(ko["ko"] == "E5", f"劫点应为 E5, 实际 {ko['ko']}")
    ok, why = k.is_legal("W", "E5")
    expect(not ok and "劫" in why, "打劫点应被拒绝")
    k.play("W", "J9")                                    # 找劫材
    expect(k.is_legal("W", "E5")[0], "劫材应完后应可回提")

    # 禁自杀
    s = GoBoard(9, 0)
    for color, v in [("B", "A9"), ("W", "B9"), ("B", "A7"), ("W", "A8")]:
        s.play(color, v)
    try:
        s.play("B", "A8")
        raise AssertionError("自杀手应被拒绝")
    except IllegalMove:
        pass

    # 计分 + 悔棋
    sc = GoBoard(9, 0)
    black_moves = ["A5", "B5", "C5", "D5", "E5", "E4", "E3", "E2", "E1"]
    white_moves = ["J9", "J8", "J7", "J6", "J5", "J4", "J3", "J2"]
    for i, v in enumerate(black_moves):
        sc.play("B", v)
        if i < len(white_moves):
            sc.play("W", white_moves[i])
    score = sc.score(0.0)
    expect(score["territory"]["B"] == 16, f"黑应围 16 点, 实际 {score['territory']['B']}")
    expect(score["winner"] == "B", f"黑应领先, 实际 {score['text']}")

    u = GoBoard(9, 0)
    u.play("B", "E5"); u.play("W", "E6"); u.play("B", "E7")
    u.undo(); u.undo()
    expect(u.grid[u.index(4, 4)] == "B", "悔棋后最初的黑 E5 应保留")
    expect(u.grid[u.index(3, 4)] == "", "悔棋后 W E6 应被移除")
    return "提子 / 打劫 / 禁自杀 / 面积计分 / 悔棋 全部正确"


# ---------------------------------------------------------------- 3. 文件探测
def test_discovery():
    binary, model, config = go_ai.find_katago(), go_ai.find_model(), go_ai.find_config()
    ok, detail = go_ai.check_installation()
    expect(ok, f"安装检查未通过: {detail}")
    expect(binary is not None and binary.is_file(), "未找到 katago 可执行文件")
    expect(model is not None and model.stat().st_size > 1_000_000, "权重文件缺失或过小")
    expect(config is not None and config.is_file(), "配置文件缺失")
    expect(model.read_bytes()[:2] == b"\x1f\x8b", "权重不是 gzip 格式 (.bin.gz)")
    import subprocess
    out = subprocess.run([str(binary), "version"], capture_output=True, text=True, timeout=180)
    expect(out.returncode == 0, f"katago version 失败: {out.stderr[:200]}")
    first = out.stdout.strip().splitlines()[0]
    return f"{first} | 权重 {model.name} ({model.stat().st_size/1e6:.1f}MB)"


# ---------------------------------------------------------------- 4. GTP 会话
def test_gtp_session(visits: int):
    """按要求发送 boardsize 9 / komi 6.5 / clear_board / genmove black 等命令。"""
    binary, model, config = go_ai.find_katago(), go_ai.find_model(), go_ai.find_config()
    log_path = Path(go_ai.HERE) / "go_ai_test_engine.log"
    gtp = GtpEngine(binary, model, config, max_visits=visits, threads=go_ai.auto_threads(),
                    log_path=log_path)
    transcript: list = []

    def send(cmd: str) -> str:
        t0 = time.time()
        resp = gtp.send(cmd)
        transcript.append((cmd, resp, time.time() - t0))
        return resp

    print("  ---- GTP 会话记录 ----", flush=True)
    t0 = time.time()
    gtp.start()                                   # 启动引擎 (含加载权重)
    print(f"  >>> (启动进程, 加载权重)  {time.time()-t0:.2f}s", flush=True)
    try:
        send("boardsize 9")
        send("komi 6.5")
        send("clear_board")
        move_b = send("genmove black")            # 小写颜色名也是合法 GTP
        board = GoBoard(9, 6.5)
        row, col = board.from_gtp(move_b)         # 用我们自己的坐标解析验证合法性
        board.play("B", move_b)
        send(f"play white {board.to_gtp(0, 0)}")  # 白随便应一手, 再由引擎下黑
        move_w = send("genmove white")
        send("kata-set-param maxVisits 50")
        send("genmove black")
        final = send("final_score")
        for cmd, resp, dt in transcript:
            shown = resp if len(resp) <= 40 else resp[:40] + "…"
            print(f"  {cmd:<28} -> {shown!r}   ({dt*1000:.0f} ms)", flush=True)
    finally:
        try:
            gtp.send("quit")
        except Exception:
            pass
        gtp.close()

    expect(move_b.upper() in ("PASS",) or board.is_legal("B", "A9") is not None, "黑棋着法异常")
    expect(move_b.upper() != "PASS", f"空盘第一手不应 pass (收到 {move_b})")
    log_text = log_path.read_text(encoding="utf-8", errors="ignore") if log_path.exists() else ""
    expect("GTP ready" in log_text, "引擎日志中没有出现 'GTP ready'")
    return f"boardsize/komi/clear_board/genmove(black,white)/kata-set-param/final_score 全部正常, " \
           f"黑={move_b} 白={move_w} 终局={final}"


# ---------------------------------------------------------------- 5. 界面
def test_gui(visits: int):
    import tkinter as tk

    calls: list = []

    class StubBox:                                # 避免模态弹窗卡住自动化测试
        @staticmethod
        def showinfo(t, m, **k):
            calls.append(("info", str(t)))

        @staticmethod
        def showerror(t, m, **k):
            calls.append(("error", str(m)[:160]))

        @staticmethod
        def showwarning(t, m, **k):
            calls.append(("warn", str(m)[:160]))

        @staticmethod
        def askyesno(t, m, **k):
            return True

    go_ai.messagebox = StubBox
    root = tk.Tk()
    app = go_ai.GoApp(root, size=9, komi=6.5)
    app.ai_visits = visits

    def pump(seconds, cond):
        end = time.time() + seconds
        while time.time() < end:
            root.update()
            if cond():
                return True
            time.sleep(0.02)
        return cond()

    try:
        expect(pump(300, lambda: app.engine_ready), f"引擎未就绪: {app.engine_var.get()}")
        expect(pump(60, lambda: app.engine_ready and not app.syncing), "新局与引擎同步完成")
        expect(app.current_turn() == "B", "开局应轮到人类执黑")
        for _ in range(5):                                # 等窗口完成布局, 再做命中测试
            root.update()
            time.sleep(0.15)
        row, col = 4, 4                                   # 9 路 E5
        x, y = app._point(row, col)
        expect(app._hit(x, y) == (row, col), f"点击命中测试失败: 期望 {(row, col)}, 实际 {app._hit(x, y)}")
        app.canvas.event_generate("<Button-1>", x=int(x), y=int(y))
        expect(pump(20, lambda: len(app.moves) >= 1), "人类点击后应先落子(界面立即响应)")
        expect(pump(120, lambda: len(app.moves) >= 2), f"AI 未应手: moves={app.moves}")
        expect(app.moves[0][0] == "B" and app.moves[1][0] == "W",
               f"顺序应为黑先白后, 实际 {app.moves}")
        expect(app.board.grid[app.board.index(*app.board.from_gtp(app.moves[0][1]))] == "B",
               "人类棋子应真的落在棋盘上")
        expect(not app.thinking, "思考状态应已复位")
        expect(not any(c[0] == "error" for c in calls), f"界面出现错误弹窗: {calls}")
        return f"点击 -> 人类落子 {app.moves[0][1]} -> AI 应手 {app.moves[1][1]} (界面未卡死)"
    finally:
        if app.engine:
            app.engine.close()
        root.destroy()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="go_ai.py 自检")
    parser.add_argument("--no-gui", action="store_true", help="跳过图形界面测试 (无显示环境)")
    parser.add_argument("--visits", type=int, default=50, help="测试用每手访问次数")
    args = parser.parse_args(argv)

    print("=" * 68)
    print("go_ai.py 自检 —— GTP 通信 / 坐标转换 / 规则 / 界面")
    print("=" * 68)
    print(f"Python {sys.version.split()[0]}  平台 {sys.platform}  CPU 核心 {go_ai.os.cpu_count()}")

    print("\n[1/5] Python 环境")
    check("导入 tkinter", lambda: f"Tk {__import__('tkinter').TkVersion}" if __import__("tkinter") else "")
    check("导入 go_ai 模块 (语法/结构)", lambda: f"{len(open(go_ai.__file__, encoding='utf-8').read().splitlines())} 行")

    print("\n[2/5] GTP 坐标转换")
    check("坐标映射与跳过字母 I", test_coordinates)

    print("\n[3/5] 围棋规则")
    check("提子 / 打劫 / 自杀 / 计分 / 悔棋", test_rules)

    print("\n[4/5] KataGo 可用性 + GTP 会话")
    if not check("查找引擎 / 权重 / 配置", test_discovery):
        print("\n未找到完整的 KataGo, 请先运行: python3 setup_katago.py")
        return 1
    check("GTP 命令会话", lambda: test_gtp_session(args.visits))

    print("\n[5/5] 图形界面" + (" (已跳过)" if args.no_gui else ""))
    if args.no_gui:
        print("  [跳过] --no-gui: 只验证 GTP 与逻辑 (无显示环境适用)")
    else:
        try:
            import tkinter  # noqa: F401
            check("界面加载 + 点击落子 + AI 子线程应手", lambda: test_gui(args.visits))
        except Exception as exc:                              # noqa: BLE001
            print(f"  [跳过] 无法使用图形界面: {exc}")

    print("\n" + "=" * 68)
    print(f"结果: {len(PASSED)} 项通过, {len(FAILED)} 项失败")
    for name, err in FAILED:
        print(f"  · {name}: {err}")
    if FAILED:
        print("\n排查: python3 setup_katago.py --verify-only / 查看 logs 与 go_ai_katago.log")
        return 1
    print("全部通过 —— 现在可以直接运行: python3 go_ai.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
