"""围棋棋盘 / 规则 (Tromp-Taylor 简化实现, 面积计分)。

坐标约定
--------
* 内部用 (row, col): row=0 是棋盘最上面一行, col=0 是最左列 —— 与 Tkinter 画布一致。
* GTP 坐标: 列 A..T (跳过 I), 行号从下往上 1..N。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

GTP_COLUMNS = "ABCDEFGHJKLMNOPQRSTUVWXYZ"

HOSHI_POINTS = {
    9: [(2, 2), (2, 6), (6, 2), (6, 6), (4, 4)],
    13: [(3, 3), (3, 9), (9, 3), (9, 9), (6, 6)],
    19: [(3, 3), (3, 9), (3, 15), (9, 3), (9, 9), (9, 15), (15, 3), (15, 9), (15, 15)],
}

# 让子棋的摆放顺序 (标准让子位置, 按 2..9 子)
HANDICAP_ORDER = {
    19: [(15, 3), (3, 15), (3, 3), (15, 15), (3, 9), (15, 9), (9, 3), (9, 15), (9, 9)],
    13: [(9, 3), (3, 9), (3, 3), (9, 9), (3, 6), (9, 6), (6, 3), (6, 9), (6, 6)],
    9: [(6, 2), (2, 6), (2, 2), (6, 6), (2, 4), (6, 4), (4, 2), (4, 6), (4, 4)],
}


class IllegalMove(ValueError):
    """不合法的落子。"""


@dataclass
class MoveResult:
    color: str
    vertex: str
    captured: list[str] = field(default_factory=list)
    ko_point: str | None = None


@dataclass
class ScoreResult:
    black_area: float
    white_area: float
    komi: float
    black_stones: int
    white_stones: int
    black_territory: int
    white_territory: int
    neutral: int
    winner: str  # "B" / "W" / "Draw"
    margin: float
    ownership: list[str] = field(default_factory=list)
    method: str = "area"

    def describe(self) -> str:
        if self.winner == "Draw":
            return f"和棋 (黑 {self.black_area:g} : 白 {self.white_area:g})"
        sign = "+" if self.margin >= 0 else "-"
        return (
            f"{'黑' if self.winner == 'B' else '白'}胜 {abs(self.margin):g} 目 "
            f"(黑 {self.black_area:g} : 白 {self.white_area:g}, 含贴目 {self.komi:g})"
        )


def other(color: str) -> str:
    return "W" if color == "B" else "B"


class GoBoard:
    """N×N 围棋棋盘, 支持提子 / 禁着点(打劫) / 禁自杀 / 面积计分。"""

    def __init__(self, size: int = 19, komi: float = 7.5) -> None:
        if not 2 <= int(size) <= 25:
            raise ValueError("棋盘大小必须在 2..25 之间")
        self.size = int(size)
        self.komi = float(komi)
        self.grid: list[str] = [""] * (self.size * self.size)
        self.ko_point: int | None = None
        self.captures = {"B": 0, "W": 0}   # 各方提掉的对方子数
        self.history: list[tuple] = []
        self.move_count = 0
        self.consecutive_passes = 0

    # ------------------------------------------------------------ 基础工具
    def clone(self) -> "GoBoard":
        b = GoBoard(self.size, self.komi)
        b.grid = list(self.grid)
        b.ko_point = self.ko_point
        b.captures = dict(self.captures)
        b.history = list(self.history)
        b.move_count = self.move_count
        b.consecutive_passes = self.consecutive_passes
        return b

    def reset(self) -> None:
        self.grid = [""] * (self.size * self.size)
        self.ko_point = None
        self.captures = {"B": 0, "W": 0}
        self.history.clear()
        self.move_count = 0
        self.consecutive_passes = 0

    def index(self, row: int, col: int) -> int:
        return row * self.size + col

    def rc(self, idx: int) -> tuple[int, int]:
        return divmod(idx, self.size)

    def in_bounds(self, row: int, col: int) -> bool:
        return 0 <= row < self.size and 0 <= col < self.size

    def to_gtp(self, row: int, col: int) -> str:
        if not self.in_bounds(row, col):
            raise ValueError("坐标越界")
        return f"{GTP_COLUMNS[col]}{self.size - row}"

    def from_gtp(self, vertex: str) -> tuple[int, int] | None:
        """GTP 坐标 -> (row, col); 'pass' 返回 None。非法坐标抛 ValueError。"""
        v = (vertex or "").strip().upper()
        if v in ("PASS", ""):
            return None
        if len(v) < 2 or v[0] not in GTP_COLUMNS:
            raise ValueError(f"无法识别的坐标: {vertex!r}")
        col = GTP_COLUMNS.index(v[0])
        try:
            number = int(v[1:])
        except ValueError:
            raise ValueError(f"无法识别的坐标: {vertex!r}") from None
        row = self.size - number
        if not self.in_bounds(row, col):
            raise ValueError(f"坐标超出棋盘: {vertex!r}")
        return row, col

    def neighbors(self, idx: int) -> Iterable[int]:
        row, col = self.rc(idx)
        if row > 0:
            yield idx - self.size
        if row < self.size - 1:
            yield idx + self.size
        if col > 0:
            yield idx - 1
        if col < self.size - 1:
            yield idx + 1

    def _group(self, idx: int) -> tuple[set[int], set[int]]:
        """返回 (同色连通块, 该块的气)。"""
        color = self.grid[idx]
        stones: set[int] = {idx}
        liberties: set[int] = set()
        stack = [idx]
        seen = {idx}
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

    def group_of(self, row: int, col: int) -> tuple[set[int], set[int]]:
        return self._group(self.index(row, col))

    # ------------------------------------------------------------ 规则
    def is_legal(self, color: str, vertex: str) -> tuple[bool, str]:
        try:
            pos = self.from_gtp(vertex)
        except ValueError as exc:
            return False, str(exc)
        if pos is None:
            return True, ""
        row, col = pos
        idx = self.index(row, col)
        if self.grid[idx]:
            return False, "该点已有棋子"
        if self.ko_point is not None and idx == self.ko_point:
            return False, "打劫, 此处暂不能落子"
        return True, ""

    def play(self, color: str, vertex: str) -> MoveResult:
        """落子; 不合法时抛 IllegalMove。"""
        color = color.upper()
        if color not in ("B", "W"):
            raise IllegalMove(f"未知颜色: {color}")
        try:
            pos = self.from_gtp(vertex)
        except ValueError as exc:
            raise IllegalMove(str(exc)) from None
        if pos is None:  # 停一手
            self.history.append(("pass", color, None))
            self.move_count += 1
            self.consecutive_passes += 1
            self.ko_point = None
            return MoveResult(color, "pass")
        row, col = pos
        idx = self.index(row, col)
        if self.grid[idx]:
            raise IllegalMove(f"{vertex} 已有棋子")
        if self.ko_point is not None and idx == self.ko_point:
            raise IllegalMove("打劫, 此处暂不能落子")

        snapshot = (list(self.grid), self.ko_point, dict(self.captures))
        self.grid[idx] = color
        captured: list[int] = []
        for n in list(self.neighbors(idx)):
            if self.grid[n] == other(color):
                stones, libs = self._group(n)
                if not libs:
                    for s in stones:
                        self.grid[s] = ""
                    captured.extend(sorted(stones))
        own_stones, own_libs = self._group(idx)
        if not own_libs:  # 自杀手
            self.grid, self.ko_point, self.captures = snapshot
            raise IllegalMove("自杀手, 不允许")

        self.captures[color] += len(captured)
        ko: int | None = None
        if len(captured) == 1 and len(own_stones) == 1 and len(own_libs) == 1:
            ko = captured[0]
        self.ko_point = ko
        self.history.append(("move", color, idx, tuple(captured), ko))
        self.move_count += 1
        self.consecutive_passes = 0
        return MoveResult(color, self.to_gtp(row, col),
                          [self.to_gtp(*self.rc(i)) for i in captured],
                          self.to_gtp(*self.rc(ko)) if ko is not None else None)

    def pass_move(self, color: str) -> MoveResult:
        return self.play(color, "pass")

    def undo(self) -> bool:
        """撤销最后一手 (含提子恢复)。"""
        if not self.history:
            return False
        entry = self.history.pop()
        self.move_count = max(0, self.move_count - 1)
        if entry[0] == "pass":
            self.ko_point = None
            self.consecutive_passes = max(0, self.consecutive_passes - 1)
            return True
        _, color, idx, captured, _ko = entry
        self.grid[idx] = ""
        for c in captured:
            self.grid[c] = other(color)
        self.captures[color] -= len(captured)
        self.ko_point = self.history[-1][4] if self.history and self.history[-1][0] == "move" else None
        self.consecutive_passes = 0
        return True

    def is_game_over(self) -> bool:
        return self.consecutive_passes >= 2

    # ------------------------------------------------------------ 计分
    def score(self, komi: float | None = None) -> ScoreResult:
        """Tromp-Taylor 面积计分: 棋子 + 只被一方包围的空点。"""
        k = self.komi if komi is None else float(komi)
        size = self.size
        visited = [False] * (size * size)
        ownership = [""] * (size * size)
        black_territory = white_territory = neutral = 0
        for start in range(size * size):
            if self.grid[start] or visited[start]:
                continue
            region: list[int] = []
            borders: set[str] = set()
            stack = [start]
            visited[start] = True
            while stack:
                cur = stack.pop()
                region.append(cur)
                for n in self.neighbors(cur):
                    c = self.grid[n]
                    if c == "":
                        if not visited[n]:
                            visited[n] = True
                            stack.append(n)
                    else:
                        borders.add(c)
            if borders == {"B"}:
                black_territory += len(region)
                for i in region:
                    ownership[i] = "B"
            elif borders == {"W"}:
                white_territory += len(region)
                for i in region:
                    ownership[i] = "W"
            else:
                neutral += len(region)
        black_stones = sum(1 for c in self.grid if c == "B")
        white_stones = sum(1 for c in self.grid if c == "W")
        for i, c in enumerate(self.grid):
            if c:
                ownership[i] = c
        black_area = float(black_stones + black_territory)
        white_area = float(white_stones + white_territory) + k
        diff = black_area - white_area
        if abs(diff) < 1e-9:
            winner, margin = "Draw", 0.0
        elif diff > 0:
            winner, margin = "B", diff
        else:
            winner, margin = "W", -diff
        return ScoreResult(black_area, white_area, k, black_stones, white_stones,
                           black_territory, white_territory, neutral, winner, margin, ownership)

    # ------------------------------------------------------------ 显示
    def ascii(self) -> str:
        lines = []
        for row in range(self.size):
            cells = []
            for col in range(self.size):
                c = self.grid[self.index(row, col)]
                cells.append({"B": "X", "W": "O", "": "."}[c])
            lines.append(f"{self.size - row:>2} " + " ".join(cells))
        lines.append("   " + " ".join(GTP_COLUMNS[: self.size]))
        return "\n".join(lines)

    @staticmethod
    def handicap_points(size: int, count: int) -> list[tuple[int, int]]:
        pts = HANDICAP_ORDER.get(size)
        if not pts:
            return []
        return pts[: max(0, min(int(count), len(pts)))]

    def play_handicap(self, count: int) -> list[str]:
        """摆放让子 (默认给黑棋), 返回已摆的 GTP 坐标。"""
        placed = []
        for row, col in self.handicap_points(self.size, count):
            idx = self.index(row, col)
            if self.grid[idx]:
                continue
            self.grid[idx] = "B"
            placed.append(self.to_gtp(row, col))
        self.history.clear()
        self.ko_point = None
        return placed
