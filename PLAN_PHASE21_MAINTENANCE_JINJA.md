# Phase 21 — Mantenimiento: the site register & preventive-maintenance scheduler, ported off Streamlit onto Flask/Jinja2/htmx

**Status:** ready for the coder agent, with 6 open questions for Oscar flagged in §0.4
**Author:** architect agent, 2026-09-20
**Branch:** `main_jinja` (worktree `Claude-main_jinja`). `main` stays the Streamlit source of truth
for behaviour and is **not modified by this phase**.
**Builds on:** `PLAN_PHASE20_PROPOSALS_JINJA.md` (Cotizaciones port, Steps 0–10 complete and
audited). This plan reuses that phase's blueprint/template/htmx conventions verbatim and does not
invent a second style. Where a rule here is unchanged from Phase 20, it says so and points at the
section rather than restating it.
**Spec sources:** `PHASES.md` Phase 10 ("Site Register & Preventive Maintenance Scheduler",
L513–611) — **read as history, not as spec; see §1's drift table**; `pages/07_maintenance.py` (793
lines, the actual shipped feature); `database/site_properties_db.py`; `calculations/maintenance.py`;
`database/site_registration_db.py`; migrations `011_import_maintenance_sites.sql`,
`045_site_maintenance_register.sql`, `046_maintenance_bundling_and_overrides.sql`,
`047_auto_create_site_property.sql`.
**Filename convention:** `21` confirmed as the next free number — existing plans are
`PLAN_PHASE6/13/14/15/16/17/18/19_FLEET_P3/20_PROPOSALS_JINJA.md`, and `PHASES.md`'s phase table
(L16–38) ends at row 20.

---

## Goal

**Mantenimiento stops being a stub.** Oscar opens `/mantenimiento`, sees the same property list,
the same KPI strip, the same yearly calendar and the same property-setup tools he sees in
Streamlit today, drills into a property, logs a visit (including a bundled multi-property visit),
edits credentials, links/unlinks sites, and moves a due date — all against the same live Supabase
data, with the same computed statuses.

"Done" means: for every property in the live register, the Flask page and the Streamlit page agree
on **status, next-due date, days-overdue, visited-this-year, site count, and client** — and every
item in the **§1.4 do-not-drop checklist** survives the port.

There are no reference number sets for this feature the way Phase 20 had María José / Jorge Ramírez.
Validation is therefore **side-by-side against the running Streamlit page on the same database**,
plus reversible write-path exercises on purpose-created QA properties (§4 explains why that
constraint is not optional here).

---

## 0. Confirmed context (do not re-derive)

### 0.1 Facts established by reading both checkouts

| Fact | Where |
|---|---|
| The whole feature is **one Streamlit page** with three tabs (Resumen / Calendario anual / Configurar propiedades) plus a detail view that replaces all three | `pages/07_maintenance.py:main()` L769–791 |
| Its only cross-view state is `st.session_state["maint_selected_property"]` — a single id used to switch list↔detail. **There is no wizard, no draft, no multi-step form, no autosave.** Every other interaction is a direct DB write followed by `st.rerun()` | L216–218, L576–578 |
| `calculations/maintenance.py` is **pure** — no `streamlit`, no `database` imports, deliberately so (its own docstring says why). `compute_status()` and `visited_this_calendar_year()` are reusable as-is, exactly like `calculations/*` was for the wizard | `calculations/maintenance.py` L1–12 |
| `database/site_properties_db.py` is likewise Streamlit-free and already framework-agnostic — 17 functions covering every read and write the page performs | whole file |
| **No staleness to reconcile.** Unlike Phase 20's §0.2 five-file drift, `pages/07_maintenance.py`, `database/site_properties_db.py`, `calculations/maintenance.py` and `database/site_registration_db.py` are byte-for-byte identical between `main` and `main_jinja` (verified by reading both copies). **There is no Step 0 in this phase.** | both checkouts |
| `_compute_property_rows()` is the feature's one shared computation, and its docstring states the invariant explicitly: the overview table, the KPI strip and the yearly calendar must all read from it "so none of them can compute a different answer for the same property" | L91–94 |
| Status math has **two implementations on purpose** — `calculations/maintenance.py:compute_status()` (Python, list view, one pass, also returns `days_overdue`) and `public.get_property_maintenance_status()` (SQL, migrations 045/046). The shipped UI calls **only the Python one**; `site_properties_db.get_maintenance_status()` exists but has **zero call sites** | `calculations/maintenance.py` L5–11, migration 046 L38–92, grep of `get_maintenance_status` |
| The register spans **two schemas**: `monitoring.sites` (Oscar's own Node-RED/Cerbo fleet) and `vrm.sites` (VRM Monitor's). 9 of the register's real sites live only in `vrm.sites`. Every `site_properties_db.py` function is schema-blind | `database/site_properties_db.py` L2–15, migration 045 L7–11 |
| **This branch already reads and writes both schemas today** — `webapp/blueprints/admin_sites.py` lists `monitoring.sites` + `vrm.sites` and `database/site_registration_db.py:register_new_site()` inserts into either. The cross-schema coupling is not introduced by this phase | `webapp/blueprints/admin_sites.py` L8–29, L56–132 |
| Established webapp conventions (unchanged from Phase 20 §1.2/§1.4): one blueprint module owns routing + one module per section (`admin_*.py`), lazy `from database... import` **inside** view functions, `request.headers.get("HX-Request")` for partial-vs-page, `hx-target="#subpanel"` + `hx-push-url="true"` for tab swaps, POSTs ending in `redirect(url_for(...), code=303)`, per-partial `<style>` blocks, global `#flash` toast on any non-GET | `webapp/blueprints/admin.py`, `webapp/templates/admin/page.html`, `webapp/templates/base.html` L36–46 |
| CSS vocabulary available: `--navy --green --green-tint --border --muted --muted-2`, `.card .card-note .card-note-sm .dtable .dtable-wrap .dtable-empty .btn .tabs .section-title .cards`, plus `.finput .fgrid .flabel .link-btn .danger-btn .pill` defined inline per-partial | `webapp/static/styles.css`, `webapp/templates/admin/_clients_panel.html` L2–6, `webapp/templates/proposals/_list.html` L5 |
| `webapp/__init__.py` registers blueprints in `create_app()`, sets `MAX_CONTENT_LENGTH = 25 MB` and a 413 handler, and has **no `SECRET_KEY`** — `flask.session` is unusable. This phase does not need it (§1.2) | `webapp/__init__.py` |
| `base.html`'s nav points Mantenimiento at `dashboard.stub(section='maintenance')`; `dashboard.STUBS` is `{"projects", "maintenance"}` | `webapp/templates/base.html` L26, `webapp/blueprints/dashboard.py` L23–26 |
| **No charts.** Nothing in this feature renders a Plotly figure or an SVG. `webapp/figures.py` and the vendored `plotly-basic.min.js` are not touched | whole page |

