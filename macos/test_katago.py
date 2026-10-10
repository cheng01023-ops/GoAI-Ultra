#!/usr/bin/env python3
"""KataGo 人机对战 — 环境自检 / 连接测试。

依次检查: 运行环境 → 文件完整性 → 围棋规则单元测试 → GTP 协议 → 实际试下 →
完整小棋局对弈。全部通过说明可以正常运行图形界面。

用法::

    python3 test_katago.py             # 全部检查
    python3 test_katago.py --quick     # 跳过完整对局烟测
"""
from __future__ import annotations

import argparse
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gogame import paths  # noqa: E402
from gogame.ai import DIFFICULTY_PRESETS, KataGoAI  # noqa: E402
from gogame.board import GoBoard, IllegalMove  # noqa: E402
from gogame.gtp import GtpEngine  # noqa: E402

RESULTS: list[tuple[bool, str, str]] = []


def check(name: str, fn) -> bool:
    try:
        detail = fn()
        RESULTS.append((True, name, str(detail or "")))
        print(f"  [通过] {name}" + (f" — {detail}" if detail else ""), flush=True)
        return True
    except Exception as exc:  # noqa: BLE001
        RESULTS.append((False, name, str(exc)))
        print(f"  [失败] {name} — {exc}", flush=True)
        traceback.print_exc(limit=3)
        return False


def assert_true(cond, message):
    if not cond:
        raise AssertionError(message)
    return True


# ---------------------------------------------------------------- 规则单测
def test_rules() -> str:
    # 1) 提子: 白 E5 被黑四面围住
    b = GoBoard(9, 0)
    b.play("W", "E5")
    b.play("B", "D5")
    b.play("W", "A1")
    b.play("B", "F5")
    b.play("W", "A2")
    b.play("B", "E6")
    b.play("W", "A3")
    res = b.play("B", "E4")          # 黑落 E4, 提掉白 E5
    assert_true(res.captured == ["E5"], f"应提掉 E5, 实际 {res.captured}")
    assert_true(b.grid[b.index(4, 4)] == "", "E5 应已清空")
    assert_true(b.captures["B"] == 1, f"黑提子数应为 1, 实际 {b.captures['B']}")

    # 2) 打劫: 经典劫形 (黑 D5 提白 E5, 黑 D5 只剩一气)
    k = GoBoard(9, 0)
    for color, vertex in [("B", "E4"), ("W", "E5"), ("B", "E6"), ("W", "C5"),
                          ("B", "F5"), ("W", "D4"), ("B", "A1"), ("W", "D6")]:
        k.play(color, vertex)
    ko_move = k.play("B", "D5")      # 黑提掉白 E5 形成劫
    assert_true(ko_move.captured == ["E5"], f"应提掉 E5, 实际 {ko_move.captured}")
    assert_true(ko_move.ko_point == "E5", f"劫点应为 E5, 实际 {ko_move.ko_point}")
    ok, why = k.is_legal("W", "E5")
    assert_true(not ok, "打劫点应立即禁着")
    k.play("W", "J9")                # 白在别处应一手, 劫解除
    ok, _why = k.is_legal("W", "E5")
    assert_true(ok, "劫材应完后应可以回提")

    # 3) 自杀手
    s = GoBoard(9, 0)
    s.play("B", "A9"); s.play("W", "B9"); s.play("B", "A7"); s.play("W", "A8")
    ok, _why = s.is_legal("B", "A8")
    assert_true(not ok, "自杀手应被禁止")
    try:
        s.play("B", "A8")
        raise AssertionError("自杀手应当抛出 IllegalMove")
    except IllegalMove:
        pass

    # 4) 计分: 黑棋用 "L 形" 围住左下角 16 个空点
    sc = GoBoard(9, 0)
    black_moves = ["A5", "B5", "C5", "D5", "E5", "E4", "E3", "E2", "E1"]
    white_moves = ["J9", "J8", "J7", "J6", "J5", "J4", "J3", "J2"]
    for i, mv in enumerate(black_moves):
        sc.play("B", mv)
        if i < len(white_moves):
            sc.play("W", white_moves[i])
    score = sc.score(0.0)
    assert_true(score.black_territory == 16,
                f"黑应围住 16 个空点, 实际 {score.black_territory}")
    assert_true(score.winner == "B", f"黑应领先, 实际 {score.describe()}")
    return "提子/打劫/自杀/计分 均正确"


