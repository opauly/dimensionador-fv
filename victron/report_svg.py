from __future__ import annotations
"""
SVG blocks for the weekly report, ported from Apps Script's `buildReportHtml()`
(`victron-monitor/apps-script/Victron_Events_App_Script_v1p7.js` lines 1007-1525).

Every constant, coordinate and colour here is copied from that function
deliberately — the goal is a report visually indistinguishable from the one
already being emailed, so "tidying up" the geometry would defeat the purpose.
Reference PDF used for calibration:
`Weekly Report - Vista Atenas LP M3 - 2026-07-27.pdf`.

The charts are absolute-coordinate SVG, which is why this port is viable at all:
nothing is left to the layout engine, so WeasyPrint and Google's converter draw
identical geometry. The surrounding HTML/CSS shell lives in
`templates/weekly_report.html`.

Kept in Python rather than Jinja2 on purpose: these blocks are computed geometry
(wrapping, stacked-height measurement, dash-array arithmetic), and expressing
that in template syntax would be far harder to check against the original.
"""
import math
from datetime import date
from html import escape

# ── Palette (from the source) ─────────────────────────────────────
GREEN = "#1FAE6E"
BLUE = "#4A9FD4"
AMBER = "#D4860F"
RED = "#C94040"
MINT = "#C8DDD5"
BG_GREY = "#F7F9F8"
BG_MINT = "#EEF9F4"
LINE = "#E8EDEA"

# ── Layout constants (from the source) ────────────────────────────
PW = 530            # content width all blocks share
GAP = 8
IPAD = 11
ROW_H = 20
IW = (PW - GAP) / 2  # info-block width (half, minus gap)


def esc(v) -> str:
    return escape(str(v), quote=False)


def _f(v, nd=1) -> str:
    return f"{float(v):.{nd}f}"


def wrap_svg_lines(text: str, max_chars: int) -> list[str]:
    """Word-wrap for SVG <text>, which does not wrap on its own.

    Character-count based, exactly like the original — not font-metric based.
    Changing this to real metrics would shift every wrapped subtitle.
    """
    if not text:
        return []
    lines, cur = [], ""
    for w in str(text).split(" "):
        cand = f"{cur} {w}" if cur else w
        if len(cand) > max_chars and cur:
            lines.append(cur)
            cur = w
        else:
            cur = cand
    if cur:
        lines.append(cur)
    return lines


SUB_MAX_CHARS = int((IW - 2 * IPAD) / 3.1)

# ── Text width estimation ─────────────────────────────────────────
# SVG <text> does not wrap or shrink to fit, so a label/value pair that is too
# wide silently draws on top of itself. English never triggered it; Spanish does
# ("Puntaje de calidad de red" + "84/100 — Fluctuaciones menores" against
# "Grid quality score" + "66/100 — Poor"). The original has the same flaw — it
# only ever shipped English layouts that happened to fit.
#
# Per-class widths in em, calibrated against Arial in the reference PDF
# ("59.57 – 60.68 Hz" measures 74.7pt at 9.81pt → ~0.476 em/char average).
_W_NARROW = set("iljItfr.,:;'`|!()[]{}-· ")
# Em/en dash glyphs render close to a full em wide — well past a lowercase
# letter's default estimate. Missing this undercounts any row value that uses
# one as a separator (e.g. "no outages — see Grid Quality"), which is exactly
# the kind of underestimate that lets row_fits() say "fits" when the real
# WeasyPrint render overlaps the label.
_W_WIDE = set("mwMW@%—–")


def text_width(s: str, size: float, bold: bool = False) -> float:
    """Approximate rendered width in SVG user units.

    An estimate on purpose: pulling real font metrics in would mean loading the
    face here, and the only decision it drives is "shrink or not", where being
    slightly conservative is the safe direction.
    """
    w = 0.0
    for ch in str(s):
        if ch in _W_NARROW:
            w += 0.30
        elif ch in _W_WIDE:
            w += 0.83
        elif ch.isupper() or ch.isdigit():
            w += 0.60
        else:
            w += 0.51
    return w * size * (1.05 if bold else 1.0)


ROW_SIZE_MAX = 9.5
ROW_SIZE_FLOOR = 7.0
ROW_GAP = 10.0


def row_fits(label: str, value: str, avail: float, size: float,
             gap: float = ROW_GAP) -> bool:
    return (text_width(label, size)
            + text_width(value, size, bold=True) + gap) <= avail


def uniform_row_size(groups: list[tuple[list[dict], float]],
                     size: float = ROW_SIZE_MAX,
                     floor: float = ROW_SIZE_FLOOR) -> float:
    """One row font size for the whole report.

    Sizing each row independently is technically tighter but reads as a
    mistake: a single shrunken line next to full-size neighbours looks like a
    rendering glitch rather than a deliberate choice. So the report finds the
    largest size at which *every* row fits and uses it everywhere — uniform,
    and only as small as the longest label/value pair actually requires.

    `groups` is [(rows, available width)], since half-width and full-width
    blocks have different room.
    """
    s = size
    while s > floor:
        if all(row_fits(r["label"], r["value"], avail, s)
               for rows, avail in groups for r in rows):
            return s
        s -= 0.25
    return floor


def fit_value(label: str, value: str, avail: float, size: float,
              gap: float = ROW_GAP) -> str:
    """Value text trimmed to fit beside `label` at `size`.

    Only bites at the floor, when even the smallest uniform size cannot fit a
    pair — ellipsizing is still better than drawing two strings on top of each
    other.
    """
    if row_fits(label, value, avail, size, gap):
        return str(value)
    room = avail - text_width(label, size) - gap
    out = str(value)
    while out and text_width(out, size, bold=True) > room:
        out = out[:-1]
    return (out[:-1] + "…") if len(out) > 1 else "…"


def info_block_first_row_y(subtitle: str | None) -> float:
    """Y of the first row, from block top: title + subtitle + separator gap."""
    n = len(wrap_svg_lines(subtitle, SUB_MAX_CHARS)) if subtitle else 0
    return 14 + n * 9 + 8 + 12


def measure_info_block(rows: list[dict], subtitle: str | None) -> float:
    """Height a block needs. Single source of truth for the renderer and for
    callers sizing a sibling block to match — they must not drift apart."""
    return info_block_first_row_y(subtitle) + (len(rows) - 1) * ROW_H + 16


