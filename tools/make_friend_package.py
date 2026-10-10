#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把项目打包成"发给朋友就能用"的精简包 (可按平台定制), 默认输出到桌面。

用法::

    python3 tools/make_friend_package.py --platform windows   # 只给 Windows 用户的包
    python3 tools/make_friend_package.py --platform macos
    python3 tools/make_friend_package.py --platform linux
    python3 tools/make_friend_package.py --platform windows --no-zip

包里只放该平台"必要的文件":
    go_ai.py / test_go_ai.py / setup_katago.py     程序与自检
    gogame/{paths,installer,gtp}.py                安装器依赖的最小模块集
    katago/bin/...                                 该平台引擎 (Windows 版连运行库 DLL 一起带上)
    katago/models/*.bin.gz                         神经网络权重 (各平台通用)
    katago/configs/default_gtp.cfg                 GTP 配置
    一键开始下棋 / 自检 / 安装修复KataGo             双击即用的启动脚本
    使用说明.md                                     给朋友看的说明
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

def _find_project() -> Path:
    """兼容两种布局: 开发目录(根下有 go_ai.py) 与发布仓库(go_ai.py 在 windows/、macos/ 子目录里)。"""
    root = Path(__file__).resolve().parent.parent
    for cand in (root, root / "macos", root / "windows"):
        if (cand / "go_ai.py").is_file():
            return cand
    return root


PROJECT = _find_project()
RELEASE = "https://github.com/lightvector/KataGo/releases/download"
PREBUILT_TAG = "v1.18.1"
CACHE = PROJECT / ".build" / "friend-pkg"
DEFAULT_MODEL = "g170e-b10c128-s1141046784-d204142634.bin.gz"

# 官方预编译包 (macOS 没有官方包, 直接使用本机已编译好的引擎)
PREBUILT = {
    "windows": "katago-" + PREBUILT_TAG + "-eigenavx2-windows-x64.zip",
    "linux": "katago-" + PREBUILT_TAG + "-eigenavx2-linux-x64.zip",
}
PKG_NAMES = {"windows": "GoAI-Ultra-Windows",
             "macos": "GoAI-Ultra-macOS",
             "linux": "GoAI-Ultra-Linux"}
PLATFORM_LABEL = {"windows": "Windows", "macos": "macOS", "linux": "Linux"}

# ----------------------------------------------------------------- 启动脚本
# 注意: Windows 批处理(.bat)里绝对不能出现非 ASCII 字符 —— cmd.exe 按系统 OEM
# 代码页(中文 Windows 是 GBK/CP936)解析批处理文件, 写 UTF-8 中文会显示成
# "鍥存嬬汉鏈哄规垬" 这样的乱码; 纯 ASCII 则与代码页无关, 永远正确。
BAT_MAIN = """@echo off
rem GoAI Ultra - Go / Weiqi game vs KataGo AI  (double-click to play)
rem NOTE: keep this file ASCII-only, otherwise cmd.exe shows mojibake.
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
  echo [X] Python not found.
  echo     Please install Python 3.9+ from https://www.python.org/downloads/
  echo     During installation, check "Add Python to PATH".
  pause
  exit /b 1
)

%PY% -c "import go_ai,sys; ok,_=go_ai.check_installation(); sys.exit(0 if ok else 1)" 2>nul
if errorlevel 1 (
  echo [*] Preparing KataGo engine ^(needs internet^) ...
  %PY% setup_katago.py
  if errorlevel 1 ( echo [X] Setup failed. Send the text above to the author. & pause & exit /b 1 )
)

echo [*] Starting the game ... ^(you play Black, click an intersection^)
%PY% go_ai.py
if errorlevel 1 ( echo Program exited with an error. Try CHECK-Windows.bat to diagnose. & pause )
"""
BAT_FULLUI = """@echo off
rem GoAI Ultra - full GUI (9/13/19 board, handicap, score estimate, SGF export)
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY ( echo [X] Python not found. Install Python 3.9+ first. & pause & exit /b 1 )
%PY% play.py
if errorlevel 1 pause
"""
BAT_SELFCHECK = """@echo off
rem GoAI Ultra - environment self check (GTP / coordinates / rules / GUI)
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY ( echo [X] Python not found. Install Python 3.9+ first. & pause & exit /b 1 )
%PY% test_go_ai.py %*
pause
"""
BAT_SETUP = """@echo off
rem GoAI Ultra - install / repair the KataGo engine and neural network weights
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY ( echo [X] Python not found. Install Python 3.9+ first. & pause & exit /b 1 )
%PY% setup_katago.py %*
pause
"""
SH_MAIN = """#!/bin/bash
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
"""
SH_SELFCHECK = """#!/bin/bash
# 环境自检: GTP 通信 / 坐标转换 / 围棋规则 / 图形界面
cd "$(dirname "$0")" || exit 1
PY="$(command -v python3 || echo /usr/bin/python3)"
"$PY" test_go_ai.py "$@"
echo
read -r -p "按回车键关闭窗口..." _
"""
SH_SETUP = """#!/bin/bash
# 安装 / 修复 KataGo 引擎与权重
cd "$(dirname "$0")" || exit 1
PY="$(command -v python3 || echo /usr/bin/python3)"
"$PY" setup_katago.py "$@"
echo
read -r -p "按回车键关闭窗口..." _
"""


def launchers_for(platform: str) -> dict:
    if platform == "windows":
        # 中文名 + 英文名各一份: 万一解压工具没保留 UTF-8 文件名, 用英文名照样能启动
        return {"START-Windows.bat": BAT_MAIN, "一键开始下棋.bat": BAT_MAIN,
                "FULLUI-Windows.bat": BAT_FULLUI, "完整版界面.bat": BAT_FULLUI,
                "CHECK-Windows.bat": BAT_SELFCHECK, "自检.bat": BAT_SELFCHECK,
                "REPAIR-Windows.bat": BAT_SETUP, "安装修复KataGo.bat": BAT_SETUP}
    names = {"一键开始下棋.sh": SH_MAIN, "自检.sh": SH_SELFCHECK, "安装修复KataGo.sh": SH_SETUP}
    if platform == "macos":
        names.update({"一键开始下棋.command": SH_MAIN, "START-macOS.command": SH_MAIN,
                      "自检.command": SH_SELFCHECK, "安装修复KataGo.command": SH_SETUP})
    else:
        names["START-Linux.sh"] = SH_MAIN
    return names


# ----------------------------------------------------------------- 使用说明
GUIDE = """# KataGo 围棋人机对战 —— 使用说明（{label} 版）

开箱即用的围棋人机对战：**你执黑先行，AI 执白应手**，鼠标点交叉点就能下。
引擎是官方 [KataGo](https://github.com/lightvector/KataGo) v1.18.2，神经网络是 CPU 上最快的 10 层小网络。

## 一、怎么开始

{double_click}

---

## 二、怎么玩

- **落子**：鼠标左键点交叉点（绿色虚线框是预览）。
- **你执黑先行**，AI 自动应手；界面右侧显示"轮到谁 / AI 思考中"。
- **停一手**：双方都停一手即终局，自动数子判胜负。**悔棋**：撤销一个回合。
- **强度**：在"强度"框填数字 → 点"应用"。数字 = AI 每手思考的访问次数：
  100 ≈ 入门、400 ≈ 5 级（默认）、1200 ≈ 1 段、4000 ≈ 更强但更慢。
- **换棋盘**：点 9路 / 13路 / 19路（19 路每手约 1-3 秒，9 路约 0.5 秒）。

坐标：列 A B C D E F G H J K ...（**跳过字母 I**），行从下往上数，例如左上角是 A19。

## 三、常见问题

| 现象 | 处理 |
| --- | --- |
| 双击没反应 / 闪一下就没了 | {python_hint} |
| 提示"没有找到可用的 KataGo" | 弹出询问时选"是"自动安装；或双击 安装修复KataGo（{setup_ext}）|
| 提示引擎无法运行 | 说明引擎不是这台电脑的版本 → 双击 安装修复KataGo 重新获取本机版本 |
| 引擎启动失败 / GTP ready 未出现 | 双击 自检（{check_ext}）看具体原因；日志在本文件夹的 go_ai_katago.log |
| 找不到模型 | 双击 安装修复KataGo 重新下载权重（约 11 MB），确认 katago/models/ 下有 .bin.gz 文件 |
| 权限 / 被系统拦截 | {perm_hint} |
| AI 太慢 | 强度调小（如 150）、改玩 9 路、关掉占 CPU 的程序 |
| 想更强 | 强度调到 1200-4000；或运行 python3 setup_katago.py --model b10c384 换更大网络（更慢）|

## 四、文件夹里有什么

    一键开始下棋 / START-...      <- 双击开始（主入口）
    自检 / 安装修复KataGo          <- 诊断与重装
    go_ai.py                      <- 程序本体（单文件，可单独拷走）
    test_go_ai.py setup_katago.py <- 自检与跨平台安装器
    gogame/                       <- 安装器依赖的最小模块
    katago/bin/                   <- 引擎（{engine_note}）
    katago/models/*.bin.gz        <- 神经网络权重
    katago/configs/default_gtp.cfg<- GTP 配置（中国规则、每手 400 次访问）

祝下棋愉快！
"""


def build_guide(platform: str) -> str:
    label = PLATFORM_LABEL[platform]
    if platform == "windows":
        double = ("双击 **START-Windows.bat** 开始下棋（中文名 **一键开始下棋.bat** 完全等价；\n若文件名乱码请一律用英文名）。\n\n"
                  "前提：电脑装了 **Python 3.9+** —— 到 https://www.python.org/downloads/ 下载安装，\n"
                  "安装时务必勾选 **Add Python to PATH**。程序只用 Python 标准库，不需要 pip 装任何东西。\n"
                  "引擎（含运行库 DLL）与神经网络权重已打包在内，**第一次运行无需联网下载**。")
        python_hint = "缺 Python：到 python.org 装 3.9+，安装时勾选 Add Python to PATH"
        perm_hint = "若被 Windows Defender / SmartScreen 拦下：选【仍要运行】；文件属性里可勾【解除锁定】"
        engine_note = "katago.exe + 运行库 DLL，Windows x64（AVX2）"
    elif platform == "macos":
        double = ("双击 **一键开始下棋.command**（若提示无法打开：右键 -> 打开 -> 打开；\n"
                  "中文名乱码时用 **START-macOS.command**）。\n\n"
                  "前提：python.org 安装的 **Python 3.9+**（自带 tkinter）。引擎为 Apple 芯片原生版；"
                  "Intel Mac 首次运行会自动编译本机版本（需要联网，几分钟）。")
        python_hint = "双击无反应说明缺 python3：到 python.org 装 Python 3.9+"
        perm_hint = "权限不足时，在该文件夹执行：chmod +x *.command *.sh katago/bin/katago"
        engine_note = "macOS 原生引擎（Apple 芯片）"
    else:
        double = ("终端里执行 **./一键开始下棋.sh**（或 bash 一键开始下棋.sh）。\n\n"
                  "前提：sudo apt install python3 python3-tk（Fedora：sudo dnf install python3 python3-tkinter）。\n"
                  "引擎与权重已打包在内，第一次运行无需联网下载。")
        python_hint = "缺 python3：sudo apt install python3 python3-tk"
        perm_hint = "权限不足时：chmod +x *.sh katago/bin/katago"
        engine_note = "Linux x64 引擎（AVX2）"
    return GUIDE.format(label=label, double_click=double, python_hint=python_hint,
                        perm_hint=perm_hint, engine_note=engine_note,
                        setup_ext=".bat" if platform == "windows" else ".sh/.command",
                        check_ext=".bat" if platform == "windows" else ".sh/.command")


# ----------------------------------------------------------------- 工具函数
def log(msg: str) -> None:
    print(msg, flush=True)


def download(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and dest.stat().st_size > 0:
        log("  已缓存 " + dest.name)
        return dest
    log("  下载 " + url)
    req = Request(url, headers={"User-Agent": "KataGo-FriendPackage/1.0"})
    with urlopen(req, timeout=180) as resp, open(dest, "wb") as fh:
        shutil.copyfileobj(resp, fh)
    return dest


def copy_engine(platform: str, dest_bin: Path) -> str:
    """把该平台的引擎 (Windows 还要带运行库 DLL) 放进包里。"""
    dest_bin.mkdir(parents=True, exist_ok=True)
    if platform == "macos":
        src = PROJECT / "katago" / "bin" / "katago"
        if not src.is_file():                                  # 发布仓库布局: macos/katago/bin/
            alt = PROJECT / "macos" / "katago" / "bin" / "katago"
            if alt.is_file():
                src = alt
        if not src.is_file():
            raise SystemExit("本机还没有编译好的 macOS 引擎, 请先运行: python3 setup_katago.py")
        shutil.copy2(src, dest_bin / "katago")
        os.chmod(dest_bin / "katago", 0o755)
        return "本机编译的 macOS 引擎"
    asset = PREBUILT[platform]
    archive = download(RELEASE + "/" + PREBUILT_TAG + "/" + asset, CACHE / asset)
    out = CACHE / archive.stem
    if not out.is_dir():
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(out)
    exe_name = "katago.exe" if platform == "windows" else "katago"
    exe = next((p for p in out.rglob(exe_name) if p.is_file()), None)
    if exe is None:
        raise SystemExit("预编译包里没有找到 " + exe_name)
    shutil.copy2(exe, dest_bin / exe_name)
    os.chmod(dest_bin / exe_name, 0o755)
    dlls = 0
    for dll in exe.parent.glob("*.dll"):
        shutil.copy2(dll, dest_bin / dll.name)
        dlls += 1
    return exe_name + (" + " + str(dlls) + " 个运行库 DLL" if dlls else "")


def copy_source_files(platform: str, dest: Path) -> None:
    for name in ("go_ai.py", "test_go_ai.py", "setup_katago.py"):
        shutil.copy2(PROJECT / name, dest / name)
    (dest / "gogame" / "assets").mkdir(parents=True, exist_ok=True)
    for name in ("__init__.py", "paths.py", "installer.py", "gtp.py"):
        shutil.copy2(PROJECT / "gogame" / name, dest / "gogame" / name)
    shutil.copy2(PROJECT / "gogame" / "assets" / "default_gtp.cfg",
                 dest / "gogame" / "assets" / "default_gtp.cfg")
    (dest / "katago" / "models").mkdir(parents=True, exist_ok=True)
    (dest / "katago" / "configs").mkdir(parents=True, exist_ok=True)
    model = PROJECT / "katago" / "models" / DEFAULT_MODEL
    if not model.is_file():
        models = sorted((PROJECT / "katago" / "models").glob("*.bin.gz"))
        if not models:
            raise SystemExit("项目里没有权重文件, 请先运行 python3 setup_katago.py")
        model = models[0]
    shutil.copy2(model, dest / "katago" / "models" / model.name)
    shutil.copy2(PROJECT / "katago" / "configs" / "default_gtp.cfg",
                 dest / "katago" / "configs" / "default_gtp.cfg")


def make_zip(folder: Path) -> Path:
    zip_path = folder.parent / (folder.name + ".zip")
    if zip_path.exists():
        zip_path.unlink()
    count = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for root, dirs, names in os.walk(folder):
            dirs[:] = sorted(d for d in dirs if d != "__pycache__")
            for name in sorted(names):
                if name.startswith(".") or name.endswith(".pyc"):
                    continue
                p = Path(root) / name
                info = zipfile.ZipInfo(p.relative_to(folder.parent).as_posix(),
                                       date_time=time.localtime(p.stat().st_mtime)[:6])
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (p.stat().st_mode & 0xFFFF) << 16
                info.flag_bits |= 0x800
                z.writestr(info, p.read_bytes())
                count += 1
    log("压缩包: " + str(zip_path) + "  (" + str(count) + " 个文件, "
        + format(zip_path.stat().st_size / 1e6, ".1f") + " MB)")
    return zip_path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="生成发给朋友的精简包")
    parser.add_argument("--platform", default="windows", choices=["windows", "macos", "linux"])
    parser.add_argument("--out", default=str(Path.home() / "Desktop"), help="输出目录 (默认桌面)")
    parser.add_argument("--no-zip", action="store_true", help="只生成文件夹, 不压缩")
    args = parser.parse_args(argv)

    platform = args.platform
    folder = Path(args.out).expanduser() / PKG_NAMES[platform]
    log("== 生成 " + PLATFORM_LABEL[platform] + " 版精简包 ==")
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)

    copy_source_files(platform, folder)
    log("  已复制程序与最小依赖模块")
    log("  已放入引擎: " + copy_engine(platform, folder / "katago" / "bin"))

    names = launchers_for(platform)
    for name, content in names.items():
        path = folder / name
        if name.lower().endswith(".bat"):
            # 批处理: 纯 ASCII + CRLF, 这样在中文/任何区域的 Windows 上都不会乱码
            body = content.replace("\n", "\r\n")
            try:
                body.encode("ascii")
            except UnicodeEncodeError as exc:
                raise SystemExit("批处理模板里出现了非 ASCII 字符, Windows 上会乱码: " + str(exc))
            path.write_bytes(body.encode("ascii"))
        else:
            path.write_text(content, encoding="utf-8")
            if name.endswith((".command", ".sh")):
                os.chmod(path, 0o755)
    # 说明文档: UTF-8 + BOM, Windows 记事本也能正确显示中文
    (folder / "使用说明.md").write_text(build_guide(platform), encoding="utf-8-sig")
    log("  已写入 " + str(len(names)) + " 个启动脚本与 使用说明.md")

    size = sum(p.stat().st_size for p in folder.rglob("*") if p.is_file())
    count = sum(1 for p in folder.rglob("*") if p.is_file())
    log("文件夹: " + str(folder) + "  (" + format(size / 1e6, ".1f") + " MB, " + str(count) + " 个文件)")
    if not args.no_zip:
        make_zip(folder)
    return 0


if __name__ == "__main__":
    sys.exit(main())