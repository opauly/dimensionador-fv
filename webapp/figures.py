"""Streamlit-free go.Figure builders for every wizard chart (PLAN_PHASE20_
PROPOSALS_JINJA.md §1.6). One function per chart; each is rendered with

    fig.to_html(full_html=False, include_plotlyjs=False,
                config={"displayModeBar": False})

against the vendored webapp/static/vendor/plotly-basic.min.js loaded once
from base.html — never `include_plotlyjs=True` / a per-fragment copy of the
JS bundle.

`monthly_coverage_fig()` was moved here from wizard/common.py's
`monthly_coverage_chart()` (still Streamlit-free itself, but living in a
Streamlit-importing module); `wizard/common.py` now re-exports it under the
old name so every existing call site in wizard/grid_zero.py and
wizard/off_grid.py is unchanged. This keeps exactly one copy of each chart's
implementation, matching §1.3's "exactly one copy of each fragment" rule
applied to figures.
"""
from __future__ import annotations


def irradiance_monthly_fig(monthly_kwh_kwp: list[float]):
    """Step 3's PVGIS monthly irradiance bar chart. Extracted verbatim from
    wizard/common.py:step3_site() so the Flask wizard's on-screen chart is
    pixel-identical to the Streamlit one for the same PVGIS response."""
    import plotly.graph_objects as go

    from calculations.sizing_grid_zero import MONTHS_ES
    from config import BRAND_GREEN

    fig = go.Figure(go.Bar(
        x=MONTHS_ES,
        y=monthly_kwh_kwp,
        marker_color=BRAND_GREEN,
        text=[f"{v:.0f}" for v in monthly_kwh_kwp],
        textposition="outside",
    ))
    fig.update_layout(
        title="Irradiancia mensual (kWh/kWp)",
        # Explicit headroom above the tallest bar — textposition="outside"
        # doesn't auto-pad the y-axis, so without this the top label (the
        # peak month) gets clipped by the plot area's edge.
        yaxis=dict(title="kWh/kWp", range=[0, max(monthly_kwh_kwp) * 1.18]),
        height=260,
        margin=dict(t=40, b=10, l=10, r=10),
    )
    return fig


