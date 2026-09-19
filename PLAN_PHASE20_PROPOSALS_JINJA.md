# Phase 20 — Cotizaciones: proposals list + the full New Proposal wizard, ported off Streamlit onto Flask/Jinja2/htmx

**Status:** ready for the coder agent, with 6 open questions for Oscar flagged in §0.3
**Author:** architect agent, 2026-09-18
**Branch:** `main_jinja` (worktree `Claude-main_jinja`). `main` stays the Streamlit source of truth
for behaviour and is **not modified by this phase**.
**Builds on:** the already-landed `main_jinja` work — `webapp/blueprints/dashboard.py` (nav shell)
and the full Admin section (`webapp/blueprints/admin*.py` + `webapp/templates/admin/`), whose
routing/partial/template conventions this plan reuses verbatim rather than inventing a second style.
**Spec sources:** `PHASES.md` Phase 2 (Grid Zero wizard), Phase 3 (Proposal management), Phase 4
(AI features), Phase 5 (Off-Grid + Hybrid, **including its "Beyond the original spec" section**);
`pages/01_proposals.py`, `pages/02_new_proposal.py`; `wizard/common.py`, `wizard/grid_zero.py`,
`wizard/off_grid.py`, `wizard/hybrid.py`, `wizard/state.py`; `proposals/generator.py`.
**Plan doc convention:** same shape as `PLAN_PHASE6.md` / `PLAN_PHASE14.md` — confirmed context,
resolved decisions with their reasoning, then vertical build steps each carrying its own
validation gate.

---

## Goal

**Cotizaciones stops being a stub.** An engineer opens `/cotizaciones`, sees the same proposals
list they see in Streamlit today, expands a row to reach versions/lock/status/PDF, clicks
"Nueva cotización", and walks an 8-step wizard — Grid Zero, Off-Grid or Hybrid — that produces
the **same numbers and the same PDF** as the Streamlit wizard for the same inputs.

"Done" means both reference datasets reproduce exactly:

- **Grid Zero — María José Castro** (`PHASES.md` L209–210): avg 1,475 kWh, avg bill ₡157,874,
  generation 1,262 kWh, new consumption 521 kWh, new bill ₡51,681, savings ₡106,192;
  savings Y1 $2,798, savings 25 yr $127,873, IRR 22.92 %, ROI 5.48.
- **Off-Grid — Jorge Ramírez** (`PHASES.md` L316–317): 8 × 620 W panels, 1 Victron MultiPlus
  5000VA, 2 Pylontech US5000C, 1 Victron MPPT 250/100 → 5.0 kW, 16 m², 6.38 kWh/día,
  9.60 kWh battery @10 h, 66.46 % discharge, $10,320 total, $2.08/Wp.

and every item in the **§1.10 do-not-drop checklist** survives the port.

---

## 0. Confirmed context (do not re-derive)

### 0.1 Facts established by reading both checkouts

| Fact | Where |
|---|---|
| Wizard state in Streamlit is **two-tiered**: seven durable sections (`wizard_meta/client/site/utility/consumption/equipment/costs` + `wizard_proposal_text`) that `autosave()` serialises into `proposal_versions.data`, and a much larger set of **transient `w{N}*_` widget/scratch keys that autosave never writes** | `wizard/state.py:autosave()` L62–84 vs. the `w5_applied_months` / `w6_scenarios` / `w6_coverage_ai` / `w4og_loads_data` / `w5og_profile` keys throughout the wizard modules |
| That tier-2 gap has already caused real, documented bugs — Step 4/5 "Atrás" had to be patched to persist before navigating, and `daytime_fraction_note` is explicitly copied into the durable blob because `w6_coverage_ai` isn't serialised | `wizard/off_grid.py` L296–309, L606–614; `wizard/grid_zero.py` L1283–1286 |
| Durable blob shape: `{"meta": {...,"step_reached": n}, "client", "site", "utility", "consumption", "equipment", "costs", "proposal_text"}` | `wizard/state.py:autosave()` / `load_draft()` |
| The proposal row is **not created until Step 2 (Tipo e idioma) completes** — steps 1–2 live purely in session_state. `create_proposal()` burns a quote number via `_next_quote_number()`, so an abandoned wizard currently costs nothing | `pages/02_new_proposal.py` L170–192, `database/proposals_db.py` L37–61 |
| Display step order ≠ function names: step **1** renders `step2_client()`, step **2** renders `step1_system_type()`. Legacy naming, not a behaviour | `pages/02_new_proposal.py` L137–192 |
| `calculations/`, `ai/`, `proposals/`, `database/`, `utils/` contain **zero Streamlit imports** — they are already framework-agnostic and reusable as-is | `grep -rn streamlit` over those packages returns only two docstring mentions |
| `proposals/generator.py:build_from_wizard_blob(blob, proposal, quote_str, version_date)` already converts a saved version blob into `generate_pdf()`'s data dict, and is what the Streamlit **list page** uses | `proposals/generator.py` L426, `pages/01_proposals.py:_generate_pdf_bytes()` |
| The wizard's own Step 8 does **not** use it — it builds the dict inline — and that divergence produced two real shipped bugs (Off-Grid PDFs at 0.00 kW / 0.0 m²; every line total $0.00) fixed only on the blob path | `proposals/generator.py` L450–456, L474–481 |
| `wizard/common.py:monthly_coverage_chart()` already returns a bare `plotly.graph_objects.Figure` with no Streamlit call — the template for extracting every other wizard chart | `wizard/common.py` L400–450 |
| PVGIS monthly + daily series are cached in Supabase `app_settings` by rounded lat/lon, so refetching a known site is free | `calculations/pvgis.py` L11–64 |
| `plotly`, `flask`, `weasyprint`, `anthropic`, `pandas` are all present in `main_jinja`'s `.venv` (Python 3.9) | `.venv/lib/python3.9/site-packages/` |
| `webapp/__init__.py` has **no `SECRET_KEY`**, so `flask.session` is unusable today | `webapp/__init__.py` |
| Established webapp conventions: blueprint + `register(bp)` per section module, lazy `from database... import` **inside** view functions, `request.headers.get("HX-Request")` to decide partial-vs-page, `hx-target="#subpanel"` + `hx-push-url="true"` for panel swaps, POST handlers ending in `redirect(url_for(...))`, per-partial `<style>` blocks, global `#flash` toast on any non-GET | `webapp/blueprints/admin.py` L94–108, `admin_clients.py`, `webapp/templates/admin/page.html`, `webapp/templates/base.html` |
| CSS vocabulary available: `--navy --green --green-tint --border --muted`, `.card .card-note .card-note-sm .dtable .dtable-wrap .dtable-empty .btn .tabs .section-title .cards`, plus `.finput .fgrid .flabel .link-btn .danger-btn` defined inline in `_clients_panel.html` | `webapp/static/styles.css`, `webapp/templates/admin/_clients_panel.html` |

### 0.2 A blocking finding: `main_jinja`'s shared Python layer is a stale snapshot of `main`

`main_jinja` did not only add `webapp/` — it froze copies of the shared packages at an older
point. Line counts differ on exactly five files (everything else is identical):

| File | `main_jinja` | `main` | What differs |
|---|---|---|---|
| `wizard/state.py` | 251 | 305 | **`get_asset_b64()` and `save_asset()` are missing entirely.** `save_company_info()` also differs semantically: `main_jinja` does `{**current, **patch}` + `upsert` (**can blank a field with an empty string**); `main` skips `None`/`""`/`[]` and uses `update` (never blanks) |
| `proposals/generator.py` | 707 | 709 | `main_jinja` still sources logo/signature/isotipo from **bundled files** (`proposals/assets/assets.py`); `main` sources them from **Supabase Storage** via `wizard.state.get_asset_b64()` |
| `calculations/pvgis.py` | 335 | 340 | small |
| `wizard/grid_zero.py` | 2126 | 2132 | small |
| `wizard/off_grid.py` | 2413 | 2416 | small |

