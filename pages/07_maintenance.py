"""Site register & preventive maintenance scheduler. Phase 10.

Replaces the manual "Registro de mantenimientos FV.xlsx" spreadsheet's overdue
tracking. A "property" groups one or more sites (from either `monitoring.sites` or
`vrm.sites` — see `database/site_properties_db.py`'s module docstring for why both)
under one maintenance visit schedule.
"""
from __future__ import annotations
from datetime import date

import streamlit as st
from dotenv import load_dotenv

load_dotenv()
st.set_page_config(page_title="Mantenimiento — Pauly&Co Solar", layout="wide")

from calculations.maintenance import compute_status, visited_this_calendar_year

MONTH_NAMES = [
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]

STATUS_BADGE = {
    "overdue":    ("Atrasado",     "#fee2e2", "#dc2626"),
    "due_soon":   ("Próximo",      "#fef9c3", "#a16207"),
    "up_to_date": ("Al día",       "#dcfce7", "#16a34a"),
    "unknown":    ("Sin datos",    "#f1f5f9", "#6b7280"),
}

# Same row-tightening convention pages/03_projects.py already established — a
# compact styled list, not Streamlit's default block spacing (and deliberately not
# st.dataframe: a raw grid widget read as too "spreadsheet," not list-like).
_CSS = """
<style>
[data-testid="column"] {
    padding-top: 0 !important;
    padding-bottom: 0 !important;
}
[data-testid="column"] > [data-testid="element-container"] {
    margin-bottom: 0 !important;
    padding: 0 !important;
}
[data-testid="stMarkdownContainer"] p {
    margin: 0 !important;
    line-height: 1 !important;
}
[data-testid="stVerticalBlock"] > [data-testid="element-container"] {
    margin-bottom: 0 !important;
}
button[data-testid="baseButton-secondary"] {
    min-height: 0 !important;
    height: 34px !important;
    padding: 0 10px !important;
    font-size: 0.9rem !important;
}
[data-testid="stHorizontalBlock"] {
    gap: 4px !important;
    align-items: center !important;
}
</style>
"""


def _pill(label: str, bg: str, fg: str) -> str:
    return (
        f'<span style="display:inline-flex;align-items:center;height:20px;padding:0 9px;'
        f'border-radius:10px;font-size:0.7rem;font-weight:600;background:{bg};color:{fg};">'
        f'{label}</span>'
    )


def _badge(status: str) -> str:
    label, bg, fg = STATUS_BADGE.get(status, STATUS_BADGE["unknown"])
    return _pill(label, bg, fg)


def _parse_date(value) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


# ── Overdue / due-soon list ─────────────────────────────────────────────────────

STATUS_EMOJI = {"overdue": "🔴", "due_soon": "🟡", "up_to_date": "🟢", "unknown": "⚪"}


def _compute_property_rows() -> list[dict]:
    """Every property's computed status, in one pass — shared by the overview table,
    the KPI strip, and the yearly calendar so none of them can compute a different
    answer for the same property."""
    from database.site_properties_db import list_properties, list_all_sites_for_maintenance, list_visits

    properties = list_properties()
    all_sites = list_all_sites_for_maintenance()

    sites_by_property: dict[str, list[dict]] = {}
    for s in all_sites:
        pid = s.get("property_id")
        if pid:
            sites_by_property.setdefault(pid, []).append(s)

    rows = []
    for p in properties:
        visits = list_visits(p["id"])
        last_visit = _parse_date(visits[0]["visit_date"]) if visits else None
        linked_sites = sites_by_property.get(p["id"], [])
        commissioned_dates = [
            _parse_date(s.get("commissioned_at")) for s in linked_sites if s.get("commissioned_at")
        ]
        fallback = min(commissioned_dates) if commissioned_dates else None

        override = _parse_date(p.get("next_due_override"))
        result = compute_status(last_visit, fallback, p["maintenance_interval_days"], override_date=override)
        rows.append({**p, **result, "visited_this_year": visited_this_calendar_year(visits)})
    return rows