def monthly_coverage_fig(
    generation_kwh: list[float],
    consumption_kwh: list[float],
    recharge_kwh: list[float] | None = None,
    flag_shortfall: bool = True,
):
    """
    Interactive Plotly twin of proposals/charts.py's monthly_coverage_svg() —
    same monthly data, same color family (imported from there so the two
    never drift apart), hoverable — for live review in the wizard (Step 6).
    The PDF keeps the static SVG version since WeasyPrint can't render
    Plotly; this is only for on-screen use.

    Generación gets its own bar per month; Consumo (+ Recarga de batería,
    stacked on top, when given) gets a second bar alongside it — same
    grouped-then-stacked layout as the PDF chart, built with Plotly's
    offsetgroup mechanism (bars sharing an offsetgroup stack; different
    offsetgroups sit side by side).
    """
    import plotly.graph_objects as go

    from calculations.sizing_grid_zero import MONTHS_ES
    from proposals.charts import AMBER, GREEN, MINT, NAVY

    gen_colors = [
        AMBER if (flag_shortfall and g < c) else GREEN
        for g, c in zip(generation_kwh, consumption_kwh)
    ]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=MONTHS_ES, y=generation_kwh, name="Generación", marker_color=gen_colors,
        offsetgroup=0, hovertemplate="%{x}<br>Generación: %{y:,.0f} kWh<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        x=MONTHS_ES, y=consumption_kwh, name="Consumo", marker_color=MINT,
        offsetgroup=1, hovertemplate="%{x}<br>Consumo: %{y:,.0f} kWh<extra></extra>",
    ))
    if recharge_kwh:
        fig.add_trace(go.Bar(
            x=MONTHS_ES, y=recharge_kwh, name="Recarga de batería", marker_color=NAVY,
            offsetgroup=1, base=consumption_kwh,
            hovertemplate="%{x}<br>Recarga de batería: %{y:,.0f} kWh<extra></extra>",
        ))
    fig.update_layout(
        barmode="group",
        yaxis_title="kWh/mes",
        height=280,
        margin=dict(t=10, b=10, l=10, r=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    return fig


def consumption_monthly_fig(kwh_values: list[float]):
    """Grid Zero Step 5's 12-month consumption bar chart. Extracted verbatim
    from wizard/grid_zero.py:step5_consumption() (L469-487) so the on-screen
    chart matches the Streamlit wizard's for the same 12-month history."""
    import plotly.graph_objects as go

    from calculations.sizing_grid_zero import MONTHS_ES
    from config import BRAND_GREEN

    fig = go.Figure(go.Bar(
        x=MONTHS_ES,
        y=kwh_values,
        marker_color=BRAND_GREEN,
        text=[f"{v:.0f}" if v else "" for v in kwh_values],
        textposition="outside",
    ))
    fig.update_layout(
        title="Consumo mensual (kWh)",
        # Same explicit-headroom reasoning as irradiance_monthly_fig().
        yaxis=dict(title="kWh", range=[0, max(v or 0 for v in kwh_values) * 1.18]),
        height=240,
        margin=dict(t=40, b=10, l=10, r=10),
    )
    return fig


def _margin_pct_color(pct: float) -> str:
    """Threshold colours for gz_margin_bars_fig() — verbatim port of
    wizard/grid_zero.py:step6_equipment()'s local `_margin_pct_color()`
    (>95% red, >80% amber, else green)."""
    from config import BRAND_GREEN

    if pct > 95:
        return "#dc2626"
    if pct > 80:
        return "#b45309"
    return BRAND_GREEN


def gz_margin_bars_fig(items: list[tuple[str, float]]):
    """Grid Zero Step 6's "Margen de diseño" horizontal bar chart — how close
    the chosen design sits to the inverter's Voc/corriente-per-MPPT ceilings.
    Extracted verbatim from wizard/grid_zero.py:step6_equipment() (L1076-1095).
    `items` is `[(label, pct_of_limit), ...]`."""
    import plotly.graph_objects as go

    fig = go.Figure(go.Bar(
        x=[v for _, v in items],
        y=[k for k, _ in items],
        orientation="h",
        marker_color=[_margin_pct_color(v) for _, v in items],
        text=[f"{v:.0f}%" for _, v in items],
        textposition="outside",
    ))
    fig.add_vline(x=100, line_dash="dash", line_color="#9ca3af")
    fig.update_layout(
        xaxis=dict(title="% del límite", range=[0, max(110, max(v for _, v in items) * 1.15)]),
        height=160,
        margin=dict(t=10, b=10, l=10, r=30),
    )
    return fig


def gz_generation_vs_consumption_fig(gen_kwh: float, consumption_kwh: float):
    """Grid Zero Step 6's "Generación vs. consumo" 2-bar snapshot for the
    currently chosen config. Extracted verbatim from
    wizard/grid_zero.py:step6_equipment() (L1154-1167). Only 2 bars (no
    "Recarga de batería" third bar — Grid Zero has no battery)."""
    import plotly.graph_objects as go

    from config import BRAND_GREEN, BRAND_NAVY

    fig = go.Figure(go.Bar(
        x=[gen_kwh, consumption_kwh],
        y=["Generación mensual", "Consumo mensual"],
        orientation="h",
        marker_color=[BRAND_GREEN, BRAND_NAVY],
        text=[f"{gen_kwh:,.0f} kWh/mes", f"{consumption_kwh:,.0f} kWh/mes"],
        textposition="outside",
    ))
    fig.update_layout(
        xaxis=dict(title="kWh/mes", range=[0, max(gen_kwh, consumption_kwh) * 1.3]),
        height=180,
        margin=dict(t=10, b=10, l=10, r=10),
    )
    return fig


def gz_solar_utilization_fig(used_kwh: float, curtailed_kwh: float, self_consumption_pct: int):
    """Grid Zero Step 6's "Aprovechamiento de generación solar" stacked bar —
    do-not-drop item 3/6 (PLAN §1.10): the solar-utilization/curtailment
    metric Grid Zero derives from the AI daytime fraction (Off-Grid derives
    its own version from the real battery-SoC simulation instead — never
    conflate the two). Extracted verbatim from
    wizard/grid_zero.py:step6_equipment() (L1220-1235)."""
    import plotly.graph_objects as go

    from config import BRAND_GREEN

    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=["Generación mensual"], x=[used_kwh], name="Autoconsumido", orientation="h",
        marker_color=BRAND_GREEN, text=[f"{self_consumption_pct}% · {used_kwh:,.0f} kWh"], textposition="inside",
    ))
    fig.add_trace(go.Bar(
        y=["Generación mensual"], x=[curtailed_kwh], name="Recorte solar (no aprovechado)", orientation="h",
        marker_color="#d1d5db", text=[f"{100 - self_consumption_pct}% · {curtailed_kwh:,.0f} kWh"], textposition="inside",
    ))
    fig.update_layout(
        barmode="stack", height=130, margin=dict(t=10, b=10, l=10, r=10),
        xaxis_title="kWh/mes", showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    return fig


def cashflow_fig(total_usd: float, savings_year1_usd: float, escalation: float = 0.05):
    """Step 8's "Flujo de caja acumulado (25 años)" chart with a break-even
    marker — extracted verbatim from wizard/grid_zero.py:step8_review()
    (L1769-1806). `escalation` is the assumed annual tariff-escalation rate
    applied to year-1 savings; kept as a parameter (default 0.05, matching
    the Streamlit source) rather than hardcoded twice."""
    import plotly.graph_objects as go

    from config import BRAND_GREEN, BRAND_NAVY

    years = list(range(0, 26))
    cashflow = [-total_usd] + [savings_year1_usd * ((1 + escalation) ** y) for y in range(25)]
    cumulative = []
    running = 0.0
    for cf in cashflow:
        running += cf
        cumulative.append(round(running, 2))
    breakeven_year = next((y for y, c in zip(years, cumulative) if c >= 0), None)
    point_colors = [BRAND_GREEN if c >= 0 else "#dc2626" for c in cumulative]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=years, y=cumulative, mode="lines", line=dict(color=BRAND_NAVY, width=2),
        fill="tozeroy", fillcolor="rgba(30,45,84,0.08)", name="Flujo acumulado",
    ))
    fig.add_trace(go.Scatter(
        x=years, y=cumulative, mode="markers", marker=dict(size=5, color=point_colors), showlegend=False,
    ))
    fig.add_hline(y=0, line_color="#9ca3af", line_width=1)
    if breakeven_year is not None:
        fig.add_vline(
            x=breakeven_year, line_dash="dash", line_color=BRAND_GREEN,
            annotation_text=f"Punto de equilibrio: año {breakeven_year}", annotation_position="top",
        )
    fig.update_layout(
        xaxis_title="Año", yaxis_title="Flujo acumulado (USD)",
        height=300, margin=dict(t=30, b=10, l=10, r=10),
    )
    return fig