def info_block_svg(x: float, y: float, bg: str, title: str,
                   rows: list[dict], total_h: float,
                   subtitle: str | None = None,
                   first_row_y: float | None = None,
                   row_size: float = ROW_SIZE_MAX) -> str:
    """`first_row_y` overrides where rows start, so two blocks side by side can
    share a baseline even when their subtitles wrap to different line counts.
    Without it a 1-line subtitle next to a 2-line one leaves the two columns'
    rows visibly out of step — invisible in English, obvious in Spanish."""
    sub_lines = wrap_svg_lines(subtitle, SUB_MAX_CHARS) if subtitle else []
    out = (f"<rect x='{_f(x)}' y='{y}' width='{_f(IW)}' height='{total_h}' "
           f"rx='8' fill='{bg}'/>")
    out += (f"<text x='{x + IPAD}' y='{y + 14}' font-size='8' font-weight='700' "
            f"fill='#777'>{esc(title.upper())}</text>")
    for li, line in enumerate(sub_lines):
        out += (f"<text x='{x + IPAD}' y='{y + 14 + (li + 1) * 9}' "
                f"font-size='6.5' fill='#bbb'>{esc(line)}</text>")
    first = y + (first_row_y if first_row_y is not None
                 else info_block_first_row_y(subtitle))
    out += (f"<line x1='{x + IPAD}' y1='{first - 12}' x2='{x + IW - IPAD}' "
            f"y2='{first - 12}' stroke='{LINE}' stroke-width='0.5'/>")
    avail = IW - 2 * IPAD
    for i, row in enumerate(rows):
        ry = first + i * ROW_H
        vtext = fit_value(row["label"], row["value"], avail, row_size)
        out += (f"<text x='{x + IPAD}' y='{ry}' font-size='{row_size:g}' fill='#999'>"
                f"{esc(row['label'])}</text>")
        out += (f"<text x='{x + IW - IPAD}' y='{ry}' font-size='{row_size:g}' "
                f"font-weight='600' fill='{row.get('valueColor', '#222')}' "
                f"text-anchor='end'>{esc(vtext)}</text>")
        if i < len(rows) - 1:
            out += (f"<line x1='{x + IPAD}' y1='{ry + 5}' x2='{x + IW - IPAD}' "
                    f"y2='{ry + 5}' stroke='{LINE}' stroke-width='0.5'/>")
    return out


def _svg(content: str, w: float, h: float) -> str:
    """No fixed height/preserveAspectRatio, so the SVG fills the container
    width and derives height from the viewBox instead of letterboxing.

    `font-family` is set on the root deliberately. WeasyPrint's SVG renderer
    does not inherit the document's body font into <text>, so without this
    every label falls back to the default sans-serif — which resolved to
    Verdana here, a much wider face than Arial. That silently overflowed every
    wrapped subtitle past its block, because the wrap width is computed in
    characters against Arial-ish metrics. Google's converter inherited Arial,
    which is why the original never needed to say so.
    """
    return (f"<svg width='100%' viewBox='0 0 {w} {h}' "
            f"font-family='Arial, Helvetica, sans-serif' "
            f"xmlns='http://www.w3.org/2000/svg'>{content}</svg>")


# ══════════════════════════════════════════════════════════════════
# KPI cards
# ══════════════════════════════════════════════════════════════════
CW = (PW - GAP * 3) / 4
CH = 80
PAD = 11


def score_colors(avg_health: float) -> tuple[str, str, str]:
    if avg_health >= 90:
        return GREEN, "#D9F2E6", "#0F7D4A"
    if avg_health >= 80:
        return BLUE, "#DCEEF8", "#1A5F88"
    if avg_health >= 70:
        return AMBER, "#FDEFC5", "#9A6200"
    return RED, "#FAD9D9", "#8A1F1F"


def wow_pct(curr, prev) -> int | None:
    if not prev:
        return None
    return round((curr - prev) / prev * 100)