### 0.2 The VRM Monitor split — checked, and it is *not* a blocker, but it is the phase's biggest standing risk

Phase 10's original spec anchored site identity in `monitoring.sites` alone. What shipped spans
`monitoring.sites` **and** `vrm.sites`. VRM Monitor was then split into its own repo
(`github.com/opauly/vrm-monitor`, 2026-09-16). The question this plan had to answer is whether the
maintenance feature now depends on a product that has left the building. Findings:

- **The split was code-only, not data.** `ARCHITECTURE.md` L3–5 states it explicitly: "every
  diagram below still describes the actual, unchanged *runtime* behavior — same Supabase project,
  same schemas, same data flows. Only the code's repo changed." `README.md` L72–78 says the
  `monitoring` schema migrations and this repo's admin-side registration code stay here.
- **`victron/` and `victron-monitor/` are gone from this working tree** (only orphaned `.pyc` and
  `.DS_Store` files remain), and `database/vrm_sites_admin.py` L5–10 / `database/site_registration_db.py`
  L18–21 / `config.py` L16 each document their own fork-rather-than-import decision *because of*
  the split. Nothing the maintenance feature imports lives in the other repo.
- **So the feature works today, and this phase changes nothing about that.** The Flask port reads
  and writes exactly the same tables through exactly the same `database/site_properties_db.py`.

What remains true and uncomfortable, and is therefore a **flagged risk (§4) and an explicit
non-goal (§3), not something this phase tries to fix**:

1. This repo owns migrations that **alter another product's schema** — `045` adds
   `vrm.sites.property_id`, `047` installs a `BEFORE INSERT` trigger on **both** `monitoring.sites`
   and `vrm.sites` that writes into `public.site_properties`.
2. The maintenance UI **writes** `vrm.sites.property_id` on every link, unlink, merge, delete and
   seed (`site_properties_db.py:link_site_to_property()` L68–79).
3. If `vrm` ever moves to its own Supabase project, the register silently loses the ~9 real sites
   that live only there, `seed_properties_from_unlinked_sites()` starts producing wrong counts, and
   migration 047's `vrm` trigger becomes an orphan. There is no code-level guard against this and
   this phase does not add one.

### 0.3 Data-volume and query-shape reality (matters for two design calls below)

Live register scale is small — ~22–25 properties, ~25–30 sites, a few hundred visits. But the
current read path is chatty:

- `_compute_property_rows()` calls `list_properties()` (which itself calls
  `list_all_sites_for_maintenance()` — 2 Supabase queries) **plus** `list_all_sites_for_maintenance()`
  a second time directly, **plus** `list_visits(p["id"])` once per property. That is ~4 + N queries
  for the overview.
- The calendar's historical mode then calls `list_visits(p["id"])` **again** per property — ~2N.
- The detail page calls `get_credentials()` once per linked site and `get_visit_group()` once per
  grouped visit row.

At 25 properties this is tolerable (it is what Streamlit does today) but it is the page's whole
latency budget. §1.5 resolves how far the port is allowed to go in fixing it.

### 0.4 Decisions (confirmed with Oscar 2026-09-20) and remaining open questions

1. **URL prefix.** Assumed `/mantenimiento` (Spanish, matching `/cotizaciones`). Still a working
   assumption, unconfirmed — low stakes, proceed on it.
2. **Nav placement.** `PHASES.md` Phase 10 L523/L601 says the UI "hangs off the Projects nav item."
   What shipped is a top-level Streamlit page, and `base.html` already gives it a top-level slot.
   *Working assumption: keep it top-level; ignore the spec here.*
3. **Credentials display — Decided: fetch on demand.** Streamlit renders every linked site's
   plaintext credentials inline in an expander on every detail render; Flask instead fetches them
   on demand (§1.6) — fewer queries, and plaintext secrets stop riding in every page's HTML by
   default. Confirmed as a deliberate, disclosed deviation from strict parity, not an oversight.
4. **May the port add an additive read helper to `database/site_properties_db.py`** (a batched
   `list_visits_for_properties()`) to collapse the N+1 in §0.3? *Working assumption: yes, additive
   only, Streamlit's own call sites untouched.* See §1.5.
5. **Duplicate property names — Decided: fix it, key by `id` throughout.** Migration 047
   auto-names a new property after its site's `display_name`, with no uniqueness constraint, and
   Streamlit's calendar-move and merge pickers are keyed by **name** (`pages/07_maintenance.py`
   L366, L533) — two same-named properties collide silently and the wrong one gets edited.
   Confirmed as a real, disclosed bug fix, not something to port faithfully.
6. **Fate of `pages/07_maintenance.py`** after cutover — same deferred decision Phase 20 §1.9 made
   for its own Streamlit pages. *Working assumption: it stays, unmodified, and deletion is a separate,
   deliberate commit made with Oscar.*

---

## 1. Resolved decisions (these are not open questions)

### 1.1 What the feature actually is — and where `PHASES.md` Phase 10 lies about it

Phase 20 found repeated drift between `PHASES.md`'s claims and shipped code. This feature is the
worst case yet: **`PHASES.md` L28 still marks Phase 10 "⬜ Not started"** while a 793-line page,
three migrations and two support modules have been in production use for weeks. `CONTEXT.md` and
`ARCHITECTURE.md` do not mention the feature *at all* (verified by grep for `maintenance`,
`site_properties`, `site_register`, `property_id`). **Read the code, not the phase doc.**

Full drift table — left column is what `PHASES.md` Phase 10 (L513–611) specifies, right column is
what is actually in the repo:

| Phase 10 spec | What actually shipped |
|---|---|
| Table row: "⬜ Not started (spans both products, no dependency on 0–9)" (L28) | Built, shipped, in daily use. The row was never updated |
| Migration `037_site_maintenance_register.sql` (L543–548) | Shipped as `045_site_maintenance_register.sql`, plus **two unplanned follow-ups**: `046` (bundled visits + due-date overrides) and `047` (auto-create-property trigger) |
| Site identity anchored in `monitoring.sites` only (L527–533) | Register spans `monitoring.sites` **and** `vrm.sites`; every DB function is schema-blind (§0.2) |
| `site_credentials.site_id text PRIMARY KEY REFERENCES monitoring.sites(site_id)` (L571–575) | Composite PK `(site_id, schema_name)` with a `CHECK (schema_name IN ('monitoring','vrm'))` and **no FK at all** — deliberately, so the schema stays dumpable (045 L13–16) |
| `site_properties` carries `client_id` and `location` columns (L562–569) | **Neither column exists.** Both are derived live from linked sites by `_derive_client_and_location()` (045 L21–28 explains why: a stored copy would go stale on every link/unlink done elsewhere) |
| `tools/import_maintenance_register.py` — openpyxl xlsx import, groups by (client, location), imports visit history, dry-run pass over credentials (L590–598) | **Never written.** `011_import_maintenance_sites.sql` hand-imported 22 sites + 11 clients instead. **Visit history and credentials were never imported** (011 L8–12 says so) |
| Geocode all 22 sites via `geocode_cr()`, fixing the San Isidro/Pérez Zeledón collision first (L535–539, L591) | **Not done.** Migration 011 §4 (L422–463) is a placeholder: every statement is `SET latitude = NULL, longitude = NULL`. The maintenance UI never reads coordinates, so nothing broke — but the "geocoded register" does not exist, and the `geocode_cr()` bug L539 describes may still be live |
| UI hangs off the Projects nav (L523, L601) | Its own top-level page; `base.html` already reserves a top-level nav slot |
| `get_property_maintenance_status()` is the status source of truth (L588) | It exists (045 L64–108, extended by 046 L38–92) and is wrapped by `get_maintenance_status()` — **but has zero call sites.** Every status the UI shows comes from `calculations/maintenance.py:compute_status()`. The SQL function is a documented cross-check, not a dependency |
| Validation: cross-check overdue flags against the xlsx `Cronograma` sheet (L606–611) | No such cross-check artifact exists in the repo. There is **no fixture dataset and no reference number set** for this feature |
| — (not in the spec at all) | **Bundled visits** (`maintenance_visit_groups`, 046): one trip, one charge, N properties, amount lives only on the group row. **Manual due-date overrides** (`next_due_override`, 046), auto-cleared by the next real visit. **The 047 auto-property trigger** on both schemas. **Property merge / delete / seed.** **The `_EXCLUDED_MONITORING_SITE_IDS` Lori Pickett exclusion** (3 dead `monitoring.sites` rows). **The yearly calendar** with its separate historical mode |

**The real shipped feature set**, tab by tab, is what §1.4's checklist enumerates and what §2's
steps build. Nothing else.

### 1.2 State management: there is none to port

This is the single biggest structural difference from Phase 20, and it makes the phase small.

Streamlit's maintenance page holds exactly one piece of cross-rerun state:
`st.session_state["maint_selected_property"]` (L216, L777). Everything else is a direct
`site_properties_db` write followed by `st.rerun()`. There is no draft blob, no autosave, no
two-tier state, no per-session scratch.

**The Flask port replaces that one key with a URL.** `/mantenimiento/propiedad/<pid>` *is* the
selection. Consequences, all good and all free:

- No `flask.session`, therefore **no `SECRET_KEY` needed** — unchanged from Phase 20 §0.3 Q6.
- No new `wizard/draft.py`-style module. **Do not create one.**
- No blob-compatibility constraint with Streamlit (there is no blob) — Streamlit and Flask simply
  read and write the same normalised tables, so both apps can be open at once with no
  drop-the-scratch asymmetry of the kind Phase 20 §1.1 had to document.
- The detail view becomes bookmarkable and back-button-correct, which Streamlit's version is not.

The three transient bits of Streamlit UI state that are *not* the selected property —
`confirm_del_prop_<id>` (L488), `merge_select_<id>` (L476), and the bundled-visit sibling
checkboxes (L715) — become, respectively: a query param on a confirm fragment, ordinary form
checkboxes, and ordinary form checkboxes inside the same `<form>` as the visit fields. See §1.6.

### 1.3 One `property_rows()`, called by everything — the §1.3-equivalent discipline

Phase 20's most important structural rule was one `build_context(blob)` per step. The analogue
here is narrower but just as load-bearing, and the Streamlit code already states it as an
invariant (L91–94):

```python
# webapp/blueprints/maintenance_common.py
def property_rows() -> list[dict]:
    """Port of pages/07_maintenance.py:_compute_property_rows(). Every property's
    computed status in one pass. The Resumen table, the KPI strip and BOTH calendar
    modes read from this and only this, so none of them can disagree."""
```

**Rule:** the Resumen table, the KPI strip, the calendar's current-year grid, the calendar's
historical grid, the not-visited banner, the future-cycle banner and the move-a-property picker all
consume `property_rows()`'s output. No route recomputes a status, a next-due date or a
visited-this-year flag from its own locals. A partial handler that mutates something re-calls
`property_rows()` and renders its fragment from that, exactly as Phase 20 §1.3 requires.

