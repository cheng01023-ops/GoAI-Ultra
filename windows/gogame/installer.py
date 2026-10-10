"""跨平台 KataGo 自动安装器。

流程
----
1. 探测操作系统 / CPU 架构 / AVX2 支持
2. 获取引擎:
     * Windows / Linux x64  -> 官方预编译包 (Eigen CPU 或 OpenCL)
     * macOS / 其他架构     -> 自动源码编译 (下载 CMake + KataGo 源码 + Eigen 头文件)
3. 下载神经网络权重 (.bin.gz)
4. 生成配置文件 katago/configs/default_gtp.cfg
5. 运行自检 (katago version + GTP 握手 + 试下一手)

所有下载都支持断点重试, 所有路径都从项目根目录推导, 不硬编码系统路径。
"""
from __future__ import annotations

import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import time
import zipfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from . import paths

# 最后一个同时提供 Eigen(CPU)/OpenCL 预编译包的版本
PREBUILT_TAG = "v1.18.1"
# 源码编译使用的版本 (最新稳定版)
SOURCE_TAG = "v1.18.2"
EIGEN_VERSION = "3.4.0"
CMAKE_FALLBACK_VERSION = "3.31.6"
GH_RELEASE = "https://github.com/lightvector/KataGo/releases/download"
GH_ARCHIVE = "https://github.com/lightvector/KataGo/archive/refs/tags"
KATAGO_ARCHIVE = "https://katagoarchive.org/g170/neuralnets"

# ------------------------------------------------------------------ 网络模型
MODELS: dict[str, dict] = {
    "b10c128": {
        "file": "g170e-b10c128-s1141046784-d204142634.bin.gz",
        "url": f"{KATAGO_ARCHIVE}/g170e-b10c128-s1141046784-d204142634.bin.gz",
        "size_mb": 9,
        "desc": "10 块 128 通道小网络 (中等规模, CPU 上最快) — 推荐",
    },
    "b15c192": {
        "file": "g170e-b15c192-s1305382144-d335919935.bin.gz",
        "url": f"{KATAGO_ARCHIVE}/g170e-b15c192-s1305382144-d335919935.bin.gz",
        "size_mb": 25,
        "desc": "15 块 192 通道, 棋力更强, CPU 速度约为小网络的 1/2",
    },
    "b10c384": {
        "file": "b10c384h6nbttflrs.bin.gz",
        "url": f"{GH_RELEASE}/v1.17.1/b10c384h6nbttflrs.bin.gz",
        "size_mb": 38,
        "desc": "现代架构小网络, 棋力明显更强, CPU 上较慢",
    },
}
DEFAULT_MODEL_KEY = "b10c128"


def human_size(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(num) < 1024.0:
            return f"{num:3.1f}{unit}"
        num /= 1024.0
    return f"{num:.1f}TB"


def _cpu_supports_avx2() -> bool:
    """判断当前 x64 CPU 是否支持 AVX2 (Windows 用 ctypes, Linux 读 /proc/cpuinfo, macOS 一律支持)。"""
    machine = (platform.machine() or "").lower()
    if machine in ("arm64", "aarch64"):
        return False
    if sys.platform == "darwin":
        # 所有支持 macOS 11+ 的 Intel Mac 都支持 AVX2; Rosetta 下也可用
        return True
    if sys.platform.startswith("linux"):
        try:
            info = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="ignore")
            return " avx2 " in info.replace("\n", " ") or "avx2" in info
        except Exception:
            return False
    if os.name == "nt":
        try:
            import ctypes

            PF_AVX2_INSTRUCTION_AVAILABLE = 40
            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            return bool(kernel32.IsProcessorFeaturePresent(PF_AVX2_INSTRUCTION_AVAILABLE))
        except Exception:
            return False
    return False