def kpi_svg(d: dict, t: dict) -> str:
    score_color, badge_bg, badge_text = score_colors(d["avgHealth"])
    tot = d["totals"]
    # Outages come only from the device's own Grid alarm flag, which can miss
    # a real disturbance the device didn't treat as a full loss — Grid
    # Quality is computed independently, from frequency/voltage extremes, and
    # can be poor even when the outage count reads zero. This is the card a
    # reader looks at first, so the flag belongs on it directly rather than
    # in a separate row elsewhere that's easy to miss.
    flag_grid_quality = tot["outageCount"] == 0 and d["gridQualityScore"] < 90
    outage_bg = "#FEF7EC" if (tot["outageCount"] > 0 or flag_grid_quality) else BG_GREY

    def rect(x, bg):
        return (f"<rect x='{x}' y='0' width='{_f(CW)}' height='{CH}' rx='8' "
                f"fill='{bg}'/>")

    def label(x, s):
        return (f"<text x='{x + PAD}' y='17' font-size='7' font-weight='600' "
                f"fill='#999'>{esc(s)}</text>")

    def value(x, val, unit, color):
        return (f"<text x='{x + PAD}' y='43' font-size='21' font-weight='700' "
                f"fill='{color}'>{esc(val)}"
                f"<tspan font-size='11' font-weight='400' fill='#999'>"
                f"{esc(unit)}</tspan></text>")

    def wow(x, pct, positive_is_good=True):
        if pct is None:
            return ""
        good = pct >= 0 if positive_is_good else pct <= 0
        col = GREEN if good else AMBER
        sign = "+" if pct >= 0 else ""
        return (f"<text x='{x + PAD}' y='57' font-size='8' fill='{col}'>"
                f"{sign}{pct}% {esc(t['wowTrendLabel'])}</text>")

    def sub(x, txt, color="#aaa"):
        return (f"<text x='{x + PAD}' y='70' font-size='8' fill='{color}'>"
                f"{esc(txt)}</text>")

    def badge(x, txt, bg, fg):
        # Width still an estimate (real font metrics need a loaded face —
        # see text_width()'s own docstring), but the text itself is
        # `text-anchor="middle"` at the pill's true horizontal center, not a
        # fixed left-inset — so any mismatch between the estimate and the
        # real glyph width no longer reads as off-center text, only as a
        # slightly generous or snug pill (fixed 2026-08-19, caught from a
        # real rendered PDF: "Excelente" sat visibly left of center).
        bw = min(text_width(txt, 8.5, bold=True) + 14, CW - PAD * 2)
        cx = x + PAD + bw / 2
        return (f"<rect x='{x + PAD}' y='58' width='{bw:.0f}' height='15' "
                f"rx='7.5' fill='{bg}'/>"
                f"<text x='{cx:.1f}' y='69' text-anchor='middle' font-size='8.5' "
                f"font-weight='600' fill='{fg}'>{esc(txt)}</text>")

    x2, x3, x4 = CW + GAP, (CW + GAP) * 2, (CW + GAP) * 3
    prev = d.get("prevTotals")
    pv_pct = wow_pct(tot["pv"], prev["pv"]) if prev else None
    prev_gi = (100 - prev["grid"] / prev["load"] * 100) if prev and prev["load"] else None
    gi_pct = wow_pct(d["gridIndependencePct"], prev_gi)

    best = d.get("bestDay")
    best_sub = (f"{t['bestDayLabel']}: {_f(best['pv'])} {t['kwh']}"
               if best else f"{t['bestDayLabel']}: —")
    gi_sub = f"{tot['daysSelfSufficient']}/{len(d['dailyGrouped'])} {t['days']}"
    outage_sub = (f"{tot['outageMinutes']} {t['minutes']}" if tot["outageCount"] > 0
                  else t["outagesGridQualityNote"] if flag_grid_quality
                  else t["noOutagesShort"])
    outage_col = AMBER if (tot["outageCount"] > 0 or flag_grid_quality) else GREEN

    status_label = t["healthStatus"].get(d["healthStatus"], d["healthStatus"])

    c = (
        rect(0, BG_MINT) + label(0, t["healthScore"].upper())
        + value(0, str(d["avgHealth"]), "/100", score_color)
        + badge(0, status_label, badge_bg, badge_text)

        + rect(x2, BG_GREY) + label(x2, t["pvGenerated"].upper())
        + value(x2, _f(tot["pv"]), " " + t["kwh"], "#111")
        + wow(x2, pv_pct) + sub(x2, best_sub)
    )
    # A grid-independence card is meaningless without a grid. Unlike the Apps
    # Script original — where dropping it meant recomputing four hardcoded
    # column offsets — the cards are laid out from a list here, so an off-grid
    # site simply gets three evenly-spaced cards.
    if d.get("systemType") != "off_grid":
        c += (rect(x3, BG_GREY) + label(x3, t["gridIndependence"].upper())
              + value(x3, f"{d['gridIndependencePct']}%", "", GREEN)
              + wow(x3, gi_pct) + sub(x3, gi_sub))

        # On a site that feeds back, exported energy is the more informative
        # headline than an outage count that is usually zero — a grid-tied
        # exporting system is by definition connected. Outages are not dropped:
        # they stay as a row in the Events block, so nothing is lost.
        if d.get("exportsToGrid"):
            exported = tot.get("gridExport", 0.0)
            share = (exported / tot["pv"] * 100) if tot["pv"] else 0
            c += (rect(x4, BG_MINT) + label(x4, t["gridExportKpi"].upper())
                  + value(x4, _f(exported), " " + t["kwh"], GREEN)
                  + sub(x4, f"{share:.0f}% {t['ofGeneration']}", "#aaa"))
        else:
            c += (rect(x4, outage_bg) + label(x4, t["outages"].upper())
                  + value(x4, str(tot["outageCount"]), "",
                          AMBER if tot["outageCount"] > 0 else "#111")
                  + sub(x4, outage_sub, outage_col))
    else:
        # Off-grid-only KPI cards (report bug fix, 2026-08-18): the two slots
        # a grid-tied card would otherwise fill are meaningless here, so two
        # off-grid-specific metrics take their place instead of sitting blank.
        shutdowns = d.get("lowBatteryShutdownCount")
        if shutdowns is None:
            # Unexpected — fetch_report_window always queries this for an
            # off_grid site — but fail soft rather than crash the report.
            shutdown_bg, shutdown_val, shutdown_val_col = BG_GREY, "—", "#999"
            shutdown_sub_txt, shutdown_sub_col = "—", "#aaa"
        else:
            shutdown_bg = "#FEF7EC" if shutdowns > 0 else BG_MINT
            shutdown_val, shutdown_val_col = str(shutdowns), (AMBER if shutdowns > 0 else "#111")
            shutdown_sub_txt = (t["inverterShutdownsSub"] if shutdowns > 0
                                else t["inverterShutdownsSubZero"])
            shutdown_sub_col = AMBER if shutdowns > 0 else GREEN
        c += (rect(x3, shutdown_bg) + label(x3, t["inverterShutdowns"].upper())
              + value(x3, shutdown_val, "", shutdown_val_col)
              + sub(x3, shutdown_sub_txt, shutdown_sub_col))

        # Standard off-grid sizing metric: how long the battery alone could
        # carry this period's actual average load with zero solar input.
        # Independent of battery_charge_kwh/battery_discharge_kwh (the NULL
        # columns on the vrm_api path) — uses only battery_usable_kwh (site
        # config) and totals["load"] (measured), so it's safe to compute
        # regardless of ingestion path.
        n_days = len(d["dailyGrouped"])
        avg_daily_load = (tot["load"] / n_days) if n_days else 0.0
        batt_usable_raw = (d.get("site") or {}).get("battery_usable_kwh")
        batt_usable = float(batt_usable_raw) if batt_usable_raw else None
        autonomy_days = (batt_usable / avg_daily_load
                         if batt_usable and avg_daily_load > 0 else None)
        c += (
            rect(x4, BG_GREY) + label(x4, t["batteryAutonomy"].upper())
            + value(x4, f"{autonomy_days:.1f}" if autonomy_days is not None else "—",
                    (" " + t["batteryAutonomyUnit"]) if autonomy_days is not None else "",
                    "#111")
            + sub(x4, t["batteryAutonomySub"] if autonomy_days is not None
                  else t["batteryAutonomyUnavailable"])
        )
    return _svg(c, PW, CH)