**Consequences that are already live on this branch:** Admin → Ajustes' logo/signature upload is
stubbed out with an apology note (`webapp/blueprints/admin.py` docstring L7–8,
`admin_settings.py`, `_ajustes.html` L53) *purely because those two functions are absent* — and
any PDF this branch generates will carry the bundled assets, not whatever Oscar has uploaded.
Porting the wizard on top of a stale PDF generator would bake that divergence into every quote.
**This is Step 0 and it blocks everything else.**

### 0.3 Decisions (confirmed with Oscar 2026-09-19) and remaining open questions

1. **Is `main` frozen during this port? — Decided: yes.** `main` is frozen for `wizard/`,
   `calculations/`, `ai/`, `proposals/` for the duration; bug fixes land on `main_jinja` and get
   cherry-picked back. Step 0's reconciliation is therefore a one-time pass, not a per-step-boundary
   recheck.
2. **Chart rendering — Decided: vendored `plotly-basic.min.js`** (~1 MB, keeps hover/zoom, reuses
   the existing figure code unchanged). See §1.6.
3. **May an abandoned draft burn a quote number? — Decided: yes, simplify.** The proposal row
   (and its quote number) is created on the very first click, not deferred to step 2. §1.2's
   pre-row `flask.session["wiz_pending"]` carry is removed entirely — step 1 creates the row.
   `_next_quote_number()` now runs a click earlier than it did in Streamlit; an abandoned wizard
   can burn a quote number going forward. Not a regression Oscar considered worth the extra
   session-carry machinery.
4. **"Mover a Proyecto"** on won proposals depends on the Projects module, which is still a stub
   on this branch. *Working assumption: render the affordance disabled with a "disponible cuando
   se migre Proyectos" note, and wire it fully in the Proyectos phase.*
5. **Does `pages/02b_new_proposal_test.py` / `wizard/design_scenarios_test.py` get ported?**
   Its own docstring calls it an ephemeral sandbox that writes nothing. *Working assumption: no —
   explicit non-goal (§3).*
6. **`SECRET_KEY` source — now likely moot.** The only planned use of `flask.session` was the
   pre-row steps 1–2 carry, which Q3's decision removes. Unless a later step introduces another
   need for `flask.session` (none currently planned), this phase does not need `SECRET_KEY` set at
   all. Revisit only if that changes; no action needed to start building.

Steps 0–3 are unblocked today, with Q1–Q3 now resolved. Step 2 still needs Q4 to be decided (a
working assumption is fine to build against; it only needs revisiting before Step 2 ships).

---

## 1. Resolved decisions (these are not open questions)

### 1.1 The draft blob **is** the state. There is no session_state analogue, and no separate autosave.

Streamlit's model is: whole-script rerun reads `st.session_state`, and `autosave()` occasionally
mirrors *part* of it to Supabase. Flask has no rerun and no per-user process memory. The port
does not try to emulate session_state — it **collapses both tiers into the persisted blob**:

```python
proposal_versions.data = {
  "meta": {...}, "client": {...}, "site": {...}, "utility": {...},
  "consumption": {...}, "equipment": {...}, "costs": {...}, "proposal_text": "...",
  "scratch": {                       # NEW — what st.session_state's w*_ keys used to hold
    "s5":   {"bill_history": [...], "bill_meta": {...},
             "applied_months": [...], "applied_source_meta": {...}, "loads_data": [...]},
    "s6":   {"scenarios": [...], "selected_scenario": "B", "use_manual": false,
             "coverage_ai": {"fraction": 0.48, "note": "..."},
             "manual": {"series": 6, "parallel": 2}, "equip_key": "<panel>_<inv>"},
    "s6og": {"selected_scenario": "2", "use_manual": false, "manual": {...},
             "equip_key": "<panel>_<cc>_<bat>"},
    "s5og": {"hourly_shape": {...}},
    "mp":   {"loads_data": [...], "hourly_shape": {...}}   # Hybrid main panel (w4h_mp/w5h_mp)
  }
}
```

**Why one store instead of a Flask session + a blob:**

- It **fixes an existing bug class by construction.** Every "persist before navigating away" patch
  in `wizard/off_grid.py` exists because tier-2 state could vanish. With one store there is no
  tier 2 to lose.
- A wizard resumed tomorrow comes back to the *exact* screen it was left on — scenario cards
  still computed, bill extraction still applied — which Streamlit cannot do today.
- It survives a browser refresh, a second tab, and a server restart for free.

**Hard constraint — blob compatibility.** `main`'s Streamlit app reads and writes the same rows.
`wizard/state.py:load_draft()` copies only the seven known keys and `build_from_wizard_blob()`
reads only those, so **adding `scratch` is additive and safe for reads in both directions**. The
port must not change the meaning, key names or units of any of the seven sections. A draft created
in Flask must open cleanly in Streamlit and vice versa — that is a Step 3 validation gate, not an
aspiration.

**Confirmed asymmetry (Step 3, empirically verified, not just reasoned about):** the "additive and
safe" guarantee holds for *reads* in both directions, but **not for a Streamlit-side write**.
`autosave()` rebuilds `data` from `session_state`'s seven known keys and `upsert_version()` does a
full-column replace, not a JSON merge — so if a draft with `scratch` data is opened in Streamlit
and Streamlit saves it again (any step advance, any field edit), `scratch` is silently dropped.
**Accepted, not fixed**: `wizard/draft.py:load()` always re-defaults a missing `scratch` to `{}`,
so this never crashes or corrupts the seven durable sections — it just means an in-progress step's
scratch data (an applied bill extraction, a computed scenario) needs recomputing if the same draft
was touched by Streamlit in between. Full details and rationale in `wizard/draft.py`'s module
docstring. **Operational implication for Steps 4 onward**: once a step starts writing real
`scratch` data (Step 4's bill parsing, Step 5's MPPT scenarios, etc.), avoid opening an
in-progress Flask draft in the Streamlit app — there is no technical guard against it, only this
documented caution.

**New module `wizard/draft.py`** (Streamlit-free, sits beside `wizard/state.py`, does not replace
it):

```python
load(version_id) -> dict            # get_version() + defaults for every missing section
save(version_id, blob) -> None      # upsert_version(version_id, blob, blob["costs"].get("total_usd"))
patch(version_id, section, values) -> dict   # read-modify-write ONE section, returns the new blob
set_step(version_id, n) -> None     # writes meta.step_reached (monotonic: never lowers it)
scratch(blob, key) -> dict          # blob["scratch"].setdefault(key, {})
```

**Every mutation is a save.** There is no debounce, no timer, no background thread. A POST loads
the blob, patches one section, writes it, re-renders. That is literally Streamlit's rerun cycle
with Supabase as the store. Keep `base.html`'s existing `#flash` toast as the "Guardado" feedback
(it already fires on every non-GET) — do **not** port `show_save_indicator()`'s clock.

**Concurrency** is last-write-wins on a whole-blob update. Acceptable: single internal user, and
every handler does a read-modify-write of one section inside one request. Do not add optimistic
locking; do note it in `draft.py`'s docstring so nobody later assumes it's safe for two users.

### 1.2 Route/blueprint structure

