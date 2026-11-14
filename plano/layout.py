"""Workshop plan ("plano de taller") layout: where the equipment hangs on ONE wall and the smallest wall that holds it.

Oscar's rules (photos of his real installs, 2026-11-10..13), front view, millimetres, y up from the floor:

  Row 1 (top)     the inverters (Victron units side by side, or a row per Fronius in Grid Zero), the gabinete 50x40x20 upright and aligned by
                  the top with them, the Chint DC box(es), then the AC-coupled Fronius (aligned by its BASE with the Victron units) or, in
                  DC-coupled systems, the charge controllers in the Fronius's place.
  Duct            a 4x4 in duct right under row 1; its length is the length of row 1 (equipment + gabinete).
  Row 2 (below)   the load centers, the Lynx Power In bars lying side by side, and the Pylontech Fidus batteries on the WALL lying flat, two per
                  column (columns side by side, hanging under the duct). US5000 / UF5000 rack batteries do not hang: they sit on a separate
                  metal stand on the floor (2 per level, up to 6 per stand).
  Many Victron    one row first; if the wall is too narrow for it, the units go in two rows.

The minimum work area is the bounding box of all of that plus a margin on the sides and on top. Sizes come from the datasheets stored in
the catalog; what has no datasheet yet is an ESTIMATE and is flagged, never silently used as if it were real.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

# Gaps (mm). Oscar: "lo que pida la ficha" for the batteries; the rest are the spacing seen in his photos, to be refined with him.
GAP_INVERTERS = 60        # between inverters in a row
GAP_BLOCKS = 80           # between the blocks of row 1 (inverters -> gabinete -> boxes -> Fronius)
GAP_BOXES = 40            # between small boxes of the same kind
GAP_TO_DUCT = 150         # bottom of row 1 to the top of the duct (the cables bend there)
GAP_DUCT_ROW2 = 100       # bottom of the duct to the top of row 2
GAP_ROWS_STACKED = 60     # between two rows of Victron units
FLOOR_GAP = 100           # lowest wall-mounted item to the floor
GAP_ROW2 = 50             # between blocks of row 2 and between battery columns
GAP_BATTERY_STACK = 20    # between the two batteries of a column
MARGIN = 50               # extra wall on each side and on top of the equipment
DUCT_SECTION = 101.6      # 4 x 4 in

# Estimates, flagged in the plan: NEMA 3R load centers (2 / 4 / 8 spaces) and the metal stand of the US5000 / UF5000.
CENTER_ESTIMATE = {2: (150.0, 230.0, 90.0), 4: (200.0, 300.0, 100.0), 8: (260.0, 360.0, 100.0)}
STAND_SLOTS = 6           # batteries per stand (3 levels x 2), the same rule as the materials list
STAND_PER_LEVEL = 2
STAND_LEVEL_H = 80        # structure between two levels (estimate)
STAND_PAD = 30            # side clearance around the batteries on the stand (estimate)

PLACEHOLDER = (300.0, 300.0, 150.0)      # for a part whose datasheet size is not loaded yet


@dataclass
class Part:
    key: str
    label: str
    w: float
    h: float
    d: float
    qty: int = 1
    real: bool = True            # size from a datasheet / drawing; False = estimate
    missing: bool = False        # no size at all: a placeholder is drawn
    note: str = ""


@dataclass
class Spec:
    """What the design needs on the wall. Parts are None when the system does not have them."""
    system: str = "hybrid"
    victron: Part | None = None
    fronius: Part | None = None          # AC-coupled Fronius, or the Grid Zero inverter(s)
    controllers: Part | None = None
    gabinete: Part | None = None
    chint: Part | None = None
    centers: list[Part] = field(default_factory=list)
    lynx: Part | None = None
    fidus: Part | None = None
    rack: Part | None = None             # US5000 / UF5000 (on stands)
    notes: list[str] = field(default_factory=list)


def part(key: str, label: str, dims: tuple | None, qty: int, *, real: bool = True, fallback: tuple | None = None, note: str = "") -> Part | None:
    """A Part from (w, h, d). No dims at all -> a placeholder, flagged as missing."""
    if qty <= 0:
        return None
    if dims and all(dims[:2]):
        w, h, d = float(dims[0]), float(dims[1]), float(dims[2] or 0)
        return Part(key, label, w, h, d, qty, real, False, note)
    if fallback:
        w, h, d = fallback
        return Part(key, label, w, h, d, qty, False, False, note)
    w, h, d = PLACEHOLDER
    return Part(key, label, w, h, d, qty, False, True, note or "sin ficha cargada")


def center_part(spaces: int, qty: int) -> Part | None:
    w, h, d = CENTER_ESTIMATE.get(spaces, CENTER_ESTIMATE[8])
    return part(f"center{spaces}", f"Centro de carga {spaces} esp.", (w, h, d), qty, real=False, note="medida estimada")


@dataclass
class Rect:
    kind: str
    label: str
    x: float
    y: float
    w: float
    h: float
    real: bool = True
    missing: bool = False


@dataclass
class Layout:
    mode: str                  # "single" | "double"
    rects: list[Rect]
    width: float               # bounding box of the equipment
    height: float
    row1_w: float
    duct: Rect | None
    notes: list[str]

    def needed(self, margin: float = MARGIN) -> tuple[float, float]:
        """Wall needed: the equipment plus the margin on both sides and on top."""
        return self.width + 2 * margin, self.height + margin


def _label(p: Part, i: int) -> str:
    return f"{p.label} #{i + 1}" if p.qty > 1 else p.label


def place(spec: Spec, mode: str = "single") -> Layout:
    """Place everything. `mode` 'double' puts the Victron units in two rows. Coordinates: x from the left edge of the equipment, y from the floor."""
    notes: list[str] = list(spec.notes)
    rects: list[Rect] = []

    # ── Row 2 first: its height fixes where the duct goes ──
    fid = spec.fidus
    rack = spec.rack
    fid_stack_h = (2 * fid.h + GAP_BATTERY_STACK) if (fid and fid.qty >= 2) else (fid.h if fid else 0.0)
    stands = math.ceil(rack.qty / STAND_SLOTS) if rack else 0
    stand_w = stand_h = 0.0
    if rack:
        per_stand = min(STAND_SLOTS, rack.qty)
        levels = math.ceil(per_stand / STAND_PER_LEVEL)
        stand_w = STAND_PER_LEVEL * rack.w + (STAND_PER_LEVEL + 1) * STAND_PAD
        stand_h = levels * (rack.h + STAND_LEVEL_H) + STAND_LEVEL_H
    row2_items_h = [c.h for c in spec.centers] + ([spec.lynx.h] if spec.lynx else [])
    wall_batt_top = (FLOOR_GAP + fid_stack_h) if fid else 0.0
    row2_top = max([wall_batt_top, stand_h] + [FLOOR_GAP + h for h in row2_items_h] + [FLOOR_GAP])

    # ── Row 1 ──
    row1_blocks: list[tuple[str, list[Rect], float, float]] = []   # (kind, rects at (0,0)-relative, w, h)

    def line_of(p: Part, kind: str, gap: float, align: str = "top") -> tuple[list[Rect], float, float]:
        rs, x = [], 0.0
        for i in range(p.qty):
            rs.append(Rect(kind, _label(p, i), x, 0, p.w, p.h, p.real, p.missing))
            x += p.w + gap
        return rs, max(0.0, x - gap), p.h

    if spec.victron:
        v = spec.victron
        if mode == "double" and v.qty >= 3:
            cols = math.ceil(v.qty / 2)
            rs = []
            for i in range(v.qty):
                r, cx = divmod(i, cols)
                rs.append(Rect("victron", _label(v, i), cx * (v.w + GAP_INVERTERS), r * (v.h + GAP_ROWS_STACKED), v.w, v.h, v.real, v.missing))
            row1_blocks.append(("victron", rs, cols * v.w + (cols - 1) * GAP_INVERTERS, 2 * v.h + GAP_ROWS_STACKED))
        else:
            rs, w, h = line_of(v, "victron", GAP_INVERTERS)
            row1_blocks.append(("victron", rs, w, h))
    if spec.system == "grid_zero" and spec.fronius:
        pass    # the Grid Zero Fronius goes last, after the gabinete (no Victron units to line up with)
    if spec.gabinete:
        g = spec.gabinete
        row1_blocks.append(("gabinete", [Rect("gabinete", g.label, 0, 0, g.w, g.h, g.real, g.missing)], g.w, g.h))
    if spec.chint:
        rs, w, h = line_of(spec.chint, "chint", GAP_BOXES)
        row1_blocks.append(("chint", rs, w, h))
    if spec.fronius:
        rs, w, h = line_of(spec.fronius, "fronius", GAP_INVERTERS)
        row1_blocks.append(("fronius", rs, w, h))
    if spec.controllers:
        rs, w, h = line_of(spec.controllers, "controller", GAP_BOXES)
        row1_blocks.append(("controller", rs, w, h))

    row1_h = max((h for *_, h in row1_blocks), default=0.0)
    victron_h = next((h for k, _, _, h in row1_blocks if k == "victron"), None)
    ref_h = victron_h if victron_h is not None else row1_h      # with Victron units the gabinete / boxes hang from THEIR top line
    duct_top = row2_top + GAP_DUCT_ROW2 + DUCT_SECTION
    row1_bottom = duct_top + GAP_TO_DUCT
    x = 0.0
    top = row1_bottom
    for kind, rs, w, h in row1_blocks:
        for r in rs:
            if victron_h is not None and kind in ("victron", "fronius"):
                base = row1_bottom                                  # the AC-coupled Fronius is aligned by its BASE with the Victron units
            else:
                base = max(row1_bottom, row1_bottom + ref_h - h)    # aligned by the top
            r.x += x
            r.y = base + r.y
            rects.append(r)
            top = max(top, r.y + r.h)
        x += w + GAP_BLOCKS
    row1_w = max(0.0, x - GAP_BLOCKS)

    duct = None
    if row1_blocks:
        duct = Rect("duct", f"Ducto 4x4\" · {row1_w:.0f} mm", 0, duct_top - DUCT_SECTION, row1_w, DUCT_SECTION)

    # ── Row 2 placement ──
    x2 = 0.0
    for c in spec.centers:
        for i in range(c.qty):
            rects.append(Rect("center", _label(c, i), x2, row2_top - c.h, c.w, c.h, c.real, c.missing))
            x2 += c.w + GAP_ROW2
    if spec.lynx:
        for i in range(spec.lynx.qty):
            rects.append(Rect("lynx", _label(spec.lynx, i), x2, row2_top - spec.lynx.h, spec.lynx.w, spec.lynx.h, spec.lynx.real, spec.lynx.missing))
            x2 += spec.lynx.w + (GAP_BOXES if i < spec.lynx.qty - 1 else GAP_ROW2)
    if fid:
        cols = math.ceil(fid.qty / 2)
        for ci in range(cols):
            for r in range(2):
                n = ci * 2 + r
                if n >= fid.qty:
                    break
                rects.append(Rect("fidus", f"{fid.label} #{n + 1}", x2, FLOOR_GAP + r * (fid.h + GAP_BATTERY_STACK), fid.w, fid.h, fid.real, fid.missing))
            x2 += fid.w + GAP_ROW2
    if rack:
        for s in range(stands):
            n_in = min(STAND_SLOTS, rack.qty - s * STAND_SLOTS)
            rects.append(Rect("stand", f"Mueble baterías #{s + 1} ({n_in} × {rack.label})", x2, 0, stand_w, stand_h, False, False))
            x2 += stand_w + GAP_ROW2
    row2_w = max(0.0, x2 - GAP_ROW2)

    width = max(row1_w, row2_w)
    height = top if row1_blocks else row2_top
    if rack:
        notes.append("El mueble de las baterías US5000 / UF5000 es una medida estimada (dos por nivel, hasta 6 por mueble).")
    return Layout(mode, rects, width, height, row1_w, duct, notes)


def check(layout: Layout, wall_w: float | None, wall_h: float | None, margin: float = MARGIN) -> dict:
    """{'fits', 'need_w', 'need_h', 'slack_w', 'slack_h'} (mm). slack < 0 = missing wall."""
    nw, nh = layout.needed(margin)
    out = {"need_w": round(nw), "need_h": round(nh), "wall_w": wall_w, "wall_h": wall_h, "fits": None, "slack_w": None, "slack_h": None}
    if wall_w and wall_h:
        out["slack_w"], out["slack_h"] = round(wall_w - nw), round(wall_h - nh)
        out["fits"] = out["slack_w"] >= 0 and out["slack_h"] >= 0
    return out


def choose(spec: Spec, wall_w: float | None, wall_h: float | None, margin: float = MARGIN) -> tuple[Layout, dict, list[tuple[Layout, dict]]]:
    """The first arrangement that fits the wall (one row of Victron units, then two rows); if none fits, the one with the least overflow.
    With no wall, one row. Returns (layout, check, all tried)."""
    modes = ["single"] + (["double"] if (spec.victron and spec.victron.qty >= 3) else [])
    tried = []
    for m in modes:
        lay = place(spec, m)
        tried.append((lay, check(lay, wall_w, wall_h, margin)))
    if not (wall_w and wall_h):
        return tried[0][0], tried[0][1], tried
    for lay, chk in tried:
        if chk["fits"]:
            return lay, chk, tried
    best = max(tried, key=lambda t: min(t[1]["slack_w"], t[1]["slack_h"]))
    return best[0], best[1], tried