# ══════════════════════════════════════════════════════════════════
# Daily solar vs. consumption bars
# ══════════════════════════════════════════════════════════════════
def bar_chart_svg(d: dict, t: dict) -> str:
    # SVG_W matches PW, the width every other block in the report uses — it
    # used to be its own narrower 520, which (combined with BAR_LPAD reserving
    # space only on the left) made this one chart sit visibly off-centre
    # against the rest of the page. BAR_RPAD gives the plot a right-hand
    # margin so it no longer runs bars flush to the edge while every other
    # block breathes.
    BAR_H_MAX, SVG_W, BAR_LPAD, BAR_RPAD = 78, PW, 46, 24
    PREF_BAR_W, PREF_BAR_GAP = 10, 3
    sub_lines = wrap_svg_lines(t["subDaily"], int((SVG_W - 22) / 3.2))
    hdr_h = 16 + len(sub_lines) * 10
    top_y = hdr_h + 6
    base_y = top_y + BAR_H_MAX
    svg_h = base_y + 18

    # Overview mode (plan doc §22) draws one bar-pair per bucket instead of
    # per day — `overviewBuckets` is already-summed output from
    # `db.bucket_days()`, so it's `pv`/`load`/`label` rather than
    # `dailyGrouped`'s `pv_kwh`/`load_kwh`/`date`. Buckets max out around 7
    # (183-day cap / ~30-day buckets), comfortably inside every size limit
    # below that was tuned for up to 31 daily bars.
    if d.get("isOverview"):
        days = d["overviewBuckets"]
        get_pv = lambda r: r.get("pv")
        get_load = lambda r: r.get("load")
        get_label = lambda r, n: r["label"]
    else:
        days = d["dailyGrouped"]
        get_pv = lambda r: r.get("pv_kwh")
        get_load = lambda r: r.get("load_kwh")
        get_label = lambda r, n: _x_axis_label(r["date"], t, n)

    n = len(days)
    plot_w = SVG_W - BAR_LPAD - BAR_RPAD
    slot_w = plot_w / max(n, 1)
    # A pair of bars at the fixed size needs 2*PREF_BAR_W+PREF_BAR_GAP px;
    # beyond ~20 days that no longer fits in one slot and neighbouring days'
    # bars start to overlap. Shrink both together to keep exactly filling the
    # slot. At n<=~20 (every length this chart was validated at) this is a
    # no-op — same BAR_W/BAR_GAP as before Phase A.
    if slot_w >= 2 * PREF_BAR_W + PREF_BAR_GAP:
        BAR_W, BAR_GAP = PREF_BAR_W, PREF_BAR_GAP
    else:
        BAR_GAP = max(1.0, slot_w * 0.15)
        BAR_W = max(2.0, (slot_w - BAR_GAP) / 2)
    label_idx = _label_indices(n)
    vals = [float(get_pv(r) or 0) for r in days] + \
           [float(get_load(r) or 0) for r in days]
    # ceil to the next 10, matching the original's Math.ceil(max/10)*10.
    # int(x/10)+1 would round an exact multiple of 10 up a whole step.
    y_max = math.ceil((max(vals) if vals else 1) / 10) * 10 or 10

    def bar_h(v):
        return max(1, round(float(v or 0) / y_max * BAR_H_MAX))

    s = (f"<text x='11' y='12' font-size='8' font-weight='700' fill='#777'>"
         f"{esc(t['sectionDaily'].upper())}</text>")
    for li, line in enumerate(sub_lines):
        s += (f"<text x='11' y='{12 + (li + 1) * 10}' font-size='7' fill='#bbb'>"
              f"{esc(line)}</text>")
    s += _two_bar_legend(SVG_W - BAR_RPAD, t["labelConsumption"], MINT, t)

    for val in (0, round(y_max / 2), y_max):
        gy = base_y - round(val / y_max * BAR_H_MAX)
        s += (f"<line x1='{BAR_LPAD}' y1='{gy}' x2='{SVG_W - BAR_RPAD}' y2='{gy}' "
              f"stroke='{LINE}' stroke-width='0.5'/>")
        s += (f"<text x='{BAR_LPAD - 3}' y='{gy + 3}' text-anchor='end' "
              f"font-size='7' fill='#bbb'>{val} kWh</text>")

    for i, r in enumerate(days):
        cx = BAR_LPAD + slot_w * i + slot_w / 2
        pv_h, load_h = bar_h(get_pv(r)), bar_h(get_load(r))
        s += (f"<rect x='{_f(cx - BAR_W - BAR_GAP / 2)}' y='{_f(base_y - pv_h)}' "
              f"width='{_f(BAR_W)}' height='{pv_h}' fill='{GREEN}' rx='1'/>"
              f"<rect x='{_f(cx + BAR_GAP / 2)}' y='{_f(base_y - load_h)}' "
              f"width='{_f(BAR_W)}' height='{load_h}' fill='{MINT}' rx='1'/>")
        if i in label_idx:
            label = esc(get_label(r, n))
            s += (f"<text x='{_f(cx)}' y='{svg_h - 4}' text-anchor='middle' "
                  f"font-size='8' fill='#aaa'>{label}</text>")
    return _svg(s, SVG_W, svg_h)


def _two_bar_legend(right_x: float, cons_label: str, cons_color: str, t: dict) -> str:
    """Right-aligned Solar/Consumption legend, matching the SOC chart's styling."""
    CWID, SWATCH, TXTGAP, ITEMGAP = 3.7, 7, 3, 12
    solar_label = t["labelSolar"]
    solar_w, cons_w = len(solar_label) * CWID, len(cons_label) * CWID
    total = SWATCH + TXTGAP + solar_w + ITEMGAP + SWATCH + TXTGAP + cons_w
    x = right_x - total
    s = (f"<rect x='{_f(x)}' y='6' width='7' height='7' rx='1' fill='{GREEN}'/>"
         f"<text x='{_f(x + SWATCH + TXTGAP)}' y='13' font-size='7' fill='#aaa'>"
         f"{esc(solar_label)}</text>")
    x += SWATCH + TXTGAP + solar_w + ITEMGAP
    s += (f"<rect x='{_f(x)}' y='6' width='7' height='7' rx='1' "
          f"fill='{cons_color}'/>"
          f"<text x='{_f(x + SWATCH + TXTGAP)}' y='13' font-size='7' fill='#aaa'>"
          f"{esc(cons_label)}</text>")
    return s


def day_abbr(iso_date: str, t: dict) -> str:
    """Weekday label. The original builds `new Date(date+"T12:00:00")` and reads
    getDay(); midday avoids any timezone rollover, and Python's isoweekday()
    is remapped to the same Sunday-first list."""
    d = date.fromisoformat(str(iso_date)[:10])
    return t["dayAbbr"][(d.weekday() + 1) % 7]