def og_category_donut_fig(cat_totals: dict):
    """Off-Grid Step 5's "Consumo por categoría" donut — extracted verbatim
    from wizard/off_grid.py:_render_demand_profile_block() (L514-538).
    `cat_totals`: {category_key: summed_kwh_day, ...}, ascending by value
    (the caller's `_cat_totals()` already sorts this way, matching
    Streamlit's own `.sort_values()`)."""
    import plotly.graph_objects as go

    from calculations.load_profile_off_grid import CATEGORY_LABELS_ES
    from config import BRAND_GREEN, BRAND_NAVY

    colors = {
        "fixed_cycling": BRAND_GREEN,
        "behavior_driven": BRAND_NAVY,
        "climate_driven": "#1d4ed8",
        "discretionary": "#b45309",
        "ignition_only": "#6b7280",
        "appliance": "#7c3aed",
    }

    fig = go.Figure(go.Pie(
        labels=[CATEGORY_LABELS_ES.get(k, k) for k in cat_totals],
        values=list(cat_totals.values()),
        hole=0.55,
        marker=dict(colors=[colors.get(k, "#9ca3af") for k in cat_totals]),
        texttemplate="%{value:.2f} kWh/día",
        textposition="outside",
    ))
    fig.update_layout(
        height=340,
        margin=dict(t=40, b=70, l=40, r=40),
        showlegend=True,
        legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5),
    )
    return fig