def _kpi_strip(rows: list[dict]) -> None:
    counts = {"overdue": 0, "due_soon": 0, "up_to_date": 0, "unknown": 0}
    for r in rows:
        counts[r["status"]] += 1

    cards = [
        ("Total", len(rows), "#1E2D54"),
        ("Atrasadas", counts["overdue"], "#dc2626"),
        ("Próximas", counts["due_soon"], "#a16207"),
        ("Al día", counts["up_to_date"], "#16a34a"),
    ]
    cols = st.columns(len(cards))
    for col, (label, value, color) in zip(cols, cards):
        col.markdown(
            f'<div style="border-left:4px solid {color};background:#f8f9fa;'
            f'border-radius:6px;padding:0.6rem 0.9rem;">'
            f'<div style="font-size:0.78rem;color:#6b7280;">{label}</div>'
            f'<div style="font-size:1.5rem;font-weight:700;color:{color};">{value}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )


_OVERVIEW_HEADER_HTML = """
<div style="display:grid;
  grid-template-columns:2fr 0.9fr 1.5fr 0.6fr 1fr;
  gap:10px;align-items:center;padding:5px 8px;
  border-bottom:2px solid #e2e8f0;margin-bottom:2px;">
  <div style="font-size:0.68rem;font-weight:700;color:#94a3b8;text-transform:uppercase;letter-spacing:0.06em;">Propiedad</div>
  <div style="font-size:0.68rem;font-weight:700;color:#94a3b8;text-transform:uppercase;letter-spacing:0.06em;">Estado</div>
  <div style="font-size:0.68rem;font-weight:700;color:#94a3b8;text-transform:uppercase;letter-spacing:0.06em;">Próxima visita</div>
  <div style="font-size:0.68rem;font-weight:700;color:#94a3b8;text-transform:uppercase;letter-spacing:0.06em;">Sitios</div>
  <div style="font-size:0.68rem;font-weight:700;color:#94a3b8;text-transform:uppercase;letter-spacing:0.06em;">Visitado este año</div>
</div>"""


def _render_overview_row(r: dict) -> bool:
    """Renders one property's row. Returns True if its '›' button was clicked."""
    due_label = "—"
    if r["status"] == "overdue" and r.get("days_overdue") is not None:
        due_label = f"{r['days_overdue']} días de atraso"
    elif r.get("next_due_date"):
        due_label = str(r["next_due_date"])
        if r.get("next_due_override"):
            due_label += " (movida)"

    visited_pill = _pill("Sí", "#dcfce7", "#16a34a") if r["visited_this_year"] else _pill("No", "#f1f5f9", "#6b7280")

    row_html = f"""
<div style="background:white;display:grid;
  grid-template-columns:2fr 0.9fr 1.5fr 0.6fr 1fr;
  gap:10px;align-items:center;padding:9px 8px;
  border-bottom:1px solid #f1f5f9;border-radius:4px;">
  <div>
    <div style="font-size:0.85rem;font-weight:600;color:#1e293b;
      white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{r['name']}</div>
    <div style="font-size:0.72rem;color:#94a3b8;">{r.get('location') or ''}</div>
  </div>
  <div>{_badge(r['status'])}</div>
  <div style="font-size:0.8rem;color:#475569;">{due_label}</div>
  <div style="font-size:0.82rem;color:#1e293b;">{r['site_count']}</div>
  <div>{visited_pill}</div>
</div>"""

    content_col, btn_col = st.columns([16, 1])
    with content_col:
        st.markdown(row_html, unsafe_allow_html=True)
    with btn_col:
        return st.button("›", key=f"maint_row_{r['id']}", type="secondary", use_container_width=True)


def _overview_section() -> None:
    try:
        rows = _compute_property_rows()
    except Exception as e:
        st.error(f"Error al cargar propiedades: {e}")
        return

    if not rows:
        st.info(
            "No hay propiedades configuradas todavía. Usa la pestaña "
            "'Configurar propiedades' para crear la primera."
        )
        return

    order = {"overdue": 0, "due_soon": 1, "unknown": 2, "up_to_date": 3}
    rows.sort(key=lambda r: (order.get(r["status"], 9), r["name"]))

    _kpi_strip(rows)
    st.divider()

    st.markdown(_OVERVIEW_HEADER_HTML, unsafe_allow_html=True)
    for r in rows:
        if _render_overview_row(r):
            st.session_state["maint_selected_property"] = r["id"]
            st.rerun()


# ── Yearly calendar ──────────────────────────────────────────────────────────

def _month_card(month_index: int, props_in_month: list[dict]) -> str:
    """`props_in_month` must already be filtered to `next_due_date.year <= <displayed year>`
    (see `_calendar_section()`) — a future-year date (already visited this cycle, not due
    again until next year) would otherwise look identical to a due-this-year date, which is
    exactly the ambiguity that prompted this filter (Oscar, 2026-09-08)."""
    items = "".join(
        f'<div style="font-size:0.76rem;padding:2px 0;line-height:1.3;">'
        f'{STATUS_EMOJI[p["status"]]} {p["next_due_date"].day}'
        + (f'/{p["next_due_date"].year}' if p["next_due_date"].year != date.today().year else "")
        + f' — {p["name"]}'
        + (' ✓' if p["visited_this_year"] else "")
        + '</div>'
        for p in sorted(props_in_month, key=lambda p: p["next_due_date"].day)
    ) or '<div style="font-size:0.76rem;color:#cbd5e1;">—</div>'

    return (
        f'<div style="border:1px solid #e2e8f0;border-radius:8px;padding:8px 10px;'
        f'min-height:110px;background:white;">'
        f'<div style="font-size:0.78rem;font-weight:700;color:#1E2D54;'
        f'border-bottom:1px solid #f1f5f9;padding-bottom:4px;margin-bottom:4px;">'
        f'{MONTH_NAMES[month_index]}</div>{items}</div>'
    )


def _historical_month_card(month_index: int, visits_in_month: list[dict]) -> str:
    """Past-year view: real logged visits, not the computed schedule — there's no
    'overdue' concept for a year that's already over, so no status color here."""
    items = "".join(
        f'<div style="font-size:0.76rem;padding:2px 0;line-height:1.3;">'
        f'✅ {v["visit_date_obj"].day} — {v["property_name"]}'
        + (f' (${v["amount_usd"]:.0f})' if v.get("amount_usd") else "")
        + '</div>'
        for v in sorted(visits_in_month, key=lambda v: v["visit_date_obj"].day)
    ) or '<div style="font-size:0.76rem;color:#cbd5e1;">—</div>'

    return (
        f'<div style="border:1px solid #e2e8f0;border-radius:8px;padding:8px 10px;'
        f'min-height:110px;background:white;">'
        f'<div style="font-size:0.78rem;font-weight:700;color:#1E2D54;'
        f'border-bottom:1px solid #f1f5f9;padding-bottom:4px;margin-bottom:4px;">'
        f'{MONTH_NAMES[month_index]}</div>{items}</div>'
    )


def _calendar_section() -> None:
    from database.site_properties_db import set_due_override, list_visits

    try:
        rows = _compute_property_rows()
    except Exception as e:
        st.error(f"Error al cargar propiedades: {e}")
        return

    if not rows:
        st.info("No hay propiedades configuradas todavía.")
        return

    current_year = date.today().year
    year_options = list(range(current_year, current_year - 6, -1))
    year = st.selectbox("Año", year_options, index=0, key="calendar_year_select")
    st.markdown(f"#### Año {year}")

    if year != current_year:
        st.caption(
            "Vista histórica: visitas reales registradas ese año — no el calendario de "
            "próximas visitas (eso solo existe para el año actual)."
        )
        by_month: dict[int, list[dict]] = {m: [] for m in range(1, 13)}
        any_visit = False
        for p in rows:
            for v in list_visits(p["id"]):
                vdate = _parse_date(v["visit_date"])
                if vdate and vdate.year == year:
                    any_visit = True
                    by_month[vdate.month].append({**v, "property_name": p["name"], "visit_date_obj": vdate})

        if not any_visit:
            st.info(f"No hay visitas registradas en {year}.")
            return

        for row_start in (0, 4, 8):
            cols = st.columns(4)
            for col, m in zip(cols, range(row_start, row_start + 4)):
                with col:
                    st.markdown(_historical_month_card(m, by_month[m + 1]), unsafe_allow_html=True)
        return

    not_visited = [r for r in rows if not r["visited_this_year"]]
    if not_visited:
        names_html = "".join(
            f'<div style="font-size:0.8rem;padding:2px 8px;">{r["name"]}</div>' for r in not_visited
        )
        st.markdown(
            f'<div style="background:#fee2e2;border:1px solid #fca5a5;border-radius:8px;'
            f'padding:8px 4px;margin-bottom:1rem;">'
            f'<div style="font-weight:700;color:#991b1b;padding:0 8px 4px;font-size:0.85rem;">'
            f'Sin mantenimiento en {year}</div>{names_html}</div>',
            unsafe_allow_html=True,
        )

    scheduled = [p for p in rows if p["next_due_date"]]
    unscheduled = [p for p in rows if not p["next_due_date"]]

    # A next_due_date in a FUTURE year means this property was already visited and its
    # next cycle isn't due until then — showing it in this year's grid (bucketed only by
    # month, ignoring year) is exactly what looked like "already fine this year" when it's
    # really "already done, see you next year." Kept out of the grid entirely instead.
    this_year_or_overdue = [p for p in scheduled if p["next_due_date"].year <= year]
    future_cycle = [p for p in scheduled if p["next_due_date"].year > year]

    by_month: dict[int, list[dict]] = {m: [] for m in range(1, 13)}
    for p in this_year_or_overdue:
        by_month[p["next_due_date"].month].append(p)

    for row_start in (0, 4, 8):
        cols = st.columns(4)
        for col, m in zip(cols, range(row_start, row_start + 4)):
            with col:
                st.markdown(_month_card(m, by_month[m + 1]), unsafe_allow_html=True)

    if future_cycle:
        future_html = "".join(
            f'<div style="font-size:0.8rem;padding:2px 8px;">'
            f'{p["name"]} — próxima visita {p["next_due_date"]}</div>'
            for p in sorted(future_cycle, key=lambda p: p["next_due_date"])
        )
        st.markdown(
            f'<div style="background:#dcfce7;border:1px solid #86efac;border-radius:8px;'
            f'padding:8px 4px;margin-top:1rem;">'
            f'<div style="font-weight:700;color:#166534;padding:0 8px 4px;font-size:0.85rem;">'
            f'✓ Ya visitadas en {year} — próximo ciclo en {year + 1} o después</div>{future_html}</div>',
            unsafe_allow_html=True,
        )

    if unscheduled:
        st.caption(
            "Sin fecha calculada todavía (sin sitios ni visitas vinculadas): "
            + ", ".join(p["name"] for p in unscheduled)
        )

    st.divider()
    st.markdown("#### Mover una propiedad a otro mes")
    st.caption("Para cuando un cliente pide cambiar su visita a otra fecha.")

    name_to_row = {p["name"]: p for p in scheduled}
    if not name_to_row:
        return

    col1, col2, col3 = st.columns([2, 1.4, 1])
    chosen_name = col1.selectbox("Propiedad", list(name_to_row.keys()), key="cal_move_pick")
    chosen = name_to_row[chosen_name]
    new_date = col2.date_input("Nueva fecha esperada", value=chosen["next_due_date"], key="cal_move_date")
    if col3.button("Aplicar", key="cal_move_apply"):
        try:
            set_due_override(chosen["id"], new_date.isoformat())
            st.rerun()
        except Exception as e:
            st.error(f"Error: {e}")

    if chosen.get("next_due_override") and st.button("Restablecer a fecha calculada", key="cal_move_reset"):
        try:
            set_due_override(chosen["id"], None)
            st.rerun()
        except Exception as e:
            st.error(f"Error: {e}")


# ── Property setup (manual grouping, replaces an automatic import) ─────────────

def _setup_section() -> None:
    from database.site_properties_db import (
        create_property, list_all_sites_for_maintenance, list_properties,
        seed_properties_from_unlinked_sites, merge_properties, delete_property,
    )
    from database.clients_db import list_all_clients

    try:
        all_sites = list_all_sites_for_maintenance()
        properties = list_properties()
        client_name_by_id = {c["id"]: c["name"] for c in list_all_clients()}
    except Exception as e:
        st.error(f"Error al cargar sitios: {e}")
        return

    unlinked = [s for s in all_sites if not s.get("property_id")]
    if unlinked:
        st.info(
            f"Hay {len(unlinked)} sitio(s) en Victron Monitor o monitoreo propio sin "
            "propiedad todavía. Esto solo debería pasar con sitios que ya existían antes "
            "de la migración 047 — cualquier sitio nuevo recibe su propiedad "
            "automáticamente al crearse (base de datos), sin necesidad de este botón."
        )
        if st.button(f"Crear una propiedad por cada sitio sin vincular ({len(unlinked)})", type="primary"):
            try:
                created = seed_properties_from_unlinked_sites()
                st.success(f"{created} propiedad(es) creada(s), una por sitio.")
                st.rerun()
            except Exception as e:
                st.error(f"Error al crear propiedades: {e}")

    st.caption(
        "Cada propiedad agrupa uno o más sitios bajo un mismo calendario de mantenimiento. "
        "Cliente y ubicación se toman automáticamente de los sitios vinculados."
    )

    st.divider()
    with st.form(key="new_property_form"):
        st.markdown("#### Nueva propiedad")
        col1, col2 = st.columns(2)
        with col1:
            name = st.text_input("Nombre de la propiedad *")
        with col2:
            interval = st.number_input("Intervalo de mantenimiento (días)", value=365, min_value=1, step=30)

        submitted = st.form_submit_button("Crear propiedad")

    if submitted:
        if not name.strip():
            st.error("El nombre es obligatorio.")
        else:
            try:
                create_property(name=name.strip(), interval_days=int(interval))
                st.success(f"Propiedad '{name}' creada. Vincúlala a sus sitios abajo.")
                st.rerun()
            except Exception as e:
                st.error(f"Error al crear propiedad: {e}")

    if not properties:
        return

    st.divider()
    st.markdown("#### Propiedades existentes")
    st.caption(
        "Marca las que en realidad son una sola propiedad (p. ej. varias casas de un mismo "
        "cliente con una sola visita), elige qué nombre conservar, y fusiónalas. Sigue "
        "siendo necesario cuando se agrega un sitio nuevo para un cliente existente — la "
        "base de datos le crea su propia propiedad automáticamente, pero decidir si en "
        "realidad debería unirse a una propiedad que ya existe sigue siendo tu decisión."
    )

    _PROP_HEADER_HTML = """
<div style="display:grid;grid-template-columns:0.4fr 2.0fr 1.4fr 0.7fr 1fr;gap:10px;align-items:center;
  padding:5px 8px;border-bottom:2px solid #e2e8f0;margin-bottom:2px;">
  <div></div>
  <div style="font-size:0.68rem;font-weight:700;color:#94a3b8;text-transform:uppercase;letter-spacing:0.06em;">Propiedad</div>
  <div style="font-size:0.68rem;font-weight:700;color:#94a3b8;text-transform:uppercase;letter-spacing:0.06em;">Cliente</div>
  <div style="font-size:0.68rem;font-weight:700;color:#94a3b8;text-transform:uppercase;letter-spacing:0.06em;">Sitios</div>
  <div></div>
</div>"""
    st.markdown(_PROP_HEADER_HTML, unsafe_allow_html=True)

    selected_ids = []
    for p in properties:
        c0, c1, c2, c3, c4 = st.columns([0.4, 2.0, 1.4, 0.7, 1.0])
        if c0.checkbox("Seleccionar para fusionar", key=f"merge_select_{p['id']}", label_visibility="collapsed"):
            selected_ids.append(p["id"])
        with c1:
            st.markdown(
                f'<div style="font-size:0.85rem;font-weight:600;color:#1e293b;">{p["name"]}</div>'
                f'<div style="font-size:0.72rem;color:#94a3b8;">{p.get("location") or ""}</div>',
                unsafe_allow_html=True,
            )
        client_label = client_name_by_id.get(p.get("client_id"), "—" if p.get("client_id") is None else "?")
        c2.markdown(f'<div style="font-size:0.82rem;color:#1e293b;">{client_label}</div>', unsafe_allow_html=True)
        c3.markdown(f'<div style="font-size:0.82rem;color:#1e293b;">{p["site_count"]}</div>', unsafe_allow_html=True)
        if c4.button("Eliminar", key=f"del_prop_{p['id']}", use_container_width=True):
            st.session_state[f"confirm_del_prop_{p['id']}"] = True
            st.rerun()

        if st.session_state.get(f"confirm_del_prop_{p['id']}"):
            st.warning(
                f"¿Eliminar '{p['name']}'? Sus sitios quedan sin vincular y su historial "
                "de visitas se borra. Esta acción no se puede deshacer."
            )
            cy, cn, _ = st.columns([1, 1, 6])
            if cy.button("Sí, eliminar", key=f"yes_del_prop_{p['id']}"):
                try:
                    delete_property(p["id"])
                    st.session_state.pop(f"confirm_del_prop_{p['id']}", None)
                    st.rerun()
                except Exception as e:
                    st.error(f"Error al eliminar: {e}")
            if cn.button("Cancelar", key=f"no_del_prop_{p['id']}"):
                st.session_state.pop(f"confirm_del_prop_{p['id']}", None)
                st.rerun()
        st.divider()

    if len(selected_ids) == 1:
        st.caption("Marca al menos 2 propiedades arriba para fusionarlas.")
    elif len(selected_ids) >= 2:
        selected_props = [p for p in properties if p["id"] in selected_ids]
        st.markdown("##### Fusionar las seleccionadas")

        client_ids = {p.get("client_id") for p in selected_props if p.get("client_id")}
        confirmed_anyway = True
        if len(client_ids) > 1:
            names = ", ".join(f"{p['name']} ({client_name_by_id.get(p.get('client_id'), 'sin cliente')})" for p in selected_props)
            st.warning(
                f"⚠️ Estas propiedades son de **clientes distintos**: {names}. Fusionar "
                "normalmente solo tiene sentido cuando son la misma propiedad física de "
                "un mismo cliente (p. ej. varias casas de Rebeca Ruiz)."
            )
            confirmed_anyway = st.checkbox(
                "Sí, quiero fusionarlas de todas formas", key="merge_confirm_diff_client",
            )

        keep_label = st.selectbox(
            "Nombre a conservar (las demás desaparecen; sus sitios y visitas se mueven aquí)",
            [p["name"] for p in selected_props],
            key="merge_keep_name",
        )
        keep_id = next(p["id"] for p in selected_props if p["name"] == keep_label)
        other_ids = [pid for pid in selected_ids if pid != keep_id]
        if st.button(
            f"Fusionar {len(selected_props)} propiedades en '{keep_label}'",
            type="primary", disabled=not confirmed_anyway,
        ):
            try:
                for other_id in other_ids:
                    merge_properties(other_id, keep_id)
                for pid in selected_ids:
                    st.session_state.pop(f"merge_select_{pid}", None)
                st.success(f"{len(other_ids)} propiedad(es) fusionada(s) en '{keep_label}'.")
                st.rerun()
            except Exception as e:
                st.error(f"Error al fusionar: {e}")

    if unlinked:
        st.caption(
            "Para vincular sitios individuales, entra a la propiedad correspondiente y usa "
            "'Agregar o quitar sitios de esta propiedad' — evita tener dos lugares distintos "
            "para la misma acción."
        )


# ── Property detail ──────────────────────────────────────────────────────────

def _detail_section(property_id: str) -> None:
    from database.site_properties_db import (
        get_property_bundle, add_visit, get_credentials, save_credentials,
        set_due_override, get_visit_group,
    )

    try:
        bundle = get_property_bundle(property_id)
    except Exception as e:
        st.error(f"Error al cargar la propiedad: {e}")
        return

    prop = bundle["property"]
    if not prop:
        st.error("Propiedad no encontrada.")
        return

    if st.button("← Volver al resumen"):
        st.session_state.pop("maint_selected_property", None)
        st.rerun()

    st.markdown(f"### {prop['name']}")
    if prop.get("location"):
        st.caption(prop["location"])

    if prop.get("client_id"):
        from database.clients_db import get_client_by_id
        client = get_client_by_id(prop["client_id"])
        if client:
            contact_bits = " · ".join(filter(None, [client.get("phone"), client.get("email")]))
            line = client["name"] + (f" ({client['empresa']})" if client.get("empresa") else "")
            if contact_bits:
                line += f" — {contact_bits}"
            st.caption(f"👤 {line}")
            if client.get("notes"):
                st.caption(f"📝 {client['notes']}")

    if prop.get("next_due_override"):
        c1, c2 = st.columns([3, 1])
        c1.caption(f"⚠️ Fecha esperada movida manualmente a {prop['next_due_override']}.")
        if c2.button("Restablecer a fecha calculada", key="detail_reset_override"):
            try:
                set_due_override(property_id, None)
                st.rerun()
            except Exception as e:
                st.error(f"Error: {e}")

    st.markdown("#### Sitios vinculados")
    if not bundle["sites"]:
        st.caption("Ningún sitio vinculado todavía — usa 'Configurar propiedades'.")
    for s in bundle["sites"]:
        schema_badge = "Victron Monitor" if s["schema_name"] == "vrm" else "Monitoreo propio"
        header = f"{s.get('display_name') or s['site_id']} — {schema_badge}"

        with st.expander(header):
            st.markdown("###### Datos del sitio")
            counts = " · ".join(filter(None, [
                f"{s['panel_count']:.0f} paneles" if s.get("panel_count") else None,
                f"{s['inverter_count']:.0f} inversores" if s.get("inverter_count") else None,
                f"{s['battery_count']:.0f} baterías" if s.get("battery_count") else None,
                f"{s['pv_kwp']:.2f} kWp" if s.get("pv_kwp") else None,
            ]))
            if counts:
                st.caption(counts)
            if s.get("commissioned_at"):
                st.caption(f"Comisionado: {s['commissioned_at']}")
            for url in (s.get("monitoring_urls") or []):
                st.caption(url)
            if not counts and not s.get("commissioned_at") and not s.get("monitoring_urls"):
                st.caption("Sin datos adicionales.")

            st.markdown("###### Credenciales")
            cred = get_credentials(s["site_id"], s["schema_name"]) or {}
            with st.form(key=f"cred_form_{s['schema_name']}_{s['site_id']}"):
                cred_text = st.text_area("Credenciales (WiFi, portal, etc.)", value=cred.get("credentials") or "")
                cred_notes = st.text_area("Notas", value=cred.get("notes") or "")
                if st.form_submit_button("Guardar credenciales"):
                    try:
                        save_credentials(s["site_id"], s["schema_name"], cred_text, cred_notes)
                        st.success("Credenciales guardadas.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error al guardar: {e}")

    st.divider()
    with st.expander("Agregar o quitar sitios de esta propiedad"):
        st.caption(
            "Todos los sitios del sistema, agrupados por cliente — marca o desmarca para "
            "vincular o desvincular. El cliente de esta propiedad aparece primero."
        )

        from database.site_properties_db import list_all_sites_for_maintenance, link_site_to_property
        from database.clients_db import list_all_clients

        client_name_by_id = {c["id"]: c["name"] for c in list_all_clients()}
        all_sites = list_all_sites_for_maintenance()
        linked_keys = {(s["site_id"], s["schema_name"]) for s in bundle["sites"]}
        this_client_id = prop.get("client_id")

        sites_by_client: dict[str, list[dict]] = {}
        for s in all_sites:
            sites_by_client.setdefault(s.get("client_id") or "", []).append(s)

        def _client_sort_key(cid: str) -> tuple[int, str]:
            if cid == this_client_id and cid:
                return (0, "")
            if not cid:
                return (2, "")
            return (1, client_name_by_id.get(cid, ""))

        for cid in sorted(sites_by_client, key=_client_sort_key):
            client_sites = sorted(sites_by_client[cid], key=lambda s: s.get("display_name") or s["site_id"])
            client_label = client_name_by_id.get(cid, "Sin cliente")
            st.markdown(f"**{client_label}**")

            for s in client_sites:
                key = (s["site_id"], s["schema_name"])
                is_linked_here = key in linked_keys
                linked_elsewhere = s.get("property_id") and not is_linked_here
                label = s.get("display_name") or s["site_id"]
                if linked_elsewhere:
                    label += " (vinculado a otra propiedad — se movería aquí)"

                checked = st.checkbox(
                    label, value=is_linked_here,
                    key=f"detail_site_{s['schema_name']}_{s['site_id']}",
                )
                if checked and not is_linked_here:
                    try:
                        link_site_to_property(s["site_id"], s["schema_name"], property_id)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error al vincular: {e}")
                elif not checked and is_linked_here:
                    try:
                        link_site_to_property(s["site_id"], s["schema_name"], None)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error al desvincular: {e}")
            st.divider()

    st.divider()
    st.markdown("#### Registrar visita")

    from database.site_properties_db import list_properties as _list_client_properties, add_bundled_visit

    client_id = prop.get("client_id")
    siblings = [p for p in _list_client_properties(client_id) if p["id"] != property_id] if client_id else []

    extra_ids = []
    if siblings:
        st.caption(
            "¿Esta misma salida también cubrió otras propiedades del mismo cliente? "
            "Se registra como una sola visita con un solo monto total."
        )
        for sp in siblings:
            if st.checkbox(sp["name"], key=f"visit_extra_{sp['id']}"):
                extra_ids.append(sp["id"])

    with st.form(key="add_visit_form"):
        col1, col2, col3 = st.columns(3)
        with col1:
            visit_date = st.date_input("Fecha de visita", value=date.today())
        with col2:
            amount = st.number_input(
                "Monto total (USD)" if extra_ids else "Monto (USD)",
                value=0.0, min_value=0.0, format="%.2f",
            )
        with col3:
            technician = st.text_input("Técnico")
        notes = st.text_area("Notas", height=60)
        if st.form_submit_button("Registrar visita", type="primary"):
            try:
                if extra_ids:
                    add_bundled_visit(
                        client_id, [property_id, *extra_ids], visit_date.isoformat(),
                        amount_usd=amount or None, technician=technician, notes=notes,
                    )
                    st.success(f"Visita registrada para {1 + len(extra_ids)} propiedad(es).")
                else:
                    add_visit(
                        property_id, visit_date.isoformat(),
                        amount_usd=amount or None, technician=technician, notes=notes,
                    )
                    st.success("Visita registrada.")
                st.rerun()
            except Exception as e:
                st.error(f"Error al registrar visita: {e}")

    st.divider()
    st.markdown("#### Historial de visitas")
    if not bundle["visits"]:
        st.caption("Sin visitas registradas todavía.")
    for v in bundle["visits"]:
        c1, c2, c3 = st.columns([1.2, 1.6, 3.0])
        c1.markdown(f"**{v['visit_date']}**")
        if v.get("visit_group_id"):
            group = get_visit_group(v["visit_group_id"])
            if group:
                amount_label = f"${group['amount_usd']:.2f}" if group.get("amount_usd") else "—"
                c2.caption(f"{amount_label} (visita agrupada, {group['property_count']} propiedades)")
            else:
                c2.caption("—")
        else:
            c2.caption(f"${v['amount_usd']:.2f}" if v.get("amount_usd") else "—")
        c3.caption(" · ".join(filter(None, [v.get("technician"), v.get("notes")])) or "—")


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)
    st.markdown(
        '<p style="color:#1E2D54;font-size:1.4rem;font-weight:700;margin:0;">Mantenimiento</p>',
        unsafe_allow_html=True,
    )
    st.divider()

    selected = st.session_state.get("maint_selected_property")
    if selected:
        _detail_section(selected)
        return

    tab_overview, tab_calendar, tab_setup = st.tabs(
        ["Resumen", "Calendario anual", "Configurar propiedades"]
    )
    with tab_overview:
        _overview_section()
    with tab_calendar:
        _calendar_section()
    with tab_setup:
        _setup_section()


main()