def _x_axis_label(iso_date: str, t: dict, n_days: int) -> str:
    """Daily bar/point x-axis label, adapted to how many days are on the
    chart (plan doc §21, Phase A).

    At up to 8 days — the validated 7-day report, with one day of slack — a
    weekday abbreviation is unchanged from before this existed. Beyond that,
    "Mon" repeating every 7 days is ambiguous with no way to tell which
    Monday, so longer `vrm` custom ranges switch to a short date instead.
    """
    if n_days <= 8:
        return day_abbr(iso_date, t)
    d = date.fromisoformat(str(iso_date)[:10])
    return f"{d.day:02d}/{d.month:02d}"


def _label_indices(n_days: int) -> set[int]:
    """Which day indices get an x-axis label, thinned so long ranges (up to
    31 days) stay legible.

    Every bar/point is always drawn — this only thins the *text* underneath,
    which is what actually collides at high day counts. Targets roughly 8
    evenly-spaced labels regardless of range length, so a 31-day chart stays
    as readable as a 10-day one. At 8 or fewer days every index is returned,
    which is every length the chart was validated at before this existed.

    The last day is always included (an operator expects the chart's right
    edge to be dated), but only added on top of the regular step if it's not
    already close to the last regularly-spaced one — otherwise the two sit
    a single slot apart and their text collides. When that happens the last
    regular index is dropped in favour of the true last day rather than
    showing both.
    """
    step = max(1, math.ceil(n_days / 8))
    shown = set(range(0, n_days, step))
    last = n_days - 1
    if last not in shown:
        prev = max(shown)
        if last - prev < step / 2:
            shown.discard(prev)
        shown.add(last)
    return shown


# ══════════════════════════════════════════════════════════════════
# Row 1 — energy mix donut + battery block
# ══════════════════════════════════════════════════════════════════
C_CIRC = 175.9


def _seg(pct: float, prev_sum: float) -> str:
    ln = pct / 100 * C_CIRC
    off = (C_CIRC / 4) - (prev_sum / 100 * C_CIRC)
    return f"stroke-dasharray='{ln:.1f} {C_CIRC:.1f}' stroke-dashoffset='{off:.1f}'"


_DONUT_CWID = 4.6  # approx px/char at font-size 9, same pattern as _two_bar_legend's CWID at font-size 7


def _legend_value_text(pctd: str | None, kwh: float, t: dict) -> str:
    """`"72.6% · 435.4 kWh"`, or an em dash when `pctd` is `None` — the
    energy-mix donut's own "no data" marker (report bug fix, 2026-08-18): a
    site whose `battery_charge_kwh`/`battery_discharge_kwh` are NULL for the
    whole window (the `vrm_api` ingestion path — see `vrm_series.py`'s own
    docstring point 2b) must not show a confident, fabricated "0.0% · 0.0
    kWh" for its Battery slice.
    """
    if pctd is None:
        return "—"
    return f"{pctd}% · {_f(kwh)} {t['kwh']}"


def _donut_dx(card_w: float, legend_rows: list[tuple], t: dict) -> float:
    """Left offset for the donut, chosen so donut+legend sit centered in a
    card of width `card_w` instead of hugging the left edge.

    A fixed offset either wastes space or crowds the numbers depending on the
    site (72.6% · 435.4 kWh vs 5.2% · 8.8 kWh render at very different
    widths), so this sizes the gap to the actual longest value string on this
    card rather than guessing one constant for every site.
    """
    max_value_w = max(len(_legend_value_text(pctd, kwh, t))
                      for _, _, pctd, kwh in legend_rows) * _DONUT_CWID
    content_w = 80 + 55 + max_value_w  # 80: donut-to-legend gap; 55: label-to-value gap
    return max(8.0, (card_w - content_w) / 2)


def row1_svg(d: dict, t: dict, batt_rows: list[dict],
             row_size: float = ROW_SIZE_MAX) -> str:
    tot = d["totals"]
    # See weekly_report.py's build_report_data — False only when
    # battery_charge_kwh AND battery_discharge_kwh are NULL for every row in
    # the window (the vrm_api ingestion path), not merely summing to zero.
    batt_available = tot.get("batteryKwhAvailable", True)
    total_energy = tot["pv"] + tot["grid"] + tot["discharge"]
    solar_pct = round(tot["pv"] / total_energy * 100) if total_energy else 0
    grid_pct = round(tot["grid"] / total_energy * 100) if total_energy else 0
    # Forced to 0, not the rounding-leftover share, when the data isn't
    # available — otherwise a stray 1% rounding leftover still draws a
    # battery-coloured sliver on the ring next to a "—" legend entry.
    batt_pct = max(0, 100 - solar_pct - grid_pct) if batt_available else 0
    sd = _f(tot["pv"] / total_energy * 100) if total_energy else "0.0"
    bd = ((_f(tot["discharge"] / total_energy * 100) if total_energy else "0.0")
          if batt_available else None)
    gd = _f(tot["grid"] / total_energy * 100) if total_energy else "0.0"

    legend_rows = [
        (t["labelSolar"], GREEN, sd, tot["pv"]),
        (t["labelBattery"], BLUE, bd, tot["discharge"]),
        (t["labelGrid"], MINT, gd, tot["grid"]),
    ]

    batt_h = measure_info_block(batt_rows, t["subBattery"])
    em_sub = wrap_svg_lines(t["subEnergyMix"], int((IW - 2 * IPAD) / 3.4))
    em_head_h = 16 + len(em_sub) * 9 + 12
    row1_h = max(batt_h, em_head_h + 72 + 8)
    DX = _donut_dx(IW, legend_rows, t)
    DY = max(em_head_h, (row1_h - 72) / 2)
    LX = DX + 80

    s = (f"<rect x='0' y='0' width='{_f(IW)}' height='{row1_h}' rx='8' "
         f"fill='{BG_GREY}'/>"
         f"<text x='{IPAD}' y='16' font-size='8' font-weight='700' fill='#777'>"
         f"{esc(t['energyMix'].upper())}</text>")
    # Renders at font-size 7, not 6.5, so it needs the wider px/char above —
    # reusing SUB_MAX_CHARS here would let a line overflow the box.
    for li, line in enumerate(em_sub):
        s += (f"<text x='{IPAD}' y='{16 + (li + 1) * 9}' font-size='7' "
              f"fill='#bbb'>{esc(line)}</text>")

    s += (f"<g transform='translate({DX},{DY:.0f})'>"
          f"<circle cx='36' cy='36' r='28' fill='none' stroke='{LINE}' stroke-width='11'/>"
          f"<circle cx='36' cy='36' r='28' fill='none' stroke='{GREEN}' "
          f"stroke-width='11' {_seg(solar_pct, 0)} stroke-linecap='butt'/>"
          f"<circle cx='36' cy='36' r='28' fill='none' stroke='{BLUE}' "
          f"stroke-width='11' {_seg(batt_pct, solar_pct)} stroke-linecap='butt'/>"
          f"<circle cx='36' cy='36' r='28' fill='none' stroke='{MINT}' "
          f"stroke-width='11' {_seg(grid_pct, solar_pct + batt_pct)} stroke-linecap='butt'/>"
          f"<text x='36' y='39' text-anchor='middle' font-size='12' "
          f"font-weight='700' fill='#111'>{sd}%</text>"
          f"<text x='36' y='50' text-anchor='middle' font-size='8' fill='#999'>solar</text>"
          f"</g>")

    for i, (lbl, col, pctd, kwh) in enumerate(legend_rows):
        cy = DY + 22 + i * 20
        s += (f"<circle cx='{LX + 4}' cy='{cy}' r='4' fill='{col}'/>"
              f"<text x='{LX + 12}' y='{cy + 4}' font-size='9' fill='#555'>"
              f"{esc(lbl)}</text>"
              f"<text x='{LX + 55}' y='{cy + 4}' font-size='9' font-weight='600' "
              f"fill='#222'>{esc(_legend_value_text(pctd, kwh, t))}</text>")

    s += info_block_svg(IW + GAP, 0, BG_GREY, t["sectionBattery"],
                        batt_rows, row1_h, t["subBattery"], row_size=row_size)
    return _svg(s, PW, row1_h)


