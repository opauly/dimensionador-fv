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


def fig_to_fragment(fig) -> str:
    """Shared to_html() call so every route renders charts with the exact
    same config (no mode bar, no per-fragment plotly.js copy) — see module
    docstring."""
    return fig.to_html(full_html=False, include_plotlyjs=False, config={"displayModeBar": False})