class Installer:
    """一键安装: 引擎 + 权重 + 配置 + 自检。"""

    def __init__(
        self,
        model_key: str = DEFAULT_MODEL_KEY,
        backend: str | None = None,
        jobs: int | None = None,
        force: bool = False,
        log=None,
    ) -> None:
        self.info = paths.system_info()
        self.model_key = model_key if model_key in MODELS else DEFAULT_MODEL_KEY
        self.backend = (backend or "auto").lower()
        self.jobs = jobs or max(1, paths.cpu_count())
        self.force = force
        self._log = log or (lambda msg: print(msg, flush=True))

    # ------------------------------------------------------------ 日志
    def log(self, message: str) -> None:
        self._log(message)

    def section(self, title: str) -> None:
        self.log("")
        self.log("=" * 62)
        self.log(f"  {title}")
        self.log("=" * 62)

    # ------------------------------------------------------------ 主流程
    def run(self) -> bool:
        paths.ensure_dirs()
        self.section("环境探测")
        self.log(f"操作系统 : {self.info['os']} ({self.info['machine']})")
        self.log(f"CPU 架构 : {self.info['arch']}")
        self.log(f"CPU 核心 : {paths.cpu_count()}")
        self.log(f"Python   : {self.info['python']} @ {self.info['python_exe']}")
        self.log(f"项目目录 : {paths.PROJECT_ROOT}")
        avx2 = _cpu_supports_avx2()
        self.log(f"AVX2     : {'支持' if avx2 else '不支持 / 不适用'}")

        self.section("第 1 步 / 4 : 准备 KataGo 引擎")
        if self.ensure_engine(avx2):
            self.log("[OK] 引擎就绪")
        else:
            self.log("[失败] 无法获得引擎, 请把日志反馈给开发者")
            return False

        self.section("第 2 步 / 4 : 下载神经网络权重")
        if self.ensure_model():
            self.log("[OK] 权重就绪")
        else:
            self.log("[失败] 权重下载失败, 请检查网络后重试")
            return False

        self.section("第 3 步 / 4 : 生成配置文件")
        self.ensure_config()
        self.log(f"[OK] {paths.CONFIGS_DIR / paths.DEFAULT_CONFIG_NAME}")

        self.section("第 4 步 / 4 : 自检")
        ok = self.verify()
        self.log("")
        if ok:
            self.log("全部完成! 运行方式:")
            self.log("  图形界面 : python3 play.py")
            self.log("  连接自检 : python3 test_katago.py")
        return ok

    # ------------------------------------------------------------ 下载工具
    def download(self, url: str, dest: Path, retries: int = 3) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists() and dest.stat().st_size > 0 and not self.force:
            self.log(f"已存在, 跳过下载: {dest.name} ({human_size(dest.stat().st_size)})")
            return dest
        tmp = dest.with_name(dest.name + ".part")
        for attempt in range(1, retries + 1):
            try:
                self.log(f"下载 {url}")
                req = Request(url, headers={"User-Agent": "KataGo-HumanVsAI-Installer/1.0"})
                with urlopen(req, timeout=90) as resp, open(tmp, "wb") as fh:
                    total = int(resp.headers.get("Content-Length") or 0)
                    got = 0
                    last = 0.0
                    while True:
                        chunk = resp.read(1 << 16)
                        if not chunk:
                            break
                        fh.write(chunk)
                        got += len(chunk)
                        now = time.time()
                        if now - last > 2.0:
                            last = now
                            if total:
                                pct = got * 100.0 / total
                                print(f"\r    {pct:5.1f}%  {human_size(got)} / {human_size(total)}", end="", flush=True)
                            else:
                                print(f"\r    {human_size(got)}", end="", flush=True)
                print("", flush=True)
                if total and tmp.stat().st_size != total:
                    raise IOError(f"下载不完整: {tmp.stat().st_size} / {total} 字节")
                tmp.replace(dest)
                self.log(f"完成: {dest.name} ({human_size(dest.stat().st_size)})")
                return dest
            except (HTTPError, URLError, IOError, TimeoutError) as exc:
                code = getattr(exc, "code", None)
                self.log(f"第 {attempt}/{retries} 次下载失败: {code or exc}")
                if isinstance(exc, HTTPError) and code in (403, 404):
                    raise
                if attempt < retries:
                    time.sleep(2 * attempt)
        raise IOError(f"下载失败: {url}")

    @staticmethod
    def _url_exists(url: str) -> bool:
        try:
            req = Request(url, method="HEAD", headers={"User-Agent": "KataGo-HumanVsAI-Installer/1.0"})
            with urlopen(req, timeout=45) as resp:
                return 200 <= resp.status < 400
        except HTTPError as exc:
            return exc.code not in (403, 404)
        except Exception:
            return False

    def _pip_install(self, package: str) -> bool:
        self.log(f"尝试 pip 安装 {package} …")
        for args in ([sys.executable, "-m", "pip", "install", "--quiet", package],
                     [sys.executable, "-m", "pip", "install", "--quiet", "--user", package],
                     [sys.executable, "-m", "pip", "install", "--quiet", "--break-system-packages", package]):
            try:
                proc = subprocess.run(args, capture_output=True, text=True, timeout=900)
            except Exception as exc:
                self.log(f"  {exc}")
                continue
            if proc.returncode == 0:
                return True
            tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-1:]
            self.log(f"  {' '.join(args[3:])} 失败: {tail[0] if tail else proc.returncode}")
        return False

    # ------------------------------------------------------------ 引擎
    def engine_runs(self, binary: Path) -> bool:
        """试跑 katago version, 判断这个可执行文件在当前系统/架构上到底能不能用。"""
        try:
            proc = subprocess.run([str(binary), "version"], capture_output=True, text=True, timeout=60)
        except Exception as exc:                                  # 跨平台拷贝时最常见的情况
            self.log(f"  已有引擎无法运行: {exc}")
            return False
        if proc.returncode == 0:
            return True
        self.log(f"  已有引擎无法运行 (退出码 {proc.returncode}, {proc.stderr.strip()[:120]})")
        return False

    def ensure_engine(self, avx2: bool) -> bool:
        engine = paths.find_engine()
        if engine and not self.force:
            if self.engine_runs(engine):
                self.log(f"发现已安装引擎: {engine}")
                return True
            self.log(f"{engine} 在当前系统上跑不起来 (多半是别的平台/架构版本), 重新安装本机可用的引擎")
            try:
                engine.unlink()                                   # 删掉不兼容的, 免得下次又被选中
            except OSError:
                pass

        backend = self.backend
        if backend == "auto":
            backend = "eigen" if self.info["os"] in ("macos",) else "eigen"
        if self.info["os"] == "macos":
            self.log("macOS 没有官方预编译包, 改为源码编译 (原生 arm64/x86_64, 性能最佳)")
            return self.build_from_source("eigen", avx2)

        names: list[str] = []
        if backend in ("eigen", "auto"):
            if self.info["arch"] == "x64" and avx2:
                names.append(f"katago-{PREBUILT_TAG}-eigenavx2-{self._os_tag()}-x64.zip")
            names.append(f"katago-{PREBUILT_TAG}-eigen-{self._os_tag()}-x64.zip")
        if backend == "opencl":
            names.insert(0, f"katago-{PREBUILT_TAG}-opencl-{self._os_tag()}-x64.zip")
        if backend == "cuda":
            names.insert(0, f"katago-{PREBUILT_TAG}-cuda12.8-cudnn9.8.0-{self._os_tag()}-x64.zip")
        if backend in ("cuda", "tensorrt"):
            self.log(f"注意: {backend} 后端需要自行安装 CUDA/cuDNN, 详见 README")

        for name in names:
            url = f"{GH_RELEASE}/{PREBUILT_TAG}/{name}"
            self.log(f"检查预编译包: {name}")
            if not self._url_exists(url):
                self.log("  不可用, 尝试下一个候选")
                continue
            try:
                archive = self.download(url, paths.BUILD_DIR / name)
                return self._install_from_zip(archive)
            except Exception as exc:
                self.log(f"  安装失败: {exc}")

        self.log("没有合适的预编译包, 回退到源码编译")
        return self.build_from_source("eigen", avx2)

    def _os_tag(self) -> str:
        return {"windows": "windows", "linux": "linux", "macos": "macos"}.get(self.info["os"], self.info["os"])

    def _install_from_zip(self, archive: Path) -> bool:
        out_dir = paths.BUILD_DIR / ("dist-" + archive.stem)
        if not out_dir.exists() or self.force:
            if out_dir.exists():
                shutil.rmtree(out_dir, ignore_errors=True)
            out_dir.mkdir(parents=True, exist_ok=True)
            self.log(f"解压 {archive.name} …")
            with zipfile.ZipFile(archive) as zf:
                zf.extractall(out_dir)
        binary = None
        for candidate in sorted(out_dir.rglob("katago*")):
            if candidate.is_file() and candidate.name.lower() in ("katago", "katago.exe"):
                binary = candidate
                break
        if binary is None:
            self.log(f"在 {archive.name} 中没有找到 katago 可执行文件")
            return False
        target = paths.BIN_DIR / paths.ENGINE_EXE
        shutil.copy2(binary, target)
        self._make_executable(target)
        # Windows 版 kataGo 依赖同目录下的运行库 DLL (msvcp140/vcruntime140/libssl…),
        # 不一起拷贝的话会报"找不到 xxx.dll"。这里把它们都带上。
        dlls = 0
        for dll in binary.parent.glob("*.dll"):
            try:
                shutil.copy2(dll, paths.BIN_DIR / dll.name)
                dlls += 1
            except OSError as exc:
                self.log(f"  拷贝 {dll.name} 失败: {exc}")
        if dlls:
            self.log(f"已随引擎拷贝 {dlls} 个运行库 DLL")
        # 顺带收集官方示例配置
        for cfg in out_dir.rglob("*.cfg"):
            dst = paths.CONFIGS_DIR / cfg.name
            if not dst.exists():
                shutil.copy2(cfg, dst)
        self.log(f"已安装: {target}")
        return True

    @staticmethod
    def _make_executable(path: Path) -> None:
        try:
            mode = path.stat().st_mode
            path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        except Exception:
            pass
        if sys.platform == "darwin":
            try:
                subprocess.run(["xattr", "-dr", "com.apple.quarantine", str(path)],
                               capture_output=True, timeout=30)
            except Exception:
                pass

    # ------------------------------------------------------------ 源码编译
    def ensure_cmake(self) -> list[str] | None:
        exe = shutil.which("cmake")
        if exe:
            return [exe]
        # pip 安装的 cmake 模块
        try:
            proc = subprocess.run([sys.executable, "-m", "cmake", "--version"],
                                  capture_output=True, text=True, timeout=120)
            if proc.returncode == 0:
                self.log(f"使用 pip 版 CMake: {proc.stdout.strip().splitlines()[0]}")
                return [sys.executable, "-m", "cmake"]
        except Exception:
            pass
        if self._pip_install("cmake"):
            return [sys.executable, "-m", "cmake"]
        # 最后: 下载官方 CMake 二进制
        version = CMAKE_FALLBACK_VERSION
        if self.info["os"] == "macos":
            asset = f"cmake-{version}-macos-universal.tar.gz"
        elif self.info["os"] == "linux" and self.info["arch"] == "arm64":
            asset = f"cmake-{version}-linux-aarch64.tar.gz"
        elif self.info["os"] == "linux":
            asset = f"cmake-{version}-linux-x86_64.tar.gz"
        elif self.info["os"] == "windows":
            asset = f"cmake-{version}-windows-x86_64.zip"
        else:
            return None
        url = f"https://github.com/Kitware/CMake/releases/download/v{version}/{asset}"
        try:
            archive = self.download(url, paths.BUILD_DIR / asset)
        except Exception as exc:
            self.log(f"CMake 下载失败: {exc}")
            return None
        extract_dir = paths.BUILD_DIR / "cmake"
        extract_dir.mkdir(parents=True, exist_ok=True)
        if asset.endswith(".zip"):
            with zipfile.ZipFile(archive) as zf:
                zf.extractall(extract_dir)
        else:
            with tarfile.open(archive) as tf:
                tf.extractall(extract_dir)
        found = list(extract_dir.rglob("cmake"))
        found = [f for f in found if f.is_file() and f.parent.name == "bin"]
        if not found:
            self.log("CMake 解压后未找到可执行文件")
            return None
        self._make_executable(found[0])
        return [str(found[0])]

    def build_from_source(self, backend: str = "eigen", avx2: bool = False) -> bool:
        self.log("开始源码编译 (首次约需 3-10 分钟)…")
        cmake_cmd = self.ensure_cmake()
        if not cmake_cmd:
            self.log("无法获得 CMake, 源码编译失败")
            return False

        src_root = paths.BUILD_DIR / f"KataGo-{SOURCE_TAG}"
        clone_root = paths.BUILD_DIR / "KataGo"
        if not (src_root / "cpp" / "CMakeLists.txt").is_file() and (clone_root / "cpp" / "CMakeLists.txt").is_file():
            src_root = clone_root      # 复用已有的源码目录, 省一次下载
            self.log(f"复用已有源码: {src_root}")
        if not (src_root / "cpp" / "CMakeLists.txt").is_file():
            tar_name = f"KataGo-{SOURCE_TAG.lstrip('v')}.tar.gz"
            url = f"{GH_ARCHIVE}/{SOURCE_TAG}.tar.gz"
            archive = self.download(url, paths.BUILD_DIR / tar_name)
            self.log("解压源码 …")
            tmp = paths.BUILD_DIR / "_src_tmp"
            if tmp.exists():
                shutil.rmtree(tmp, ignore_errors=True)
            tmp.mkdir(parents=True, exist_ok=True)
            with tarfile.open(archive) as tf:
                tf.extractall(tmp)
            inner = [p for p in tmp.iterdir() if p.is_dir()]
            if not inner:
                self.log("源码解压失败")
                return False
            if src_root.exists():
                shutil.rmtree(src_root, ignore_errors=True)
            inner[0].rename(src_root)
            shutil.rmtree(tmp, ignore_errors=True)

        eigen_root = paths.BUILD_DIR / f"eigen-{EIGEN_VERSION}"
        if backend == "eigen" and not (eigen_root / "Eigen").is_dir():
            url = f"https://gitlab.com/libeigen/eigen/-/archive/{EIGEN_VERSION}/eigen-{EIGEN_VERSION}.tar.gz"
            archive = self.download(url, paths.BUILD_DIR / f"eigen-{EIGEN_VERSION}.tar.gz")
            self.log("解压 Eigen …")
            with tarfile.open(archive) as tf:
                tf.extractall(paths.BUILD_DIR)
            if not eigen_root.is_dir():
                found = [p for p in paths.BUILD_DIR.iterdir() if p.is_dir() and p.name.startswith("eigen-")]
                if found:
                    found[0].rename(eigen_root)

        build_dir = paths.BUILD_DIR / f"build-{backend}{'-avx2' if avx2 and backend == 'eigen' else ''}"
        # 如果 build 目录里的 CMake 缓存指向别的源码树 (比如手工编译过), 先清掉再配置
        cache = build_dir / "CMakeCache.txt"
        if cache.is_file():
            try:
                m = re.search(r"(?m)^CMAKE_HOME_DIRECTORY:INTERNAL=(.+)$",
                              cache.read_text(encoding="utf-8", errors="ignore"))
                wanted = (src_root / "cpp").resolve()
                if m and Path(m.group(1).strip()).resolve() != wanted:
                    self.log("检测到旧的 CMake 缓存指向其它源码目录, 重新配置构建目录")
                    shutil.rmtree(build_dir, ignore_errors=True)
            except Exception:
                pass
        backend_name = {"eigen": "EIGEN", "opencl": "OPENCL", "metal": "METAL"}.get(backend, backend.upper())
        configure = list(cmake_cmd) + [
            "-S", str(src_root / "cpp"),
            "-B", str(build_dir),
            f"-DUSE_BACKEND={backend_name}",
            "-DCMAKE_BUILD_TYPE=Release",
            "-DNO_GIT_REVISION=1",
        ]
        if backend == "eigen":
            configure.append(f"-DEIGEN3_INCLUDE_DIRS={eigen_root}")
            if avx2:
                configure.append("-DUSE_AVX2=1")
        self.log("配置: " + " ".join(configure[-4:]))
        if subprocess.run(configure, timeout=1800).returncode != 0:
            self.log("CMake 配置失败")
            return False
        self.log(f"编译中 (-j {self.jobs}) …")
        build = list(cmake_cmd) + ["--build", str(build_dir), "-j", str(self.jobs)]
        if subprocess.run(build, timeout=7200).returncode != 0:
            self.log("编译失败")
            return False
        binary = build_dir / ("katago.exe" if os.name == "nt" else "katago")
        if not binary.is_file():
            self.log(f"编译完成但未找到 {binary}")
            return False
        target = paths.BIN_DIR / paths.ENGINE_EXE
        shutil.copy2(binary, target)
        self._make_executable(target)
        # 官方示例配置一起带上
        for cfg in (src_root / "cpp" / "configs").glob("*.cfg"):
            dst = paths.CONFIGS_DIR / cfg.name
            if not dst.exists():
                shutil.copy2(cfg, dst)
        self.log(f"编译完成: {target}")
        return True

    # ------------------------------------------------------------ 权重
    def ensure_model(self) -> bool:
        existing = paths.find_model()
        if existing and not self.force:
            self.log(f"发现已安装权重: {existing.name}")
            return True
        spec = MODELS[self.model_key]
        self.log(f"选择模型: {self.model_key} — {spec['desc']}")
        dest = paths.MODELS_DIR / spec["file"]
        try:
            self.download(spec["url"], dest)
        except Exception as exc:
            self.log(f"下载失败: {exc}")
            # 依次尝试其它模型
            for key, other in MODELS.items():
                if key == self.model_key:
                    continue
                self.log(f"改用备用模型 {key} …")
                try:
                    self.download(other["url"], paths.MODELS_DIR / other["file"])
                    return True
                except Exception as exc2:
                    self.log(f"  {key} 也失败: {exc2}")
            return False
        return self._validate_model(dest)

    @staticmethod
    def _validate_model(path: Path) -> bool:
        """.bin.gz 必须以 gzip 魔数开头。"""
        try:
            with open(path, "rb") as fh:
                magic = fh.read(2)
        except Exception:
            return False
        if magic != b"\x1f\x8b":
            print(f"警告: {path.name} 不是合法的 gzip 文件 (魔数 {magic!r})")
            return False
        return True

    # ------------------------------------------------------------ 配置
    def ensure_config(self) -> Path:
        target = paths.CONFIGS_DIR / paths.DEFAULT_CONFIG_NAME
        if target.is_file() and not self.force:
            return target
        template = Path(__file__).resolve().parent / "assets" / paths.DEFAULT_CONFIG_NAME
        if template.is_file():
            shutil.copy2(template, target)
            return target
        # 退化方案: 从官方示例配置改一份
        example = paths.CONFIGS_DIR / "gtp_example.cfg"
        if example.is_file():
            text = example.read_text(encoding="utf-8", errors="ignore")
            target.write_text(render_config(text), encoding="utf-8")
            return target
        target.write_text(render_config(""), encoding="utf-8")
        return target

    # ------------------------------------------------------------ 自检
    def verify(self) -> bool:
        engine = paths.find_engine()
        model = paths.find_model()
        config = paths.find_config()
        if not (engine and model and config):
            self.log(f"缺少组件: 引擎={engine} 权重={model} 配置={config}")
            return False
        try:
            proc = subprocess.run([str(engine), "version"], capture_output=True, text=True, timeout=180)
        except Exception as exc:
            self.log(f"无法运行 katago version: {exc}")
            return False
        if proc.returncode != 0:
            self.log(f"katago version 退出码 {proc.returncode}: {proc.stderr[:400]}")
            return False
        version_line = (proc.stdout or "").strip().splitlines()[:3]
        for line in version_line:
            self.log("  " + line)

        from .gtp import GtpEngine

        try:
            with GtpEngine(engine, model, config, workdir=paths.PROJECT_ROOT,
                           log_path=paths.LOGS_DIR / "install_check.log", startup_timeout=600) as gtp:
                gtp.boardsize(9)
                gtp.komi(7.5)
                gtp.clear_board()
                gtp.play("B", "E5")
                move = gtp.genmove("W")
            self.log(f"GTP 握手成功, 9x9 试下一手 -> {move}")
            return True
        except Exception as exc:
            self.log(f"GTP 自检失败: {exc}")
            return False