def energy_mix_full_svg(d: dict, t: dict) -> str:
    """Energy mix donut alone, full width, Solar/Grid split only — no battery
    slice or legend row.

    For `grid_zero` sites (grid connection, no battery). The donut is still
    meaningful without a battery — it's just a 2-way split — so the earlier
    version of this report substituted a second, full-width Grid Quality block
    into this slot instead, which then duplicated the Grid Quality block row2
    already renders for any grid-connected system. Solar/Battery/Grid is also
    deliberately not just "Solar/0%/Grid": a `grid_zero` site has no battery
    hardware at all, so the slice is structurally absent, not a
    coincidentally-quiet week for a battery that exists.
    """
    tot = d["totals"]
    total_energy = tot["pv"] + tot["grid"]
    solar_pct = round(tot["pv"] / total_energy * 100) if total_energy else 0
    grid_pct = max(0, 100 - solar_pct)
    sd = _f(tot["pv"] / total_energy * 100) if total_energy else "0.0"
    gd = _f(tot["grid"] / total_energy * 100) if total_energy else "0.0"
    legend_rows = [
        (t["labelSolar"], GREEN, sd, tot["pv"]),
        (t["labelGrid"], MINT, gd, tot["grid"]),
    ]

    em_sub = wrap_svg_lines(t["subEnergyMix"], int((PW - 2 * IPAD) / 3.4))
    em_head_h = 16 + len(em_sub) * 9 + 12
    h = em_head_h + 72 + 8
    DX = _donut_dx(PW, legend_rows, t)
    DY = em_head_h
    LX = DX + 80

    s = (f"<rect x='0' y='0' width='{PW}' height='{h}' rx='8' fill='{BG_GREY}'/>"
         f"<text x='{IPAD}' y='16' font-size='8' font-weight='700' fill='#777'>"
         f"{esc(t['energyMix'].upper())}</text>")
    for li, line in enumerate(em_sub):
        s += (f"<text x='{IPAD}' y='{16 + (li + 1) * 9}' font-size='7' "
              f"fill='#bbb'>{esc(line)}</text>")

    s += (f"<g transform='translate({DX},{DY:.0f})'>"
          f"<circle cx='36' cy='36' r='28' fill='none' stroke='{LINE}' stroke-width='11'/>"
          f"<circle cx='36' cy='36' r='28' fill='none' stroke='{GREEN}' "
          f"stroke-width='11' {_seg(solar_pct, 0)} stroke-linecap='butt'/>"
          f"<circle cx='36' cy='36' r='28' fill='none' stroke='{MINT}' "
          f"stroke-width='11' {_seg(grid_pct, solar_pct)} stroke-linecap='butt'/>"
          f"<text x='36' y='39' text-anchor='middle' font-size='12' "
          f"font-weight='700' fill='#111'>{sd}%</text>"
          f"<text x='36' y='50' text-anchor='middle' font-size='8' fill='#999'>solar</text>"
          f"</g>")

    for i, (lbl, col, pctd, kwh) in enumerate(legend_rows):
        cy = DY + 22 + i * 20
        s += (f"<circle cx='{LX + 4}' cy='{cy}' r='4' fill='{col}'/>"
              f"<text x='{LX + 12}' y='{cy + 4}' font-size='9' fill='#555'>"
              f"{esc(lbl)}</text>"
              f"<text x='{LX + 55}' y='{cy + 4}' font-size='9' font-weight='600' "
              f"fill='#222'>{esc(_legend_value_text(pctd, kwh, t))}</text>")

    return _svg(s, PW, h)


# ══════════════════════════════════════════════════════════════════
# Row 2 — grid quality + events
# ══════════════════════════════════════════════════════════════════
def two_block_row_svg(left_title: str, left_rows: list[dict], left_sub: str,
                      right_title: str, right_rows: list[dict], right_sub: str,
                      right_bg: str = BG_GREY,
                      row_size: float = ROW_SIZE_MAX) -> str:
    # Shared row baseline so the two columns stay in step regardless of how
    # many lines each subtitle wraps to.
    first = max(info_block_first_row_y(left_sub), info_block_first_row_y(right_sub))
    lh = first + (len(left_rows) - 1) * ROW_H + 16
    rh = first + (len(right_rows) - 1) * ROW_H + 16
    h = max(lh, rh)
    c = (info_block_svg(0, 0, BG_GREY, left_title, left_rows, lh, left_sub,
                        first_row_y=first, row_size=row_size)
         + info_block_svg(IW + GAP, 0, right_bg, right_title, right_rows, rh,
                          right_sub, first_row_y=first, row_size=row_size))
    return _svg(c, PW, h)


