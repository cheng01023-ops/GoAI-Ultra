#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""KataGo 围棋人机对战 —— 单文件跨平台版 (Windows / macOS / Linux)

功能
----
* 人类执黑先行, AI 执白自动应手; 鼠标点击落子。
* 默认 9 路棋盘, 改配置区 BOARD_SIZE 即可切换 19 路 (界面里也能随时切换)。
* 完整的 GTP 坐标转换: 列 A-T **跳过字母 I** (如 A8 / D4 / J10)。
* 界面显示网格、星位、黑白子、当前轮到谁、AI 思考状态与胜率。
* AI 思考放在**子线程**执行 genmove; 子线程只往 queue 里放结果,
  主线程用 root.after 定时轮询队列并刷新界面 (tkinter 不是线程安全的,
  after() 必须由主线程调用, 这是"回主线程更新 UI"的正确写法), 界面绝不卡死。
* 自动启动 KataGo 子进程并收发 GTP 命令, 全程异常处理 + 友好弹窗。
* KataGo / 模型 / 配置文件既可在配置区写死, 也可用环境变量覆盖, 还会自动搜索
  与本文件同级的 katago/ 目录。

运行
----
    python3 go_ai.py                 # 直接开玩
    KATAGO_BIN=/path/katago python3 go_ai.py       # 用环境变量指定引擎
    python3 test_go_ai.py            # 配套自检 (GTP 通信 / 坐标 / 规则 / 界面)

环境变量
--------
    KATAGO_BIN     KataGo 可执行文件路径
    KATAGO_MODEL   神经网络权重 (.bin.gz) 路径
    KATAGO_CONFIG  GTP 配置文件 (.cfg) 路径
"""

from __future__ import annotations

import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import traceback
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

# ============================================================================
# ① 配置区 —— 想调什么改这里就行
# ============================================================================

BOARD_SIZE = 9            # 棋盘大小: 9 (默认) / 13 / 19, 改这里即可
KOMI = 6.5                # 贴目 (9 路常用 6.5 / 7.5)
MAX_VISITS = 400          # AI 强度: 每手搜索的神经网络访问次数 (越大越强越慢)
NUM_SEARCH_THREADS = 0    # 搜索线程数, 0 = 自动 (CPU 核心数 - 1, 上限 16)
HUMAN_COLOR = "B"         # 人类执黑先行
AI_COLOR = "W"            # AI 执白

GTP_TIMEOUT = 600.0       # 单条 GTP 命令超时秒数 (首次 genmove 需加载模型, 给足时间)
STARTUP_TIMEOUT = 900.0   # 启动引擎 (含加载权重) 的超时
DEBUG_GTP = False         # True 则把每条 GTP 收发打印到控制台, 便于排查

# 显式路径 (留空字符串则自动搜索; 也可以用环境变量 KATAGO_BIN / KATAGO_MODEL / KATAGO_CONFIG)
KATAGO_BIN = ""
KATAGO_MODEL = ""
KATAGO_CONFIG = ""

# 自动搜索权重时的优先顺序 (找不到第一个就找下一个)
PREFERRED_MODELS = (
    "g170e-b10c128-s1141046784-d204142634.bin.gz",   # 小网络, CPU 最快
    "b10c384h6nbttflrs.bin.gz",                      # 现代小网络, 更强但更慢
)
DEFAULT_CONFIG_NAME = "default_gtp.cfg"              # 本程序会自动生成这个配置

# 找不到 KataGo 时的提示 (弹窗 + 控制台都会显示)
MISSING_KATAGO_HINT = """没有找到可用的 KataGo 引擎 / 模型 / 配置文件。