Row shape (a superset of Streamlit's `{**p, **result, "visited_this_year": ...}`):

```python
{
  # from site_properties_db.list_properties() — includes the derived fields
  "id", "name", "maintenance_interval_days", "next_due_override", "created_at",
  "client_id", "location", "site_count",
  # from calculations.maintenance.compute_status()
  "next_due_date",        # datetime.date | None
  "status",               # "overdue" | "due_soon" | "up_to_date" | "unknown"
  "days_overdue",         # int | None  (negative when not overdue — only render when overdue)
  # computed here
  "visited_this_year",    # bool, from visited_this_calendar_year()
  "visits",               # NEW: the already-fetched list_visits() rows (see §1.5)
}
```

`compute_status()` is called with **exactly** Streamlit's argument set (L117): last visit date,
`min(commissioned_at)` across linked sites as fallback, the property's interval, and
`override_date` parsed from `next_due_override`. Do not add a `today=` argument, do not reorder,
do not substitute the SQL function.

Port `_parse_date()` (L78–83) verbatim into `maintenance_common.py` — `list_visits()` and
`list_properties()` return ISO strings from PostgREST, and `compute_status()` needs `date` objects.

### 1.4 Do-not-drop checklist

This is the acceptance criteria for Step 4 and should be re-read at every step boundary. Items
marked **⚠** encode a documented bug fix or a decision made with Oscar — dropping one silently
reintroduces a real problem.

**Resumen tab**

1. Sort order `overdue → due_soon → unknown → up_to_date`, then by name (L207–208). Note `unknown`
   sorts *above* `up_to_date` — a property nobody can compute a date for needs attention.
2. KPI strip: Total / Atrasadas / Próximas / Al día, with the exact left-border colours `#1E2D54`,
   `#dc2626`, `#a16207`, `#16a34a` (L127–132).
3. `STATUS_BADGE` labels and colour pairs verbatim (L24–29): Atrasado / Próximo / Al día / Sin datos.
4. "Próxima visita" cell logic (L159–167): `"{days_overdue} días de atraso"` when overdue;
   otherwise the date; **plus the `" (movida)"` suffix when `next_due_override` is set**.
5. "Visitado este año" Sí/No pill — deliberately **distinct** from `status`; `visited_this_calendar_year()`'s
   docstring explains why a property can be `up_to_date` and still not visited this year.
6. Empty state pointing the user at the "Configurar propiedades" tab (L200–205).

**Calendario anual tab**

7. Year selector: current year and the 5 prior (L280).
8. ⚠ **Current-year grid filters to `next_due_date.year <= year`** (L329–330) and pushes the rest
   into a separate green "✓ Ya visitadas en {year} — próximo ciclo en {year+1} o después" box
   (L342–354). `_month_card()`'s docstring records this as a fix for a real ambiguity Oscar hit on
   2026-09-08: a future-year due date bucketed by month alone looks identical to a due-this-year
   one. Dropping the filter reintroduces exactly that bug.
9. Month cards: `STATUS_EMOJI` (🔴🟡🟢⚪), day number, a `/{year}` suffix only when the date is not
   in the current year, the property name, and a trailing ` ✓` when visited this year; `—` when the
   month is empty (L222–243).
10. Historical mode (any past year): **real logged visits, not the computed schedule** — ✅ marker,
    day, property name, `(${amount})` when present, **no status colour**, plus the caption
    explaining the difference and a "No hay visitas registradas en {year}" empty state (L246–263,
    L284–307).
11. Red "Sin mantenimiento en {year}" banner listing every not-visited-this-year property (L309–320).
12. "Sin fecha calculada todavía (sin sitios ni visitas vinculadas): …" caption for `unknown`
    properties (L356–360).
13. "Mover una propiedad a otro mes" picker + "Restablecer a fecha calculada", with its
    "Para cuando un cliente pide cambiar su visita a otra fecha." caption (L362–386).

**Configurar propiedades tab**

14. The unlinked-sites info box with its **exact** explanation that this should only happen for
    pre-migration-047 sites, plus the "Crear una propiedad por cada sitio sin vincular (N)" button
    → `seed_properties_from_unlinked_sites()` (L406–420).
15. New-property form: name required (with the "El nombre es obligatorio." error), interval
    `value=365, min=1, step=30`, and the "Vincúlala a sus sitios abajo." success note (L428–447).
16. Existing-properties table with its caption explaining merge is still a human judgement call
    even after 047 (L454–460), and columns Propiedad (name + location) / Cliente / Sitios.
17. ⚠ Merge: ≥2 selected; the **different-clients warning** plus its mandatory "Sí, quiero
    fusionarlas de todas formas" gate that keeps the button disabled (L515–526); keep-name picker;
    N−1 `merge_properties(other, keep)` calls; the "Marca al menos 2 propiedades arriba" hint at
    exactly 1 selected (L509–510).
18. ⚠ Delete: two-step confirm carrying the exact warning — sites become unlinked, **visit history
    is deleted**, irreversible (L491–506). The cascade is real (045 L47).
19. The closing "Para vincular sitios individuales, entra a la propiedad correspondiente…" caption
    that deliberately keeps site-linking in one place (L549–554).

**Property detail**

20. Header: name, location caption, and the client line — `name (empresa) — phone · email` plus a
    separate `📝 notes` line, all conditional (L584–594).
21. Override banner "⚠️ Fecha esperada movida manualmente a {date}." + reset button (L596–604).
22. Per-site block: the schema badge **"Victron Monitor" vs "Monitoreo propio"** (L610); the counts
    line with its exact formats (`{:.0f} paneles/inversores/baterías`, `{:.2f} kWp`) joined by ` · `;
    `Comisionado: {date}`; every `monitoring_urls` entry; and the "Sin datos adicionales." fallback
    when all three are absent (L613–628).
23. Credentials form per site → `save_credentials(site_id, schema_name, credentials, notes)`, which
    upserts on the composite key (L630–641).
24. ⚠ Site linker: **all** sites grouped by client, **this property's client first**, "Sin cliente"
    last (`_client_sort_key`, L662–667); sites sorted by display name; the
    "(vinculado a otra propiedad — se movería aquí)" label on a site linked elsewhere (L677–680);
    check → `link_site_to_property(..., property_id)`, uncheck → `link_site_to_property(..., None)`.
25. ⚠ Registrar visita: the sibling-property checkboxes listing **other properties of the same
    client** (`list_properties(client_id)` minus self, L703–716); the amount label switching between
    "Monto total (USD)" and "Monto (USD)" when any sibling is checked; `amount or None` so 0 becomes
    NULL; `add_bundled_visit()` when siblings are checked, `add_visit()` otherwise; and the
    "Visita registrada para N propiedad(es)." vs "Visita registrada." messages (L718–746).
26. ⚠ Do **not** re-implement override clearing — `add_visit()`/`add_bundled_visit()` already call
    `set_due_override(pid, None)` (`site_properties_db.py` L222, L247).
27. Historial de visitas: date; then either `"${group.amount_usd} (visita agrupada, N propiedades)"`
    via `get_visit_group()` when `visit_group_id` is set, or the row's own amount, or `—`; then
    `technician · notes` or `—` (L748–764).
28. ⚠ `_EXCLUDED_MONITORING_SITE_IDS` — Lori Pickett's three dead `monitoring.sites` rows must never
    appear anywhere in this UI. This comes free from `list_all_sites_for_maintenance()`; the port
    must not bypass that function with its own query.

### 1.5 Query shape — one additive helper, nothing more

Given §0.3's N+1s and §0.4 Q4's assumption, the port is allowed exactly two optimisations, both
safe and both inside `property_rows()`:

1. **`property_rows()` keeps the visits it already fetched** (the `"visits"` key in §1.3's shape).
   The calendar's historical mode then costs **zero** extra queries instead of N. This is free —
   Streamlit throws the same data away and refetches it 40 lines later.
2. **One additive function in `database/site_properties_db.py`:**
   ```python
   def list_visits_for_properties(property_ids: list[str]) -> dict[str, list[dict]]:
       """Batched list_visits() for the register overview — one query instead of N.
       Additive: list_visits() is unchanged and stays the single-property entry point
       Streamlit uses. Returns {property_id: [visits, newest first]}."""
   ```
   Implemented with `.in_("property_id", property_ids).order("visit_date", desc=True)`, grouped in
   Python. **`list_visits()` itself must not change** — `pages/07_maintenance.py` and
   `get_property_bundle()` both call it and `main` is untouched by this phase.

**Nothing else.** Specifically: do **not** add caching, do not collapse
`list_all_sites_for_maintenance()`'s double call into a global, do not batch `get_credentials()`
(§1.6 removes that N entirely), and do not touch `get_property_bundle()`. Latency here is a
nice-to-have; correctness parity is the deliverable.

### 1.6 htmx interaction model — Phase 20's three patterns, applied

No new patterns (Phase 20 §1.4). Mapping every Streamlit interaction onto one of them:

| Streamlit interaction | Pattern | Flask shape |
|---|---|---|
| Tab switch (Resumen / Calendario / Configurar) | **tab swap** | `hx-get` → `#subpanel`, `hx-swap="innerHTML"`, `hx-push-url="true"` — copy `webapp/templates/admin/page.html` L13–27 verbatim, including its `hx-on::after-request` active-class toggle |
| `›` row button → detail (L190) | **plain link** | `<a href="/mantenimiento/propiedad/<pid>">` — a real page, a real URL (§1.2) |
| "← Volver al resumen" (L576) | **plain link** | `<a href="/mantenimiento/">` |
| Calendar year `selectbox` (L281) | **pattern 3** | `<select name="anio" hx-get=".../calendario" hx-target="#subpanel" hx-push-url="true">` |
| "Aplicar" / "Restablecer" due-date override (L374, L381, L599) | **form POST + 303** | `POST .../override` → `set_due_override()` → 303 back to the calendar (with `?anio=`) or the detail page |
| Registrar visita (L718–746) | **form POST + 303** | one `<form>` carrying the sibling checkboxes *and* the visit fields (Streamlit had to split them because `st.form` does not rerun on checkbox change — Flask does not have that constraint) |
| Credentials save (L632–641) | **pattern 2** | `hx-post` → swap the one site's credentials fragment; `#flash` gives the "Guardado" toast |
| Credentials **display** | **pattern 2** | `hx-get .../credenciales?schema=…&site_id=…` with `hx-trigger="click once"` on a "Ver / editar credenciales" toggle. Per §0.4 Q3: plaintext secrets are fetched on demand, not baked into every detail render |
| Site linker checkbox (L682–697) | **pattern 2** | `hx-post .../sitio` with `site_id`/`schema_name`/`linked` in the body, swapping the whole linker fragment (`hx-target="#site-linker" hx-swap="outerHTML"`) so "(vinculado a otra propiedad)" labels update |
| Merge multi-select → reactive warning + keep-name picker (L509–547) | **pattern 3** | checkboxes in one `<form>` with `hx-get .../fusionar/panel hx-trigger="change" hx-target="#merge-panel" hx-swap="outerHTML"`; the panel renders the different-client warning, the gate checkbox and the keep-name `<select>` |
| Delete confirm (L487–506) | **pattern 2** | "Eliminar" is `hx-get .../eliminar/confirmar` swapping an inline confirm fragment with Sí/Cancelar; "Sí" is a `POST` → 303 |
| Seed unlinked / create property (L414, L436) | **form POST + 303** | straightforward |

`hx-indicator` + `hx-disabled-elt="this"` on merge, delete and seed — they are multi-write loops
over the network and a double-submit is destructive.

### 1.7 Route / blueprint structure

Mirrors `webapp/blueprints/admin.py`: one module owns routing and tab dispatch, one module per tab
owns its logic. Names follow the existing `admin_*.py` convention exactly.

```
webapp/blueprints/maintenance.py          Blueprint("maintenance", __name__, url_prefix="/mantenimiento")
  GET  /                                  Resumen tab                                    (page)
  GET  /calendario                        Calendario anual tab (?anio=YYYY)              (page | partial)
  GET  /configurar                        Configurar propiedades tab                     (page | partial)
  GET  /propiedad/<pid>                   property detail                                (page)

  POST /propiedad/<pid>/visita            add_visit | add_bundled_visit        → 303 detail
  POST /propiedad/<pid>/override          set_due_override(date | None)        → 303 detail
  POST /propiedad/<pid>/sitio             link_site_to_property(...)           (partial: linker)
  GET  /propiedad/<pid>/credenciales      get_credentials(site_id, schema)     (partial: cred form)
  POST /propiedad/<pid>/credenciales      save_credentials(...)                (partial: cred form)

  POST /calendario/override               set_due_override from the calendar   → 303 /calendario?anio=
  POST /propiedades                       create_property(name, interval)      → 303 /configurar
  POST /propiedades/sembrar               seed_properties_from_unlinked_sites() → 303 /configurar
  GET  /propiedades/fusionar/panel        live merge panel                     (partial)
  POST /propiedades/fusionar              merge_properties() × (N-1)           → 303 /configurar
  GET  /propiedades/<pid>/eliminar        inline delete-confirm fragment       (partial)
  POST /propiedades/<pid>/eliminar        delete_property(pid)                 → 303 /configurar

webapp/blueprints/maintenance_common.py   property_rows(), _parse_date(), STATUS_BADGE,
                                          STATUS_EMOJI, MONTH_NAMES, badge/pill helpers
webapp/blueprints/maintenance_overview.py render_overview_panel()
webapp/blueprints/maintenance_calendar.py render_calendar_panel(year)
webapp/blueprints/maintenance_setup.py    render_setup_panel(), merge-panel context
webapp/blueprints/maintenance_detail.py   detail_ctx(pid) and its write handlers' logic
```

Templates, mirroring `webapp/templates/admin/` + `webapp/templates/proposals/`:

```
webapp/templates/maintenance/page.html            tab shell (clone of admin/page.html)
                            _overview.html        KPI strip + property table
                            _calendar.html        year picker + 12-month grid + banners + move form
                            _setup.html           unlinked box + new-property form + property table
                            _merge_panel.html     reactive merge block                (partial target)
                            _delete_confirm.html  inline confirm                      (partial target)
                            detail.html           full detail page
                            _site_block.html      one linked site (counts, urls, cred toggle)
                            _credentials.html     cred form fragment                  (partial target)
                            _site_linker.html     grouped checkbox linker             (partial target)
                            _visit_history.html   visit rows
                            _macros.html          pill() / badge() — same trick as proposals/_macros.html
```

`SECTIONS`/`SECTION_ORDER` dicts in `maintenance.py` mirror `admin.py` L24–32. Tab dispatch returns
the bare partial when `request.headers.get("HX-Request")`, else wraps it in `page.html` — copy
`admin.sub_view()` L92–106.

Every panel render is wrapped in `try/except` → `admin/_error.html` (reuse it; do not make a second
error partial), matching `admin.py` L134–201 and Streamlit's own
`st.error(f"Error al cargar propiedades: {e}")` behaviour (L196, L272, L402).

### 1.8 Calculation logic: reusable as-is, with one thing to port rather than extract

Answering the question directly:

- **`calculations/maintenance.py` is pure and reusable verbatim.** `compute_status()` and
  `visited_this_calendar_year()` are imported and called unchanged. **No extraction, no move, no
  edit.** This is the `calculations/*` situation from Phase 20 §0.1, not the
  `_estimate_daytime_fraction_ai()` situation from §1.7.
- **`database/site_properties_db.py` is likewise reusable verbatim**, plus the one additive helper
  in §1.5.
- **`_compute_property_rows()` (L91–119) and `_parse_date()` (L78–83) are Streamlit-free logic that
  happens to live in a Streamlit page.** They are small and private to that page, so the port
  **copies** them into `maintenance_common.py` rather than extracting-and-re-importing.
  `pages/07_maintenance.py` stays untouched (§3), so there will briefly be two copies. That is
  accepted: the alternative (edit the Streamlit page to import from `webapp/`) would make a
  UI-framework package a dependency of the Streamlit app, which is backwards.
- **Everything else in the page is presentation** — f-string HTML, `st.columns`, `st.expander`,
  `st.form`, `st.rerun()`. It is replaced, not ported.

**No status logic may be reinvented.** In particular: do not compute "overdue" from a date
comparison in a Jinja template, and do not call `get_maintenance_status()` (the SQL path) anywhere.
§1.4 item 4's `days_overdue` rendering is the only place a status-derived number is formatted, and
it comes from `compute_status()`'s return value.

---

## 2. Build steps

Each step is a vertical slice ending in something runnable plus a validation you can execute.
**Do not start step N+1 until step N's validation passes.**

Every step's validation is run **side by side with the Streamlit app on the same Supabase project**
— that is the only oracle this feature has (§4).

---

### Step 1 — Blueprint shell + Resumen tab (read-only)

**Build**
- `webapp/blueprints/maintenance.py` with the blueprint, `SECTIONS`/`SECTION_ORDER`, the three tab
  routes and the partial-vs-page dispatch; registered in `webapp/__init__.py:create_app()`.
- `webapp/blueprints/maintenance_common.py`: `property_rows()` per §1.3, `_parse_date()`,
  `STATUS_BADGE`, `STATUS_EMOJI`, `MONTH_NAMES`, and the `pill`/`badge` macro data. Its module
  docstring carries §1.3's invariant.
- `database/site_properties_db.py:list_visits_for_properties()` per §1.5, used by `property_rows()`.
- `webapp/templates/maintenance/page.html` (clone of `admin/page.html`) + `_overview.html` +
  `_macros.html`: KPI strip (§1.4 item 2) and the property table using `.dtable`/`.dtable-wrap`,
  with the five columns Propiedad / Estado / Próxima visita / Sitios / Visitado este año.
- `/calendario` and `/configurar` render a one-line "en construcción" placeholder for now, so the
  tab shell is real from the first step.
- Remove `"maintenance"` from `dashboard.STUBS` and point `base.html`'s nav at `maintenance.index`,
  with the active-class rule `request.blueprint == 'maintenance'` (same shape as the Cotizaciones
  entry, L23).

**Validate**
- Side by side with Streamlit's Resumen tab on the same database: **identical property count,
  identical row order, and for every row identical name, location, status badge, "Próxima visita"
  text (including `(movida)` where applicable), site count and Sí/No pill.** Walk all ~25 rows; do
  not spot-check three.
- KPI counts sum to the row count and match Streamlit's four numbers exactly.
- At least one property in each of the four statuses is present and correct; if the live register
  has no `unknown` property, create a QA property with no sites and no visits, confirm it renders
  "Sin datos" and sorts above the `up_to_date` block, then delete it.
- With zero properties matching (temporarily filter in a scratch REPL, not by deleting data),
  confirm the empty-state copy matches §1.4 item 6.
- The nav highlights Mantenimiento; `/maintenance` (the old stub URL) now 404s and nothing links to
  it.

---

### Step 2 — Property detail (all the write paths)

The densest step. Port it whole; do not ship a partial detail page.

**Build**
- `GET /propiedad/<pid>` → `maintenance_detail.detail_ctx(pid)` built on `get_property_bundle()`,
  rendering §1.4 items 20–22 and 27: header + client line, override banner + reset, the linked-site
  blocks, and the visit history (including the `get_visit_group()` branch).
- Credentials: reveal-on-demand `GET`/`POST` fragment pair per §1.6 / §0.4 Q3.
- `_site_linker.html` + `POST /propiedad/<pid>/sitio` per §1.4 item 24, including the client
  grouping/ordering rule and the "se movería aquí" label.
- `POST /propiedad/<pid>/visita` per §1.4 items 25–26: one form, sibling checkboxes inside it,
  label switching, `amount or None`, `add_bundled_visit()` vs `add_visit()`, success message
  wording. **Do not clear the override here** — the DB layer already does.
- `POST /propiedad/<pid>/override` (reset only, from the detail banner).

**Validate**

*Read paths, against real data:*
- Pick a property with sites in **both** schemas if one exists (otherwise one of each): badges say
  "Victron Monitor" / "Monitoreo propio" correctly; counts, kWp, `Comisionado`, and every
  monitoring URL match Streamlit character for character; a site with none of the three shows
  "Sin datos adicionales."
- Pick a property whose client has `empresa`, `phone`, `email` and `notes` — the whole client line
  and the `📝` line match Streamlit.
- Pick a property with a **bundled** visit in its history: the row reads
  `"$X (visita agrupada, N propiedades)"` with the same N Streamlit shows.
- Lori Pickett's `vista-atenas-lp-m1/m2/m3` appear **nowhere** in the site linker (§1.4 item 28).

*Write paths — on a purpose-created QA property only (§4):*
- Create "QA Mantenimiento `<timestamp>`" via the DB layer in a REPL; link one site to it through
  the Flask linker; confirm `monitoring.sites`/`vrm.sites`'s `property_id` actually changed and the
  site's former property now shows one fewer site in Streamlit.
- Link a site that is already linked elsewhere; confirm the "(vinculado a otra propiedad — se
  movería aquí)" label appeared beforehand and that it really moves (the old property loses it).
- Log a plain visit: status flips to `up_to_date` in both apps, `next_due_date` recomputes as
  `visit_date + interval`, and any `next_due_override` on that property is **cleared automatically**.
- Set an override via a REPL, then log a visit, then confirm the override is gone and the
  `(movida)` suffix disappeared from the Resumen row.
- Log a **bundled** visit covering the QA property plus one sibling of the same client: one
  `maintenance_visit_groups` row carries the amount, both `maintenance_visits` rows have
  `amount_usd IS NULL` and the same `visit_group_id`, both properties' schedules recompute, and
  both histories render the grouped wording.
- Save credentials for a site in each schema; confirm the composite-key upsert overwrites rather
  than duplicating, and that a reload shows the saved text.
- Unlink everything and delete the QA property when done.

---

### Step 3 — Calendario anual + Configurar propiedades

**Build**
- `_calendar.html` per §1.4 items 7–13: year `<select>`, the current-year 12-month grid (4×3), the
  ⚠ `next_due_date.year <= year` filter and the separate future-cycle box, the red
  "Sin mantenimiento" banner, the unscheduled caption, and the move/reset block —
  **keyed by property id, not name** (§0.4 Q5).
- Historical mode for any past year, built from `property_rows()`'s carried `"visits"` (§1.5), with
  its own caption and empty state.
- `POST /calendario/override` → 303 back to `/calendario?anio=<year>` so the year survives the
  round trip.
- `_setup.html` per §1.4 items 14–19: unlinked info box + seed button, new-property form with
  validation, the existing-properties table, the reactive merge panel (`_merge_panel.html`), and
  the inline delete confirm (`_delete_confirm.html`).

**Validate**
- For the current year, every month card matches Streamlit's cell-for-cell: same properties, same
  emoji, same day numbers, same `✓` marks, same `—` for empty months.
- ⚠ **The future-cycle case specifically:** find or construct (on the QA property) a property whose
  `next_due_date` falls in a later year; confirm it is **absent from the grid** and **present in the
  green "Ya visitadas" box** in both apps. This is item 8 and it is the single easiest thing in the
  phase to silently get wrong.
- Pick a past year with real visits: the historical grid matches Streamlit, shows amounts where
  present, uses no status colours, and a year with no visits shows the empty-state message.
- Move a property to another month from the calendar: the date changes, the Resumen row gains
  `(movida)`, the calendar re-buckets it, and "Restablecer a fecha calculada" puts it back.
- ⚠ **Duplicate-name check:** create two QA properties with the *same* name, confirm the move picker
  and the merge keep-name picker each address the right one (this is the §0.4 Q5 fix; in Streamlit
  the same test picks the wrong row).
- Merge: select two QA properties of **different** clients → the warning appears and the button is
  disabled until the confirm checkbox is ticked; merge → sites and visits both moved, source row
  gone. Select one → the "Marca al menos 2" hint.
- Delete: the confirm fragment carries the exact warning text; Cancelar leaves everything alone;
  Sí unlinks the sites (they reappear as unlinked) and removes the property.
- Seed: verify the unlinked count matches Streamlit's, and if any genuinely unlinked site exists,
  run it on a QA-created unlinked site and confirm it makes exactly one property per site and is
  idempotent on a second run.
- **Every destructive validation above is performed on QA-created properties only.**

---

### Step 4 — Cutover

**Build**
- Sweep `dashboard.STUBS` (only `"projects"` should remain) and the nav.
- Walk the **entire §1.4 checklist** against the running app, item by item, and record the result in
  this document under a new "Built" section — the same way `PLAN_PHASE20_PROPOSALS_JINJA.md` §5 and
  `PLAN_PHASE18.md` do. Mark each item PASS (live) / PASS (code) / FAIL / WAIVED with its evidence.
- **Fix the documentation drift this phase uncovered** (§1.1) — this is a deliverable, not a
  courtesy:
  - `PHASES.md` L28: Phase 10 is **not** "Not started." Replace with an accurate status naming the
    actual migrations (045/046/047, not the spec's 037), the two-schema reality, the never-built
    `tools/import_maintenance_register.py` and geocoding backfill, and the never-called SQL status
    function.
  - Add a Phase 21 row to `PHASES.md`'s table pointing at this document.
  - `CONTEXT.md`: the maintenance register currently does not exist in it. Add a short section.
  - `ARCHITECTURE.md`: document the `public.site_properties` ↔ `monitoring.sites`/`vrm.sites`
    `property_id` coupling and migration 047's dual-schema trigger — §0.2's risk is invisible in
    that document today.
- Raise §0.4 Q6 (fate of `pages/07_maintenance.py`) with Oscar. **Do not delete it as part of this
  step** — Phase 20 §1.9's precedent is that deletion is its own deliberate commit.

**Validate**
- A full pass over every §1.4 item with recorded evidence; no item left unaddressed.
- One complete real-world exercise, end to end, in Flask only: open Mantenimiento, identify the
  most-overdue property, open it, log a real visit, confirm it disappears from the overdue block and
  the calendar re-buckets it, and confirm Streamlit agrees on a refresh.
- `git diff main..main_jinja -- calculations/ database/ pages/` shows **only**
  `database/site_properties_db.py`'s one additive function (§1.5) and nothing else this phase
  touched — same discipline as Phase 20 §5.6.

---

## 3. Explicit non-goals

- **Anything about credentials security beyond not over-exposing them.** `public.site_credentials`
  stores plaintext WiFi/portal passwords, service_role-only, no encryption, no RLS, no auth in front
  of the Flask app at all. §1.6's reveal-on-demand reduces incidental exposure; it is **not** a
  security control. Encryption at rest, a secrets manager, app-level auth and audit logging are all
  out of scope and remain open product questions (§4).
- **Decoupling from `vrm.sites`, or anything else about the VRM Monitor split** (§0.2). This phase
  keeps writing `vrm.sites.property_id` exactly as Streamlit does. Deciding who owns that column,
  what happens if `vrm` ever moves to its own Supabase project, and whether migration 047's `vrm`
  trigger should live in the other repo is a cross-product conversation, not a UI port.
- **Any schema change.** No new migration in this phase. `045`/`046`/`047` stand as-is.
- **Any change to `calculations/maintenance.py` or `public.get_property_maintenance_status()`.** In
  particular, do **not** "fix" the dead SQL function, do not switch the UI to it, and do not delete
  it — the two-implementations arrangement is documented and deliberate.
- **The Phase 10 spec's never-built pieces** (§1.1): `tools/import_maintenance_register.py`, the
  xlsx visit-history and credentials import, the lat/lon geocoding backfill, and the `geocode_cr()`
  San Isidro/Pérez Zeledón fix. Each may still be worth doing; none is a port.
- **A Projects ↔ property link.** `PHASES.md` L523 says the register is deliberately not scoped to a
  `projects` row. Projects is still a stub on this branch anyway.
- **New features of any kind**: no search/filter on the overview (Streamlit has none), no visit
  editing or deletion (Streamlit has none — visits are append-only from the UI), no email/calendar
  reminders, no CSV/bulk visit import, no maintenance-revenue reporting, no mobile/field-tech view,
  no per-property interval editing after creation (Streamlit cannot do it either).
- **Deleting `pages/07_maintenance.py`** or any other Streamlit file (§0.4 Q6).
- **Auth, multi-user, or concurrency control.** Single internal operator, same as Phase 20 §3.

---

## 4. Risks and tradeoffs

**The biggest risk is that validation has no oracle but a live production register.** Phase 20 had
María José and Jorge Ramírez — fixed inputs with published expected outputs. This feature has
nothing equivalent: no fixture, no reference numbers, and (per §1.1) not even the xlsx cross-check
its own spec promised. The only oracle is the Streamlit page rendering the same live rows. That has
two consequences the coder must internalise:

1. **Validation is exhaustive row-by-row comparison, not sampling.** A status that is wrong for one
   property in one edge case (an override set, a property with no sites, a visit dated today) is
   invisible to a three-row spot check and completely visible in a 25-row diff.
2. **The write paths are destructive and operate on data Oscar bills against.** `delete_property()`
   cascade-deletes `maintenance_visits` (migration 045 L47) and `merge_properties()` is
   irreversible. There is no soft delete, no undo and no backup step in any of these functions.
   Every destructive validation in §2 is therefore scoped to purpose-created QA properties. **A
   coder who tests "Eliminar" on a real property destroys real visit history with no recovery
   path.** This is the one place in the phase where a mistake is not merely a bug.

**Cross-schema coupling to a split-out product (§0.2).** Dimensionador writes `property_id` on VRM
Monitor's `vrm.sites`, and a trigger this repo owns fires on inserts into that table. Today that is
fine — same Supabase project, documented in `ARCHITECTURE.md` L3–5. It stops being fine the moment
anyone separates the databases, and nothing in either repo would warn them: `vrm-monitor` has no
reference to `site_properties`, and `ARCHITECTURE.md` does not mention the register at all. Step 4's
documentation work is the mitigation — it does not remove the coupling, it just makes it visible
before someone trips over it.

**Two status implementations that can drift.** `compute_status()` (Python, used) and
`get_property_maintenance_status()` (SQL, unused) both encode the override short-circuit, the
last-visit/commissioned-at fallback and the 30-day due-soon window. They agree today. Nothing tests
that they still will, and the SQL one has no caller to notice. The port deliberately does not
consolidate them (§3) — but it also must not quietly start using the SQL one "because it is the
database's job," which would change behaviour (it does not return `days_overdue`, item 4's whole
rendering depends on that).

**Losing the calendar's year-filter nuance.** §1.4 item 8 is a fix for an ambiguity Oscar reported
by name on 2026-09-08, and its entire implementation is one comparison plus a second render block.
It is the most likely thing in this phase to be "simplified" out by someone bucketing dates by month
and moving on, and the symptom — a property that was already visited quietly appearing as due — is
exactly the class of error a maintenance scheduler exists to prevent.

**Deliberate deviations from strict parity, both disclosed.** Reveal-on-demand credentials
(§0.4 Q3) and id-keyed rather than name-keyed pickers (§0.4 Q5). The second is a real bug fix and
becomes reachable the moment migration 047's trigger auto-creates two properties with the same site
display name — which it will, since nothing prevents it. Both are called out here rather than
buried so the tester compares against intent, not against Streamlit's behaviour, on these two points.

**Query volume is tolerable, not good.** §1.5's two optimisations take the overview from roughly
`4 + 2N` queries to roughly `5`, and the detail page from `2 + sites + grouped_visits` to
`2 + grouped_visits`. At 25 properties nobody will notice either way. The reason to do it at all is
that the calendar's historical mode currently refetches data the same request already had, which is
the kind of thing that looks like a deliberate decision to the next reader when it is just an
artifact of Streamlit's top-down script model.