def single_block_row_svg(title: str, rows: list[dict], sub: str,
                         row_size: float = ROW_SIZE_MAX) -> str:
    """Full-width variant, used when a system_type makes the sibling block
    meaningless (e.g. Grid Quality on an off-grid site)."""
    h = measure_info_block(rows, sub)
    r = (f"<rect x='0' y='0' width='{PW}' height='{h}' rx='8' fill='{BG_GREY}'/>"
         f"<text x='{IPAD}' y='14' font-size='8' font-weight='700' fill='#777'>"
         f"{esc(title.upper())}</text>")
    for li, line in enumerate(wrap_svg_lines(sub, int((PW - 2 * IPAD) / 3.1))):
        r += (f"<text x='{IPAD}' y='{14 + (li + 1) * 9}' font-size='6.5' "
              f"fill='#bbb'>{esc(line)}</text>")
    first = info_block_first_row_y(sub)
    r += (f"<line x1='{IPAD}' y1='{first - 12}' x2='{PW - IPAD}' y2='{first - 12}' "
          f"stroke='{LINE}' stroke-width='0.5'/>")
    avail_full = PW - 2 * IPAD
    for i, row in enumerate(rows):
        ry = first + i * ROW_H
        vtext = fit_value(row["label"], row["value"], avail_full, row_size)
        r += (f"<text x='{IPAD}' y='{ry}' font-size='{row_size:g}' fill='#999'>"
              f"{esc(row['label'])}</text>"
              f"<text x='{PW - IPAD}' y='{ry}' font-size='{row_size:g}' font-weight='600' "
              f"fill='{row.get('valueColor', '#222')}' text-anchor='end'>"
              f"{esc(vtext)}</text>")
        if i < len(rows) - 1:
            r += (f"<line x1='{IPAD}' y1='{ry + 5}' x2='{PW - IPAD}' y2='{ry + 5}' "
                  f"stroke='{LINE}' stroke-width='0.5'/>")
    return _svg(r, PW, h)


# ══════════════════════════════════════════════════════════════════
# 4-week solar trend (page 2)
# ══════════════════════════════════════════════════════════════════
def four_week_trend_svg(buckets: list[dict], t: dict) -> str:
    FW, F_LPAD, F_RPAD = PW, 46, IPAD
    BM4, BW4, BAR4GAP = 60, 15, 3
    sub_lines = wrap_svg_lines(t["sub4Week"], int((FW - 22) / 3.2))
    hdr = 16 + len(sub_lines) * 10
    top = hdr + 14
    baseline = top + BM4
    date_y = baseline + 16
    trend_y = baseline + 30
    note_y = trend_y + 16
    box_h = note_y + 6

    vals = [v for b in buckets for v in (b["pv"], b.get("load") or 0) if v > 0]
    y_max = math.ceil((max(vals) if vals else 1) / 50) * 50 or 100
    n = len(buckets)
    slot_w = (FW - F_LPAD - F_RPAD) / max(n, 1)

    def bh(v):
        return max(2 if v > 0 else 0, round(v / y_max * BM4))

    s = (f"<rect x='0' y='0' width='{FW}' height='{box_h}' rx='8' fill='{BG_GREY}'/>"
         f"<text x='11' y='12' font-size='8' font-weight='700' fill='#777'>"
         f"{esc(t['fourWeekChart'].upper())}</text>")
    for li, line in enumerate(sub_lines):
        s += (f"<text x='11' y='{12 + (li + 1) * 10}' font-size='7' fill='#bbb'>"
              f"{esc(line)}</text>")
    s += _two_bar_legend(FW - 20, t["labelConsumption"], "#E0E8E4", t)

    for val in (0, round(y_max / 2), y_max):
        gy = baseline - round(val / y_max * BM4)
        s += (f"<line x1='{F_LPAD}' y1='{gy}' x2='{FW - F_RPAD}' y2='{gy}' "
              f"stroke='{LINE}' stroke-width='0.5'/>"
              f"<text x='{F_LPAD - 3}' y='{gy + 3}' text-anchor='end' "
              f"font-size='7' fill='#bbb'>{val} kWh</text>")

    for i, b in enumerate(buckets):
        cx = F_LPAD + slot_w * (i + 0.5)
        pv_h, ld_h = bh(b["pv"]), bh(b.get("load") or 0)
        pv_x, ld_x = cx - BW4 - BAR4GAP / 2, cx + BAR4GAP / 2
        current = i == n - 1
        s += (f"<rect x='{pv_x:.1f}' y='{baseline - pv_h}' width='{BW4}' "
              f"height='{pv_h}' rx='2' fill='{GREEN if current else MINT}'/>"
              f"<rect x='{ld_x:.1f}' y='{baseline - ld_h}' width='{BW4}' "
              f"height='{ld_h}' rx='2' fill='#E0E8E4'/>"
              f"<text x='{cx:.1f}' y='{date_y}' text-anchor='middle' "
              f"font-size='8' fill='#aaa'>{esc(b['label'])}</text>")
        if b["pv"] > 0:
            s += (f"<text x='{pv_x + BW4 / 2:.1f}' y='{baseline - pv_h - 3}' "
                  f"text-anchor='middle' font-size='7.5' "
                  f"fill='{GREEN if current else '#aaa'}'>{b['pv']}</text>")
        # Anchored under THIS week's solar bar — the week the change describes —
        # rather than floating between two bars. Colour is neutral on purpose:
        # a week-on-week solar change is weather, not something the customer
        # did right or wrong, so only the ▲/▼ glyph carries direction.
        if i > 0 and buckets[i - 1]["pv"] > 0 and b["pv"] > 0:
            chg = round((b["pv"] - buckets[i - 1]["pv"]) / buckets[i - 1]["pv"] * 100)
            arrow = "▲ " if chg >= 0 else "▼ "
            sign = "+" if chg >= 0 else ""
            s += (f"<text x='{pv_x + BW4 / 2:.1f}' y='{trend_y}' "
                  f"text-anchor='middle' font-size='7.5' fill='#777'>"
                  f"{arrow}{sign}{chg}%</text>")

    s += (f"<text x='11' y='{note_y}' font-size='7' fill='#bbb'>"
          f"{esc(t['trendNote'])}</text>")
    return _svg(s, FW, box_h)