Two blueprints, both following `webapp/blueprints/admin.py`'s dispatch shape (one module owns
routing, per-step modules own their logic):

```
webapp/blueprints/proposals.py        Blueprint("proposals", url_prefix="/cotizaciones")
  GET  /                              list: search + status filter + table         (page)
  GET  /filtrar                       same table body, htmx target #plist          (partial)
  GET  /<pid>/detalle                 expanded detail panel for one row            (partial)
  POST /<pid>/estado                  status transition (+ promote_prospect on won)(partial)
  POST /<pid>/v/<vid>/pdf             generate → store → return a ready link       (partial)
  GET  /<pid>/v/<vid>/pdf/descargar   send_file / redirect to signed URL           (file)
  POST /<pid>/v/<vid>/nueva-version   create_version(from) → 303 into the wizard
  POST /<pid>/v/<vid>/enviada         mark_version_sent                            (partial)
  GET  /dev/pdf-muestra               sample-PDF panel (port of _render_test_pdf_panel)

webapp/blueprints/wizard.py           Blueprint("wizard", url_prefix="/cotizaciones/asistente")
  GET      /nueva                     step 1 Cliente — POST creates the row immediately, 303 out
  POST     /nueva                     create_prospect()/upsert_client() + create_proposal(), 303 → paso/2
  GET      /<vid>/paso/<int:n>        render step n                                (page)
  POST     /<vid>/paso/<int:n>        persist section + 303 → paso/<n+1>
  POST     /<vid>/paso/<int:n>/atras  persist section + 303 → paso/<n-1>
  POST     /<vid>/paso/<int:n>/<act>  in-step action, returns a fragment           (partial)

webapp/wizard_steps/                  one module per step, mirroring admin_*.py granularity
  common.py        build_context() helpers shared by every step; form parsers
  s1_client.py  s2_type.py  s3_site.py
  gz_s4_utility.py  gz_s5_consumption.py  gz_s6_equipment.py  gz_s7_costs.py  gz_s8_review.py
  og_s4_loads.py    og_s5_demand.py       og_s6_equipment.py  og_s7_costs.py  og_s8_review.py
  hy_s4_loads.py    hy_s5_demand.py                                   # 6/7/8 delegate to og_*
```

**Step numbering follows the *displayed* order** — 1 Cliente, 2 Tipo e idioma, 3 Sitio, 4, 5, 6,
7, 8 — i.e. the port drops `pages/02_new_proposal.py`'s legacy `step1_system_type()`/
`step2_client()` name inversion. Say so in `wizard.py`'s docstring so the next reader doesn't
think it's a behaviour change.

**Branching** is a single dispatch table keyed on `meta.system_type`, exactly as
`pages/02_new_proposal.py` L202–268 does today. Steps 1–3 are shared by all three types. Hybrid
delegates steps 6–8 to the Off-Grid modules, matching `wizard/hybrid.py` L382–397.

**Row created on step 1, not deferred (§0.3 Q3).** Unlike Streamlit, the proposal row — and its
quote number — is created by step 1's own POST: `create_prospect()`/`upsert_client()` +
`create_proposal()` run immediately, writing `client` and a default `meta` (system type/language
not yet chosen) into a fresh blob, then 303s to `/…/<vid>/paso/2`. There is no
`flask.session["wiz_pending"]` carry — every step from 1 onward operates on a real `vid`. Step 2's
POST just patches `meta` (system type + language) into the same row. Trade-off accepted: an
abandoned draft after step 1 burns a quote number, same as it would after any later step.

**Step guard.** `GET /<vid>/paso/<n>` with `n > meta.step_reached + 1` → 303 to
`paso/<step_reached>`. Completed steps stay clickable in the breadcrumb (that's a genuine
improvement over Streamlit, where only ← Atrás moves backwards, and it costs nothing).

**Locked versions are read-only.** `GET /<vid>/paso/<n>` on a version with `locked = true` →
303 to the proposals list with a message. `pages/01_proposals.py` enforces this by disabling
"Continuar"; here the guard has to be server-side because the URL is directly reachable.

### 1.3 One `build_context(blob)` per step — the direct analogue of Streamlit's whole-script rerun

This is the single most important structural rule of the port, and the one that, if broken,
produces silent numeric drift.

Streamlit recomputes *every* derived value on every rerun: tariff tiers, `avg_irradiance`,
`daytime_fraction`, `target_kw`, scenario projections, totals. A Flask partial handler that
updates one panel is tempted to recompute only what that panel shows — and then the panel below
it, rendered from a previous request, is stale in a way nobody sees until the PDF is wrong.

**Rule:** each step module exposes exactly one

```python
def build_context(blob: dict) -> dict:   # pure-ish: reads blob + DB, computes everything the step shows
```

and **every** route that renders any part of that step — the full page GET, and every one of its
action POSTs — calls it. A partial handler's job is: `patch()` → `build_context()` → render the
*fragment* from the same context dict the full page would have used. Never render a fragment from
handler locals.

Corollary: every step's page template is `{% include %}`-composed from the same fragments its
partial routes return, so there is exactly one copy of each fragment's markup.

### 1.4 htmx interaction model — three patterns, no more

Reuse the admin section's vocabulary; do not introduce a fourth pattern.

1. **Step navigation is a plain form POST with a 303 redirect — not htmx.** Back and Next are
   `<form method="post">` submits. This buys correct browser history, refresh-safety and
   bookmarkable step URLs for free, and it means "Atrás persists the section before leaving"
   (`wizard/off_grid.py` L296–309's hard-won fix) is automatic rather than a special case.
2. **In-step actions are `hx-post` returning a fragment**, swapped into a named region
   (`#s6-escenarios`, `#s5-tabla`, `#s3-irradiancia`, …) with `hx-swap="outerHTML"`. Mirrors
   `admin.sub_view`'s `#subpanel` swap. Add `hx-indicator` + `hx-disabled-elt="this"` on every
   action that calls AI, PVGIS or the SoC simulator.
3. **Live recompute is `hx-trigger="change delay:400ms"` from the enclosing form**, posting the
   whole table and swapping the recomputed table/totals back. This is how `st.data_editor`'s
   implicit rerun-on-edit becomes explicit (§1.5).

`hx-push-url` is used only for the list page's filter/detail, not inside the wizard (the wizard's
URL is owned by the step redirects).

### 1.5 Replacing `st.data_editor` — plain HTML tables, one form, server-side recompute

Seven editable grids exist across the wizard (GZ consumption 12-month, GZ loads, GZ/OG cost line
items, OG loads ×2, OG demand-profile ×2). All become the same construct — **no JS grid library**:

```html
<form hx-post=".../tabla" hx-target="#s5-tabla" hx-swap="outerHTML"
      hx-trigger="change delay:400ms">
  <table class="dtable">
    ...<td><input class="finput" name="r-3-kwh" value="1480"></td>...
  </table>
</form>
```

- `webapp/wizard_steps/common.py:parse_rows(form, prefix, fields)` turns `r-<i>-<field>` back into
  a `list[dict]`, coercing blanks to `None` (not `0`) so the "qty is None ⇒ treat as 1" rule in
  `_row_subtotal()` ports unchanged.
- "+ Fila" / "✕" are POSTs that append/remove and re-render the table fragment.
- Disabled/computed columns render as plain `<td>`, not inputs — matching `disabled=True` in the
  existing `column_config`.
