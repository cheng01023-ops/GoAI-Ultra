#!/usr/bin/env python3
"""KataGo 性能基准测试 — 用来决定难度、线程数与网络选择。

用法::

    python3 tools/benchmark.py                # 9/13/19 路各测一遍
    python3 tools/benchmark.py --size 19      # 只测 19 路
    python3 tools/benchmark.py --threads 6    # 指定线程数
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gogame import paths  # noqa: E402
from gogame.gtp import GtpEngine  # noqa: E402

OPENINGS = {
    9: ["E5", "C3", "G7", "C7", "G3", "E3", "E7", "C5"],
    13: ["G7", "D10", "K4", "D4", "K10", "G4", "G10", "D7"],
    19: ["D4", "Q16", "Q4", "D16", "C3", "R17", "Q5", "D5"],
}


def measure(model: Path, size: int, threads: int, visits: int, analyze_seconds: float) -> dict:
    with GtpEngine(paths.find_engine(), model, paths.find_config(),
                   override_config={"numSearchThreads": threads},
                   workdir=paths.PROJECT_ROOT) as engine:
        engine.boardsize(size)
        engine.komi(7.5)
        engine.clear_board()
        for i, vertex in enumerate(OPENINGS[size]):
            engine.play("B" if i % 2 == 0 else "W", vertex)
        color = "B"
        t = time.time()
        move, info = engine.genmove_analyze(color, interval_ms=100)
        genmove_time = time.time() - t
        root = engine.root_info(color, seconds=analyze_seconds, interval_ms=200) or {}
        rate = float(root.get("visits", 0)) / analyze_seconds
        return {
            "size": size,
            "move": move,
            "genmove_time": genmove_time,
            "rate": rate,
            "winrate": root.get("winrate"),
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="KataGo 性能基准")
    parser.add_argument("--size", type=int, default=0, help="棋盘大小 (默认依次测 9/13/19)")
    parser.add_argument("--threads", type=int, default=None, help="搜索线程数")
    parser.add_argument("--visits", type=int, default=400, help="genmove 使用的访问量")
    parser.add_argument("--seconds", type=float, default=2.0, help="每次分析计时窗口")
    args = parser.parse_args(argv)

    model = paths.find_model()
    if not (paths.find_engine() and model and paths.find_config()):
        print("未检测到完整的 KataGo 安装, 请先运行: python3 setup_katago.py")
        return 1
    threads = args.threads or max(1, min(16, paths.cpu_count()))
    sizes = [args.size] if args.size else [9, 13, 19]

    print(f"引擎  : {paths.find_engine()}")
    print(f"权重  : {model.name}")
    print(f"线程数: {threads}    CPU 核心: {paths.cpu_count()}")
    print()
    print(f"{'棋盘':>4} {'访问/秒':>10} {'复杂度':>8} {'建议难度':>10} {'预计 400 访问耗时':>18}")
    for size in sizes:
        try:
            r = measure(model, size, threads, args.visits, args.seconds)
        except Exception as exc:  # noqa: BLE001
            print(f"{size:>4}  测试失败: {exc}")
            continue
        per_move = 400.0 / r["rate"] if r["rate"] else float("inf")
        if r["rate"] >= 1500:
            level = "专家/高级"
        elif r["rate"] >= 500:
            level = "高级/中级"
        elif r["rate"] >= 200:
            level = "中级"
        else:
            level = "初级/入门"
        print(f"{size:>4} {r['rate']:>10.0f} {size*size:>8} {level:>10} {per_move:>15.2f}s")
    print()
    print("提示:")
    print("· 表中'访问/秒'越高越好; 换小棋盘、换小网络 (b10c128) 都能显著提速。")
    print("· 觉得慢就降低难度或改玩 9 路; 有 GPU 时可用 setup_katago.py --backend cuda/opencl。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