def og_hourly_stack_fig(cat_totals: dict, shapes: dict):
    """Off-Grid Step 5's "Perfil horario ilustrativo (IA)" stacked-area
    chart — extracted verbatim from wizard/off_grid.py:
    _render_demand_profile_block() (L556-579). `shapes`:
    {category_key: [24 relative-intensity floats]} from
    estimate_hourly_shape_illustrative(). A category present in
    `cat_totals` but missing from `shapes` is skipped (same as the
    Streamlit source's `if not weights: continue`)."""
    import plotly.graph_objects as go

    from calculations.load_profile_off_grid import CATEGORY_LABELS_ES
    from config import BRAND_GREEN, BRAND_NAVY

    colors = {
        "fixed_cycling": BRAND_GREEN,
        "behavior_driven": BRAND_NAVY,
        "climate_driven": "#1d4ed8",
        "discretionary": "#b45309",
        "ignition_only": "#6b7280",
        "appliance": "#7c3aed",
    }

    hours = list(range(24))
    fig = go.Figure()
    for cat, kwh_day in cat_totals.items():
        weights = shapes.get(cat)
        if not weights:
            continue
        total_w = sum(weights) or 1
        values = [kwh_day * w / total_w for w in weights]
        fig.add_trace(go.Scatter(
            x=hours, y=values, mode="lines", stackgroup="one",
            name=CATEGORY_LABELS_ES.get(cat, cat),
            line=dict(width=0.5, color=colors.get(cat, "#9ca3af")),
            fillcolor=colors.get(cat, "#9ca3af"),
        ))
    fig.update_layout(
        xaxis=dict(title="Hora del día", tickmode="linear", tick0=0, dtick=2),
        yaxis_title="kWh (ilustrativo)",
        height=280,
        margin=dict(t=10, b=10, l=10, r=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    return fig


def og_generation_vs_consumption_fig(daily_generation_kwh: float, daily_kwh: float, margin_kwh: float):
    """Off-Grid Step 6's "Generación vs. consumo" 3-bar snapshot for the
    currently chosen config — extracted verbatim from
    wizard/off_grid.py:step6_equipment() (L1593-1608). Unlike Grid Zero's
    2-bar gz_generation_vs_consumption_fig() (no battery), this adds a third
    "Recarga de batería" bar for the daily surplus, and the units are
    kWh/día (Off-Grid sizes off a DAILY figure), not kWh/mes."""
    import plotly.graph_objects as go

    from config import BRAND_GREEN, BRAND_NAVY

    fig = go.Figure(go.Bar(
        x=[daily_generation_kwh, daily_kwh, margin_kwh],
        y=["Generación diaria", "Consumo diario", "Recarga de batería"],
        orientation="h",
        marker_color=[BRAND_GREEN, BRAND_NAVY, "#86efac"],
        text=[f"{daily_generation_kwh:.2f} kWh/día", f"{daily_kwh:.2f} kWh/día", f"{margin_kwh:.2f} kWh/día"],
        textposition="outside",
    ))
    fig.update_layout(
        xaxis=dict(title="kWh/día", range=[0, max(daily_generation_kwh, daily_kwh, margin_kwh) * 1.3]),
        height=220,
        margin=dict(t=10, b=10, l=10, r=10),
    )
    return fig


def og_solar_utilization_fig(used_kwh: float, curtailed_kwh: float, utilization_pct: float, is_hybrid_grid: bool = False):
    """Off-Grid Step 6's "Aprovechamiento de generación solar" stacked bar —
    do-not-drop item 3 (PLAN §1.10): the real-simulation-driven counterpart
    to Grid Zero's AI-daytime-fraction-driven gz_solar_utilization_fig() —
    never conflate the two. Extracted verbatim from
    wizard/off_grid.py:step6_equipment() (L1684-1702), including the
    hybrid-aware trace labels ("Batería/cargas críticas" / "Acoplado a red
    (ahorro)" instead of "Autoconsumido" / "Curtailed") — a low
    battery-side percentage on a grid-connected system isn't waste, it
    AC-couples back to the main panel."""
    import plotly.graph_objects as go

    from config import BRAND_GREEN

    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=["Generación anual"], x=[used_kwh],
        name="Batería/cargas críticas" if is_hybrid_grid else "Aprovechado",
        orientation="h", marker_color=BRAND_GREEN,
        text=[f"{utilization_pct:.0f}% · {used_kwh:,.0f} kWh"], textposition="inside",
    ))
    fig.add_trace(go.Bar(
        y=["Generación anual"], x=[curtailed_kwh],
        name="Acoplado a red (ahorro)" if is_hybrid_grid else "Curtailed (no aprovechado)",
        orientation="h", marker_color="#d1d5db",
        text=[f"{100 - utilization_pct:.0f}% · {curtailed_kwh:,.0f} kWh"], textposition="inside",
    ))
    fig.update_layout(
        barmode="stack", height=130, margin=dict(t=10, b=10, l=10, r=10),
        xaxis_title="kWh/año", showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    return fig


def og_seasonal_coverage_fig(months_es: list[str], monthly_gen_kwh_day: list[float], daily_kwh: float, worst_idx: int):
    """Off-Grid Step 6's "Cobertura estacional" line chart — gross monthly
    generation (real PVGIS seasonal variation) against the flat daily-
    consumption reference, with the weakest month flagged when it falls
    short. Extracted verbatim from wizard/off_grid.py:step6_equipment()
    (L1739-1760)."""
    import plotly.graph_objects as go

    from config import BRAND_GREEN, BRAND_NAVY

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=months_es, y=monthly_gen_kwh_day, mode="lines+markers", name="Generación",
        line=dict(color=BRAND_GREEN, width=3), marker=dict(size=7),
        fill="tozeroy", fillcolor="rgba(75,174,106,0.12)",
    ))
    fig.add_hline(
        y=daily_kwh, line_dash="dash", line_color=BRAND_NAVY,
        annotation_text="Consumo diario", annotation_position="top left",
    )
    if monthly_gen_kwh_day[worst_idx] < daily_kwh:
        fig.add_trace(go.Scatter(
            x=[months_es[worst_idx]], y=[monthly_gen_kwh_day[worst_idx]], mode="markers",
            marker=dict(size=14, color="#dc2626", symbol="x", line=dict(width=3)),
            name="Mes más débil",
        ))
    fig.update_layout(
        yaxis_title="kWh/día", height=260,
        margin=dict(t=10, b=10, l=10, r=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    return fig


def og_energy_flow_sankey_fig(
    display_array_kw: float, avg_peak_sun_hours: float, display_daily_generation: float,
    daily_kwh: float, cat_kwh: dict, category_labels: dict, category_colors: dict,
):
    """Off-Grid Step 6's "Flujo de energía" Sankey — gross generation ->
    system losses / useful energy -> load categories (+ any surplus above
    the load, which recharges the battery bank). Extracted verbatim from
    wizard/off_grid.py:step6_equipment() (L1789-1824) — `gross_kwh` is
    recomputed from `display_array_kw * avg_peak_sun_hours` (no derating),
    NOT back-derived from `display_daily_generation` by dividing out the 20%
    derating factor, to avoid a second rounding pass on top of
    `display_daily_generation`'s own `round(..., 2)`. `cat_kwh`: already
    rescaled to the (possibly manually edited) daily_kwh total, ascending or
    any order — this function re-sorts descending by value itself, matching
    the Streamlit source's `sorted(cat_kwh.items(), key=lambda x: -x[1])`."""
    import plotly.graph_objects as go

    from config import BRAND_GREEN, BRAND_NAVY

    gross_kwh = round(display_array_kw * avg_peak_sun_hours, 2)
    losses_kwh = round(max(0, gross_kwh - display_daily_generation), 2)
    margin_kwh = round(max(0, display_daily_generation - daily_kwh), 2)

    labels = ["Generación bruta", "Pérdidas del sistema", "Energía útil"]
    node_colors = [BRAND_GREEN, "#9ca3af", BRAND_NAVY]
    sources = [0, 0]
    targets = [1, 2]
    values = [losses_kwh, display_daily_generation]
    link_colors = ["rgba(156,163,175,0.45)", "rgba(75,174,106,0.4)"]
    for cat, kwh in sorted(cat_kwh.items(), key=lambda x: -x[1]):
        if kwh <= 0:
            continue
        labels.append(category_labels.get(cat, cat))
        node_colors.append(category_colors.get(cat, "#9ca3af"))
        sources.append(2)
        targets.append(len(labels) - 1)
        values.append(kwh)
        link_colors.append("rgba(30,45,84,0.3)")
    if margin_kwh > 0.01:
        labels.append("Margen / recarga batería")
        node_colors.append("#86efac")
        sources.append(2)
        targets.append(len(labels) - 1)
        values.append(margin_kwh)
        link_colors.append("rgba(75,174,106,0.25)")

    fig = go.Figure(go.Sankey(
        node=dict(label=labels, color=node_colors, pad=20, thickness=16,
                  line=dict(color="white", width=0.5)),
        link=dict(source=sources, target=targets, value=values, color=link_colors),
        textfont=dict(color=BRAND_NAVY, size=13, family="Arial, sans-serif"),
    ))
    fig.update_layout(height=320, margin=dict(t=10, b=10, l=10, r=10))
    return fig


def fig_to_fragment(fig) -> str:
    """Shared to_html() call so every route renders charts with the exact
    same config (no mode bar, no per-fragment plotly.js copy) — see module
    docstring."""
    return fig.to_html(full_html=False, include_plotlyjs=False, config={"displayModeBar": False})