- `st.column_config.SelectboxColumn` → `<select>`; `NumberColumn(min_value=…)` →
  `<input type="number" min=…>`. Keep the existing `help=` strings as `title=` attributes; they
  carry real engineering meaning (e.g. the "Factor demanda" and "Energía (kWh/día)" explanations
  in `wizard/off_grid.py` L418–445), and losing them is a silent regression.
- `pandas` is still used for the arithmetic where it already is (`_row_subtotal`, the
  groupby in the category chart) — the port changes the *input surface*, not the math.

Grid Zero's auto-recalculation of `Factura (₡)` when `kWh` changes (`wizard/grid_zero.py`
L421–455, today a `st.rerun()`) is exactly pattern 3: the `change` trigger posts the table, the
handler re-runs `estimate_bill_crc()` per month, updates `scratch.s5.applied_months` and the
source badge (including the `· editada` suffix rule), and swaps the table back.

### 1.6 Charts — reuse the existing Plotly figure code, render server-side to HTML fragments

`monthly_coverage_chart()` already proves the pattern: a function that returns a `go.Figure` and
touches no Streamlit. Extract every other `go.Figure(...)` construction out of the wizard modules
into **`webapp/figures.py`** (Streamlit-free, one function per chart), and render with:

```python
fig.to_html(full_html=False, include_plotlyjs=False, config={"displayModeBar": False})
```

with **`plotly-basic.min.js` vendored** into `webapp/static/vendor/` beside `htmx.min.js` and
loaded from `base.html`.

- **Why not static SVG:** `proposals/charts.py` only covers the monthly-coverage chart. Every other
  wizard chart (margin bars, utilization stack, category donut, hourly stack, cash-flow curve,
  consumption bars, irradiance bars, generation-vs-consumption bars) would have to be written from
  scratch as SVG, and hover — which is how an engineer actually reads the seasonal charts — would
  be lost. Reusing the figures is both less new code and zero drift risk.
- **Keep the SVG/Plotly twinning that already exists.** `monthly_coverage_chart()`'s docstring
  records that it deliberately shares colours with `proposals/charts.py` so screen and PDF never
  diverge. That property must survive: `webapp/figures.py` imports the colours from
  `proposals/charts.py` exactly as `wizard/common.py` does today.
- **Two gotchas to verify in Step 3, not later:** (a) htmx does execute `<script>` in swapped
  content, so a chart inside a swapped fragment initialises — confirm on the first PVGIS chart;
  (b) `plotly-basic` must actually contain `Bar`, `Scatter` and `Pie` — confirm all three render
  before committing to it, and fall back to the full bundle if not.

### 1.7 AI features and file uploads in the Flask request lifecycle

Every AI entry point is already a pure `bytes`/`str` → `dict` function. Nothing about them needs
porting; only their invocation does.

| Wizard surface | Existing call | Flask route |
|---|---|---|
| GZ Step 5 — bill PDFs (multi-file) | `calculations.bill_parser.parse_bill_pdf(bytes)` then `fill_bill_amounts()`, then `build_12_month_grid(history, location, tariff_info)` on "Aplicar" | `POST …/paso/5/factura/extraer` (multipart, `request.files.getlist`), `POST …/paso/5/factura/aplicar` |
| GZ Step 5 — tablero image/PDF | `calculations.tablero_parser.parse_tablero(bytes, media_type)` | `POST …/paso/5/tablero/extraer` |
| GZ Step 5 — loads → 12 months | `calculations.load_estimator.estimate_loads_12_months_ai()` | `POST …/paso/5/cargas/aplicar` |
| GZ Step 6 — daytime fraction | `_estimate_daytime_fraction_ai()` (currently **inline in `wizard/grid_zero.py`** L549–587, constructing its own `anthropic.Anthropic`) | move verbatim to `ai/daytime_fraction.py` and call from `POST …/paso/6/mppt/calcular`. It is the only prompt living outside `ai/`; a Flask blueprint must not hold prompts |
| OG/Hybrid Step 4 — tablero + pasted text | `parse_tablero_off_grid(bytes, mime)` / `parse_tablero_text_off_grid(text)` | `POST …/paso/4/tablero/extraer`, `POST …/paso/4/texto/extraer` |
| OG/Hybrid Step 5 — hourly shape | `load_profile_off_grid.estimate_hourly_shape_illustrative()` | `POST …/paso/5/perfil/horario` |
| Step 8 — intro paragraph | `ai.proposal_writer.generate_intro(params, language)` → `{"es":…, "en":…}` | `POST …/paso/8/intro/generar` |
| Admin — datasheet ingestion | `calculations.datasheet_parser.parse_*_datasheet(bytes)` | **out of scope here** — it belongs to the Admin section's own gap (`webapp/blueprints/admin.py` docstring L6–7); noted as a non-goal (§3) |

**Synchronous, no job queue.** These calls take 5–40 s. Reasons, stated so nobody re-proposes a
worker: one internal user; Streamlit is synchronous today and that latency is already accepted;
and a jobs table plus polling is real infrastructure with no payoff at this scale. Mitigations
instead: `hx-indicator` spinner, `hx-disabled-elt="this"` to block double-submits, and a
`MAX_CONTENT_LENGTH` (25 MB) with a friendly 413 handler. Flask's dev server is threaded by
default, so a long AI call does not freeze the whole app — verify that once, in Step 4, with a
second tab.

**The AI never does the energy math.** `PHASES.md` Phase 5 is explicit that AI is used only for
bounded classification/extraction. The port introduces no new AI call and moves no arithmetic into
a prompt.

### 1.8 PDF generation — converge both paths on `build_from_wizard_blob()`

Today there are two PDF data-dict builders: the wizard's inline one (`wizard/grid_zero.py`
L1968–2029, `wizard/off_grid.py`'s equivalent) and `build_from_wizard_blob()` used by the list.
`proposals/generator.py`'s own comments record two shipped bugs that existed *only* because the
list path was a second implementation.

**Decision: the Flask port has one path — `build_from_wizard_blob()` — used by Step 8 and by the
proposals list alike.** This is the highest-value structural change in the phase.

It is not free: the wizard's inline dict currently carries things the blob path may not
(`monthly_coverage` built from `sizing["monthly_generation"]`, `technical.self_consumption_pct`,
`payment_notes_*`, warranty rows, `**bank`, `company`, `validity_days`). **Step 6's first task is
a field-by-field diff of the two dicts on a real draft**, and any gap is closed by *extending*
`build_from_wizard_blob()` — additively, so `main`'s list page inherits the fix too. Do not
re-create the inline builder in Flask "just for now"; that is precisely how the two paths diverged
the first time.

**Download flow** (htmx cannot swap a file response — this is the one place the pattern breaks):

1. `POST …/paso/8/pdf` (htmx, with spinner) → `build_from_wizard_blob()` → `generate_pdf()` →
   `upload_pdf()` + `save_pdf_path()` → returns a fragment containing a plain
   `<a href="…/pdf/descargar" download>⬇ Descargar PDF (ES)</a>`.
2. `GET …/pdf/descargar` → if the version has a `pdf_path`, redirect to a signed URL
   (port `_signed_url()` from `pages/01_proposals.py` L192–198); otherwise regenerate and
   `send_file(BytesIO(pdf), mimetype="application/pdf", as_attachment=True, download_name=…)`.
3. `download_name` comes from the existing `wizard.state.pdf_filename(quote_number, client_name,
   lang_label)` — its convention (quote number first, so a downloads folder sorts chronologically)
   is documented in that file and must not be reinvented.

The two-step mirrors Streamlit's own "Generar PDF → ⬇ Descargar" two-click, so it is not even a UX
change.

### 1.9 What stays untouched

