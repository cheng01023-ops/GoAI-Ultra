"""KataGo 对手封装: 引擎生命周期、难度参数、走子与分析。"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable

from . import paths
from .gtp import GtpEngine, GtpEngineDied, GtpError

# 难度档位: (键, 显示名, maxVisits, 说明)
DIFFICULTY_PRESETS = [
    ("beginner", "入门", 30, "几乎不思考, 适合完全新手"),
    ("easy", "初级", 100, "约 10 级水平"),
    ("normal", "中级", 400, "约 5 级水平 (推荐)"),
    ("hard", "高级", 1200, "约 1 段水平"),
    ("expert", "专家", 4000, "尽量强, CPU 上每手较慢"),
]

DIFFICULTY_BY_KEY = {k: (name, visits, desc) for k, name, visits, desc in DIFFICULTY_PRESETS}


def default_threads() -> int:
    """CPU 搜索线程数: 留一个核给界面, 最多 16。"""
    return max(1, min(16, paths.cpu_count() - 1 if paths.cpu_count() > 2 else paths.cpu_count()))


class KataGoAI:
    """把 GTP 引擎包装成一个"会下棋的对手"。"""

    def __init__(
        self,
        engine_path: str | Path | None = None,
        model_path: str | Path | None = None,
        config_path: str | Path | None = None,
        visits: int = 400,
        threads: int | None = None,
        log_path: str | Path | None = None,
        on_log: Callable[[str], None] | None = None,
    ) -> None:
        self.engine_path = Path(engine_path) if engine_path else paths.find_engine()
        self.model_path = Path(model_path) if model_path else paths.find_model()
        self.config_path = Path(config_path) if config_path else paths.find_config()
        self.visits = int(visits)
        self.threads = int(threads) if threads else default_threads()
        self.log_path = Path(log_path) if log_path else (paths.LOGS_DIR / "katago_engine.log")
        self.on_log = on_log
        self._engine: GtpEngine | None = None
        self._lock = threading.RLock()
        self._size = 19
        self._komi = 7.5
        self.last_error: str | None = None

    # ------------------------------------------------------------ 状态
    @property
    def engine(self) -> GtpEngine | None:
        return self._engine

    @property
    def alive(self) -> bool:
        return bool(self._engine and self._engine.alive)

    def require_ready(self) -> None:
        missing = []
        if not self.engine_path or not Path(self.engine_path).is_file():
            missing.append("引擎 (katago/bin)")
        if not self.model_path or not Path(self.model_path).is_file():
            missing.append("权重 (katago/models/*.bin.gz)")
        if not self.config_path or not Path(self.config_path).is_file():
            missing.append("配置 (katago/configs/default_gtp.cfg)")
        if missing:
            raise RuntimeError("缺少 " + "、".join(missing) + ", 请先运行: python3 setup_katago.py")

    # ------------------------------------------------------------ 生命周期
    def start(self, startup_timeout: float = 600.0) -> None:
        """启动引擎 (若已在运行则直接返回)。首次调用会加载神经网络, 需要数秒。"""
        with self._lock:
            if self.alive:
                return
            self.require_ready()
            self.stop()
            override = {
                "maxVisits": self.visits,
                "numSearchThreads": self.threads,
                "ponderingEnabled": "false",
                "logSearchInfo": "false",
                "logAllGTPCommunication": "false",
                "reportAnalysisWinratesAs": "BLACK",
            }
            paths.LOGS_DIR.mkdir(parents=True, exist_ok=True)
            self._engine = GtpEngine(
                binary=self.engine_path,
                model=self.model_path,
                config=self.config_path,
                override_config=override,
                workdir=paths.PROJECT_ROOT,
                log_path=self.log_path,
                startup_timeout=startup_timeout,
                timeout=1800.0,
            )
            self._log(f"启动引擎: {self._engine.command()}")
            self._engine.start()
            self._engine.boardsize(self._size)
            self._engine.komi(self._komi)
            version = ""
            try:
                version = self._engine.version()
            except GtpError:
                pass
            self._log(f"引擎就绪: {self._engine.engine_name} {version} (线程 {self.threads}, 每手 {self.visits} 次访问)")

    def stop(self) -> None:
        with self._lock:
            if self._engine is not None:
                try:
                    self._engine.close()
                except Exception:
                    pass
                self._engine = None

    def restart(self) -> None:
        self.stop()
        self.start()

    def _log(self, message: str) -> None:
        if self.on_log:
            try:
                self.on_log(message)
            except Exception:
                pass

    # ------------------------------------------------------------ 参数
    def set_visits(self, visits: int) -> None:
        self.visits = max(1, int(visits))
        if self.alive and self._engine is not None:
            if not self._engine.set_param("maxVisits", self.visits):
                self._log("kata-set-param 不受支持, 下次重开引擎时生效")
        self._log(f"每手访问次数 = {self.visits}")

    def set_threads(self, threads: int) -> None:
        """线程数只能在启动时确定 (需要重启引擎)。"""
        threads = max(1, int(threads))
        if threads != self.threads:
            self.threads = threads
            if self.alive:
                self.restart()

    # ------------------------------------------------------------ 对局
    def new_game(self, size: int, komi: float, handicap: int = 0) -> None:
        self._size = int(size)
        self._komi = float(komi)
        self.start()
        assert self._engine is not None
        self._engine.boardsize(self._size)
        self._engine.komi(self._komi)
        self._engine.clear_board()
        if handicap:
            for vertex in _handicap_vertices(self._size, handicap):
                self._engine.play("B", vertex)

    def replay(self, moves: list[tuple[str, str]], size: int, komi: float, handicap: int = 0) -> None:
        """用完整棋谱重建引擎局面 (悔棋/读谱时使用)。"""
        self.start()
        assert self._engine is not None
        self._engine.boardsize(size)
        self._engine.komi(komi)
        self._engine.clear_board()
        if handicap:
            for vertex in _handicap_vertices(size, handicap):
                self._engine.play("B", vertex)
        for color, vertex in moves:
            self._engine.play(color, vertex)
        self._size, self._komi = size, komi

    def play(self, color: str, vertex: str) -> None:
        if self.alive and self._engine is not None:
            self._engine.play(color, vertex)

    def genmove(self, color: str, on_info: Callable[[dict], None] | None = None,
                interval_ms: int = 250) -> tuple[str, dict | None]:
        """让 AI 走一手, 返回 (坐标, 分析信息)。坐标可能是 'pass' 或 'resign'。"""
        self.start()
        assert self._engine is not None
        try:
            move, info = self._engine.genmove_analyze(color, interval_ms=interval_ms, on_info=on_info)
        except GtpEngineDied:
            self._log("引擎意外退出, 正在重启…")
            self.restart()
            assert self._engine is not None
            move, info = self._engine.genmove_analyze(color, interval_ms=interval_ms, on_info=on_info)
        return move, info

    def analyze(self, color: str | None = None, seconds: float = 1.0) -> tuple[dict | None, list[dict]]:
        """形势判断: 返回 (rootInfo, 候选点列表)。"""
        self.start()
        assert self._engine is not None
        root = self._engine.root_info(color, seconds=seconds)
        return root, []

    def final_score(self) -> str | None:
        if not self.alive or self._engine is None:
            return None
        try:
            return self._engine.final_score()
        except GtpError:
            return None


def _handicap_vertices(size: int, count: int) -> list[str]:
    from .board import GoBoard
    board = GoBoard(size)
    return [board.to_gtp(r, c) for r, c in GoBoard.handicap_points(size, count)]
