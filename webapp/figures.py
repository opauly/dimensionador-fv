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


def fig_to_fragment(fig) -> str:
    """Shared to_html() call so every route renders charts with the exact
    same config (no mode bar, no per-fragment plotly.js copy) — see module
    docstring."""
    return fig.to_html(full_html=False, include_plotlyjs=False, config={"displayModeBar": False})
