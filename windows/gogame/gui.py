"""Tkinter 人机对战界面。

界面线程只负责绘图; 所有引擎调用 (加载模型 / 思考 / 分析) 都在后台线程完成,
通过 queue 回传结果, 避免界面卡死。
"""
from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk  # noqa: F401  (filedialog 由 save_sgf 使用)

from . import paths
from .ai import DIFFICULTY_PRESETS, KataGoAI
from .board import GTP_COLUMNS, GoBoard, IllegalMove, other

WOOD = "#e3b96b"
WOOD_DARK = "#c99b4e"
LINE = "#4a3520"
BLACK_STONE = "#1b1b1b"
WHITE_STONE = "#f7f7f2"
HUMAN_HINT = "#1e6f2f"

PRESET_BY_LABEL = {f"{name} · 每手 {visits} 次": (key, visits, desc) for key, name, visits, desc in DIFFICULTY_PRESETS}
DEFAULT_DIFFICULTY = "中级 · 每手 400 次"


def sgf_vertex(board: GoBoard, vertex: str) -> str:
    """GTP 坐标 (如 Q16) -> SGF 坐标 (如 pd); 'pass' 转成空字符串。"""
    if not vertex or vertex.lower() == "pass":
        return ""
    row, col = board.from_gtp(vertex)

    def letter(index: int) -> str:
        return chr(ord("a") + index) if index < 26 else chr(ord("A") + index - 26)

    return letter(col) + letter(row)