`wizard/state.py`, `wizard/common.py`, `wizard/grid_zero.py`, `wizard/off_grid.py`,
`wizard/hybrid.py` and `pages/*` stay on this branch, unmodified beyond Step 0's reconciliation,
for the whole phase — they are the porting reference and the only way to diff behaviour. Their
deletion is Step 10's decision, not an earlier convenience. The one exception is the two extractions
named above (`_estimate_daytime_fraction_ai` → `ai/`, the `go.Figure` builders → `webapp/figures.py`);
both are *moves* with the Streamlit modules re-importing from the new home, so `main`'s behaviour is
unchanged and the diff stays reviewable.

### 1.10 Do-not-drop checklist — the things a port loses silently

This list is the acceptance criteria for Step 10 and should be re-read at every step boundary.

**Phase 5 "beyond the original spec" (`PHASES.md` L320–327) — non-negotiable, these changed how the
tool sizes systems:**

1. **Taxonomy-driven load profile.** 5 categories, `classify_load_category()` run at *import* time
   so the engineer sees and can correct the category immediately; the `(Automático)` option;
   per-line **Horas/día** and **Factor demanda (%)** overrides with the exact
   `user_confirmed`-vs-changed rule in `wizard/off_grid.py` L466–484 (getting this wrong produces
   two opposite bugs, both documented there); the `default_demand_factor_pct()` fallback for drafts
   saved before v3; the diversified total and its `diversified_used_downstream` caption switch.
2. **Real day-by-day battery SoC simulation.** `simulate_battery_soc()` over the PVGIS *daily*
   series drives the reliability scenarios — `min_soc_actual_pct`, `days_full_pct`,
   `unmet_load_days`, longest low-SoC streak. Never substitute the flat `discharge_pct`.
   Includes the lazy backfill in `wizard/off_grid.py` L937–946 that fetches the daily series for
   drafts created before it existed.
3. **Solar-utilization / curtailment metric**, in all three places it appears: Step 6's
   "Aprovechamiento de generación solar" stacked bar, Step 8's summary KV, and the PDF's
   `DETALLES TÉCNICOS` column. Grid Zero derives it from the AI daytime fraction; Off-Grid from the
   real simulation. Both must survive.

**Audit-trail / provenance fields that are easy to drop because nothing crashes without them:**

4. `scratch.s5.applied_source_meta` — the "📊 Fuente: Factura CNFL · Ene 2025 – Dic 2025" badge,
   including the `· editada` suffix appended when a human edits on top of an imported source.
5. `_CONFIDENCE_BADGES` per profile line + the "⚠️ N línea(s) usan un estimado genérico — revísalas
   antes de continuar" warning.
6. `equipment.daytime_fraction_note` — persisted precisely because the transient AI note wasn't
   serialised (`wizard/grid_zero.py` L1283–1286).
7. `equipment.scenarios` / `equipment.array_scenarios` — the **full** scenario set is stored, not
   just the chosen one. A later reviewer needs to see what was rejected.
8. `equipment.mppt_scenario` / `array_scenario` label, **including `"M"` for manual**.
9. `consumption.loads_display` — keeps the `Categoría` column round-trippable; distinct from
   `consumption.loads`.

**MPPT / scenario selection UX (Grid Zero A/B/C/M):**

10. Three projection cards + an inline `● / ○` selector button per card; invalid scenarios render
    greyed with "fuera de límites" and no button.
11. `equip_key` reset: changing panel or inverter clears scenarios, manual mode and selection
    (`wizard/grid_zero.py` L728–734). Off-Grid's equivalent keys on panel + charge controller +
    battery (`wizard/off_grid.py` L978–982).
12. The "all three scenarios exceed daytime consumption" warning with its computed optimal kW.
13. Default selection logic `valid_labels[min(1, len(valid_labels)-1)]` — i.e. B when available.
14. Manual mode: live Voc/Vmp/Imax validation rows, chips, its own projection card, and the rule
    that it can only be *selected* when `within_limits`.
15. "Siguiente" disabled unless a valid auto scenario or a valid manual design exists.

**Off-Grid / Hybrid specifics:**

16. Scenario tiers 1/2/3 with their SoC targets, **and** the switch to
    `_HYBRID_RELIABILITY_SCENARIO_DEFS` when `consumption.grid_connected` — with the explanatory
    caption about AC-coupled surplus not being wasted.
17. Split-phase check + warning + autotransformer note; `inverter_qty` doubling and the fact that
    Step 7 must prefer `equipment.inverter_qty` over re-deriving it.
18. `compute_ac_breaker_summary()` electrical summary section; `_MAX_CHARGE_CONTROLLERS = 4`.
19. Hybrid: `grid_connected` checkbox, the utility/tariff block, `panel_scope` primary/secondary,
    the main-panel block in **both** `bill` and `loads` modes (a second full loads table *and* a
    second demand-profile block), and the AC-coupling note auto-appended to the intro text once.

**Lifecycle and money:**

20. `STATUS_TRANSITIONS` as a directed map (no free-form status editing), and `promote_prospect()`
    firing on `won`.
21. Lock (+ optional version note) → immutable; "Nueva versión" copies the blob and resets to step 1;
    "Marcar como enviada".
22. `format_quote_number()` everywhere a quote number is shown, including the `-v2` suffix.
23. Interconnection-permit USD from Step 5 overriding that line item's unit cost in Step 7.
24. Service defaults filtered by `system_types` — this is what excludes the interconnection permit
    from a true Off-Grid quote.
25. `_refresh_prices()` touching **only** `unit_cost`, never qty/IVA/custom rows, and reporting how
    many changed.
26. The zero-export disclaimer: `new_bill` is energy + access charge only — no bomberos, alumbrado,
    IVA or Generación Distribuida. It must ride along wherever that number is shown.

---

## 2. Build steps

Each step is a vertical slice ending in something runnable plus a validation you can execute.
**Do not start step N+1 until step N's validation passes.**

---

### Step 0 — Reconcile the shared Python layer with `main` (blocking, ~half a day)

**Build**
- `git diff main..main_jinja -- wizard/state.py proposals/generator.py calculations/pvgis.py
  wizard/grid_zero.py wizard/off_grid.py` and take `main`'s side on all five (`main` is the source
  of truth for behaviour, §0.2). Specifically: bring across `get_asset_b64()` / `save_asset()` /
  `_ASSET_FILENAMES`, `main`'s never-blanking `save_company_info()`, and the
  Storage-backed asset sourcing in `_build_context()` / `_build_context_off_grid()`.
- Un-stub Admin → Ajustes' logo/signature upload now that its dependency exists: remove the
  apology notes in `webapp/blueprints/admin.py` (docstring), `webapp/blueprints/admin_settings.py`
  and `webapp/templates/admin/_ajustes.html` L53, and wire the upload with
  `request.files` → `save_asset(kind, file.read())`, preview via `get_asset_b64(kind)`.
- Check `save_company_info()`'s **call sites in `admin_settings.py`** still behave — the signature
  is compatible but the semantics change (empty fields are now ignored rather than blanking).

**Validate**
- `python -c "import proposals.generator, wizard.state"` clean in `main_jinja`'s venv.
- Generate all three sample PDFs (`MARIA_JOSE_DATA`, `JORGE_RAMIREZ_DATA`, `HYBRID_DATA`) and
  confirm the **uploaded** logo/signature/isotipo appear — not the bundled ones.
- Upload a new signature in Admin → Ajustes, regenerate, confirm it changed.
- `git diff main..main_jinja -- calculations/ ai/ proposals/ wizard/` now shows nothing outside
  files this phase deliberately owns.