def render_config(base_text: str = "") -> str:
    """在官方示例配置基础上写入对人机对战友好的参数。"""
    text = base_text or DEFAULT_CONFIG_TEXT
    # 注意: KataGo 不允许同时指定 logDir / logFile / logDirDated, 这里只用 logDir
    replacements = {
        "logDir": "logs",
        "logAllGTPCommunication": "false",
        "logSearchInfo": "false",
        "logSearchInfoForChosenMove": "false",
        "logToStderr": "false",
        "rules": "chinese",
        "allowResignation": "false",
        "resignThreshold": "-0.95",
        "resignConsecTurns": "4",
        "maxVisits": "400",
        "ponderingEnabled": "false",
        "numSearchThreads": str(max(1, min(16, paths.cpu_count()))),
        "nnMaxBatchSize": "16",
        "chosenMoveTemperature": "0.0",
        "chosenMoveTemperatureEarly": "0.0",
        "reportAnalysisWinratesAs": "BLACK",
    }
    lines = text.splitlines()
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        m = re.match(r"^(\s*)([A-Za-z][A-Za-z0-9_]*)(\s*)=(\s*)(.*)$", line)
        if m and not m.group(1).startswith("#") and m.group(2) in replacements:
            key = m.group(2)
            out.append(f"{key} = {replacements[key]}")
            seen.add(key)
            continue
        out.append(line)
    for key, value in replacements.items():
        if key not in seen:
            out.append(f"{key} = {value}")
    # 防御: 万一模板里同时存在 logDir 与 logFile, 注释掉 logFile, 否则引擎会拒绝启动
    has_dir = any(re.match(r"^\s*logDir\s*=", line) for line in out)
    if has_dir:
        out = [("\u0023 " + line) if re.match(r"^\s*logFile\s*=", line) else line for line in out]
    return "\n".join(out) + "\n"


DEFAULT_CONFIG_TEXT = """# KataGo GTP 配置 — 人机对战默认设置
# 完整参数说明见 KataGo 官方 gtp_example.cfg
logDir = logs
logFile = katago_gtp.log
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
"""