本程序会自动搜索以下位置:
  1) 配置区 KATAGO_BIN / KATAGO_MODEL / KATAGO_CONFIG 或同名环境变量
  2) 与本文件同级的 katago/ 目录 (katago/bin/katago、katago/models/*.bin.gz、katago/configs/*.cfg)
  3) 系统 PATH 里的 katago

获取方式 (任选其一):
  · 一键安装 (推荐): 在项目目录执行  python3 setup_katago.py
      - Windows / Linux x64 : 会自动下载官方预编译包 (CPU 用 Eigen 后端, 显卡可用 OpenCL/CUDA)
      - macOS               : 官方没有预编译包, 会自动源码编译 (CMake + Eigen)
  · 手动下载: https://github.com/lightvector/KataGo/releases
      引擎: katago-*-eigen-windows-x64.zip / katago-*-eigen-linux-x64.zip (CPU 版)
      权重: https://katagoarchive.org/g170/neuralnets/  (推荐 g170e-b10c128-...bin.gz, 约 11 MB)
      解压后摆成:  katago/bin/katago[.exe]  +  katago/models/xxx.bin.gz  +  katago/configs/default_gtp.cfg
  · macOS 也可 brew install katago, 然后 export KATAGO_BIN=$(which katago)
"""

# ============================================================================
# ② 常量与路径探测
# ============================================================================

# GTP 列字母: 标准围棋坐标跳过字母 I, 所以是 A B C D E F G H J K L M N O P Q R S T
COLUMNS = "ABCDEFGHJKLMNOPQRSTUVWXYZ"

STAR_POINTS = {
    9: [(2, 2), (2, 6), (6, 2), (6, 6), (4, 4)],
    13: [(3, 3), (3, 9), (9, 3), (9, 9), (6, 6)],
    19: [(3, 3), (3, 9), (3, 15), (9, 3), (9, 9), (9, 15), (15, 3), (15, 9), (15, 15)],
}

HERE = Path(__file__).resolve().parent           # 本文件所在目录
KATAGO_DIR = HERE / "katago"                     # 默认约定的引擎目录


def _exe_names() -> tuple:
    return ("katago.exe", "katago") if os.name == "nt" else ("katago", "katago.exe")


def _first_existing(paths) -> Path | None:
    for p in paths:
        if p and Path(p).is_file() and (os.name == "nt" or os.access(p, os.X_OK)):
            return Path(p).resolve()
    return None


def find_katago(explicit: str = "") -> Path | None:
    """按优先级查找 KataGo 可执行文件。"""
    candidates = [
        explicit or KATAGO_BIN,
        os.environ.get("KATAGO_BIN", ""),
        *[KATAGO_DIR / "bin" / n for n in _exe_names()],
        *[KATAGO_DIR / n for n in _exe_names()],
        *[HERE / n for n in _exe_names()],
    ]
    found = _first_existing(candidates)
    if found:
        return found
    which = shutil.which("katago")                   # 最后再找系统 PATH
    return Path(which).resolve() if which else None


def find_model(explicit: str = "") -> Path | None:
    """查找神经网络权重, 优先 PREFERRED_MODELS 里的小网络。"""
    for cand in (explicit or KATAGO_MODEL, os.environ.get("KATAGO_MODEL", "")):
        if cand and Path(cand).is_file():
            return Path(cand).resolve()
    model_dir = KATAGO_DIR / "models"
    for name in PREFERRED_MODELS:
        p = model_dir / name
        if p.is_file():
            return p.resolve()
    if model_dir.is_dir():
        models = sorted(model_dir.glob("*.bin.gz"))
        if models:
            return models[0].resolve()
    return None


def find_config(explicit: str = "") -> Path | None:
    """查找 GTP 配置; 找不到就自动生成一份最小可用配置。"""
    for cand in (explicit or KATAGO_CONFIG, os.environ.get("KATAGO_CONFIG", ""),
                 KATAGO_DIR / "configs" / DEFAULT_CONFIG_NAME,
                 KATAGO_DIR / "configs" / "gtp_example.cfg"):
        if cand and Path(cand).is_file():
            return Path(cand).resolve()
    cfg_dir = KATAGO_DIR / "configs"
    try:                                             # 自动生成默认配置
        cfg_dir.mkdir(parents=True, exist_ok=True)
        target = cfg_dir / DEFAULT_CONFIG_NAME
        target.write_text(DEFAULT_CONFIG_TEXT, encoding="utf-8")
        return target.resolve()
    except OSError:
        return None


# 自动生成的最小配置 (注意: logDir 与 logFile 不能同时出现, 否则 KataGo 拒绝启动)
DEFAULT_CONFIG_TEXT = """# KataGo GTP 配置 (go_ai.py 自动生成)
logDir = logs
logAllGTPCommunication = false
logSearchInfo = false
logToStderr = false
rules = chinese
allowResignation = false
maxVisits = 400
ponderingEnabled = false
numSearchThreads = 4
nnMaxBatchSize = 16
chosenMoveTemperature = 0.0
chosenMoveTemperatureEarly = 0.0
reportAnalysisWinratesAs = BLACK
"""


def auto_threads() -> int:
    """默认搜索线程数: 留一个核给界面, 最多 16。"""
    if NUM_SEARCH_THREADS > 0:
        return int(NUM_SEARCH_THREADS)
    cores = os.cpu_count() or 2
    return max(1, min(16, cores - 1 if cores > 2 else cores))


def engine_runs(binary: Path, timeout: float = 30.0) -> tuple:
    """试跑 katago version, 判断这个可执行文件在当前系统上能不能用。

    拷贝给别人 / 换系统最常见的坑就是: 文件在, 但架构不对 (例如把 macOS 的二进制拿到
    Windows 或 Intel 机器上), 这里提前发现并给出提示。
    """
    try:
        proc = subprocess.run([str(binary), "version"], capture_output=True, text=True, timeout=timeout)
    except Exception as exc:                                      # noqa: BLE001
        return False, f"无法执行: {exc}"
    if proc.returncode != 0:
        return False, ((proc.stderr or proc.stdout).strip()[:160] or f"退出码 {proc.returncode}")
    first = proc.stdout.strip().splitlines()
    return True, (first[0] if first else "OK")


def find_installer() -> Path | None:
    """同目录下的一键安装脚本 (打包分发时随程序一起带上)。"""
    for name in ("setup_katago.py", "install_katago.py"):
        candidate = HERE / name
        if candidate.is_file():
            return candidate
    return None


def auto_install(progress=print) -> tuple:
    """调用同目录的 setup_katago.py 自动下载/编译引擎+权重, 返回 (是否成功, 说明)。"""
    script = find_installer()
    if script is None:
        return False, "同目录没有找到 setup_katago.py, 请手动下载引擎后放到 katago/bin/"
    progress(f"开始自动安装: {script}")
    try:
        proc = subprocess.run([sys.executable, str(script)], cwd=str(HERE), timeout=3600)
    except Exception as exc:                                      # noqa: BLE001
        return False, f"安装脚本执行失败: {exc}"
    if proc.returncode == 0:
        return True, "安装完成"
    return False, f"安装脚本退出码 {proc.returncode} (详情见上一条输出)"


def check_installation(verify_runs: bool = True) -> tuple:
    """返回 (是否可用, 说明文字)。启动时用它做检查并决定是否弹窗。"""
    binary, model, config = find_katago(), find_model(), find_config()
    problems = []
    if binary is None:
        problems.append("引擎可执行文件 (katago)")
    if model is None:
        problems.append("神经网络权重 (*.bin.gz)")
    if config is None:
        problems.append("GTP 配置文件 (*.cfg)")
    if problems:
        return False, "缺少: " + "、".join(problems)
    if verify_runs:
        ok, detail = engine_runs(binary)
        if not ok:
            return False, (f"找到的引擎 {binary.name} 在本机无法运行: {detail}\n"
                           "(多半是从别的系统/架构拷贝过来的, 需要换成本机版本)")
    return True, f"引擎: {binary}\n权重: {model.name} ({model.stat().st_size / 1e6:.1f} MB)\n配置: {config}"


# ============================================================================
# ③ GTP 协议客户端 (子进程 + 读取线程 + 队列, 支持超时, 不会卡死界面)
# ============================================================================

class GtpError(Exception):
    """GTP 通信错误 (引擎返回 '?' 或进程退出 / 超时)。"""


class GtpEngine:
    """KataGo GTP 子进程封装。

    只做最必要的事: 启动进程、发送命令、读回响应、关闭进程。
    读取用独立线程 + 队列, 因此 send() 可以安全地设置超时。
    """

    def __init__(self, binary, model, config, max_visits=None, threads=None,
                 log_path: Path | None = None, debug: bool = DEBUG_GTP):
        self.binary = Path(binary)
        self.model = Path(model)
        self.config = Path(config)
        self.max_visits = int(max_visits or MAX_VISITS)
        self.threads = int(threads or auto_threads())
        self.log_path = Path(log_path) if log_path else (HERE / "go_ai_katago.log")
        self.debug = debug

        self._proc: subprocess.Popen | None = None
        self._queue: "queue.Queue[str]" = queue.Queue()
        self._reader: threading.Thread | None = None
        self._err_thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._stderr_tail: list = []
        self.engine_name = "KataGo"

    # ---------------------------------------------------------------- 生命周期
    def command(self) -> list:
        cmd = [str(self.binary), "gtp", "-model", str(self.model), "-config", str(self.config)]
        overrides = {
            "maxVisits": self.max_visits,
            "numSearchThreads": self.threads,
            "ponderingEnabled": "false",
            "logSearchInfo": "false",
            "logAllGTPCommunication": "false",
            "reportAnalysisWinratesAs": "BLACK",
        }
        cmd += ["-override-config", ",".join(f"{k}={v}" for k, v in overrides.items())]
        return cmd

    def start(self) -> "GtpEngine":
        if self.alive:
            return self
        kwargs = dict(stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                      text=True, encoding="utf-8", errors="replace", bufsize=1, cwd=str(HERE))
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            self._proc = subprocess.Popen(self.command(), **kwargs)
        except OSError as exc:
            raise GtpError(f"无法启动 KataGo: {exc}\n命令: {' '.join(self.command())}") from None

        self._reader = threading.Thread(target=self._read_loop, name="gtp-reader", daemon=True)
        self._reader.start()
        self._err_thread = threading.Thread(target=self._stderr_loop, name="gtp-stderr", daemon=True)
        self._err_thread.start()

        # 首次握手: 引擎在这一步加载神经网络, 可能要几秒到几十秒
        self.engine_name = self.send("name", timeout=STARTUP_TIMEOUT).strip() or "KataGo"
        return self

    def close(self) -> None:
        proc = self._proc
        if proc is None:
            return
        try:
            if proc.poll() is None and proc.stdin:
                proc.stdin.write("quit\n")
                proc.stdin.flush()
                proc.wait(timeout=10)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        finally:
            self._proc = None

    def kill(self) -> None:
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.kill()
            except Exception:
                pass

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    @property
    def stderr_tail(self) -> str:
        return "".join(self._stderr_tail[-20:])

    # ---------------------------------------------------------------- 收发
    def _read_loop(self) -> None:
        """后台线程: 持续把引擎 stdout 的每一行放进队列。"""
        proc = self._proc
        assert proc and proc.stdout
        try:
            for line in proc.stdout:
                self._queue.put(line)
        except Exception:
            pass
        finally:
            self._queue.put("")            # 空串 = 进程结束的哨兵

    def _stderr_loop(self) -> None:
        """后台线程: 收集 stderr 并写日志 (不这样做管道写满会让引擎阻塞)。"""
        proc = self._proc
        assert proc and proc.stderr
        fh = None
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            fh = open(self.log_path, "a", encoding="utf-8")
            fh.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} 引擎启动 =====\n")
        except OSError:
            fh = None
        try:
            for line in proc.stderr:
                self._stderr_tail.append(line)
                del self._stderr_tail[:-40]
                if fh:
                    fh.write(line)
                    fh.flush()
        except Exception:
            pass
        finally:
            if fh:
                fh.close()

    def send(self, command: str, timeout: float | None = None) -> str:
        """发送一条 GTP 命令并返回响应正文; '?' 响应抛 GtpError。"""
        if not self.alive:
            raise GtpError("KataGo 进程未运行")
        with self._lock:                                    # 同一时刻只允许一条命令
            if self.debug:
                print(f">>> {command}", flush=True)
            try:
                self._proc.stdin.write(command + "\n")
                self._proc.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                raise GtpError(f"无法向 KataGo 写入命令: {exc}") from None
            text = self._read_response(command, timeout or GTP_TIMEOUT)
            if self.debug:
                print(f"<<< {text!r}", flush=True)
            return text

    def _read_response(self, command: str, timeout: float) -> str:
        deadline = time.time() + timeout
        status: str | None = None
        body: list = []
        while True:
            remain = deadline - time.time()
            if remain <= 0:
                raise GtpError(f"等待 {command!r} 的响应超时 ({timeout:.0f}s)")
            try:
                line = self._queue.get(timeout=min(remain, 0.5))
            except queue.Empty:
                continue
            if line == "":                                   # 哨兵: 进程退出
                raise GtpError("KataGo 进程已退出。" + self.stderr_tail[-400:])
            text = line.rstrip("\r\n")
            if status is None:
                if text[:1] in ("=", "?"):                   # 跳过启动横幅, 直到响应行
                    status = text[0]
                    rest = text[1:].strip()
                    if rest:
                        body.append(rest)
                continue
            if text.strip() == "":                           # 空行 = 响应结束 (GTP 规范)
                break
            body.append(text)
        payload = "\n".join(body).strip()
        if status == "?":
            raise GtpError(f"{command} 失败: {payload}")
        return payload

    # ---------------------------------------------------------------- 常用命令
    def send_ok(self, command: str) -> tuple:
        """不抛异常的 send, 返回 (是否成功, 文本)。"""
        try:
            return True, self.send(command)
        except GtpError as exc:
            return False, str(exc)

    def version(self) -> str:
        return self.send("version", timeout=60)

    def boardsize(self, size: int) -> str:
        return self.send(f"boardsize {int(size)}")

    def komi(self, value: float) -> str:
        return self.send(f"komi {value}")

    def clear_board(self) -> str:
        return self.send("clear_board")

    def play(self, color: str, vertex: str) -> str:
        return self.send(f"play {color} {vertex}")

    def genmove(self, color: str) -> str:
        """让引擎思考并落子, 返回如 'D4' / 'pass' / 'resign'。"""
        text = self.send(f"genmove {color}")
        first = text.splitlines()[0].strip() if text else "pass"
        return first.split()[0] if first else "pass"

    def set_max_visits(self, visits: int) -> bool:
        """运行时调整 AI 强度 (KataGo 扩展命令)。"""
        ok, _ = self.send_ok(f"kata-set-param maxVisits {int(visits)}")
        if ok:
            self.max_visits = int(visits)
        return ok

    def final_score(self) -> str:
        ok, text = self.send_ok("final_score")
        return text if ok else ""


# ============================================================================
# ④ 围棋规则 (提子 / 打劫 / 禁自杀 / 面积计分 / 悔棋)
# ============================================================================

class IllegalMove(ValueError):
    """非法着法。"""


class GoBoard:
    def __init__(self, size: int = BOARD_SIZE, komi: float = KOMI):
        self.size = int(size)
        self.komi = float(komi)
        self.grid = [""] * (self.size * self.size)   # 行优先: index = row * size + col
        self.ko_point: int | None = None
        self.captures = {"B": 0, "W": 0}
        self.consecutive_passes = 0
        self.history: list = []

    # ---------------------------------------------------------------- 坐标转换
    def to_gtp(self, row: int, col: int) -> str:
        """(row, col) -> GTP 坐标; row=0 是最上面一行, 行号从下往上数。"""
        if not (0 <= row < self.size and 0 <= col < self.size):
            raise ValueError(f"坐标越界: row={row} col={col}")
        return f"{COLUMNS[col]}{self.size - row}"

    def from_gtp(self, vertex: str):
        """GTP 坐标 -> (row, col); 'pass' 返回 None; 非法坐标抛 ValueError。"""
        v = (vertex or "").strip().upper()
        if v in ("PASS", ""):
            return None
        if len(v) < 2 or v[0] not in COLUMNS:
            raise ValueError(f"无法识别的 GTP 坐标: {vertex!r} (列字母跳过 I)")
        col = COLUMNS.index(v[0])
        if not v[1:].isdigit():
            raise ValueError(f"无法识别的 GTP 坐标: {vertex!r}")
        row = self.size - int(v[1:])
        if not (0 <= row < self.size and 0 <= col < self.size):
            raise ValueError(f"坐标超出 {self.size} 路棋盘: {vertex!r}")
        return row, col

    def index(self, row: int, col: int) -> int:
        return row * self.size + col

    def rc(self, idx: int):
        return divmod(idx, self.size)

    def neighbors(self, idx: int):
        row, col = self.rc(idx)
        if row > 0:
            yield idx - self.size
        if row < self.size - 1:
            yield idx + self.size
        if col > 0:
            yield idx - 1
        if col < self.size - 1:
            yield idx + 1

    def _group(self, idx: int):
        """返回 (同色连通块, 该块的气)。"""
        color = self.grid[idx]
        stones, liberties, stack, seen = {idx}, set(), [idx], {idx}
        while stack:
            cur = stack.pop()
            for n in self.neighbors(cur):
                c = self.grid[n]
                if c == "":
                    liberties.add(n)
                elif c == color and n not in seen:
                    seen.add(n)
                    stones.add(n)
                    stack.append(n)
        return stones, liberties

    # ---------------------------------------------------------------- 规则
    def is_legal(self, color: str, vertex: str) -> tuple:
        """返回 (是否合法, 原因)。"""
        try:
            pos = self.from_gtp(vertex)
        except ValueError as exc:
            return False, str(exc)
        if pos is None:
            return True, ""                                  # 停一手永远合法
        idx = self.index(*pos)
        if self.grid[idx]:
            return False, "该点已有棋子"
        if self.ko_point == idx:
            return False, "打劫: 此处需先找劫材"
        return True, ""

    def play(self, color: str, vertex: str) -> dict:
        """落子; 非法时抛 IllegalMove。返回 {'vertex','captured','ko'}。"""
        color = color.upper()
        pos = self.from_gtp(vertex)
        if pos is None:                                      # 停一手
            self.history.append(("pass", color, None))
            self.consecutive_passes += 1
            self.ko_point = None
            return {"vertex": "pass", "captured": [], "ko": None}
        ok, why = self.is_legal(color, vertex)
        if not ok:
            raise IllegalMove(why)
        idx = self.index(*pos)
        self.grid[idx] = color
        captured: list = []
        for n in list(self.neighbors(idx)):
            if self.grid[n] and self.grid[n] != color:
                stones, libs = self._group(n)
                if not libs:                                 # 对方无气 -> 提子
                    for s in stones:
                        self.grid[s] = ""
                    captured.extend(sorted(stones))
        own_stones, own_libs = self._group(idx)
        if not own_libs:                                     # 自己无气 -> 自杀, 撤销
            self.grid[idx] = ""
            for c in captured:
                self.grid[c] = "W" if color == "B" else "B"
            raise IllegalMove("自杀手: 该点落子后自己无气")
        self.captures[color] += len(captured)
        ko = captured[0] if (len(captured) == 1 and len(own_stones) == 1 and len(own_libs) == 1) else None
        self.ko_point = ko
        self.consecutive_passes = 0
        self.history.append(("move", color, idx, tuple(captured)))
        return {"vertex": self.to_gtp(*self.rc(idx)),
                "captured": [self.to_gtp(*self.rc(i)) for i in captured],
                "ko": self.to_gtp(*self.rc(ko)) if ko is not None else None}

    def pass_move(self, color: str) -> dict:
        return self.play(color, "pass")

    def undo(self) -> bool:
        """撤销最后一手 (含恢复被提的子)。"""
        if not self.history:
            return False
        entry = self.history.pop()
        if entry[0] == "pass":
            self.consecutive_passes = max(0, self.consecutive_passes - 1)
            self.ko_point = None
            return True
        _, color, idx, captured = entry
        self.grid[idx] = ""
        for c in captured:
            self.grid[c] = "W" if color == "B" else "B"
        self.captures[color] -= len(captured)
        self.consecutive_passes = 0
        self.ko_point = self.history[-1][3][0] if (self.history and self.history[-1][0] == "move"
                                                   and len(self.history[-1][3]) == 1) else None
        return True

    def is_game_over(self) -> bool:
        return self.consecutive_passes >= 2

    def score(self, komi: float | None = None) -> dict:
        """Tromp-Taylor 面积计分: 棋子 + 只被一方包围的空点。"""
        k = self.komi if komi is None else float(komi)
        visited = [False] * (self.size * self.size)
        territory = {"B": 0, "W": 0}
        for start in range(self.size * self.size):
            if self.grid[start] or visited[start]:
                continue
            region, borders, stack = [], set(), [start]
            visited[start] = True
            while stack:
                cur = stack.pop()
                region.append(cur)
                for n in self.neighbors(cur):
                    if self.grid[n] == "":
                        if not visited[n]:
                            visited[n] = True
                            stack.append(n)
                    else:
                        borders.add(self.grid[n])
            if borders == {"B"}:
                territory["B"] += len(region)
            elif borders == {"W"}:
                territory["W"] += len(region)
        black = sum(1 for c in self.grid if c == "B") + territory["B"]
        white = sum(1 for c in self.grid if c == "W") + territory["W"] + k
        diff = black - white
        winner = "B" if diff > 0 else ("W" if diff < 0 else "Draw")
        return {"black": float(black), "white": float(white), "winner": winner,
                "margin": abs(diff), "territory": territory,
                "captures": dict(self.captures),
                "text": (f"{'黑' if winner == 'B' else '白'}胜 {abs(diff):g} 目"
                         if winner != "Draw" else "和棋")}

    @staticmethod
    def star_points(size: int) -> list:
        return STAR_POINTS.get(size, [])


# ============================================================================
# ⑤ tkinter 图形界面
# ============================================================================

class GoApp:
    """人机对战主界面。所有引擎调用都在子线程, 通过 root.after 回主线程刷新。"""

    def __init__(self, master: tk.Tk, size: int = BOARD_SIZE, komi: float = KOMI):
        self.master = master
        self.size = int(size)
        self.komi = float(komi)
        self.board = GoBoard(self.size, self.komi)
        self.moves: list = []                # [(颜色, GTP 坐标)]
        self.engine: GtpEngine | None = None
        self.engine_ready = False
        self.thinking = False
        self.syncing = False          # 新局/悔棋时正在与引擎同步棋局
        self.msg_queue: "queue.Queue[tuple]" = queue.Queue()   # 子线程 -> 主线程的消息
        self.game_over = False
        self.hover = None
        self.last_move = None
        self.black_winrate = None
        self.ai_visits = MAX_VISITS
        self._dots = 0

        master.title("KataGo 围棋人机对战 (单文件版)")
        master.minsize(820, 640)
        self._build_widgets()
        self._draw_board()
        self.master.after(150, self.start_engine_async)       # 启动时检查环境
        self.master.after(100, self._poll_queue)              # 主线程轮询子线程消息
        self.master.after(300, self._tick)

    # ---------------------------------------------------------------- 界面搭建
    def _build_widgets(self) -> None:
        try:
            ttk.Style().theme_use("clam")
        except tk.TclError:
            pass
        outer = ttk.Frame(self.master, padding=8)
        outer.pack(fill="both", expand=True)

        # 左边: 棋盘
        self.canvas = tk.Canvas(outer, background="#e3b96b", highlightthickness=1,
                                highlightbackground="#8a6a30")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Button-1>", self.on_click)
        self.canvas.bind("<Motion>", self.on_motion)
        self.canvas.bind("<Leave>", lambda _e: self._set_hover(None))
        self.canvas.bind("<Configure>", lambda _e: self._draw_board())

        # 右边: 状态 + 操作
        panel = ttk.Frame(outer, padding=(10, 0, 0, 0))
        panel.pack(side="right", fill="y")

        self.turn_var = tk.StringVar(value="正在检查 KataGo…")
        ttk.Label(panel, textvariable=self.turn_var, font=("", 13, "bold"),
                  wraplength=240, justify="left").pack(anchor="w")
        self.thinking_var = tk.StringVar(value="")
        ttk.Label(panel, textvariable=self.thinking_var, foreground="#b35c00",
                  wraplength=240, justify="left").pack(anchor="w", pady=(2, 8))

        info = ttk.LabelFrame(panel, text="形势 (黑棋视角)", padding=6)
        info.pack(fill="x", pady=4)
        self.winrate_var = tk.StringVar(value="—")
        ttk.Label(info, textvariable=self.winrate_var, font=("", 11, "bold")).pack(anchor="w")
        self.bar = ttk.Progressbar(info, maximum=100, length=220)
        self.bar.pack(fill="x", pady=(4, 0))

        settings = ttk.LabelFrame(panel, text="设置", padding=6)
        settings.pack(fill="x", pady=4)
        row = ttk.Frame(settings)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="棋盘", width=6).pack(side="left")
        self.size_var = tk.IntVar(value=self.size)
        for n in (9, 13, 19):
            ttk.Radiobutton(row, text=f"{n}路", value=n, variable=self.size_var,
                            command=self.new_game).pack(side="left")
        row = ttk.Frame(settings)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="强度", width=6).pack(side="left")
        self.visits_var = tk.StringVar(value=str(MAX_VISITS))
        ttk.Entry(row, textvariable=self.visits_var, width=7).pack(side="left")
        ttk.Label(row, text="次访问/手").pack(side="left", padx=4)
        ttk.Button(row, text="应用", width=5, command=self.apply_visits).pack(side="left")

        ops = ttk.LabelFrame(panel, text="操作", padding=6)
        ops.pack(fill="x", pady=4)
        grid = ttk.Frame(ops)
        grid.pack(fill="x")
        ttk.Button(grid, text="新局", command=self.new_game).grid(row=0, column=0, sticky="ew", padx=2, pady=2)
        ttk.Button(grid, text="停一手", command=self.human_pass).grid(row=0, column=1, sticky="ew", padx=2, pady=2)
        ttk.Button(grid, text="悔棋", command=self.undo).grid(row=1, column=0, sticky="ew", padx=2, pady=2)
        ttk.Button(grid, text="认输", command=self.resign).grid(row=1, column=1, sticky="ew", padx=2, pady=2)
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)

        engine_box = ttk.LabelFrame(panel, text="引擎", padding=6)
        engine_box.pack(fill="both", expand=True, pady=4)
        self.engine_var = tk.StringVar(value="未连接")
        ttk.Label(engine_box, textvariable=self.engine_var, wraplength=240,
                  justify="left").pack(anchor="w")
        self.log_text = tk.Text(engine_box, height=6, width=30, wrap="word", state="disabled",
                                font=("", 9))
        self.log_text.pack(fill="both", expand=True, pady=(4, 0))
        self.capture_var = tk.StringVar(value="")
        ttk.Label(panel, textvariable=self.capture_var, foreground="#444").pack(anchor="w")

    # ---------------------------------------------------------------- 落子与轮次
    def current_turn(self) -> str:
        return "B" if not self.moves else ("W" if self.moves[-1][0] == "B" else "B")

    def on_motion(self, event) -> None:
        self._set_hover(self._hit(event.x, event.y))

    def _set_hover(self, hit) -> None:
        if hit != self.hover:
            self.hover = hit
            self._draw_board()

    def on_click(self, event) -> None:
        """鼠标点击落子 (只在轮到人类且引擎空闲时生效)。"""
        if self.game_over or self.thinking or not self.engine_ready:
            return
        if self.syncing:                                      # 新局/悔棋正在与引擎同步
            self.turn_var.set("正在与引擎同步棋局, 请稍候…")
            return
        if self.current_turn() != HUMAN_COLOR:
            return
        hit = self._hit(event.x, event.y)
        if hit is None:
            return
        vertex = self.board.to_gtp(*hit)
        ok, why = self.board.is_legal(HUMAN_COLOR, vertex)
        if not ok:
            self.turn_var.set(f"{vertex} 不能下: {why}")
            return
        result = self.board.play(HUMAN_COLOR, vertex)
        self.moves.append((HUMAN_COLOR, result["vertex"]))
        self.last_move = (*hit, HUMAN_COLOR)
        self.log(f"你: {result['vertex']}" + (f" 提 {len(result['captured'])} 子" if result["captured"] else ""))
        self._send_play(HUMAN_COLOR, result["vertex"])        # 同步发给引擎 (毫秒级)
        self._refresh()
        self._maybe_ai_move()

    def _send_play(self, color: str, vertex: str) -> None:
        """把一手棋同步告诉引擎。

        play 是毫秒级命令, 同步发送可以保证"先 play 再 genmove"的先后顺序
        (如果也丢给子线程, genmove 可能抢先发出, 引擎就会算错局面)。
        """
        if not (self.engine and self.engine.alive):
            return
        try:
            self.engine.play(color, vertex)
        except GtpError as exc:
            self.log(f"play 发送失败: {exc}")

    def _maybe_ai_move(self) -> None:
        if self.game_over or self.current_turn() != AI_COLOR:
            return
        self.thinking = True
        self.thinking_var.set("AI 思考中")
        threading.Thread(target=self._ai_worker, daemon=True).start()

    def _ai_worker(self) -> None:
        """子线程: 执行 genmove (耗时操作); 结果放进队列, 由主线程取出更新界面。"""
        started = time.time()
        try:
            if self.engine is None or not self.engine.alive:
                raise GtpError("引擎未就绪")
            move = self.engine.genmove(AI_COLOR)
            self.msg_queue.put(("ai_move", (move, None, time.time() - started)))
        except Exception as exc:                              # noqa: BLE001
            self.msg_queue.put(("ai_move", (None, exc, time.time() - started)))

    def _apply_ai_move(self, move, error, elapsed: float) -> None:
        """主线程: 根据 genmove 结果更新棋盘 (一定在主线程执行)。"""
        self.thinking = False
        self.thinking_var.set("")
        if error is not None:
            self.log(f"AI 出错: {error}")
            messagebox.showerror("引擎错误", f"AI 思考失败:\n{error}\n\n"
                                             "可重新运行 python3 test_go_ai.py 排查, "
                                             "或检查 katago/models 下的权重文件。")
            return
        move = (move or "pass").strip()
        if move.lower() in ("resign", "cancelled"):
            self.game_over = True
            self.turn_var.set("AI 认输, 你赢了!")
            self._refresh()
            messagebox.showinfo("对局结束", "AI 认输, 你赢了!")
            return
        try:
            if move.lower() == "pass":
                self.board.pass_move(AI_COLOR)
                self.moves.append((AI_COLOR, "pass"))
                self.last_move = None
                self.log("AI: 停一手")
            else:
                result = self.board.play(AI_COLOR, move)
                self.moves.append((AI_COLOR, result["vertex"]))
                row, col = self.board.from_gtp(result["vertex"])
                self.last_move = (row, col, AI_COLOR)
                self.log(f"AI: {result['vertex']} ({elapsed:.1f}s)"
                         + (f" 提 {len(result['captured'])} 子" if result["captured"] else ""))
        except (IllegalMove, ValueError) as exc:
            self.log(f"AI 返回了非法着法 {move}: {exc}")
            messagebox.showerror("引擎异常", f"AI 返回非法着法 {move}: {exc}")
            return
        self._refresh()
        self._check_end()
        if not self.game_over:
            self.turn_var.set(f"轮到你 (执黑) — AI 刚下 {move}")

    # ---------------------------------------------------------------- 操作按钮
    def new_game(self) -> None:
        if self.thinking:
            return
        self.size = int(self.size_var.get())
        self.board = GoBoard(self.size, self.komi)
        self.moves = []
        self.game_over = False
        self.last_move = None
        self.black_winrate = None
        self.winrate_var.set("—")
        self.bar["value"] = 0
        self._refresh()
        if self.engine_ready and self.engine and self.engine.alive:
            self.syncing = True
            self.turn_var.set("正在与引擎同步棋局…")

            def work():
                try:
                    self.engine.boardsize(self.size)
                    self.engine.komi(self.komi)
                    self.engine.clear_board()
                    self.msg_queue.put(("new_game_done", None))
                except GtpError as exc:
                    self.msg_queue.put(("sync_error", f"新局失败: {exc}"))
            threading.Thread(target=work, daemon=True).start()
        else:
            self.turn_var.set("引擎未就绪")

    def _after_new_game(self) -> None:
        self.turn_var.set("新局开始 — 轮到你 (执黑先行)")
        self.log(f"新局: {self.size} 路, 贴目 {self.komi}")

    def human_pass(self) -> None:
        if self.game_over or self.thinking or not self.engine_ready:
            return
        if self.current_turn() != HUMAN_COLOR:
            return
        self.board.pass_move(HUMAN_COLOR)
        self.moves.append((HUMAN_COLOR, "pass"))
        self.last_move = None
        self._send_play(HUMAN_COLOR, "pass")
        self.log("你: 停一手")
        self._refresh()
        if not self._check_end():
            self._maybe_ai_move()

    def undo(self) -> None:
        """悔棋: 退回到自己行棋 (通常撤销 AI + 自己各一手)。"""
        if self.thinking or not self.moves:
            return
        for _ in range(2):
            if not self.moves:
                break
            color, _vertex = self.moves.pop()
            self.board.undo()
            if color == HUMAN_COLOR:
                break
        self.game_over = False
        self.last_move = None
        self._refresh()
        if self.engine_ready and self.engine and self.engine.alive:
            moves = list(self.moves)

            self.syncing = True

            def work():
                try:
                    self.engine.boardsize(self.size)
                    self.engine.komi(self.komi)
                    self.engine.clear_board()
                    for color, vertex in moves:
                        self.engine.play(color, vertex)
                    self.msg_queue.put(("undo_done", None))
                except GtpError as exc:
                    self.msg_queue.put(("sync_error", f"悔棋同步失败: {exc}"))
            threading.Thread(target=work, daemon=True).start()

    def resign(self) -> None:
        if self.game_over:
            return
        if messagebox.askyesno("认输", "确定认输吗?"):
            self.game_over = True
            self.turn_var.set("你认输了")
            self._refresh()

    def apply_visits(self) -> None:
        try:
            visits = max(1, int(self.visits_var.get()))
        except ValueError:
            messagebox.showwarning("强度设置", "请输入正整数 (每手访问次数)。")
            return
        self.visits_var.set(str(visits))
        if self.engine and self.engine.alive:
            if self.engine.set_max_visits(visits):
                self.ai_visits = visits
                self.log(f"AI 强度已改为每手 {visits} 次访问")
            else:
                self.log("引擎不支持 kata-set-param, 重启程序后生效")
        else:
            self.ai_visits = visits

    # ---------------------------------------------------------------- 引擎
    def start_engine_async(self) -> None:
        threading.Thread(target=self._start_engine_worker, daemon=True).start()

    def _start_engine_worker(self) -> None:
        ok, detail = check_installation()
        if not ok:
            self.msg_queue.put(("missing", detail))
            return
        try:
            engine = GtpEngine(find_katago(), find_model(), find_config(),
                               max_visits=self.ai_visits, threads=auto_threads())
            engine.start()                                    # 这一步会加载权重, 较慢
            self.engine = engine
            version = ""
            try:
                version = engine.version()
            except GtpError:
                pass
            self.msg_queue.put(("engine_ready", version))
        except Exception as exc:                              # noqa: BLE001
            self.msg_queue.put(("engine_error", str(exc)))

    def _engine_started(self, version: str) -> None:
        self.engine_ready = True
        self.engine_var.set(f"{self.engine.engine_name} {version}\n线程 {auto_threads()} · "
                            f"每手 {self.ai_visits} 次访问")
        self.log(f"引擎就绪: {self.engine.binary}")
        self.new_game()

    def _report_missing(self, detail: str) -> None:
        """没找到引擎/权重: 给出说明, 并在有安装脚本时提供"一键自动安装"。"""
        self.turn_var.set("未找到可用的 KataGo")
        self.engine_var.set(detail)
        self.log(detail)
        script = find_installer()
        if script is not None and messagebox.askyesno(
                "需要先安装 KataGo",
                f"{detail}\n\n是否现在自动下载安装?\n"
                "(需要联网, Windows/Linux 直接下预编译包, macOS 会自动编译)\n"
                f"安装脚本: {script.name}"):
            self.start_auto_install()
            return
        messagebox.showwarning("需要先安装 KataGo", f"{detail}\n\n{MISSING_KATAGO_HINT}")

    def start_auto_install(self) -> None:
        """在子线程里调用同目录的 setup_katago.py, 装完自动重启引擎。"""
        self.turn_var.set("正在自动安装 KataGo (可能需要几分钟)…")
        self.log("开始自动安装 KataGo, 详细过程见控制台窗口…")

        def work():
            ok, message = auto_install(progress=lambda m: self.msg_queue.put(("log", m)))
            self.msg_queue.put(("install_done", (ok, message)))

        threading.Thread(target=work, daemon=True).start()

    def _install_finished(self, ok: bool, message: str) -> None:
        self.log(f"自动安装结果: {message}")
        if not ok:
            self.turn_var.set("自动安装失败")
            messagebox.showerror("自动安装失败",
                                 f"{message}\n\n{MISSING_KATAGO_HINT}")
            return
        self.turn_var.set("安装完成, 正在启动引擎…")
        self.engine_ready = False
        self.start_engine_async()                              # 装好后再试一次

    def _report_engine_error(self, error: str) -> None:
        self.turn_var.set("引擎启动失败")
        self.engine_var.set(error[:200])
        self.log(f"引擎启动失败: {error}")
        script = find_installer()
        hint = ("\n· 如果这个文件夹是从别人电脑拷贝过来的, 请选“是”重新安装本机可用的引擎版本"
                if script is not None else "")
        retry = script is not None and messagebox.askyesno(
            "引擎启动失败",
            f"{error[:500]}\n\n排查建议:\n"
            "· 确认权重文件完整 (katago/models/*.bin.gz, 约 11 MB)\n"
            "· 手动执行: katago gtp -model 权重 -config 配置, 看是否出现 GTP ready\n"
            f"· 详细日志: go_ai_katago.log{hint}\n\n是否现在重新安装/修复 KataGo?")
        if retry:
            self.start_auto_install()
            return
        messagebox.showerror("引擎启动失败", f"{error[:600]}\n\n详细日志: go_ai_katago.log")

    # ---------------------------------------------------------------- 其它
    def _check_end(self) -> bool:
        if not self.board.is_game_over():
            return False
        self.game_over = True
        result = self.board.score(self.komi)
        engine_score = self.engine.final_score() if (self.engine and self.engine.alive) else ""
        text = f"双方停一手, 对局结束。\n\n按面积计分: {result['text']}\n" \
               f"(黑 {result['black']:g} : 白 {result['white']:g}, 含贴目 {self.komi:g})"
        if engine_score:
            text += f"\n\nKataGo 终局判定: {engine_score}"
        self.turn_var.set("对局结束: " + result["text"])
        self._refresh()
        messagebox.showinfo("对局结束", text)
        return True

    def _poll_queue(self) -> None:
        """主线程: 定时把子线程的消息取出来, 在这里安全地更新界面。

        注意: 这里必须保证无论如何都重新排程 (finally), 否则一次异常会让轮询停摆,
        界面就再也收不到引擎消息了。
        """
        try:
            self._drain_queue()
        except Exception as exc:                              # noqa: BLE001
            traceback.print_exc()
            self.log(f"界面刷新异常: {exc}")
        finally:
            self.master.after(80, self._poll_queue)

    def _drain_queue(self) -> None:
        """取出当前所有待处理消息并逐条分发 (每条都单独捕获异常, 互不影响)。"""
        while True:
            try:
                kind, payload = self.msg_queue.get_nowait()
            except queue.Empty:
                return
            try:
                self._handle_message(kind, payload)
            except Exception as exc:                          # noqa: BLE001
                traceback.print_exc()
                self.log(f"处理 {kind} 消息时出错: {exc}")

    def _handle_message(self, kind: str, payload) -> None:
        if kind == "log":
            self.log(str(payload))
        elif kind == "engine_ready":
            self._engine_started(payload)
        elif kind == "engine_error":
            self._report_engine_error(str(payload))
        elif kind == "missing":
            self._report_missing(str(payload))
        elif kind == "ai_move":
            self._apply_ai_move(*payload)
        elif kind == "new_game_done":
            self.syncing = False
            self._after_new_game()
        elif kind == "undo_done":
            self.syncing = False
            self.turn_var.set("已悔棋 — 轮到你")
        elif kind == "install_done":
            self._install_finished(*payload)
        elif kind == "sync_error":
            self.syncing = False
            self.log(str(payload))

    def _tick(self) -> None:
        """每 300ms 刷新一次思考动画 (主线程定时器)。"""
        if self.thinking:
            self._dots = (self._dots + 1) % 4
            self.thinking_var.set("AI 思考中" + "." * self._dots + f"  (每手 {self.ai_visits} 次访问)")
        self.master.after(300, self._tick)

    def log(self, message: str) -> None:
        try:
            self.log_text.configure(state="normal")
            self.log_text.insert("end", message.rstrip() + "\n")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        except tk.TclError:
            pass

    # ---------------------------------------------------------------- 绘图
    def _geometry(self):
        w = max(self.canvas.winfo_width(), 200)
        h = max(self.canvas.winfo_height(), 200)
        cell = min(w, h) / (self.size + 1.6)
        return cell, (w - cell * (self.size - 1)) / 2, (h - cell * (self.size - 1)) / 2

    def _point(self, row: int, col: int):
        cell, mx, my = self._geometry()
        return mx + col * cell, my + row * cell

    def _hit(self, x: float, y: float):
        cell, mx, my = self._geometry()
        col, row = round((x - mx) / cell), round((y - my) / cell)
        if 0 <= row < self.size and 0 <= col < self.size:
            px, py = self._point(row, col)
            if (px - x) ** 2 + (py - y) ** 2 <= (cell * 0.6) ** 2:
                return row, col
        return None

    def _draw_board(self) -> None:
        c = self.canvas
        c.delete("all")
        cell, mx, my = self._geometry()
        n = self.size
        pad = cell * 0.8
        c.create_rectangle(mx - pad, my - pad, mx + (n - 1) * cell + pad, my + (n - 1) * cell + pad,
                           fill="#e3b96b", outline="#c99b4e", width=2)
        for i in range(n):                                    # 网格
            x0, y0 = self._point(0, i)
            x1, y1 = self._point(n - 1, i)
            c.create_line(x0, y0, x1, y1, fill="#4a3520")
            x0, y0 = self._point(i, 0)
            x1, y1 = self._point(i, n - 1)
            c.create_line(x0, y0, x1, y1, fill="#4a3520")
        for r, col in GoBoard.star_points(n):                 # 星位
            x, y = self._point(r, col)
            d = max(2.0, cell * 0.08)
            c.create_oval(x - d, y - d, x + d, y + d, fill="#4a3520", outline="#4a3520")
        for i in range(n):                                    # 坐标 (跳过 I)
            x, _ = self._point(n - 1, i)
            c.create_text(x, my + (n - 1) * cell + cell * 0.55, text=COLUMNS[i],
                          fill="#5b4321", font=("", max(8, int(cell * 0.32))))
            _, y = self._point(i, 0)
            c.create_text(mx - cell * 0.55, y, text=str(n - i),
                          fill="#5b4321", font=("", max(8, int(cell * 0.32))))
        radius = cell * 0.46
        for idx, stone in enumerate(self.board.grid):         # 棋子
            if not stone:
                continue
            r, col = self.board.rc(idx)
            x, y = self._point(r, col)
            c.create_oval(x - radius, y - radius, x + radius, y + radius,
                          fill="#1b1b1b" if stone == "B" else "#f7f7f2",
                          outline="#000000" if stone == "B" else "#9a9a92", width=1.2)
            if stone == "W":
                c.create_oval(x - radius * 0.7, y - radius * 0.7, x - radius * 0.15, y - radius * 0.15,
                              fill="#ffffff", outline="")
        if self.last_move:                                    # 最后一手标记
            r, col, color = self.last_move
            x, y = self._point(r, col)
            d = max(2.0, cell * 0.13)
            c.create_oval(x - d, y - d, x + d, y + d,
                          fill="#ffffff" if color == "B" else "#d33",
                          outline="#ffffff" if color == "B" else "#d33")
        if self.hover and not self.game_over and not self.thinking:   # 悬停预览
            r, col = self.hover
            if not self.board.grid[self.board.index(r, col)]:
                x, y = self._point(r, col)
                c.create_oval(x - radius, y - radius, x + radius, y + radius,
                              outline="#1e6f2f", width=2, dash=(4, 3))

    def _refresh(self) -> None:
        self.capture_var.set(f"提子  黑 {self.board.captures['B']} : 白 {self.board.captures['W']}"
                             f"   ·   手数 {len(self.moves)}")
        if not self.game_over and not self.thinking:
            self.turn_var.set("轮到你 (执黑)" if self.current_turn() == HUMAN_COLOR else "轮到 AI")
        self._draw_board()


# ============================================================================
# ⑥ 入口
# ============================================================================

def main() -> int:
    try:
        root = tk.Tk()
    except tk.TclError as exc:                    # 没有图形界面时给出文字提示
        print("无法创建窗口:", exc)
        print("· Linux 需要装 tkinter: sudo apt install python3-tk")
        print("· 服务器/无显示环境请用: python3 test_go_ai.py --no-gui  (只测 GTP 与规则)")
        return 1
    GoApp(root, size=BOARD_SIZE, komi=KOMI)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())