---

### Step 1 — Proposals list (read-only) + the sample-PDF harness

**Build**
- `webapp/blueprints/proposals.py` registered in `create_app()`; remove `"proposals"` from
  `dashboard.STUBS` and point `base.html`'s nav at `proposals.index`.
- `webapp/templates/proposals/page.html` + `_list.html`: search box + status pills
  (`Todas/Borrador/Enviada/Ganada/Perdida` ← `FILTER_MAP`), table with the same seven columns
  (status dot, quote number, client, system type, total, date, badge). Use `.dtable` / `.dtable-wrap`
  and a `_badge()`/`_pill()` Jinja macro carrying `STATUS_BADGE`'s colours.
- Filter + search post to `GET /cotizaciones/filtrar` with `hx-target="#plist"`,
  `hx-trigger="keyup changed delay:300ms"` on the search input — same idiom as
  `admin.sub_view`'s panel swap.
- `GET /cotizaciones/dev/pdf-muestra`: port `_render_test_pdf_panel()` — a system-type selector and
  ES/EN generate buttons hitting `generate_pdf(SAMPLE, type, lang)`. Small, and it is the fastest
  smoke test for the PDF engine for the rest of the phase.

**Validate**
- Side by side with the Streamlit list against the same Supabase: identical row count, identical
  quote numbers (including `-vN` suffixes), identical totals and badges for every proposal.
- Search and each filter return the same sets as Streamlit's.
- All six sample PDFs (3 types × 2 languages) download and open.

---

### Step 2 — Detail panel + version lifecycle

**Build**
- `GET /<pid>/detalle` → `proposals/_detail.html`, swapped inline under the clicked row
  (`hx-target="#det-<pid>"`), reproducing `_render_detail_panel()`: header line, status-transition
  buttons from `STATUS_TRANSITIONS`, Continuar / Nueva versión, and the versions list.
- `POST /<pid>/estado` — transition + `promote_prospect()` on `won` (with the same
  "ganada pero no se pudo promover" fallback message).
- Per-version row (`_version_row.html`): quote number, Bloqueada/Borrador + Enviada pills, total,
  date, note, and the PDF affordance — signed URL when `pdf_path` exists, otherwise a
  "Generar PDF" POST (§1.8).
- `POST /<pid>/v/<vid>/nueva-version` → `create_version(pid, data)` → 303 to
  `/cotizaciones/asistente/<new_vid>/paso/1`.
- `POST /<pid>/v/<vid>/enviada` → `mark_version_sent()`.
- "Mover a Proyecto" on won proposals: render `get_project_by_proposal()`'s result as a
  "Ver proyecto →" link when one exists, otherwise a disabled button with the note from §0.3 Q4.

**Validate**
- On a real existing multi-version proposal: every version listed with the same badges/totals as
  Streamlit; locking state correct; "Continuar" disabled exactly when the current version is locked.
- Generate a PDF from the list for a **Grid Zero** and an **Off-Grid** version and byte-compare
  against the PDF Streamlit's list produces for the same version. (Both go through
  `build_from_wizard_blob()`, so they must match exactly. Any difference is a bug in this step, not
  in the generator.)
- Drive a proposal `draft → active → won` and confirm the prospect moved to Clientes.

---

### Step 3 — Wizard shell, state engine, and steps 1–3 (Cliente / Tipo e idioma / Sitio + PVGIS)

**Build**
- `wizard/draft.py` per §1.1, with a header comment carrying the blob-compatibility constraint and
  the last-write-wins note.
