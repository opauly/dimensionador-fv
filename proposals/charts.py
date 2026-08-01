from __future__ import annotations
"""
Inline-SVG charts for the proposal PDFs.

Deliberately hand-built SVG rather than matplotlib/plotly: WeasyPrint renders
inline SVG directly, so this needs no new dependency, no temp image files and
no external fetch (the templates are otherwise pure HTML/CSS + base64 assets).
Only basic shapes are used — rect / line / text — because WeasyPrint's SVG
support does not cover filters, gradients or CSS-in-SVG.

Sizing and palette intentionally mirror victron/report_svg.py's bar_chart_svg()
so the quote PDFs and the VRM weekly reports read as one family: same 520-unit
content width, same 78-unit bar height, same paired-bar layout, same muted
grey labels. Those proportions are already proven against WeasyPrint, which is
also why an earlier 720x236 version of this chart overflowed the page and
collided with the fixed footer.
"""
import math

# Palette lifted from victron/report_svg.py (do not diverge — see module docstring)
GREEN = "#1FAE6E"     # generation
MINT = "#C8DDD5"      # consumption
AMBER = "#D4860F"     # month below coverage (off-grid only)
NAVY = "#1E2D54"      # battery recharge (Off-Grid/Hybrid only) — brand navy (config.BRAND_NAVY)
LINE = "#E8EDEA"      # gridlines
_LBL = "#aaa"         # month labels / legend text
_LBL_LIGHT = "#bbb"   # y-axis labels

_MONTHS = {
    "es": ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"],
    "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
}
_LABELS = {
    "es": {"gen": "Generación", "cons": "Consumo", "short": "Mes bajo cobertura", "recharge": "Recarga de batería"},
    "en": {"gen": "Generation", "cons": "Consumption", "short": "Month below coverage", "recharge": "Battery recharge"},
}

# Geometry — mirrors victron/report_svg.py's bar_chart_svg()
SVG_W = 520.0
BAR_H_MAX = 78.0
BAR_LPAD = 58.0  # wide enough for "1,000 kWh"-style gridline labels with units
BAR_W = 11.0
BAR_GAP = 3.0
_TOP_Y = 18.0                       # leaves room for the legend row at y 6-13
_BASE_Y = _TOP_Y + BAR_H_MAX
_SVG_H = _BASE_Y + 18.0             # room for month labels beneath the baseline


