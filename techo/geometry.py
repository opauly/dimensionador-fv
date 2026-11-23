"""Geometry of the roof plan: the modules of a string as rotated rectangles in photo pixels, and the fit checks (overlap, inside the roof).

Conventions: photo pixels, y down, rotation in degrees clockwise (what the eye sees on screen). A string is a block of modules around its centre:
`count` modules in `rows` rows, `portrait` (the long side of each module vertical in the block) or `landscape`, with `gap_m` between modules
(the mid clamp) in both directions. The same maths runs in the browser (webapp/static/techo.js); validate_techo.py pins the numbers.
"""
from __future__ import annotations

import math

Point = tuple[float, float]


def module_dims(width_m: float, height_m: float, orient: str) -> tuple[float, float]:
    """(w, h) of one module in the string's own frame: portrait = short side across, landscape = long side across."""
    return (width_m, height_m) if orient != "landscape" else (height_m, width_m)


def block_layout(count: int, rows: int, w: float, h: float, gap: float) -> dict:
    """Rows x columns of a string and the size of its block (metres)."""
    count = max(0, int(count))
    rows = max(1, min(int(rows or 1), max(1, count)))
    cols = max(1, math.ceil(count / rows))
    return {"rows": rows, "cols": cols, "w": cols * w + (cols - 1) * gap, "h": rows * h + (rows - 1) * gap}


def _rot(x: float, y: float, deg: float) -> Point:
    a = math.radians(deg)
    return x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a)


def module_polys(s: dict, width_m: float, height_m: float, gap_m: float, px_per_m: float) -> list[list[Point]]:
    """The four corners (photo pixels) of every module of string `s` ({count, rows, orient, x, y, rot})."""
    w, h = module_dims(width_m, height_m, s.get("orient") or "portrait")
    b = block_layout(s.get("count", 0), s.get("rows", 1), w, h, gap_m)
    out = []
    for i in range(max(0, int(s.get("count", 0)))):
        r, c = divmod(i, b["cols"])
        x0, y0 = -b["w"] / 2 + c * (w + gap_m), -b["h"] / 2 + r * (h + gap_m)
        quad = []
        for (lx, ly) in ((x0, y0), (x0 + w, y0), (x0 + w, y0 + h), (x0, y0 + h)):
            rx, ry = _rot(lx * px_per_m, ly * px_per_m, s.get("rot", 0.0))
            quad.append((s.get("x", 0.0) + rx, s.get("y", 0.0) + ry))
        out.append(quad)
    return out


def _axes(poly: list[Point]) -> list[Point]:
    ax = []
    for i in range(len(poly)):
        x1, y1 = poly[i]; x2, y2 = poly[(i + 1) % len(poly)]
        ex, ey = x2 - x1, y2 - y1
        n = math.hypot(ex, ey) or 1.0
        ax.append((-ey / n, ex / n))
    return ax


def convex_overlap(a: list[Point], b: list[Point], eps: float = 0.5) -> bool:
    """Separating-axis test for two convex polygons; touching edges (within `eps` pixels) do not count as overlap."""
    for ax, ay in _axes(a) + _axes(b):
        pa = [x * ax + y * ay for x, y in a]
        pb = [x * ax + y * ay for x, y in b]
        if max(pa) <= min(pb) + eps or max(pb) <= min(pa) + eps:
            return False
    return True


def point_in_polygon(pt: Point, poly: list[Point]) -> bool:
    x, y = pt
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]; x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / ((y2 - y1) or 1e-12) + x1:
            inside = not inside
    return inside


def check(strings: list[dict], width_m: float, height_m: float, gap_m: float, px_per_m: float, roof: list[Point] | None = None) -> dict:
    """{polys: {string id: [quads]}, overlaps: [(id, id)], outside: {string id: modules outside the roof outline}}."""
    polys = {s["id"]: module_polys(s, width_m, height_m, gap_m, px_per_m) for s in strings}
    overlaps = []
    ids = [s["id"] for s in strings]
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            if any(convex_overlap(a, b) for a in polys[ids[i]] for b in polys[ids[j]]):
                overlaps.append((ids[i], ids[j]))
    outside: dict = {}
    if roof and len(roof) >= 3:
        for sid, quads in polys.items():
            n = sum(1 for q in quads if not all(point_in_polygon(p, roof) for p in q))
            if n:
                outside[sid] = n
    return {"polys": polys, "overlaps": overlaps, "outside": outside}