- `MAX_CONTENT_LENGTH = 25 MB` and a 413 handler. (`SECRET_KEY`/`flask.session` is **not** needed
  for this step — §0.3 Q6's only planned use, the pre-row steps 1–2 carry, was removed when Q3
  moved row creation to step 1's own POST. Skip it unless a later step introduces a real need.)
- `webapp/blueprints/wizard.py` + `webapp/templates/wizard/shell.html`: breadcrumb (✓ / current /
  greyed, labels switching on `system_type` exactly as `STEP_LABELS_GRID_ZERO` /
  `STEP_LABELS_OFF_GRID` do), header title logic, step guard, locked-version guard.
- **Step 1 Cliente** — live client search (`search_clients`, `hx-trigger="keyup changed delay:300ms"`,
  results as a `<select>`/list that fills the form fields), previous-proposals selector
  (`list_proposals_by_client` → picking one loads that draft and 303s straight into its wizard),
  the six fields, NISE default `"N/A"`, and the prospect-vs-client rule from
  `pages/02_new_proposal.py` L141–166. **Its POST creates the proposal row and burns the quote
  number immediately** (§0.3 Q3, revised from the original Streamlit-matching plan — this is a
  deliberate simplification Oscar signed off on, not a bug): `create_prospect()`/`upsert_client()`
  + `create_proposal()` run here, writing `client` and a default `meta` (system type/language not
  yet chosen) into a fresh blob, then 303s to `paso/2`. No `flask.session` carry.
- **Step 2 Tipo e idioma** — three system types × two languages; its POST patches `meta` (system
  type + language) into the row step 1 already created.
- **Step 3 Sitio e irradiancia** — city/province prefilled from the client's `location`, the manual
  lat/lon override, `POST …/paso/3/pvgis` running `geocode_cr()` → `fetch_irradiance()` → and
  `fetch_daily_series()` **only for off_grid/hybrid** (`wizard/common.py` L297–298 — Grid Zero
  deliberately skips the second call), two metric cards, and the first Plotly chart.
- `webapp/figures.py` seeded with `irradiance_monthly_fig()` and `monthly_coverage_fig()` (the
  latter moved from `wizard/common.py`, which now imports it back).
- Vendor `plotly-basic.min.js`; load it from `base.html`.

**Validate**
- **Blob round-trip, both directions** (the gate for §1.1): create a draft through Flask steps 1–3,
  open it in the Streamlit app on `main` → client, meta and site all populate correctly and the
  wizard resumes at step 3. Then advance it one step in Streamlit, reopen in Flask → the seven
  durable sections are still correct. **Confirmed empirically: `scratch` does NOT survive this
  round-trip** — Streamlit's `autosave()` full-replaces the blob and drops it. See §1.1's
  "Confirmed asymmetry" note. Not a Step 3 defect (nothing writes `scratch` yet); a real
  consideration for Step 4 onward.
- Loading `GET /nueva` and abandoning it without submitting the form creates **no** proposal row.
  Submitting step 1's form **does** create the row and burn a quote number immediately, even if the
  wizard is then abandoned before step 2 completes — this is the accepted trade-off from §0.3 Q3,
  not a bug to fix.
- PVGIS: first fetch hits the network, second fetch for the same lat/lon returns from the
  `app_settings` cache; the monthly chart renders inside an htmx-swapped fragment (§1.6 gotcha a);
  Bar renders under `plotly-basic` (gotcha b).
- Browser refresh mid-step, and the back button, both land somewhere sane.
- Requesting `paso/6` on a draft at `step_reached = 3` redirects to `paso/3`.

---

### Step 4 — Grid Zero steps 4–5 (Distribuidora, Consumo)

**Build**
- **Step 4 Distribuidora** — distributor `<select>` (`hx-get` repopulating the tariff `<select>` on
  change), NISE prefilled from the client, the fixed-charge caption **with its full disclaimer text**
  (§1.10 item 26), and the tariff-rate fields carried into `utility` so Step 5 needs no extra DB call.
- **Step 5 Consumo** — the three-source selector; the bill-upload block (multi-file, extract →
  preview table → "Aplicar al historial de 12 meses" running `build_12_month_grid()`), the loads
  block (tablero upload + editable loads table + "Aplicar a 12 meses" running
  `estimate_loads_12_months_ai()`), the overwrite warning when switching sources, the source badge,
  the editable 12-month table with auto-recalculated `bill_crc` (§1.5), the two metric cards, the
  consumption bar chart, and the interconnection-permit USD field.

**Validate**
- **María José: avg 1,475 kWh/mes, avg bill ₡157,874** after entering her 12 months.
- Upload a real CNFL or ICE bill PDF → extracted months match the bill; "Aplicar" fills the missing
  months and computes `bill_crc` from the Step 4 tariff.
- Edit one month's kWh by hand → that month's Factura recomputes and the badge gains `· editada`.
- Switch source bill → loads with data present → the overwrite warning appears before anything is
  replaced.
- Open a second browser tab during the ~30 s bill extraction and confirm the app still responds
  (the threaded-dev-server check, §1.7).
- Reload the page mid-step: extracted history and applied months are still there (they are in
  `scratch`, not in a session).

---

### Step 5 — Grid Zero step 6 (Equipos: MPPT A/B/C/M)

The single densest screen in the wizard. Port it as a whole; do not ship a partial version.

**Build**
- Panel / inverter / monitoring selectors with their spec cards; `equip_key` reset (§1.10 item 11).
- `POST …/paso/6/mppt/calcular` → `ai/daytime_fraction.py` (moved, §1.7) → `validate_string_design()`
  → `scratch.s6.scenarios`; the scenario table and the three projection cards with
  `_scenario_projection()` per card.
- `POST …/paso/6/escenario/<label>` and `POST …/paso/6/manual` for selection;
  `POST …/paso/6/manual/validar` (change-triggered) re-running `check_design()` for the live
  Voc/Vmp/Imax rows and chips.
- The chosen-config block: Validación del diseño banner + three param rows, Margen de diseño bar
  chart, Dimensionamiento chips + metric cards, Generación vs. consumo bars, Estadísticas
  (Cobertura mensual estimada, Aprovechamiento de generación solar), and the saturation warning.
- Next persists `equipment` with **every** key `wizard/grid_zero.py` L1274–1289 writes — including
  `scenarios`, `projection`, `daytime_fraction_note`, and `mppt_scenario` = `"M"` in manual mode.

**Validate**
- **María José: generation 1,262 kWh/mes** for the selected configuration.
- **Blob diff.** Run the same client/site/utility/consumption inputs through the Streamlit wizard
  and through Flask, then diff `proposal_versions.data["equipment"]` key-for-key. They must be
  equal (floating-point equal, not "close"). *This is the strongest gate in the plan — a PDF-level
  check would hide a wrong intermediate that happens not to reach the PDF.*
- Change the inverter → scenarios, manual mode and selection all clear.
- Force an out-of-limits manual design → it cannot be selected and "Siguiente" stays disabled.
- Deliberately oversize the array → the saturation warning appears with a sane optimal kW, and
  "Aprovechamiento solar" drops below 50 % with its warning.

---

### Step 6 — Grid Zero steps 7–8 (Costos, Revisión, PDF, lock)

**Build**
- **Step 7 Costos** — line items seeded from equipment + `list_service_defaults()` (filtered by
  `system_types`), live prices via `_get_current_prices()`, the interconnection-permit override,
  the editable table with per-row IVA `<select>`, `🔄 Refrescar precios`, and the invoice-footer
  Subtotal / IVA / TOTAL / $/Wp block recomputed on `change` (§1.5).
- **Step 8 Revisión** — the sectioned summary panel (Técnico / Costos / Facturación estimada /
  Proyección financiera) as a real Jinja partial rather than a Python f-string wall; the 25-year
  cumulative cash-flow chart with its break-even marker; the intro-paragraph textarea with
  "Generar con IA"; PDF generate + download (§1.8); the lock block with version note; and the
  post-lock actions (Nueva versión / Marcar como enviada / Ir a cotizaciones).
- **First task of this step:** the `build_from_wizard_blob()` field diff described in §1.8. Extend
  that function for any field the wizard's inline dict carries and it doesn't. Do not branch.

**Validate**
- **María José, end to end: new bill ₡51,681, savings ₡106,192, Y1 $2,798, 25 yr $127,873,
  IRR 22.92 %, ROI 5.48, and the PDF matches the reference.**
- The PDF generated from Flask's Step 8 is **byte-identical** to the one the Streamlit list page
  produces from the same saved version (both now run through `build_from_wizard_blob()`; a
  difference means the extension in this step is wrong).
- `Refrescar precios` after changing a panel price in Admin updates only `unit_cost` and reports
  the count; custom rows, quantities and IVA are untouched.
- Lock → the wizard URL becomes unreachable (303 to the list) and "Nueva versión" produces an
  editable copy at step 1 whose blob equals the locked one.
- Downloaded filename follows `pdf_filename()`'s convention.

---

### Step 7 — Off-Grid steps 4–5 (Cargas, Perfil de demanda)

**Build**
- **Step 4** — autonomy slider (0.5–7.0, half-day steps), 120 V / split-phase selector, and the
  reusable loads block: catálogo multiselect + "+ Agregar", tablero image/PDF import, pasted-text
  import, and the resulting editable table with the `Categoría` `<select>`. Every import method
  **appends** (never replaces) and runs `classify_load_category()` at import time (§1.10 item 1).
  Keep the block parameterised by a `scratch` key prefix — Hybrid renders it twice (Step 9).
- **Step 5** — `build_load_profile()` on "Calcular perfil de consumo"; the confidence-badged table
  with editable `Horas/día` and `Factor demanda (%)`; "Recalcular con cambios" implementing the
  `user_confirmed`-vs-changed override rule **exactly** as `wizard/off_grid.py` L466–484 does; the
  generic-estimate warning; the total + diversified-total metric card with its
  `diversified_used_downstream` caption switch; the category donut; and the illustrative hourly
  stack behind its own button and its "⚠️ Ilustrativo únicamente" caption.
- Same `_render_demand_profile_block()` parameterisation — Hybrid renders it twice.

**Validate**
- Jorge Ramírez's load list reproduces **6.38 kWh/día**.
- Import via all three methods in sequence → rows accumulate, none are lost, and each row lands in
  a plausible category rather than `(Automático)`.
- Edit `Horas/día` on one line → Recalcular → that line flips to "✅ Confirmado por cliente" and
  keeps its override across a **second** Recalcular where nothing was retyped (the documented
  double-bug, §1.10 item 1).
- Reload the page after calculating: the profile is still there.
- Category donut totals equal the table's `kWh/día` sum.

---

### Step 8 — Off-Grid step 6 (Equipos + reliability scenarios) and steps 7–8

**Build**
- Panel / hybrid-inverter / battery / charge-controller / monitoring selectors with spec cards;
  split-phase check and warning; the daily-series lazy backfill (§1.10 item 2).
- `generate_reliability_scenarios()` → the scenario table (all 20-odd columns) and the three
  projection cards with their reliability lines; selection + manual mode with a battery-count
  override; `w6og_equip_key`-equivalent reset.
- Validación del diseño using `min_soc_actual_pct` from the simulation (**not** `discharge_pct`);
  Margen de diseño; **Resumen eléctrico — carga y protecciones** from
  `compute_ac_breaker_summary()`; Dimensionamiento; Estadísticas (Cobertura mensual, Aprovechamiento
  solar via `_og_monthly_coverage_and_sim()`, Cobertura estacional, Flujo de energía).
- Steps 7–8 for Off-Grid: the line-item set including battery bank, charge controllers, mounting
  structure and `system_types`-filtered services; the Off-Grid summary panel (Técnico / Generación y
  autonomía / Costos, with `Aprovechamiento solar` from the simulation); PDF + lock as in Step 6.
- `_og_monthly_coverage_and_sim()` must stay **one** implementation shared by Step 6's preview,
  Step 8's KV and the PDF's chart — its docstring says exactly why.

**Validate**
- **Jorge Ramírez: 5.0 kW, 16 m², 6.38 kWh/día, 9.60 kWh battery @10 h, 66.46 % discharge,
  $10,320 total, $2.08/Wp; PDF matches the reference.**
- Blob diff of `equipment` against the Streamlit wizard for identical inputs, as in Step 5.
- The Off-Grid quote contains **no** interconnection-permit line (the `system_types` filter).
- 120/240 V selected with a single-phase-capable inverter → split-phase warning and
  `inverter_qty = 2`, and Step 7's inverter line quantity is 2.
- `Aprovechamiento solar` in Step 6, Step 8 and the PDF are the same number.

---

### Step 9 — Hybrid (steps 4–5; 6–8 delegate)

**Build**
- Step 4: `grid_connected` checkbox, the distributor/tariff block when connected, the critical-loads
  block, the `panel_scope` primary/secondary radio, and — when secondary — the bordered main-panel
  container in **both** modes (`bill`: avg kWh/mes + estimated current bill; `loads`: a second full
  loads block under the `mp` scratch prefix).
- Step 5: the critical-loads profile block with `diversified_used_downstream=True`, plus the
  main-panel profile block (category chart on, hourly chart off) when in `loads` mode;
  `_build_step5_result()`'s `avg_kwh_month` / `avg_kwh_month_diversified` derivation.
- Steps 6–8 route to the Off-Grid modules, with the hybrid scenario-tier switch, the hybrid caption,
  `estimate_hybrid_savings_pct()` per card and at persist time, the "Facturación estimada" summary
  section, and the AC-coupling note appended once to the intro text.

**Validate**
- A hybrid draft with `grid_connected = true` uses `_HYBRID_RELIABILITY_SCENARIO_DEFS` (scenarios 2
  and 3 land on visibly larger arrays than the Off-Grid tiers would).
- `panel_scope = secondary` + `mode = loads` renders two genuinely independent loads tables and two
  independent profile blocks; editing one never touches the other.
- "Reducción de factura estimada" appears on the cards and in the Step 8 summary, and the hybrid PDF
  carries the AC-coupling note exactly once (generate twice; it must not duplicate).

---

### Step 10 — Cutover

**Build**
- Remove `"proposals"` from `dashboard.STUBS` (if anything remains) and sweep the nav.
- Walk the **entire §1.10 checklist** against the running app, item by item, and record the result
  in this document under a new "Built" section — the same way `PLAN_PHASE18.md` records its own
  Phase 2 outcome.
- Update `PHASES.md` and `CONTEXT.md` with the port's status and this document's path.
- Decide (with Oscar) the fate of `pages/01_proposals.py`, `pages/02_new_proposal.py`,
  `pages/02b_new_proposal_test.py` and the `wizard/*.py` Streamlit UI modules on this branch. They
  stay until this step (§1.9); deleting them is a deliberate, separate commit.

**Validate**
- One full Grid Zero quote and one full Off-Grid quote created from scratch in Flask, locked, and
  their PDFs compared against the two reference documents.
- Both reference number sets reproduced one final time end to end.
- Every item in §1.10 explicitly ticked or explicitly waived in writing.

---

## 3. Explicit non-goals

- **The 02b sandbox** (`pages/02b_new_proposal_test.py`, `wizard/design_scenarios_test.py`). Its own
  docstring calls it ephemeral and non-persisting; porting it would double the Step 6 surface for a
  tool that writes nothing.
- **Projects and Maintenance.** "Mover a Proyecto" gets a placeholder (§0.3 Q4) and nothing more.
- **Admin's remaining gap** — equipment datasheet AI extraction (`webapp/blueprints/admin.py`
  docstring L6–7). Step 0 closes the *asset-upload* half of that docstring's apology; the datasheet
  half belongs to an Admin phase.
