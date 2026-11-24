"""Pill snapping, as plain arithmetic (no Qt), so it can be tested on its own."""
from __future__ import annotations

Rect = tuple[int, int, int, int]      # left, top, width, height


def snap(x: int, y: int, w: int, h: int, others: list[Rect], area: Rect, px: int = 10) -> tuple[int, int]:
    """Nudge a window at (x, y) of size (w, h) so its edges meet nearby windows' edges
    (side by side, stacked, or lined up) and the screen's edges, if within px."""
    best_x: int | None = None
    best_y: int | None = None

    def consider(cur: int, target: int, best: int | None) -> int | None:
        d = target - cur
        if abs(d) <= px and (best is None or abs(d) < abs(best)):
            return d
        return best

    for ol, ot, ow, oh in others:
        o_right, o_bottom = ol + ow, ot + oh
        if y < o_bottom + px and y + h > ot - px:            # level with each other: snap sides
            for target in (o_right, ol - w, ol, o_right - w):
                best_x = consider(x, target, best_x)
        if x < o_right + px and x + w > ol - px:             # above/below each other: snap tops/bottoms
            for target in (o_bottom, ot - h, ot, o_bottom - h):
                best_y = consider(y, target, best_y)
    al, at, aw, ah = area
    for target in (al, al + aw - w):
        best_x = consider(x, target, best_x)
    for target in (at, at + ah - h):
        best_y = consider(y, target, best_y)
    return x + (best_x or 0), y + (best_y or 0)


def _touch(a: tuple[int, int, int, int], b: tuple[int, int, int, int], tol: int) -> bool:
    """Two rectangles (x, y, w, h) touch or overlap, allowing a small gap."""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return (ax - tol <= bx + bw and bx - tol <= ax + aw and ay - tol <= by + bh and by - tol <= ay + ah)


def touching_group(start: int, rects: list[tuple[int, int, int, int]], tol: int = 2) -> list[int]:
    """Indexes of every rectangle connected to rects[start] through touching edges (start included)."""
    seen, todo = {start}, [start]
    while todo:
        i = todo.pop()
        for j, r in enumerate(rects):
            if j not in seen and _touch(rects[i], r, tol):
                seen.add(j)
                todo.append(j)
    return sorted(seen)