def _nice_ceiling(value: float) -> float:
    """Readable axis maximum (1/1.5/2/2.5/3/4/5/6/8 × 10^n).

    Not VRM's ceil-to-next-10: monthly kWh runs into the hundreds or thousands,
    where rounding 1,475 up to 1,480 gives an axis label nobody reads cleanly.
    """
    if value <= 0:
        return 1.0
    exp = math.floor(math.log10(value))
    base = 10.0 ** exp
    for m in (1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if value <= m * base:
            return m * base
    return 10 * base


def _f(v: float, nd: int = 1) -> str:
    return f"{v:.{nd}f}".rstrip("0").rstrip(".")


def _num(v: float) -> str:
    return f"{v:,.0f}"


def monthly_coverage_svg(
    generation_kwh: list[float] | None,
    consumption_kwh: list[float] | None,
    lang: str = "es",
    flag_shortfall: bool = True,
    recharge_kwh: list[float] | None = None,
) -> str:
    """
    12-month "does this cover me all year?" chart. Green = estimated
    generation. Off-Grid/Hybrid (when `recharge_kwh` is supplied) stack mint
    (consumption) + navy (battery recharge) in the paired bar, so the chart
    shows where the month's generated energy actually went, not just whether
    it was "enough" — Grid Zero (no battery) keeps the original plain mint bar.

    Both `generation_kwh`/`consumption_kwh` are kWh **per month** (not per
    day) — the unit a client already recognizes from a bill. Grid Zero passes
    its 12 real billed months; Off-Grid passes daily consumption ×
    days-in-month. `recharge_kwh`, when given, is the real simulated monthly
    total of energy that actually charged the battery (see
    calculations/sizing_off_grid.py: simulate_battery_soc()'s
    `daily_charge_in_kwh` — already net of round-trip losses and clipped at
    the battery's capacity), aggregated by wizard/off_grid.py's Step 8 from a
    real reference year, not a flat max(0, generation-consumption) estimate.

    flag_shortfall tints the generation bar amber when it falls below
    consumption. It MUST be False for Grid Zero: that system is deliberately
    sized to cover daytime consumption only, with the grid supplying the rest,
    so generation sits below consumption every month by design — flagging it
    would read as "your system fails year-round" on a correct quote. Off-Grid
    has no grid to fall back on, so a short month is a real finding the
    engineer must see before sending. The comparison is always generation vs.
    consumption alone (never consumption+recharge) — recharge is surplus by
    definition, not part of the minimum the array must clear.

    Returns "" when the data isn't usable (missing, wrong length, all zeros),
    so the template can omit the whole section.
    """
    if not generation_kwh or not consumption_kwh:
        return ""
    if len(generation_kwh) != 12 or len(consumption_kwh) != 12:
        return ""
    try:
        gen = [float(v) for v in generation_kwh]
        con = [float(v) for v in consumption_kwh]
        rec = None
        if recharge_kwh is not None and len(recharge_kwh) == 12:
            rec = [max(0.0, float(v)) for v in recharge_kwh]
    except (TypeError, ValueError):
        return ""
    if max(gen + con) <= 0:
        return ""

    months = _MONTHS.get(lang, _MONTHS["es"])
    lab = _LABELS.get(lang, _LABELS["es"])
    stack_totals = [c + r for c, r in zip(con, rec)] if rec else con
    y_max = _nice_ceiling(max(max(gen), max(stack_totals)))
    slot_w = (SVG_W - BAR_LPAD) / 12.0

    def bar_h(v: float) -> float:
        return max(1.0, round(v / y_max * BAR_H_MAX, 1))

    s = _legend(SVG_W - 8, lab, flag_shortfall and any(g < c for g, c in zip(gen, con)), rec is not None)

    # gridlines + y labels (0, ½, max)
    for val in (0.0, y_max / 2, y_max):
        gy = _BASE_Y - val / y_max * BAR_H_MAX
        s += (f"<line x1='{BAR_LPAD}' y1='{_f(gy)}' x2='{SVG_W}' y2='{_f(gy)}' "
              f"stroke='{LINE}' stroke-width='0.5'/>")
        s += (f"<text x='{BAR_LPAD - 3}' y='{_f(gy + 3)}' text-anchor='end' "
              f"font-size='7' fill='{_LBL_LIGHT}'>{_num(val)} kWh</text>")

    # paired bars + month labels
    for i, (g, c) in enumerate(zip(gen, con)):
        cx = BAR_LPAD + slot_w * i + slot_w / 2
        gh = bar_h(g)
        gcolor = AMBER if (flag_shortfall and g < c) else GREEN
        s += (f"<rect x='{_f(cx - BAR_W - BAR_GAP / 2)}' y='{_f(_BASE_Y - gh)}' "
              f"width='{_f(BAR_W)}' height='{_f(gh)}' fill='{gcolor}' rx='1'/>")
        cons_x = _f(cx + BAR_GAP / 2)
        if rec is not None:
            ch, rh = bar_h(c), bar_h(c + rec[i])
            s += (f"<rect x='{cons_x}' y='{_f(_BASE_Y - ch)}' "
                  f"width='{_f(BAR_W)}' height='{_f(ch)}' fill='{MINT}' rx='1'/>"
                  f"<rect x='{cons_x}' y='{_f(_BASE_Y - rh)}' "
                  f"width='{_f(BAR_W)}' height='{_f(rh - ch)}' fill='{NAVY}'/>")
        else:
            ch = bar_h(c)
            s += (f"<rect x='{cons_x}' y='{_f(_BASE_Y - ch)}' "
                  f"width='{_f(BAR_W)}' height='{_f(ch)}' fill='{MINT}' rx='1'/>")
        s += (f"<text x='{_f(cx)}' y='{_f(_SVG_H - 4)}' text-anchor='middle' "
              f"font-size='8' fill='{_LBL}'>{months[i]}</text>")

    return (f"<svg width='100%' viewBox='0 0 {_f(SVG_W)} {_f(_SVG_H)}' "
            f"font-family='Arial, Helvetica, sans-serif' "
            f"xmlns='http://www.w3.org/2000/svg'>{s}</svg>")


def _legend(right_x: float, lab: dict, show_short: bool, show_recharge: bool) -> str:
    """Right-aligned legend, matching victron/report_svg.py's _two_bar_legend().

    Widths are estimated at 3.7 units/char — the same rough Arial metric the
    VRM report uses — so the block can be right-aligned without measuring text.
    """
    CWID, SWATCH, TXTGAP, ITEMGAP = 3.7, 7.0, 3.0, 12.0

    items = [(GREEN, lab["gen"]), (MINT, lab["cons"])]
    if show_recharge:
        items.append((NAVY, lab["recharge"]))
    if show_short:
        items.append((AMBER, lab["short"]))

    total = sum(SWATCH + TXTGAP + len(text) * CWID for _, text in items)
    total += ITEMGAP * (len(items) - 1)

    x = right_x - total
    out = ""
    for color, text in items:
        out += (f"<rect x='{_f(x)}' y='6' width='7' height='7' rx='1' fill='{color}'/>"
                f"<text x='{_f(x + SWATCH + TXTGAP)}' y='13' font-size='7' "
                f"fill='{_LBL}'>{text}</text>")
        x += SWATCH + TXTGAP + len(text) * CWID + ITEMGAP
    return out