# ══════════════════════════════════════════════════════════════════
# Estimated savings placeholder (page 2)
# ══════════════════════════════════════════════════════════════════
def savings_placeholder_svg(t: dict) -> str:
    """Full-width placeholder until the Supabase-backed tariff calculation is
    wired in. Kept because the reference report ships it — removing it would
    change what customers already receive."""
    W, PADX = PW, 11
    sub_lines = wrap_svg_lines(t["subSavings"], int((W - 2 * PADX) / 3.1))
    sep_y = 14 + len(sub_lines) * 9 + 8
    row_y = sep_y + 16
    h = row_y + 4
    s = (f"<rect x='0' y='0' width='{W}' height='{h}' rx='8' fill='{BG_GREY}'/>"
         f"<text x='{PADX}' y='14' font-size='8' font-weight='700' fill='#777'>"
         f"{esc(t['tariffSavings'].upper())}</text>")
    for li, line in enumerate(sub_lines):
        s += (f"<text x='{PADX}' y='{14 + (li + 1) * 9}' font-size='6.5' "
              f"fill='#bbb'>{esc(line)}</text>")
    s += (f"<line x1='{PADX}' y1='{sep_y}' x2='{W - PADX}' y2='{sep_y}' "
          f"stroke='{LINE}' stroke-width='0.5'/>"
          f"<text x='{PADX}' y='{row_y}' font-size='9.5' fill='#999'>"
          f"{esc(t['tariffComingSoon'])}</text>"
          f"<text x='{W - PADX}' y='{row_y}' text-anchor='end' font-size='9.5' "
          f"font-weight='600' fill='#bbb'>{esc(t['comingSoonValue'])}</text>")
    return _svg(s, W, h)


# ══════════════════════════════════════════════════════════════════
# SOC timeline (page 2)
# ══════════════════════════════════════════════════════════════════
def soc_chart_svg(d: dict, t: dict) -> str:
    SH, SW, SPAD, SPH, SPY = 168, PW, 30, 112, 34

    def sy(p):
        return SPY + SPH - (float(p) / 100 * SPH)

    s = (f"<rect x='0' y='0' width='{SW}' height='{SH}' rx='8' fill='{BG_GREY}'/>"
         f"<text x='{IPAD}' y='12' font-size='8' font-weight='700' fill='#777'>"
         f"{esc(t['socTimeline'].upper())}</text>"
         f"<text x='{IPAD}' y='22' font-size='7' fill='#bbb'>"
         f"{esc(t['subSocChart'])}</text>"
         f"<rect x='{SW - SPAD - 95}' y='6' width='7' height='7' rx='1' "
         f"fill='{GREEN}' fill-opacity='0.3'/>"
         f"<text x='{SW - SPAD - 86}' y='13' font-size='7' fill='#aaa'>"
         f"{esc(t['labelMaxSocBand'])}</text>"
         f"<circle cx='{SW - SPAD - 22}' cy='10' r='3' fill='{GREEN}'/>"
         f"<text x='{SW - SPAD - 17}' y='13' font-size='7' fill='#aaa'>"
         f"{esc(t['labelMinSoc'])}</text>")

    for p in (0, 50, 100):
        y = sy(p)
        s += (f"<line x1='{SPAD}' y1='{y:.1f}' x2='{SW - SPAD}' y2='{y:.1f}' "
              f"stroke='{LINE}' stroke-width='0.5'/>"
              f"<text x='{SPAD - 3}' y='{y + 3:.1f}' font-size='7' fill='#ccc' "
              f"text-anchor='end'>{p}%</text>")

    # Overview mode (plan doc §22): one min/max point per bucket instead of
    # per day. `bucket_days()` names its aggregates `min_soc`/`max_soc` to
    # match `energy_daily`'s own columns exactly for this reason — the band
    # logic below reads the same keys either way, only the label source and
    # point count change.
    if d.get("isOverview"):
        days = d["overviewBuckets"]
        get_label = lambda r, n: r["label"]
    else:
        days = d["dailyGrouped"]
        get_label = lambda r, n: _x_axis_label(r["date"], t, n)

    n = len(days)
    sw = (SW - SPAD * 2) / max(n - 1, 1)

    band_fwd, band_rev, min_line = "", "", ""
    first_max = first_min = True
    for i, r in enumerate(days):
        x = SPAD + i * sw
        if r.get("max_soc") is not None:
            band_fwd += f"{'M' if first_max else 'L'}{x:.1f},{sy(r['max_soc']):.1f} "
            first_max = False
        if r.get("min_soc") is not None:
            band_rev = f"L{x:.1f},{sy(r['min_soc']):.1f} " + band_rev
            min_line += f"{'M' if first_min else 'L'}{x:.1f},{sy(r['min_soc']):.1f} "
            first_min = False
    if band_fwd and band_rev:
        s += (f"<path d='{band_fwd}{band_rev}Z' fill='{GREEN}' "
              f"fill-opacity='0.12'/>")
    if min_line:
        s += f"<path d='{min_line}' fill='none' stroke='{GREEN}' stroke-width='1.5'/>"

    # Annotating every day under 40% reads fine for a 7-day report, where a
    # dip is the exception. Over a longer custom range, a site whose battery
    # is simply configured to run down toward its floor every day (e.g. a
    # 25% minimum-SOC setting) hits that "low" threshold daily — the
    # annotation stops flagging an outlier and just repeats the same number
    # under every point. Calling out only the period's actual lowest point(s)
    # keeps the one number worth noticing instead of drowning it in copies of
    # the everyday baseline.
    period_min = min((float(r["min_soc"]) for r in days if r.get("min_soc") is not None),
                     default=None)
    label_idx = _label_indices(n)
    for i, r in enumerate(days):
        x = SPAD + i * sw
        mp = r.get("min_soc") if r.get("min_soc") is not None else 0
        dy = sy(mp)
        s += f"<circle cx='{x:.1f}' cy='{dy:.1f}' r='2.5' fill='{GREEN}'/>"
        if i in label_idx:
            s += (f"<text x='{x:.1f}' y='{SH - 5}' text-anchor='middle' "
                  f"font-size='7.5' fill='#aaa'>"
                  f"{esc(get_label(r, n))}</text>")
        if float(mp) < 40 and period_min is not None and float(mp) == period_min:
            s += (f"<text x='{x + 4:.1f}' y='{dy - 4:.1f}' font-size='7' "
                  f"fill='{AMBER}'>{_f(mp, 0)}%</text>")
    return _svg(s, SW, SH)
