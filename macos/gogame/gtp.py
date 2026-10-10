"""KataGo GTP 协议客户端 (线程安全, 支持流式分析)。

协议要点 (实测 KataGo v1.18)
---------------------------
* 普通命令: 响应形如 ``= 文本`` 或 ``?错误``, 多行响应以空行结束。
* 分析类命令 (``kata-analyze`` / ``kata-genmove_analyze``): 引擎先立刻回一行 ``=id``,
  随后把 ``info move ...`` 行当作响应正文持续输出, 最后以空行结束;
  ``kata-genmove_analyze`` 在结尾追加一行 ``play <落子>``。
  因此这类命令不能等"读完响应再返回", 必须一边流式接收一边处理。
* ``interval`` 参数单位是厘秒 (centiseconds), 本文接口统一用毫秒并自动换算。
* 发送空行可以中断正在进行的分析。

本模块用一条后台线程读取 stdout, 普通响应按 id 投递给等待者, 分析行投递给流回调,
分析结束 (收到空行) 时触发事件, 因此可以安全地"限时分析 + 主动中断"。
"""
from __future__ import annotations

import os
import queue
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, Iterable, Sequence

__all__ = [
    "GtpEngine", "GtpError", "GtpTimeout", "GtpEngineDied",
    "parse_info_line", "parse_info_segments",
]

_INFO_KEYS = {
    "move", "visits", "edgeVisits", "winrate", "utility", "scoreMean", "scoreStdev",
    "scoreLead", "scoreSelfplay", "scoreUtility", "prior", "lcb", "utilityLcb", "order",
    "pv", "pvVisits", "pvEdgeVisits", "ownership", "ownershipStdev", "movesOwnership",
    "movesOwnershipStdev", "noResultValue", "isSymmetryOf", "weight", "rawStWrError",
    "rawStScoreError", "rawVarTimeLeft",
}
_SEGMENT_TOKENS = ("info", "rootInfo", "ownership", "ownershipStdev")


class GtpError(RuntimeError):
    """引擎返回 '?' 或协议异常。"""


class GtpTimeout(GtpError):
    """等待响应超时。"""


class GtpEngineDied(GtpError):
    """引擎进程已退出。"""


def _centiseconds(interval_ms: float) -> int:
    """KataGo 的 interval 单位是厘秒, 这里从毫秒换算。"""
    return max(0, int(round(float(interval_ms) / 10.0)))


def _num(value: str):
    try:
        num = float(value)
    except (TypeError, ValueError):
        return value
    if num.is_integer() and "." not in value and "e" not in value.lower():
        return int(num)
    return num


def parse_info_segments(line: str) -> list[dict]:
    """把一行分析输出解析成若干段 (KataGo 会把多个 info 段塞进同一行)。"""
    tokens = (line or "").split()
    if not tokens:
        return []
    segments: list[dict] = []
    current: dict | None = None
    kind = "info"
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in _SEGMENT_TOKENS:
            if current:
                current["_type"] = kind
                segments.append(current)
            kind = tok
            current = {}
            i += 1
            continue
        if current is None:
            current = {}
        if tok in _INFO_KEYS and i + 1 < len(tokens):
            if tok in ("pv", "movesOwnership"):
                j = i + 1
                values = []
                while j < len(tokens) and tokens[j] not in _INFO_KEYS and tokens[j] not in _SEGMENT_TOKENS:
                    values.append(tokens[j])
                    j += 1
                current[tok] = values
                i = j
                continue
            current[tok] = _num(tokens[i + 1])
            i += 2
            continue
        i += 1
    if current:
        current["_type"] = kind
        segments.append(current)
    return segments


def parse_info_line(line: str) -> dict:
    """返回该行第一个 info 段 (兼容旧接口)。"""
    for seg in parse_info_segments(line):
        if seg.get("_type") == "info":
            return seg
    segs = parse_info_segments(line)
    return segs[0] if segs else {}