- **Auth, multi-user, or any concurrency control.** Single internal operator (§1.1).
- **Any change to the calculation engines.** `calculations/*` is imported, never edited. If the port
  finds a genuine bug there, it is a separate commit on `main` first.
- **Changing the PDF templates** (`proposals/templates/*.html`). Byte-identical output is the goal.
- **Removing the Streamlit app.** `main` keeps running; `pages/*` survive on this branch until
  Step 10.

---

## 4. Risks and tradeoffs

**The biggest risk: numeric drift that no test catches.** The wizard's arithmetic is not in one
place — it is threaded through per-step context (tariff tiers loaded in Step 4 and reused in 5 and 6,
`avg_irradiance` derived in 6, `daytime_fraction` cached across reruns, `total_connected_load_kw`
summed from the profile). A port that rebuilds that context slightly differently produces numbers
that are *plausible* rather than *equal*, and a PDF-level check will not catch it because the PDF
shows rounded figures that agree. **The mitigation is structural, not procedural:** §1.3's one
`build_context(blob)` per step, plus the **blob-equality diffs against the Streamlit wizard at Steps
5 and 8** — comparing the persisted `equipment` dict key-for-key, not the rendered output. If a step
boundary can't produce an equal blob, stop and find out why; do not proceed and "check it in the PDF
later."

**`main` moving underneath the port.** Step 0 reconciles five drifted files once. The five-file
drift (§0.2) is what a few weeks of unsynchronised parallel work already produced, and it silently
disabled an Admin feature and changed which logo goes on every PDF. §0.3 Q1 asks for a freeze; if the
answer is no, add a `git diff main..main_jinja -- wizard/ calculations/ ai/ proposals/` check to
every step's validation.

**Losing the `st.data_editor` affordances.** Streamlit's grid gives free row add/delete, column
typing, and inline validation. The HTML replacement (§1.5) is more code and slightly worse UX for
bulk editing. Accepted deliberately: a JS grid library would be a third front-end paradigm alongside
Jinja and htmx, and this app's tables are small (12 rows, ~10 line items, a few dozen loads). The
`help=` → `title=` carry-through in §1.5 is the part most likely to be skipped and most costly to
lose — several of those strings are the only place a demand-factor or diversification rule is
explained to the engineer.

**Synchronous AI calls on a synchronous server.** A 40 s bill extraction holds a worker. Fine for one
user on a threaded dev server; it becomes a real problem the day this is deployed behind a single
gunicorn worker. Documented rather than solved: the upgrade path is a `jobs` row + htmx polling, and
§1.7 says why it isn't worth it yet.

**Converging on `build_from_wizard_blob()` (§1.8) is the right call *and* the riskiest single change
in the phase.** It removes a duplicated implementation that has already shipped two bugs — but it
also means Step 6 changes the code path that generates *every* PDF, including ones generated from the
Streamlit list on `main`. That is why the extension must be additive and why Step 6's gate is a
byte-comparison against the existing list-page output, not just "the PDF looks right."

**`scratch` grows the blob.** `scratch.s6.scenarios` holds three full scenario dicts; the Off-Grid
ones embed simulation summaries. Still kilobytes, well inside a JSONB column, and `equipment.scenarios`
already stores the same thing durably today. Worth a glance at row sizes after Step 8 all the same.