def test_undo() -> str:
    b = GoBoard(9, 0)
    b.play("B", "E5")
    b.play("W", "E6")
    b.play("B", "E7")
    b.undo()
    assert_true(b.grid[b.index(2, 4)] == "", "撤销后 B E7 应被移除")
    assert_true(b.grid[b.index(3, 4)] == "W", "撤销后 W E6 应仍在")
    b.undo()
    assert_true(b.grid[b.index(3, 4)] == "", "再撤销后 W E6 应被移除")
    assert_true(b.grid[b.index(4, 4)] == "B", "最初的黑 E5 应仍在")
    # 提子后悔棋要还原被提的子
    c = GoBoard(9, 0)
    for color, vertex in [("W", "E5"), ("B", "D5"), ("W", "A1"), ("B", "F5"),
                          ("W", "A2"), ("B", "E6"), ("W", "A3")]:
        c.play(color, vertex)
    c.play("B", "E4")                       # 提掉白 E5
    assert_true(c.captures["B"] == 1, "黑应提 1 子")
    c.undo()
    assert_true(c.grid[c.index(4, 4)] == "W", "悔棋应恢复被提的白子")
    assert_true(c.captures["B"] == 0, "悔棋后提子数应还原")
    return "悔棋状态还原正确"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="KataGo 环境自检")
    parser.add_argument("--quick", action="store_true", help="跳过完整对局烟测")
    parser.add_argument("--size", type=int, default=9, help="烟测使用的棋盘大小")
    args = parser.parse_args(argv)

    info = paths.system_info()
    print("=" * 66)
    print("KataGo 人机对战 — 环境自检")
    print("=" * 66)
    print(f"系统: {info['os']} / {info['arch']}    CPU 核心: {paths.cpu_count()}    "
          f"Python: {info['python']}")
    print(f"项目目录: {paths.PROJECT_ROOT}")
    print()

    print("[1/6] 文件完整性")
    engine = paths.find_engine()
    model = paths.find_model()
    config = paths.find_config()
    check("引擎可执行文件", lambda: assert_true(engine is not None, "未找到, 请运行 python3 setup_katago.py") and str(engine))
    check("神经网络权重", lambda: assert_true(model is not None, "未找到 .bin.gz, 请运行 python3 setup_katago.py") and f"{model.name} ({model.stat().st_size/1e6:.1f} MB)")
    check("配置文件", lambda: assert_true(config is not None, "缺少 default_gtp.cfg") and str(config))
    if not (engine and model and config):
        print("\n缺少组件, 请先运行: python3 setup_katago.py")
        return 1

    def _gzip_magic() -> str:
        with open(model, "rb") as fh:
            magic = fh.read(2)
        assert_true(magic == b"\x1f\x8b", f"权重文件不是 gzip 格式 (魔数 {magic!r})")
        return "gzip 魔数正确"

    check("权重文件格式", _gzip_magic)

    print("\n[2/6] 引擎版本")
    def _version() -> str:
        import subprocess
        proc = subprocess.run([str(engine), "version"], capture_output=True, text=True, timeout=180)
        assert_true(proc.returncode == 0, f"退出码 {proc.returncode}: {proc.stderr[:200]}")
        return proc.stdout.strip().splitlines()[0]
    check("katago version", _version)

    print("\n[3/6] 围棋规则单元测试")
    check("提子 / 打劫 / 自杀 / 计分", test_rules)
    check("悔棋还原", test_undo)

    print("\n[4/6] GTP 协议连接")
    gtp_holder: dict = {}

    def _start() -> str:
        e = GtpEngine(engine, model, config, workdir=paths.PROJECT_ROOT,
                      log_path=paths.LOGS_DIR / "test_engine.log", startup_timeout=900)
        e.start()
        gtp_holder["e"] = e
        return f"{e.engine_name} 加载完成 ({time.strftime('%H:%M:%S')})"

    if not check("启动引擎并加载权重", _start):
        return 1
    e: GtpEngine = gtp_holder["e"]
    try:
        check("version 命令", lambda: e.version())
        check("boardsize / komi / clear_board", lambda: (e.boardsize(9), e.komi(7.5), e.clear_board()) and "OK")
        check("play 命令", lambda: (e.play("B", "E5"), e.play("W", "E6")) and "OK")
        check("kata-set-param maxVisits", lambda: assert_true(e.set_param("maxVisits", 60), "命令被拒绝") and "maxVisits=60")

        print("\n[5/6] 实际试算 (含计时)")
        def _genmove() -> str:
            t = time.time()
            move, info = e.genmove_analyze("B", interval_ms=100)
            dt = time.time() - t
            assert_true(move and move not in ("", "pass"), f"引擎返回了异常着法: {move!r}")
            wr = info.get("winrate") if info else None
            return (f"落子 {move}, 用时 {dt:.2f}s" + (f", 黑棋胜率 {float(wr)*100:.1f}%" if isinstance(wr, (int, float)) else ""))
        check("genmove_analyze 思考并落子", _genmove)

        def _analyze() -> str:
            root = e.root_info("W", seconds=1.5)
            assert_true(root is not None, "未收到 rootInfo 分析数据")
            return f"胜率 {float(root.get('winrate', 0))*100:.1f}%, 访问 {root.get('visits')}"
        check("kata-analyze 形势判断", _analyze)
        check("final_score", lambda: e.final_score())
    finally:
        e.close()

    print("\n[6/6] 完整小棋局烟测" + (" (已跳过)" if args.quick else ""))
    if not args.quick:
        size = max(5, min(19, args.size))

        def _smoke() -> str:
            ai = KataGoAI(visits=40, threads=max(2, paths.cpu_count() - 1))
            try:
                ai.new_game(size, 7.5)
                board = GoBoard(size, 7.5)
                color = "B"
                moves = 0
                for _ in range(2 * size):
                    move, info = ai.genmove(color)
                    if move in ("pass", "resign"):
                        board.pass_move(color)
                    else:
                        board.play(color, move)
                    moves += 1
                    color = "W" if color == "B" else "B"
                score = board.score(7.5)
                return f"{size}路 双方各下 {moves//2} 手, 当前形势: {score.describe()}"
            finally:
                ai.stop()

        check(f"{size}路完整对弈烟测", _smoke)

    ok = sum(1 for r in RESULTS if r[0])
    bad = [r for r in RESULTS if not r[0]]
    print("\n" + "=" * 66)
    print(f"结果: {ok}/{len(RESULTS)} 项通过")
    if bad:
        print("失败项:")
        for _flag, name, err in bad:
            print(f"  · {name}: {err}")
        print("\n可尝试: python3 setup_katago.py --force 重新安装, 或查看 logs/ 目录下的日志")
        return 1
    print("全部通过 — 可以直接运行: python3 play.py")
    print(f"难度档位: " + ", ".join(f"{name}={visits}次" for _k, name, visits, _d in DIFFICULTY_PRESETS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
