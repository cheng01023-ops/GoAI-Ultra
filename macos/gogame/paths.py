"""跨平台路径与平台探测。

本模块集中管理所有目录/文件位置, 全部由项目根目录推导, 不硬编码任何绝对路径,
因此在 Windows / macOS / Linux 上都能直接工作。
"""
from __future__ import annotations

import os
import platform
import shutil
import sys
from pathlib import Path

# ---------------------------------------------------------------- 目录布局
PROJECT_ROOT = Path(__file__).resolve().parent.parent
KATAGO_DIR = PROJECT_ROOT / "katago"
BIN_DIR = KATAGO_DIR / "bin"
MODELS_DIR = KATAGO_DIR / "models"
CONFIGS_DIR = KATAGO_DIR / "configs"
LOGS_DIR = PROJECT_ROOT / "logs"
BUILD_DIR = PROJECT_ROOT / ".build"

ENGINE_EXE = "katago.exe" if os.name == "nt" else "katago"
# 默认使用小网络: 在 CPU 上快约 10 倍, 人机对战体验最好
DEFAULT_MODEL_NAME = "g170e-b10c128-s1141046784-d204142634.bin.gz"
DEFAULT_CONFIG_NAME = "default_gtp.cfg"

_ARCH_ALIASES = {
    "x86_64": "x64",
    "amd64": "x64",
    "x64": "x64",
    "i386": "x86",
    "i686": "x86",
    "arm64": "arm64",
    "aarch64": "arm64",
}


def system_info() -> dict:
    """返回当前操作系统/架构信息。"""
    machine = (platform.machine() or "").lower()
    arch = _ARCH_ALIASES.get(machine, machine or "unknown")
    if sys.platform.startswith("win"):
        os_name = "windows"
    elif sys.platform == "darwin":
        os_name = "macos"
    elif sys.platform.startswith("linux"):
        os_name = "linux"
    else:
        os_name = sys.platform
    return {
        "os": os_name,
        "arch": arch,
        "machine": machine,
        "python": platform.python_version(),
        "python_exe": sys.executable,
    }


def is_windows() -> bool:
    return os.name == "nt"


def is_macos() -> bool:
    return sys.platform == "darwin"


def is_linux() -> bool:
    return sys.platform.startswith("linux")


def cpu_count() -> int:
    """物理/逻辑核心数, 至少返回 1。"""
    try:
        n = os.cpu_count() or 1
    except Exception:
        n = 1
    if is_macos():
        # macOS 上 os.cpu_count() 已包含性能核 + 能效核, 直接使用即可
        return max(1, n)
    return max(1, n)


def ensure_dirs() -> None:
    for d in (BIN_DIR, MODELS_DIR, CONFIGS_DIR, LOGS_DIR, BUILD_DIR):
        d.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------- 查找资源
def find_engine() -> Path | None:
    """返回可用的 katago 可执行文件路径 (优先项目内 katago/bin)。"""
    candidates = [BIN_DIR / ENGINE_EXE, BIN_DIR / "katago", KATAGO_DIR / ENGINE_EXE, KATAGO_DIR / "katago"]
    for c in candidates:
        if c.is_file() and os.access(c, os.X_OK):
            return c
    found = shutil.which("katago")
    if found:
        return Path(found)
    return None


def list_models() -> list[Path]:
    if not MODELS_DIR.is_dir():
        return []
    return sorted(MODELS_DIR.glob("*.bin.gz"), key=lambda p: p.name)


def find_model(name: str | None = None) -> Path | None:
    """查找权重文件; name 为空时优先默认小网络。"""
    if name:
        p = Path(name)
        if p.is_file():
            return p
        p = MODELS_DIR / name
        return p if p.is_file() else None
    preferred = MODELS_DIR / DEFAULT_MODEL_NAME
    if preferred.is_file():
        return preferred
    models = list_models()
    return models[0] if models else None


def find_config(name: str | None = None) -> Path | None:
    if name:
        p = Path(name)
        if p.is_file():
            return p
        p = CONFIGS_DIR / name
        return p if p.is_file() else None
    p = CONFIGS_DIR / DEFAULT_CONFIG_NAME
    return p if p.is_file() else None


def is_installed() -> bool:
    """引擎 + 权重 + 配置三者齐备才算安装完成。"""
    return find_engine() is not None and find_model() is not None and find_config() is not None


def missing_pieces() -> list[str]:
    missing = []
    if find_engine() is None:
        missing.append("引擎可执行文件 (katago/bin/%s)" % ENGINE_EXE)
    if find_model() is None:
        missing.append("神经网络权重 (katago/models/*.bin.gz)")
    if find_config() is None:
        missing.append("配置文件 (katago/configs/%s)" % DEFAULT_CONFIG_NAME)
    return missing