class GtpEngine:
    """一个 KataGo GTP 子进程。

    典型用法::

        with GtpEngine(engine_path, model_path, config_path) as e:
            e.boardsize(9); e.komi(7.5); e.clear_board()
            e.play("B", "E5")
            move, info = e.genmove_analyze("W", on_info=print)
            infos = e.analyze("B", seconds=1.5)
    """

    def __init__(
        self,
        binary: str | Path,
        model: str | Path | None = None,
        config: str | Path | None = None,
        extra_args: Sequence[str] = (),
        override_config: dict | None = None,
        workdir: str | Path | None = None,
        log_path: str | Path | None = None,
        startup_timeout: float = 600.0,
        timeout: float = 900.0,
        verbose: bool = False,
    ) -> None:
        self.binary = str(binary)
        self.model = str(model) if model else None
        self.config = str(config) if config else None
        self.extra_args = list(extra_args)
        self.override_config = dict(override_config or {})
        self.workdir = str(workdir) if workdir else None
        self.log_path = Path(log_path) if log_path else None
        self.startup_timeout = startup_timeout
        self.timeout = timeout
        self.verbose = verbose

        self.engine_name = "KataGo"
        self._proc: subprocess.Popen | None = None
        self._reader: threading.Thread | None = None
        self._err_thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._stream_lock = threading.Lock()
        self._waiters: dict[int, queue.Queue] = {}
        self._streaming_ids: set[int] = set()
        self._stream_end: dict[int, threading.Event] = {}
        self._active_stream: int | None = None
        self._stream_cb: Callable[[str], None] | None = None
        self._next_id = 0
        self._alive = False
        self._closing = False
        self._unsolicited: list[str] = []
        self._stderr_tail: list[str] = []

    # ------------------------------------------------------------ 生命周期
    def command(self) -> list[str]:
        cmd = [self.binary, "gtp"]
        if self.model:
            cmd += ["-model", self.model]
        if self.config:
            cmd += ["-config", self.config]
        if self.override_config:
            pairs = ",".join(f"{k}={v}" for k, v in self.override_config.items())
            cmd += ["-override-config", pairs]
        cmd += self.extra_args
        return cmd

    def start(self) -> "GtpEngine":
        if self._alive:
            return self
        kwargs: dict = dict(
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        if self.workdir:
            kwargs["cwd"] = self.workdir
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self._proc = subprocess.Popen(self.command(), **kwargs)
        self._alive = True
        self._closing = False
        self._reader = threading.Thread(target=self._reader_loop, name="gtp-reader", daemon=True)
        self._reader.start()
        self._err_thread = threading.Thread(target=self._stderr_loop, name="gtp-stderr", daemon=True)
        self._err_thread.start()
        self.engine_name = self.send("name", timeout=self.startup_timeout).strip()
        return self

    def close(self, timeout: float = 10.0) -> None:
        proc = self._proc
        if proc is None:
            return
        self._closing = True
        try:
            if proc.poll() is None and proc.stdin:
                try:
                    proc.stdin.write("quit\n")
                    proc.stdin.flush()
                except Exception:
                    pass
                try:
                    proc.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    proc.kill()
        finally:
            self._alive = False
            try:
                if proc.stdin:
                    proc.stdin.close()
            except Exception:
                pass
            self._proc = None

    def kill(self) -> None:
        proc = self._proc
        if proc and proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                pass
        self._alive = False

    def __enter__(self) -> "GtpEngine":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.close()

    @property
    def alive(self) -> bool:
        return bool(self._alive and self._proc is not None and self._proc.poll() is None)

    @property
    def stderr_tail(self) -> str:
        return "".join(self._stderr_tail[-40:])

    # ------------------------------------------------------------ 读取线程
    def _reader_loop(self) -> None:
        proc = self._proc
        assert proc is not None and proc.stdout is not None
        try:
            while True:
                line = proc.stdout.readline()
                if line == "":
                    break
                text = line.rstrip("\r\n")
                if text[:1] in ("=", "?"):
                    self._collect_response(text)
                elif text.strip():
                    self._dispatch_stream(text)
                else:
                    self._finish_stream()
        except Exception:
            pass
        finally:
            self._alive = False
            with self._lock:
                waiters = list(self._waiters.values())
                self._waiters.clear()
                events = list(self._stream_end.values())
                self._stream_end.clear()
            for q in waiters:
                q.put(("!", "engine process ended"))
            for ev in events:
                ev.set()

    def _collect_response(self, first: str) -> None:
        status = first[0]
        body = first[1:].strip()
        rid: int | None = None
        m = re.match(r"^(\d+)\s?(.*)$", body)
        if m:
            rid = int(m.group(1))
            body = m.group(2)
        with self._lock:
            streaming = rid is not None and rid in self._streaming_ids
        if streaming:
            # 分析类命令: '=id' 只是"已开始", 后续 info/play 行稍后流式到达
            self._active_stream = rid
            with self._lock:
                q = self._waiters.pop(rid, None)
            if q is not None:
                q.put((status, body))
            return
        lines = [body] if body else []
        proc = self._proc
        if proc is not None and proc.stdout is not None:
            while True:
                nxt = proc.stdout.readline()
                if nxt == "":
                    break
                t = nxt.rstrip("\r\n")
                if t.strip() == "":
                    break
                lines.append(t)
        text = "\n".join(lines).strip()
        if self.verbose:
            print("<", status, rid, text[:400])
        with self._lock:
            q = self._waiters.pop(rid, None) if rid is not None else None
        if q is not None:
            q.put((status, text))
        else:
            self._unsolicited.append(f"{status}{rid if rid is not None else ''} {text}".strip())
            del self._unsolicited[:-50]

    def _dispatch_stream(self, line: str) -> None:
        with self._stream_lock:
            cb = self._stream_cb
        if cb is not None:
            try:
                cb(line)
                return
            except Exception:
                return
        self._unsolicited.append(line)
        del self._unsolicited[:-50]

    def _finish_stream(self) -> None:
        rid = self._active_stream
        self._active_stream = None
        if rid is None:
            return
        with self._lock:
            ev = self._stream_end.pop(rid, None)
        if ev is not None:
            ev.set()

    def _stderr_loop(self) -> None:
        proc = self._proc
        assert proc is not None and proc.stderr is not None
        fh = None
        if self.log_path:
            try:
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                fh = open(self.log_path, "a", encoding="utf-8")
                fh.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} 引擎启动 =====\n")
                fh.flush()
            except Exception:
                fh = None
        try:
            for line in proc.stderr:
                self._stderr_tail.append(line)
                del self._stderr_tail[:-40]
                if fh:
                    try:
                        fh.write(line)
                        fh.flush()
                    except Exception:
                        pass
        except Exception:
            pass
        finally:
            if fh:
                try:
                    fh.close()
                except Exception:
                    pass

    # ------------------------------------------------------------ 命令收发
    def _write(self, text: str) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None or proc.poll() is not None:
            raise GtpEngineDied("引擎进程未运行")
        if self.verbose:
            print(">", text)
        proc.stdin.write(text + "\n")
        proc.stdin.flush()

    def _register(self, streaming: bool = False) -> tuple[int, queue.Queue]:
        with self._lock:
            self._next_id += 1
            rid = self._next_id
            q: queue.Queue = queue.Queue()
            self._waiters[rid] = q
            if streaming:
                self._streaming_ids.add(rid)
                self._stream_end[rid] = threading.Event()
            return rid, q

    def _unregister(self, rid: int) -> None:
        with self._lock:
            self._waiters.pop(rid, None)
            self._streaming_ids.discard(rid)
            self._stream_end.pop(rid, None)

    def send(self, command: str, timeout: float | None = None) -> str:
        """发送普通命令并等待 '=' 响应; '?' 响应抛 GtpError。"""
        if self._proc is None or (not self._alive and not self._closing):
            raise GtpEngineDied("引擎尚未启动或已经退出")
        rid, q = self._register()
        try:
            self._write(f"{rid} {command}")
        except Exception:
            self._unregister(rid)
            raise
        wait = self.timeout if timeout is None else timeout
        try:
            status, text = q.get(timeout=wait)
        except queue.Empty:
            self._unregister(rid)
            raise GtpTimeout(f"等待 {command!r} 响应超时 ({wait:.0f}s)") from None
        if status == "!":
            raise GtpEngineDied(text or "引擎进程已退出")
        if status == "?":
            raise GtpError(f"{command} 失败: {text}")
        return text

    def send_ok(self, command: str, timeout: float | None = None) -> tuple[bool, str]:
        """发送命令但不抛 GtpError, 返回 (是否成功, 文本)。"""
        try:
            return True, self.send(command, timeout=timeout)
        except GtpEngineDied:
            raise
        except GtpError as exc:
            return False, str(exc)

    # ------------------------------------------------------------ 流式分析
    def set_stream_callback(self, cb: Callable[[str], None] | None) -> None:
        with self._stream_lock:
            self._stream_cb = cb

    def start_stream(self, command: str, timeout: float = 30.0) -> int:
        """发送分析类命令, 等引擎回 '=' 后立即返回 (分析结果通过回调流式到达)。"""
        rid, q = self._register(streaming=True)
        try:
            self._write(f"{rid} {command}")
            status, text = q.get(timeout=timeout)
        except queue.Empty:
            self._unregister(rid)
            raise GtpTimeout(f"等待 {command!r} 开始响应超时") from None
        except Exception:
            self._unregister(rid)
            raise
        if status == "?":
            self._unregister(rid)
            raise GtpError(f"{command} 失败: {text}")
        return rid

    def stop_stream(self, rid: int, timeout: float = 6.0) -> None:
        """中断分析: 先发空行, 必要时用普通命令兜底, 然后等分析自然收尾。"""
        with self._lock:
            ev = self._stream_end.get(rid)
        try:
            self._write("")
        except Exception:
            self._unregister(rid)
            return
        if ev is not None and ev.wait(timeout=timeout):
            self._unregister(rid)
            return
        try:
            self._write("kata-get-param maxVisits")   # 兜底: 真实命令也能打断分析
        except Exception:
            pass
        if ev is not None:
            ev.wait(timeout=timeout)
        self._unregister(rid)

    def analyze(self, color: str | None = None, seconds: float = 1.0, interval_ms: int = 200,
                options: Iterable[str] = ()) -> list[dict]:
        """对当前局面限时分析, 返回按 visits 降序的候选点列表。"""
        collected: list[str] = []
        self.set_stream_callback(collected.append)
        rid = None
        try:
            parts = ["kata-analyze"]
            if color:
                parts.append(color.upper())
            parts += [f"interval {_centiseconds(interval_ms)}", "rootInfo true"]
            parts += list(options)
            rid = self.start_stream(" ".join(parts))
            deadline = time.time() + max(0.0, float(seconds))
            while time.time() < deadline:
                time.sleep(0.02)
        finally:
            if rid is not None:
                self.stop_stream(rid)
            self.set_stream_callback(None)
        infos: list[dict] = []
        for line in collected:
            for seg in parse_info_segments(line):
                if seg.get("_type") == "info" and "move" in seg:
                    infos.append(seg)
        infos.sort(key=lambda d: float(d.get("visits", 0) or 0), reverse=True)
        return infos

    def root_info(self, color: str | None = None, seconds: float = 1.0,
                  interval_ms: int = 200) -> dict | None:
        """限时分析并返回 rootInfo (整体胜率 / 目差 / 访问量)。"""
        collected: list[str] = []
        self.set_stream_callback(collected.append)
        rid = None
        try:
            parts = ["kata-analyze"]
            if color:
                parts.append(color.upper())
            parts += [f"interval {_centiseconds(interval_ms)}", "rootInfo true"]
            rid = self.start_stream(" ".join(parts))
            deadline = time.time() + max(0.0, float(seconds))
            while time.time() < deadline:
                time.sleep(0.02)
        finally:
            if rid is not None:
                self.stop_stream(rid)
            self.set_stream_callback(None)
        root = None
        for line in collected:
            for seg in parse_info_segments(line):
                if seg.get("_type") == "rootInfo":
                    root = seg
        return root

    def genmove_analyze(self, color: str, interval_ms: int = 200,
                        on_info: Callable[[dict], None] | None = None,
                        options: Iterable[str] = ()) -> tuple[str, dict | None]:
        """带实时分析的 genmove: 返回 (落子, 最后一条 info)。

        ``on_info`` 会在搜索过程中被不断调用, 可用于刷新胜率显示。
        """
        collected: list[dict] = []
        streamed: list[str] = []

        def _cb(line: str) -> None:
            streamed.append(line)
            infos = [s for s in parse_info_segments(line)
                     if s.get("_type") == "info" and "move" in s]
            if not infos:
                return
            # KataGo 每行按 order 排序, 第一个 info 段就是当前最佳着法
            top = infos[0]
            collected.append(top)
            if on_info:
                try:
                    on_info(top)
                except Exception:
                    pass

        self.set_stream_callback(_cb)
        rid = None
        try:
            parts = ["kata-genmove_analyze", color.upper(), f"interval {_centiseconds(interval_ms)}"]
            parts += list(options)
            rid = self.start_stream(" ".join(parts))
            deadline = time.time() + self.timeout
            move = None
            while time.time() < deadline:
                move = self._move_from_lines(streamed)
                if move:
                    break
                if not self.alive:
                    raise GtpEngineDied("引擎在思考过程中退出")
                time.sleep(0.02)
            if not move:
                raise GtpTimeout("等待 genmove 结果超时")
        finally:
            if rid is not None:
                self._unregister(rid)
            self.set_stream_callback(None)
        best = collected[-1] if collected else None
        return move, best

    @staticmethod
    def _move_from_lines(lines: Sequence[str]) -> str | None:
        for line in reversed(list(lines)):
            text = line.strip()
            if text.lower().startswith("play "):
                return text.split(None, 1)[1].strip()
        return None

    @staticmethod
    def _extract_move(text: str) -> str:
        """从 genmove 的普通响应文本里取出落子。"""
        text = (text or "").strip()
        if not text:
            return "pass"
        for line in reversed(text.splitlines()):
            line = line.strip()
            if line.lower().startswith("play "):
                return line.split(None, 1)[1].strip()
        first = text.splitlines()[0].strip()
        return first.split()[0] if first else "pass"

    # ------------------------------------------------------------ 常用封装
    def name(self) -> str:
        return self.send("name", timeout=self.startup_timeout).strip()

    def version(self) -> str:
        return self.send("version").strip()

    def boardsize(self, size: int) -> str:
        return self.send(f"boardsize {int(size)}")

    def komi(self, value: float) -> str:
        return self.send(f"komi {value}")

    def clear_board(self) -> str:
        return self.send("clear_board")

    def play(self, color: str, vertex: str) -> str:
        return self.send(f"play {color} {vertex}")

    def genmove(self, color: str) -> str:
        return self._extract_move(self.send(f"genmove {color}"))

    def undo(self) -> str:
        return self.send("undo")

    def final_score(self) -> str:
        return self.send("final_score").strip()

    def set_param(self, key: str, value) -> bool:
        ok, _ = self.send_ok(f"kata-set-param {key} {value}")
        return ok

    def get_param(self, key: str) -> str | None:
        ok, text = self.send_ok(f"kata-get-param {key}")
        return text if ok else None

    def set_rules(self, rules: str) -> bool:
        ok, _ = self.send_ok(f"kata-set-rules {rules}")
        return ok

    def time_settings(self, main_time: float, byo_yomi: float = 0.0, stones: int = 1) -> bool:
        ok, _ = self.send_ok(f"time_settings {main_time} {byo_yomi} {stones}")
        return ok
