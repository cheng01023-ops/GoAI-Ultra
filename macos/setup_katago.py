#!/usr/bin/env python3
"""KataGo 自动安装 / 修复工具 (跨平台)。

示例::

    python3 setup_katago.py                      # 默认安装 (自动选平台与网络)
    python3 setup_katago.py --model b10c384      # 指定更强的网络
    python3 setup_katago.py --backend opencl     # 使用 OpenCL (GPU) 预编译包
    python3 setup_katago.py --force              # 强制重新下载/重装
    python3 setup_katago.py --verify-only        # 只做自检
    python3 setup_katago.py --list-models        # 列出可选网络
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gogame import paths  # noqa: E402
from gogame.installer import DEFAULT_MODEL_KEY, MODELS, Installer  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="自动下载安装 KataGo 引擎与神经网络权重")
    parser.add_argument("--model", default=DEFAULT_MODEL_KEY, choices=sorted(MODELS.keys()),
                        help="要下载的神经网络 (默认 b10c128, CPU 上最快)")
    parser.add_argument("--backend", default="auto",
                        choices=["auto", "eigen", "opencl", "cuda"],
                        help="引擎后端; macOS 会忽略此项并自动源码编译 Eigen 版")
    parser.add_argument("--jobs", type=int, default=None, help="源码编译并行度")
    parser.add_argument("--force", action="store_true", help="忽略已有文件, 强制重新安装")
    parser.add_argument("--verify-only", action="store_true", help="只运行自检")
    parser.add_argument("--list-models", action="store_true", help="列出可下载的网络")
    args = parser.parse_args(argv)

    if args.list_models:
        print("可选网络:")
        for key, spec in MODELS.items():
            mark = " (默认)" if key == DEFAULT_MODEL_KEY else ""
            print(f"  {key:<10} {spec['size_mb']:>3} MB  {spec['desc']}{mark}")
        print("\n更换网络: python3 setup_katago.py --model <名称> --force")
        return 0

    installer = Installer(model_key=args.model, backend=args.backend, jobs=args.jobs,
                          force=args.force, log=lambda m: print(m, flush=True))
    if args.verify_only:
        return 0 if installer.verify() else 1
    return 0 if installer.run() else 1


if __name__ == "__main__":
    raise SystemExit(main())