class GoGameApp:
    def __init__(self, root: tk.Tk, visits: int | None = None, threads: int | None = None) -> None:
        self.root = root
        root.title("KataGo 人机对战 · 围棋")
        root.minsize(880, 700)

        # ---------------------------------------------------------- 对局状态
        self.board_size = 19
        self.komi = 7.5
        self.handicap = 0
        self.human_color = "B"
        self.ai_color = "W"
        self.board = GoBoard(self.board_size, self.komi)
        self.moves: list[tuple[str, str]] = []
        self.ai_thinking = False
        self.game_over = False
        self.hover: tuple[int, int] | None = None
        self.last_move: tuple[int, int, str] | None = None
        self.black_winrate: float | None = None
        self.show_territory = tk.BooleanVar(value=False)
        self.auto_ai_resign = tk.BooleanVar(value=True)

        # ---------------------------------------------------------- 引擎
        # 命令行传入的 --visits / --threads 优先级高于界面里的难度下拉框
        self.custom_visits = int(visits) if visits else None
        self.ai = KataGoAI(visits=int(visits) if visits else 400, threads=threads,
                           on_log=self._engine_log)
        self.msg_queue: "queue.Queue[tuple]" = queue.Queue()
        self.engine_ready = False
        self.engine_error: str | None = None
        self.install_running = False
        self.thinking_started = 0.0
        self.last_visits = 0

        self._build_ui()
        self._draw_board()
        self.root.after(60, self._poll_queue)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(200, self._boot_engine)

    # ================================================================ 界面
    def _build_ui(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        outer = ttk.Frame(self.root, padding=8)
        outer.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(outer, background=WOOD, highlightthickness=1,
                                highlightbackground="#8a6a30")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Button-1>", self.on_click)
        self.canvas.bind("<Motion>", self.on_motion)
        self.canvas.bind("<Leave>", lambda _e: self._clear_hover())
        self.canvas.bind("<Configure>", lambda _e: self._draw_board())

        panel = ttk.Frame(outer, padding=(10, 0, 0, 0))
        panel.pack(side="right", fill="y")

        ttk.Label(panel, text="KataGo 人机对战", font=("", 16, "bold")).pack(anchor="w")
        self.status_var = tk.StringVar(value="正在启动引擎…")
        ttk.Label(panel, textvariable=self.status_var, foreground="#0a5", wraplength=250,
                  justify="left").pack(anchor="w", pady=(4, 8))

        # 胜率
        wr_box = ttk.LabelFrame(panel, text="形势 (黑棋视角)", padding=6)
        wr_box.pack(fill="x", pady=4)
        self.winrate_var = tk.StringVar(value="—")
        ttk.Label(wr_box, textvariable=self.winrate_var, font=("", 12, "bold")).pack(anchor="w")
        self.winrate_bar = ttk.Progressbar(wr_box, maximum=100, length=230)
        self.winrate_bar.pack(fill="x", pady=(4, 0))

        self.info_var = tk.StringVar(value="AI 尚未落子")
        ttk.Label(panel, textvariable=self.info_var, wraplength=250, justify="left",
                  foreground="#444").pack(anchor="w", pady=(4, 8))

        # 新局设置
        box = ttk.LabelFrame(panel, text="新局设置", padding=6)
        box.pack(fill="x", pady=4)

        row = ttk.Frame(box)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="棋盘", width=6).pack(side="left")
        self.size_var = tk.IntVar(value=19)
        for size in (9, 13, 19):
            ttk.Radiobutton(row, text=f"{size}路", value=size, variable=self.size_var,
                            command=self._on_setting_change).pack(side="left")

        row = ttk.Frame(box)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="执子", width=6).pack(side="left")
        self.color_var = tk.StringVar(value="B")
        ttk.Radiobutton(row, text="执黑先行", value="B", variable=self.color_var,
                        command=self._on_setting_change).pack(side="left")
        ttk.Radiobutton(row, text="执白", value="W", variable=self.color_var,
                        command=self._on_setting_change).pack(side="left")

        row = ttk.Frame(box)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="贴目", width=6).pack(side="left")
        self.komi_var = tk.StringVar(value="7.5")
        ttk.Entry(row, textvariable=self.komi_var, width=6).pack(side="left")
        ttk.Label(row, text="让子").pack(side="left", padx=(10, 2))
        self.handicap_var = tk.IntVar(value=0)
        ttk.Spinbox(row, from_=0, to=9, width=4, textvariable=self.handicap_var).pack(side="left")

        row = ttk.Frame(box)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="难度", width=6).pack(side="left")
        self.difficulty_var = tk.StringVar(value=DEFAULT_DIFFICULTY)
        combo = ttk.Combobox(row, textvariable=self.difficulty_var, state="readonly", width=18,
                             values=[f"{name} · 每手 {visits} 次" for _k, name, visits, _d in DIFFICULTY_PRESETS])
        combo.pack(side="left", fill="x", expand=True)
        combo.bind("<<ComboboxSelected>>", lambda _e: self._on_difficulty_change())

        row = ttk.Frame(box)
        row.pack(fill="x", pady=2)
        ttk.Checkbutton(row, text="显示地盘估算", variable=self.show_territory,
                        command=self._draw_board).pack(anchor="w")
        ttk.Checkbutton(row, text="AI 劣势过大时认输", variable=self.auto_ai_resign).pack(anchor="w")

        ttk.Button(box, text="开始新局", command=self.new_game).pack(fill="x", pady=(6, 0))

        # 对局操作
        ops = ttk.LabelFrame(panel, text="对局操作", padding=6)
        ops.pack(fill="x", pady=4)
        grid = ttk.Frame(ops)
        grid.pack(fill="x")
        ttk.Button(grid, text="停一手", command=self.human_pass).grid(row=0, column=0, sticky="ew", padx=2, pady=2)
        ttk.Button(grid, text="悔棋", command=self.undo).grid(row=0, column=1, sticky="ew", padx=2, pady=2)
        ttk.Button(grid, text="形势判断", command=self.estimate).grid(row=1, column=0, sticky="ew", padx=2, pady=2)
        ttk.Button(grid, text="认输", command=self.resign).grid(row=1, column=1, sticky="ew", padx=2, pady=2)
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)

        # 引擎状态 / 日志
        log_box = ttk.LabelFrame(panel, text="引擎", padding=6)
        log_box.pack(fill="both", expand=True, pady=4)
        self.engine_status_var = tk.StringVar(value="未连接")
        ttk.Label(log_box, textvariable=self.engine_status_var, wraplength=250,
                  justify="left").pack(anchor="w")
        self.log_text = tk.Text(log_box, height=7, width=30, wrap="word", state="disabled",
                                font=("", 9))
        self.log_text.pack(fill="both", expand=True, pady=(4, 0))

        self.capture_var = tk.StringVar(value="提子  黑 0 : 白 0")
        ttk.Label(panel, textvariable=self.capture_var, foreground="#444").pack(anchor="w")

        menubar = tk.Menu(self.root)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="新局", command=self.new_game)
        file_menu.add_command(label="保存棋谱 (SGF)…", command=self.save_sgf)
        file_menu.add_command(label="重新安装 / 修复 KataGo", command=self.run_installer_dialog)
        file_menu.add_separator()
        file_menu.add_command(label="退出", command=self.on_close)
        menubar.add_cascade(label="文件", menu=file_menu)
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="使用说明", command=self._show_help)
        help_menu.add_command(label="关于", command=self._show_about)
        menubar.add_cascade(label="帮助", menu=help_menu)
        self.root.config(menu=menubar)

    # ================================================================ 绘图
    def _geometry(self) -> tuple[float, float, float]:
        """返回 (格子边长, 左边距, 上边距)。"""
        w = max(self.canvas.winfo_width(), 200)
        h = max(self.canvas.winfo_height(), 200)
        cell = min(w, h) / (self.board_size + 1.6)
        margin_x = (w - cell * (self.board_size - 1)) / 2
        margin_y = (h - cell * (self.board_size - 1)) / 2
        return cell, margin_x, margin_y

    def _point(self, row: int, col: int) -> tuple[float, float]:
        cell, mx, my = self._geometry()
        return mx + col * cell, my + row * cell

    def _hit(self, x: float, y: float) -> tuple[int, int] | None:
        cell, mx, my = self._geometry()
        col = round((x - mx) / cell)
        row = round((y - my) / cell)
        if 0 <= row < self.board_size and 0 <= col < self.board_size:
            px, py = self._point(row, col)
            if (px - x) ** 2 + (py - y) ** 2 <= (cell * 0.62) ** 2:
                return row, col
        return None

    def _draw_board(self) -> None:
        c = self.canvas
        c.delete("all")
        cell, mx, my = self._geometry()
        n = self.board_size
        pad = cell * 0.8
        c.create_rectangle(mx - pad, my - pad, mx + (n - 1) * cell + pad, my + (n - 1) * cell + pad,
                           fill=WOOD, outline=WOOD_DARK, width=2)
        for i in range(n):
            x0, y0 = self._point(0, i)
            x1, y1 = self._point(n - 1, i)
            c.create_line(x0, y0, x1, y1, fill=LINE, width=1)
            x0, y0 = self._point(i, 0)
            x1, y1 = self._point(i, n - 1)
            c.create_line(x0, y0, x1, y1, fill=LINE, width=1)
        # 星位
        for r, col in GoBoard.handicap_points(n, 9 if n == 19 else 5):
            x, y = self._point(r, col)
            rad = max(2.0, cell * 0.09)
            c.create_oval(x - rad, y - rad, x + rad, y + rad, fill=LINE, outline=LINE)
        # 坐标
        for i in range(n):
            x, _y = self._point(n - 1, i)
            c.create_text(x, my + (n - 1) * cell + cell * 0.55, text=GTP_COLUMNS[i],
                          fill="#5b4321", font=("", max(8, int(cell * 0.34))))
            _x, y = self._point(i, 0)
            c.create_text(mx - cell * 0.55, y, text=str(n - i),
                          fill="#5b4321", font=("", max(8, int(cell * 0.34))))

        # 地盘估算
        if self.show_territory.get():
            score = self.board.score(self.komi)
            for idx, owner in enumerate(score.ownership):
                if owner and not self.board.grid[idx]:
                    r, col = self.board.rc(idx)
                    x, y = self._point(r, col)
                    s = cell * 0.16
                    color = "#2b2b2b" if owner == "B" else "#ffffff"
                    c.create_rectangle(x - s, y - s, x + s, y + s, fill=color, outline="")

        # 棋子
        radius = cell * 0.46
        for idx, stone in enumerate(self.board.grid):
            if not stone:
                continue
            r, col = self.board.rc(idx)
            x, y = self._point(r, col)
            fill = BLACK_STONE if stone == "B" else WHITE_STONE
            outline = "#000000" if stone == "B" else "#9a9a92"
            c.create_oval(x - radius, y - radius, x + radius, y + radius,
                          fill=fill, outline=outline, width=1.2)
            if stone == "W":
                c.create_oval(x - radius * 0.72, y - radius * 0.72, x - radius * 0.15, y - radius * 0.15,
                              fill="#ffffff", outline="")

        # 最后一手标记
        if self.last_move and not self.game_over:
            r, col, color = self.last_move
            x, y = self._point(r, col)
            mark = "#ffffff" if color == "B" else "#d33"
            rad = max(2.0, cell * 0.14)
            c.create_oval(x - rad, y - rad, x + rad, y + rad, fill=mark, outline=mark)

        # 悬停预览
        if self.hover and not self.game_over and not self.ai_thinking:
            r, col = self.hover
            if not self.board.grid[self.board.index(r, col)]:
                x, y = self._point(r, col)
                c.create_oval(x - radius, y - radius, x + radius, y + radius,
                              outline=HUMAN_HINT, width=2, dash=(4, 3))

        self.capture_var.set(f"提子  黑 {self.board.captures['B']} : 白 {self.board.captures['W']}"
                             f"   ·   手数 {len(self.moves)}")

    def _clear_hover(self) -> None:
        if self.hover is not None:
            self.hover = None
            self._draw_board()

    def on_motion(self, event) -> None:
        hit = self._hit(event.x, event.y)
        if hit != self.hover:
            self.hover = hit
            self._draw_board()

    # ================================================================ 引擎
    def _engine_log(self, message: str) -> None:
        self.msg_queue.put(("log", message))

    def _boot_engine(self) -> None:
        if not paths.is_installed():
            missing = "、".join(paths.missing_pieces())
            self.engine_status_var.set("缺少组件: " + missing)
            self._append_log("未检测到完整的 KataGo 安装。")
            self.status_var.set("需要先安装 KataGo")
            self.root.after(300, self.run_installer_dialog)
            return
        self.status_var.set("引擎加载中, 请稍候…")
        self._append_log(f"引擎: {paths.find_engine()}")
        self._append_log(f"权重: {paths.find_model().name}")
        # 注意: Tk 变量只能在主线程读取, 先把难度值取出来再交给后台线程
        visits = self._current_visits()
        threading.Thread(target=self._start_engine_worker, args=(visits,), daemon=True).start()

    def _start_engine_worker(self, visits: int) -> None:
        try:
            self.ai.set_visits(visits)
            self.ai.start()
            self.msg_queue.put(("engine_ready", None))
        except Exception as exc:  # noqa: BLE001
            self.msg_queue.put(("engine_error", str(exc)))

    def _current_visits(self) -> int:
        if self.custom_visits:
            return self.custom_visits
        label = self.difficulty_var.get()
        return PRESET_BY_LABEL.get(label, ("normal", 400, ""))[1]

    def _on_difficulty_change(self) -> None:
        self.custom_visits = None      # 手动改难度后, 以界面选择为准
        visits = self._current_visits()
        self.ai.set_visits(visits)
        self._append_log(f"难度调整为每手 {visits} 次访问")

    def _on_setting_change(self) -> None:
        if self.moves:
            self.status_var.set("设置已改变, 点击\u201c开始新局\u201d生效")

    # ================================================================ 新局
    def new_game(self, *, auto_start: bool = True) -> None:
        if self.ai_thinking:
            messagebox.showinfo("请稍候", "AI 正在思考, 等它下完再开新局。")
            return
        self.board_size = int(self.size_var.get())
        try:
            self.komi = float(self.komi_var.get())
        except ValueError:
            self.komi = 7.5
            self.komi_var.set("7.5")
        self.handicap = max(0, min(9, int(self.handicap_var.get())))
        self.human_color = self.color_var.get()
        self.ai_color = other(self.human_color)
        if self.handicap:
            self.human_color = "B"
            self.ai_color = "W"
            self.komi = 0.5 if self.komi >= 1 else self.komi
            self.komi_var.set(str(self.komi))
        self.board = GoBoard(self.board_size, self.komi)
        self.moves = []
        self.game_over = False
        self.last_move = None
        self.black_winrate = None
        self.winrate_var.set("—")
        self.winrate_bar["value"] = 0
        self.info_var.set("AI 尚未落子")
        if self.handicap:
            self.board.play_handicap(self.handicap)
        self._draw_board()
        self.status_var.set("新局开始")
        if auto_start:
            threading.Thread(target=self._new_game_worker,
                             args=(self.handicap,), daemon=True).start()

    def _new_game_worker(self, handicap: int) -> None:
        try:
            self.ai.new_game(self.board_size, self.komi, handicap)
            self.msg_queue.put(("new_game_done", None))
        except Exception as exc:  # noqa: BLE001
            self.msg_queue.put(("engine_error", str(exc)))

    # ================================================================ 落子
    def on_click(self, event) -> None:
        if self.game_over:
            return
        if self.ai_thinking:
            return
        if not self.engine_ready:
            self.status_var.set("引擎尚未就绪, 请稍候…")
            return
        if self.board_size != self.board.size:
            self.status_var.set("请先点击\u201c开始新局\u201d")
            return
        hit = self._hit(event.x, event.y)
        if hit is None:
            return
        row, col = hit
        if self.current_turn() != self.human_color:
            self.status_var.set("现在轮到 AI 思考")
            return
        vertex = self.board.to_gtp(row, col)
        ok, why = self.board.is_legal(self.human_color, vertex)
        if not ok:
            self.status_var.set(f"不能下在 {vertex}: {why}")
            return
        try:
            result = self.board.play(self.human_color, vertex)
        except IllegalMove as exc:
            self.status_var.set(str(exc))
            return
        self.moves.append((self.human_color, result.vertex))
        self.last_move = (row, col, self.human_color)
        self.ai.play(self.human_color, result.vertex)
        self._draw_board()
        self.status_var.set(f"你下在 {result.vertex}" + (f", 提 {len(result.captured)} 子" if result.captured else ""))
        self._maybe_ai_move()

    def current_turn(self) -> str:
        if not self.moves:
            # 让子局: 黑方摆完让子后由白方先下
            return "W" if self.handicap else "B"
        return other(self.moves[-1][0])

    def _maybe_ai_move(self) -> None:
        if self.game_over:
            return
        if self.current_turn() != self.ai_color:
            return
        self.ai_thinking = True
        self.thinking_started = time.time()
        self.last_visits = 0
        self.status_var.set("AI 思考中…")
        threading.Thread(target=self._ai_move_worker, daemon=True).start()

    def _ai_move_worker(self) -> None:
        def on_info(info: dict) -> None:
            self.msg_queue.put(("info", info))

        try:
            move, info = self.ai.genmove(self.ai_color, on_info=on_info, interval_ms=250)
            elapsed = time.time() - self.thinking_started
            self.msg_queue.put(("move", (move, info, elapsed)))
        except Exception as exc:  # noqa: BLE001
            self.msg_queue.put(("engine_error", str(exc)))

    def _apply_ai_move(self, move: str, info: dict | None, elapsed: float) -> None:
        self.ai_thinking = False
        move_clean = (move or "pass").strip()
        if move_clean.lower() in ("resign", "cancelled"):
            self.game_over = True
            self.status_var.set("AI 认输了, 你赢了!")
            self._draw_board()
            messagebox.showinfo("对局结束", "AI 认输, 你赢了!")
            return
        if move_clean.lower() == "pass":
            self.board.pass_move(self.ai_color)
            self.moves.append((self.ai_color, "pass"))
            self.last_move = None
            self.status_var.set("AI 停一手")
        else:
            try:
                result = self.board.play(self.ai_color, move_clean)
            except IllegalMove as exc:
                self.game_over = True
                self.status_var.set(f"AI 返回了非法着法 {move_clean}: {exc}")
                messagebox.showerror("引擎异常", f"AI 返回非法着法 {move_clean}: {exc}")
                return
            self.moves.append((self.ai_color, result.vertex))
            row, col = self.board.from_gtp(result.vertex)
            self.last_move = (row, col, self.ai_color)
            self.status_var.set(f"AI 下在 {result.vertex}"
                                + (f", 提 {len(result.captured)} 子" if result.captured else "")
                                + f"   ({elapsed:.1f}s)")
        self._update_winrate(info)
        self._draw_board()
        self._check_game_end()
        if not self.game_over:
            self._maybe_ai_resign()
        if not self.game_over:
            self.status_var.set(self.status_var.get() + "   →  轮到你")

    def _update_winrate(self, info: dict | None) -> None:
        if not info:
            return
        wr = info.get("winrate")
        if isinstance(wr, (int, float)):
            self.black_winrate = float(wr)
            pct = self.black_winrate * 100
            self.winrate_var.set(f"黑 {pct:.1f}%  :  白 {100 - pct:.1f}%")
            self.winrate_bar["value"] = pct
        visits = info.get("visits")
        score_lead = info.get("scoreLead")
        parts = []
        if visits:
            parts.append(f"访问 {visits}")
        if isinstance(score_lead, (int, float)):
            parts.append(f"目差 {float(score_lead):+.1f} (黑视角)")
        pv = info.get("pv")
        if isinstance(pv, list) and pv:
            parts.append("推荐: " + " ".join(str(x) for x in pv[:6]))
        if parts:
            self.info_var.set("\n".join(parts))

    def _maybe_ai_resign(self) -> None:
        if not self.auto_ai_resign.get() or self.black_winrate is None:
            return
        ai_wr = self.black_winrate if self.ai_color == "B" else 1.0 - self.black_winrate
        if ai_wr < 0.02 and len(self.moves) >= max(12, self.board_size):
            self.game_over = True
            self.status_var.set("AI 认输")
            messagebox.showinfo("对局结束", "AI 认为大势已去, 认输了 — 你赢了!")

    # ================================================================ 操作
    def human_pass(self) -> None:
        if self.game_over or self.ai_thinking or not self.engine_ready:
            return
        if self.current_turn() != self.human_color:
            self.status_var.set("现在轮到 AI")
            return
        self.board.pass_move(self.human_color)
        self.moves.append((self.human_color, "pass"))
        self.last_move = None
        self.ai.play(self.human_color, "pass")
        self._draw_board()
        self.status_var.set("你停一手")
        self._check_game_end()
        if not self.game_over:
            self._maybe_ai_move()

    def undo(self) -> None:
        if self.ai_thinking:
            return
        if not self.moves:
            return
        # 撤到轮回玩家行棋为止 (最多两步)
        for _ in range(2):
            if not self.moves:
                break
            color, _vertex = self.moves.pop()
            if color == self.human_color:
                break
        self._rebuild_from_moves()
        self.status_var.set("已悔棋, 轮到你")

    def _rebuild_from_moves(self) -> None:
        self.board = GoBoard(self.board_size, self.komi)
        if self.handicap:
            self.board.play_handicap(self.handicap)
        last = None
        for color, vertex in self.moves:
            try:
                self.board.play(color, vertex)
            except IllegalMove:
                continue
            if vertex != "pass":
                row, col = self.board.from_gtp(vertex)
                last = (row, col, color)
        self.last_move = last
        self.game_over = False
        self._draw_board()
        threading.Thread(target=self._replay_worker, daemon=True).start()

    def _replay_worker(self) -> None:
        try:
            self.ai.replay(list(self.moves), self.board_size, self.komi, self.handicap)
            self.msg_queue.put(("replay_done", None))
        except Exception as exc:  # noqa: BLE001
            self.msg_queue.put(("engine_error", str(exc)))

    def resign(self) -> None:
        if self.game_over:
            return
        if messagebox.askyesno("认输", "确定要认输吗?"):
            self.game_over = True
            self.status_var.set("你认输了")
            messagebox.showinfo("对局结束", "你认输了, 再接再厉!")

    def estimate(self) -> None:
        if not self.engine_ready or self.ai_thinking:
            return
        self.status_var.set("形势判断中…")
        score = self.board.score(self.komi)
        threading.Thread(target=self._estimate_worker, args=(score.describe(),), daemon=True).start()

    def _estimate_worker(self, local_desc: str) -> None:
        try:
            root_info, _ = self.ai.analyze(self.current_turn(), seconds=1.5)
        except Exception as exc:  # noqa: BLE001
            root_info = None
            self.msg_queue.put(("log", f"形势判断失败: {exc}"))
        self.msg_queue.put(("estimate", (local_desc, root_info)))

    def _show_estimate(self, payload) -> None:
        local_desc, root_info = payload
        lines = [f"按当前盘面数子: {local_desc}"]
        if root_info:
            wr = root_info.get("winrate")
            lead = root_info.get("scoreLead")
            visits = root_info.get("visits")
            if isinstance(wr, (int, float)):
                lines.append(f"KataGo 判断黑棋胜率: {float(wr) * 100:.1f}%")
            if isinstance(lead, (int, float)):
                lines.append(f"KataGo 判断目差 (黑视角): {float(lead):+.1f}")
            if visits:
                lines.append(f"分析访问量: {visits}")
        self.status_var.set("形势判断完成")
        messagebox.showinfo("形势判断", "\n".join(lines))

    def _check_game_end(self) -> None:
        if not self.board.is_game_over():
            return
        self.game_over = True
        score = self.board.score(self.komi)
        engine_score = self.ai.final_score()
        text = f"双方停一手, 对局结束。\n\n按面积计分(中国规则): {score.describe()}"
        if engine_score:
            text += f"\n\nKataGo 终局判定: {engine_score}"
        self.status_var.set("对局结束: " + score.describe())
        self._draw_board()
        messagebox.showinfo("对局结束", text)

    # ================================================================ 安装
    def run_installer_dialog(self) -> None:
        if self.install_running:
            return
        if paths.is_installed():
            return
        missing = "、".join(paths.missing_pieces())
        if not messagebox.askyesno("安装 KataGo",
                                   f"检测到缺少: {missing}\n\n是否现在自动下载安装?\n"
                                   "(需要联网, 首次约 1-10 分钟)"):
            return
        self.install_running = True
        self.status_var.set("正在安装 KataGo…")
        threading.Thread(target=self._install_worker, daemon=True).start()

    def _install_worker(self) -> None:
        try:
            from .installer import Installer

            installer = Installer(log=lambda msg: self.msg_queue.put(("log", msg)))
            ok = installer.run()
            self.msg_queue.put(("install_done", ok))
        except Exception as exc:  # noqa: BLE001
            self.msg_queue.put(("log", f"安装异常: {exc}"))
            self.msg_queue.put(("install_done", False))

    # ================================================================ 队列
    def _poll_queue(self) -> None:
        try:
            while True:
                kind, payload = self.msg_queue.get_nowait()
                self._handle_message(kind, payload)
        except queue.Empty:
            pass
        if self.ai_thinking:
            dots = "." * (int(time.time() * 2) % 4)
            self.status_var.set(f"AI 思考中{dots}   {self.last_visits} 次访问")
        self.root.after(80, self._poll_queue)

    def _handle_message(self, kind: str, payload) -> None:
        if kind == "log":
            self._append_log(str(payload))
        elif kind == "info":
            visits = payload.get("visits")
            if visits:
                self.last_visits = visits
        elif kind == "engine_ready":
            self.engine_ready = True
            name = self.ai.engine.engine_name if self.ai.engine else "KataGo"
            self.engine_status_var.set(f"已连接: {name} · 线程 {self.ai.threads} · 每手 {self.ai.visits} 次")
            self.status_var.set("引擎就绪, 点击棋盘落子")
            self.new_game()
        elif kind == "new_game_done":
            self.status_var.set("新局开始 — 轮到你" if self.current_turn() == self.human_color else "轮到 AI")
            if self.current_turn() == self.ai_color:
                self._maybe_ai_move()
        elif kind == "replay_done":
            self.status_var.set("已悔棋, 轮到你")
        elif kind == "move":
            self._apply_ai_move(*payload)
        elif kind == "estimate":
            self._show_estimate(payload)
        elif kind == "engine_error":
            self.ai_thinking = False
            self.engine_ready = False
            self.engine_status_var.set("引擎异常: " + str(payload)[:120])
            self._append_log("引擎错误: " + str(payload))
            self.status_var.set("引擎出错, 详见右侧日志")
            messagebox.showerror("引擎错误",
                                 f"{payload}\n\n可尝试: 菜单 文件 → 重新安装 / 修复 KataGo\n"
                                 f"或运行 python3 test_katago.py 查看详细诊断。")
        elif kind == "install_done":
            self.install_running = False
            if payload:
                self._append_log("安装完成, 正在启动引擎…")
                self.status_var.set("安装完成, 启动引擎…")
                self.root.after(300, self._boot_engine)
            else:
                self.status_var.set("安装失败, 请查看日志")
                messagebox.showerror("安装失败", "自动安装未完成, 请查看右侧日志或手动运行:\n"
                                                 "python3 setup_katago.py")

    def _append_log(self, message: str) -> None:
        try:
            self.log_text.configure(state="normal")
            self.log_text.insert("end", message.rstrip() + "\n")
            lines = int(self.log_text.index("end-1c").split(".")[0])
            if lines > 400:
                self.log_text.delete("1.0", f"{lines - 400}.0")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        except tk.TclError:
            pass

    # ================================================================ 棋谱
    def _build_sgf(self) -> str:
        """生成标准 SGF (Sabaki / Lizzie / KaTrain 均可打开)。"""
        size = self.board_size
        props = ["GM[1]", "FF[4]", "CA[UTF-8]", "AP[KataGo-HumanVsAI:1.0]",
                 f"SZ[{size}]", f"KM[{self.komi:g}]", "RU[Chinese]"]
        engine_name = "KataGo"
        if self.ai.engine is not None:
            engine_name = self.ai.engine.engine_name or "KataGo"
        props.append(f"PB[人类({self.human_color})]")
        props.append(f"PW[{engine_name}({self.ai_color})]")
        props.append(f"GN[KataGo 人机对战 {time.strftime('%Y-%m-%d %H:%M')}]")
        if self.game_over:
            score = self.board.score(self.komi)
            if score.winner == "Draw":
                props.append("RE[0]")
            else:
                props.append(f"RE[{score.winner}+{score.margin:g}]")
        if self.handicap:
            props.append(f"HA[{self.handicap}]")
            stones = "".join(f"[{sgf_vertex(self.board, self.board.to_gtp(r, c))}]"
                             for r, c in GoBoard.handicap_points(size, self.handicap))
            props.append("AB" + stones)
        body = "".join(f";{'B' if color == 'B' else 'W'}[{sgf_vertex(self.board, vertex)}]"
                       for color, vertex in self.moves)
        return "(;" + "".join(props) + "\n" + body + ")\n"   # SGF 根节点必须以 ; 开头

    def save_sgf(self) -> None:
        if not self.moves:
            messagebox.showinfo("保存棋谱", "还没有落子, 先下一手吧。")
            return
        from tkinter import filedialog

        default = f"katago_game_{time.strftime('%Y%m%d_%H%M%S')}.sgf"
        path = filedialog.asksaveasfilename(title="保存棋谱 (SGF)", defaultextension=".sgf",
                                            initialfile=default,
                                            filetypes=[("SGF 棋谱", "*.sgf"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            Path(path).write_text(self._build_sgf(), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("保存失败", str(exc))
            return
        self._append_log(f"棋谱已保存: {path}")
        messagebox.showinfo("保存棋谱", f"已保存到:\n{path}")

    # ================================================================ 其它
    def _show_help(self) -> None:
        messagebox.showinfo("使用说明", HELP_TEXT)

    def _show_about(self) -> None:
        messagebox.showinfo("关于", "KataGo 人机对战\n\n"
                                    "KataGo 引擎: https://github.com/lightvector/KataGo\n"
                                    "本程序: Python + tkinter, 通过 GTP 协议直接调用 KataGo。\n"
                                    "模型与引擎均下载到本项目的 katago/ 目录。")

    def on_close(self) -> None:
        try:
            self.ai.stop()
        except Exception:
            pass
        self.root.destroy()


HELP_TEXT = """操作方式
· 点击棋盘交叉点落子; 绿色虚线框是鼠标预览。
· "停一手" = 弃权, 双方都停一手即终局并自动数子。
· "悔棋" 会撤销一个回合 (你的一手 + AI 的一手)。
· "形势判断" 让 KataGo 花约 2 秒重新评估全局, 给出黑棋胜率与目差。
· 右侧 "显示地盘估算" 会在空点上标出归属(本程序的简化面积计分)。

难度
· 入门/初级/中级/高级/专家 分别对应每手 30/100/400/1200/4000 次神经网络访问。
· CPU 运行时, 19 路棋盘每手约 1-4 秒; 9 路棋盘快得多, 想快就先玩 9 路。

棋盘与规则
· 支持 9/13/19 路、让子 (2-9 子, 让子时自动把贴目改为 0.5)。
· 规则为 KataGo 默认的中国规则 (面积计分), 打劫与自杀均按标准判定。
"""


def run() -> None:
    root = tk.Tk()
    GoGameApp(root)
    root.mainloop()
