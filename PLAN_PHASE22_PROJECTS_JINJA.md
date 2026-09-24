# Phase 22 — Proyectos: the projects list + project financial workspace, ported off Streamlit onto Flask/Jinja2/htmx, **plus Facturación and Pagos/ONVO built for real**

**Status:** ready for the coder agent. §0.4 Q3 was **decided by Oscar on 2026-09-21: build
Facturación and the Pagos/ONVO commission screen for real in this phase**, not as placeholders.
This document was revised against that decision — it is no longer a pure port. 7 open questions
remain in §0.4; one of them (Q8, which historical payments were genuinely ONVO) **blocks Step 0's
migration**, not the rest of the phase.
**Author:** architect agent, 2026-09-21 (revised same day for the Q3 scope change)
**Branch:** `main_jinja` (worktree `Claude-main_jinja`). `main` stays the Streamlit source of truth
for the ported surfaces and is **not modified by this phase**.
**Builds on:** `PLAN_PHASE20_PROPOSALS_JINJA.md` (Cotizaciones port, Steps 0–10 complete and
audited) and `PLAN_PHASE21_MAINTENANCE_JINJA.md` (Mantenimiento port, Steps 1–4 complete and
audited). This plan reuses those phases' blueprint/template/htmx conventions verbatim and invents
no new style. Where a rule here is unchanged, it says so and points at the section rather than
restating it.
**Spec sources — ported surfaces:** `pages/03_projects.py` (268 lines) and
`pages/04_project_detail.py` (649 lines, the actual shipped feature); `database/projects_db.py`
(671 lines); `calculations/project_finance.py`; `scripts/validate_phase6.py`.
**Spec sources — new construction (§1.10):** `REQUIREMENTS.md` §5.5 (Facturación) and §5.6
(Client payments / ONVO), and `PLAN_PHASE6.md` §1.4 (the ONVO decision) + Steps 7 and 8 (the
screens' designs *and their hand-computed reference numbers*, which become this phase's oracle for
code that has no Streamlit equivalent to compare against).
**Schema:** `database/schema.sql` L170–264, migrations `020_projects_extras.sql`,
`022_project_contract_iva.sql`, and **one new migration this phase must write, `048` (§1.10.3)**.
**Filename convention:** `22` confirmed as the next free number — existing plans are
`PLAN_PHASE6/13/14/15/16/17/18/19_FLEET_P3/20_PROPOSALS_JINJA/21_MAINTENANCE_JINJA.md`, and
`PHASES.md`'s phase table (L16–39) ends at row 21.

---

## Goal

**Proyectos stops being a stub — the last one in the app — and Phase 6 finally gets its last two
screens.** Oscar opens `/proyectos`, sees the same project list and status filter he sees in
Streamlit today, creates a manual project, opens a project, and works its financial workspace:
the Presupuesto dashboard (Ingresos / Pagos / Gastos por rubro / Utilidad), the five expense
ledgers, and the Mano de obra tab with worker advances. **"Mover a Proyecto" becomes real**,
replacing the disabled placeholder Phase 20 left in `proposals/_detail.html` L86–87. And the two
tabs that have read `Disponible en el siguiente paso.` since Phase 6 — **Facturación** and
**Pagos** — become working screens: an electronic-invoice line-item log with per-category totals
and a reconciliation line against the contract, and a client-payment screen with per-payment
Transferencia/ONVO classification, commission and IVA-on-commission breakdown, net-to-deposit, and
an explicit (never automatic) "record this commission as a Banco expense" action.

"Done" has two halves, because this phase has two kinds of work:

- **Ported surfaces** (list, detail header, Presupuesto, five ledgers, Mano de obra, promotion):
  for every project in the live database, the Flask page and the Streamlit page agree on **every
  money figure on every tab**, and every item in the §1.4 do-not-drop checklist survives.
- **New surfaces** (Facturación, Pagos/ONVO): there is no Streamlit page to compare against, so
  the oracle is **hand-computed reference numbers** — `PLAN_PHASE6.md` Step 7's invoice fixture
  and Step 8's ONVO fixture — asserted both as pure-function unit checks in
  `scripts/validate_phase6.py` **and** as a live end-to-end exercise on a QA project (§1.10.5).

`scripts/validate_phase6.py` is the numeric backbone throughout: it already covers `summarize()`
(Jorge Ramírez, the Oscar Pauly mixed-IVA case, the Equipo-expense case, the Cuadrilla labor case),
its own docstring instructs each build step to extend it, and this phase extends it with Step 7's
and Step 8's cases.

---

## 0. Confirmed context (do not re-derive)

### 0.1 Facts established by reading both checkouts

| Fact | Where |
|---|---|
| The ported feature is **two Streamlit pages**: a list (`pages/03_projects.py`) and a detail page with **nine `st.tabs`** (`pages/04_project_detail.py`). There is no wizard, no draft, no multi-step form, no autosave | both files |
| **Only two of the nine tabs' contents are cross-cutting**: Presupuesto (Ingresos, the whole Pagos block, Gastos por rubro, Utilidad) and Mano de obra. Five tabs share one renderer (`_render_expense_ledger`). **Two tabs — Facturación and Pagos — are literally `st.info("Disponible en el siguiente paso.")`**, which is why they are new construction here, not a port | L626–646 |
| Cross-rerun state is **one key**: `st.session_state["selected_project_id"]`, set by the list, the manual-create form and the proposals page's promotion block, read by the detail page. Everything else is a direct DB write followed by `st.rerun()` | L577; `03_projects.py` L204/264; `01_proposals.py` L445/574 |
| `calculations/project_finance.py` is **pure** — no `streamlit`, no `database` imports, deliberately so (docstring L5–8). `summarize()`, `labor_balance()` and `onvo_breakdown()` are reusable as-is | `calculations/project_finance.py` |
| `database/projects_db.py` is likewise Streamlit-free and already framework-agnostic — 43 functions covering every read and write both pages perform, **plus the complete, never-called CRUD for `project_invoice_items` and `project_extras`**, plus the promotion derivations and `get_project_bundle()` | whole file |
| **No staleness to reconcile.** `pages/03_projects.py`, `pages/04_project_detail.py`, `database/projects_db.py` and `calculations/project_finance.py` are identical between `main` and `main_jinja` (verified by reading/grepping both copies — same content at the same line numbers). **There is no port-side Step 0**; this phase's Step 0 is the ONVO data migration (§1.10.3), which is a different thing | both checkouts |
| `scripts/validate_phase6.py` exists, runs with no DB and no Streamlit, and asserts 19 reference figures across four fixtures. **This is a real oracle Phase 21 did not have**, and its docstring says to extend it per build step | `scripts/validate_phase6.py` L1–12 |
| Three tables carry **Postgres `GENERATED ALWAYS AS ... STORED` columns** — `project_expenses.total_with_iva`, `project_invoice_items.iva_amount`/`total_usd`, `project_extras.total_with_iva`. Including one in a write payload makes Postgres reject the **whole** statement. Every write in `projects_db.py` routes through `_clean()`, which strips them | `projects_db.py` L8–14, L29–33; `schema.sql` L202–259 |
| `projects.proposal_id` has a **partial unique index** (`WHERE proposal_id IS NOT NULL`) — one project per proposal, unlimited proposal-less manual projects | `schema.sql` L263–264 |
| **There is no project-delete path anywhere** — not in `projects_db.py`, not in either page. `PLAN_PHASE6.md` §3 made that an explicit non-goal. Removing a bad project requires SQL | grep of `delete.*project\b` |
| The Flask side **already reads projects in two places**: `webapp/blueprints/dashboard.py` L44–66 (active-project KPIs, via `list_projects()` + a `get_project_bundle()` + `summarize()` per project) and `webapp/blueprints/proposals.py` L277–309 (`get_project_by_proposal()` + a hardcoded `/proyectos/<id>` link). **`/proyectos/<id>` is therefore already a committed URL shape** | those files |
| `webapp/templates/proposals/_detail.html` L85–88 renders the disabled `Mover a Proyecto` span + the note `disponible cuando se migre Proyectos` — Phase 20 §0.3 Q4's placeholder. It is the **only** such placeholder in the tree (grepped for the phrase and for `get_project_by_proposal`) | that file |
| **No Supabase Storage, no PDF, no file upload, no AI call anywhere in this feature — including the two new screens.** `project_expenses.receipt_path` exists in the schema, is never written, and receipt upload was an explicit Phase 6 non-goal. Nothing here shares `proposals/generator.py`'s upload/accent/upsert code path, so Phase 20's fixes there neither help nor hurt this phase | grep of `storage`/`upload`/`receipt_path` |
| ⚠ **The "ONVO" in this phase is not the ONVO integration in `CONTEXT.md`.** Phase 16's ONVO Pay work (`vrm_api/onvo.py`, webhooks, subscriptions) belongs to **VRM Monitor**, a different product in a different repo. This phase makes **no API calls to ONVO** and touches none of that code. Here "ONVO" is bookkeeping: a commission percentage the operator types into a form | `CONTEXT.md` L1342–1401 vs `calculations/project_finance.py` L156–176 |
| **No charts.** Nothing renders a Plotly figure or an SVG. `webapp/figures.py` and the vendored `plotly-basic.min.js` are not touched | both pages, both new screens |
| Established webapp conventions (unchanged from Phase 20 §1.2/§1.4 and Phase 21 §0.1): one blueprint module owns routing + tab dispatch, one module per section registered via `register(bp)`, lazy `from database... import` **inside** view functions, `request.headers.get("HX-Request")` for partial-vs-page, `hx-target="#subpanel"` + `hx-push-url="true"` for tab swaps, POSTs ending in `redirect(url_for(...), code=303)`, per-partial `<style>` blocks, global `#flash` toast on any non-GET, `admin/_error.html` reused for every panel-level error | `webapp/blueprints/maintenance.py`, `webapp/templates/maintenance/page.html`, `webapp/templates/base.html` |
| The editable-table vocabulary already exists: `webapp/wizard_steps/common.py:parse_rows(form, prefix, fields)` (the `st.data_editor` replacement, Phase 20 §1.5) and `webapp/templates/wizard/_s7_costos.html` (whole-fragment re-render on `change delay:400ms`, `+ Fila`, per-row `✕`) | those files |
| `webapp/__init__.py` has **no `SECRET_KEY`** — `flask.session` is unusable. This phase does not need it (§1.2) | `webapp/__init__.py` L12–16 |
| `base.html` L24 points Proyectos at `dashboard.stub(section='projects')`; `dashboard.STUBS` is now `{"projects": "Proyectos"}` — **the last stub** | `base.html`, `dashboard.py` L24–26 |
| Highest migration in the tree is `047`; `043`/`044` do not exist (numbers consumed elsewhere). **`048` is the next free number** | `database/migrations/` |

### 0.2 What actually shipped of Phase 6: Steps 1–5, not 1–9 — and what this phase now does about it

`PHASES.md` L24 says Phase 6 is **"✅ Complete."** It is not. Reading the code:

| Phase 6 step | Shipped? | Evidence | This phase |
|---|---|---|---|
| Step 1 — schema + migration 020 | ✅ | `schema.sql` L170–264, `migrations/020_projects_extras.sql` | — |
| Step 2 — `projects_db.py`, promotion, manual creation, list | ✅ | whole module; `01_proposals.py:_render_promotion_block()`; `03_projects.py` | ported (Steps 1, 2, 9) |
| Step 3 — `project_finance.py`, Presupuesto, Pagos block | ✅ | `project_finance.py`; `_render_presupuesto_tab()` L103–267 | ported (Steps 3, 4) |
| Step 4 — five expense ledgers | ✅ | `_render_expense_ledger()` L290–396 — **except** §1.7's "dim the budget-skeleton rows", which `st.data_editor` could not do | ported (Step 5) + §0.4 Q5's dimming |
| Step 5 — Mano de obra + adelantos | ✅ | `_render_labor_tab()` L401–566, plus `delete_advance()` | ported (Step 6) |
| **Step 6 — INGRESOS extras editor** | ❌ **never built** | Presupuesto shows a **read-only** "Extras (órdenes adicionales)" card (L117, L131–136). `add_extra`/`update_extra`/`delete_extra` have **zero call sites**. Every project's extras list is empty in practice | ⚠ **still out of scope** (§3) — Oscar's Q3 decision named Facturación and Pagos, not this |
| **Step 7 — Facturación** | ❌ **never built** | Tab 7 renders `st.info("Disponible en el siguiente paso.")`. `project_invoice_items` CRUD exists with zero call sites | ✅ **built for real this phase** (§1.10, Step 7) |
| **Step 8 — Pagos / ONVO tab** | ❌ **never built** | Tab 8 renders the same placeholder. `onvo_breakdown()` is pure, correct, and has **zero call sites outside `scripts/validate_phase6.py`**. The payment tracking that *does* exist is the Pagos **block inside Presupuesto**, with no método toggle, no commission, no IVA-on-commission, no "por depositar" | ✅ **built for real this phase** (§1.10, Steps 0 + 8) |
| **Step 9 — list polish, `app.py` wiring, docs** | 🔶 partial | `app.py`'s "Proyectos activos" card was wired (Flask `dashboard.py` L44–66 ports it). The list has **no search box** and **no per-project financial columns** | ⚠ out of scope (§3) |

**Consequence, stated once here so no step re-litigates it:** this phase is a **port plus two new
screens**. The two new screens have no Streamlit behaviour to diff against, so §1.10 gives them
their own design basis, their own must-build checklist items (§1.4 items 35–50) and their own
oracle. Everything else follows the Phase 20/21 porting discipline unchanged.

### 0.3 Data-volume and query-shape reality

- The list is **one query** (`list_projects(status=…)`, ordered `created_at desc`). No N+1.
- The detail page is **one `get_project_bundle()` per render = 6 queries** (project, payments,
  expenses, labor, invoice_items, extras — note it **already fetches `invoice_items`**, so
  Facturación costs zero extra queries). Streamlit pays this once per rerun and renders all nine
  tabs from it; Flask pays it once per tab request.
- The already-shipped Flask **dashboard has a real N+1**: `get_project_bundle()` + `summarize()`
  *per active project* (`dashboard.py` L52–60), i.e. `1 + 6N` queries on the landing page. It is
  pre-existing, out of scope, and named here only so nobody "fixes" it mid-phase or copies the
  shape into the list page (§1.5).
- **Unknown, and the first thing Step 1 must establish:** how many real projects exist, and how
  many have payments / expenses / labor / non-zero `contract_iva_usd`. Phase 21 could baseline
  "16 properties, 28 sites" from the start; the equivalent baseline here is unmeasured. Step 0's
  audit produces the payment-row half of it before any UI exists (§1.10.3).

### 0.4 Decisions and open questions

1. **URL prefix — decided by precedent, not open.** `/proyectos`, detail at `/proyectos/<pid>`.
   Not a free choice: `webapp/blueprints/proposals.py` L309 already hardcodes
   `f"/proyectos/{project['id']}"` and its docstring L13–14 documents it. Match it, then replace the
   hardcode with `url_for()` in Step 9.
2. **Nav placement.** Top-level, in the slot `base.html` L24 already reserves. Unchanged.
3. **Facturación and Pagos/ONVO — DECIDED 2026-09-21 by Oscar: build them for real.** Not
   placeholder parity. They are Phase 6 Steps 7 and 8, designed but never implemented; this phase
   implements them directly in Flask, and `pages/04_project_detail.py` keeps its two placeholders
   (it is not modified — §3). The full design basis, schema verdict, migration and oracle are
   §1.10. **The INGRESOS extras editor (Phase 6 Step 6) was not part of this decision and stays out
   of scope** — Facturación's reconciliation line reads `project_extras` and works correctly with
   an empty list.
4. **Ledger edit model.** Streamlit uses `st.data_editor` + one "Guardar cambios" reading the
   widget's `added_rows`/`edited_rows`/`deleted_rows` deltas. HTML has no such widget.
   *Decision (§1.6): one `<form>` per ledger with an explicit "Guardar cambios" that **updates rows
   by hidden `id` and inserts rows with no `id`** — and **deletion is never inferred from a row's
   absence**; it is its own explicit per-row `✕` → inline confirm → `delete_expense()`. Rationale in
   §1.6 and §4.* The same rule governs the new Facturación editor.
5. **Budget-skeleton rows — implement `PLAN_PHASE6.md` §1.7's dimming?** A promoted project's
   ledgers open full of `amount_usd = 0, budgeted_usd > 0` placeholder rows. The spec asked for them
   to render dimmed with a small `presupuesto` pill; `st.data_editor` could not do it, so it never
   shipped. *Working assumption: **yes** — plain HTML can, the spec asked for it, and it removes a
   genuinely confusing surface. Disclosed deviation, flagged ⚠ in §1.4 item 24.*
6. **Manual-project client typeahead.** *Working assumption: port as an htmx search fragment
   modelled on `wizard/_s1_search_results.html`, same behaviour, same copy. `client_id` is still
   accepted and still **not stored** (there is no FK — `projects_db.py` L304–316).*
7. **Fate of `pages/03_projects.py` / `pages/04_project_detail.py`** after cutover — same deferred
   decision Phase 20 §1.9 and Phase 21 §0.4 Q6 made. *Working assumption: they stay, unmodified;
   deletion is a separate, deliberate commit made with Oscar.*
8. ⚠ **OPEN, AND IT BLOCKS STEP 0's `UPDATE`: were any of Oscar's historical client payments
   actually received through ONVO card (and therefore really did lose 2.4% + IVA), or were they all
   bank transfers?** Every existing `project_payments` row currently carries
   `onvo_commission_pct = 0.024` purely because that is the column default — nothing ever set it,
   nothing ever read it (§1.10.3). The moment Step 8's UI reads that column, every historical
   payment starts asserting a commission that probably never happened. *Working assumption (and the
   recommendation): **all historical payments are transfers** — Step 0 backfills them to
   `0 / 0`, i.e. "no commission", which is the only claim the data actually supports, and Oscar
   re-marks any genuinely-ONVO payment through the new UI afterwards, which is a 10-second edit per
   payment.* Step 0's read-only audit runs first and stops if the data contradicts this. Do not run
   the `UPDATE` half of migration 048 without Oscar's yes.

---

## 1. Resolved decisions (these are not open questions)

### 1.1 Drift table — `PHASES.md` / `PLAN_PHASE6.md` versus what is in the repo

§0.2 covers the big one (Steps 6–8 never built). The rest:

| Spec says | What actually shipped |
|---|---|
| `PHASES.md` L24: Phase 6 "✅ Complete" | Steps 1–5 of 9 complete, Step 9 partial, Steps 6–8 absent. The row was corrected once (2026-09-02, from "Not started") and overshot |
| `PLAN_PHASE6.md` §1.5 original: `contract_usd` is an ex-IVA base with a blended `contract_iva_rate` | **Superseded in-file 2026-08-17.** `contract_usd` is the FULL quoted total; `contract_iva_rate` is vestigial and always 0; `contract_iva_usd` (migration 022) carries the embedded IVA. Both `derive_contract_terms()` and `summarize()` implement the revised rule. **Read §1.5's revision, not its struck original** |
| §1.4: `add_payment()`/`update_payment()` persist `net_deposited`; the payments UI has a método toggle | Neither exists — **this phase builds both** (§1.10). Meanwhile `project_payments.onvo_commission_pct` is `NOT NULL DEFAULT 0.024`, `onvo_iva_pct` and `net_deposited` are NULL on every row, and nothing reads any of the three (§1.10.3) |
| §1.7: ledger budget-skeleton rows render dimmed with a `presupuesto` pill | Never built (§0.4 Q5) |
| §6: the detail header shows a "Ver propuesta" link when `proposal_id` is set | Shipped instead as a plain caption: `Promovido desde cotización — proposal_id {uuid}` (L621–622). A raw uuid, not a link |
| §3 non-goal "no project deletion from the UI" | Held. No delete path exists, in the UI or the DB layer |
| Step 9: list cards with recibido / gastos / utilidad, plus a client search box | Not built. The list is four columns and a status filter |
| `mark_payment_paid(payment_id, paid_date, bank_account)` | Exists, **zero call sites** — the UI calls `update_payment(paid=…, paid_date=…, bank_account=…)` instead, because the checkbox can also *un*-mark a payment |
| `CONTEXT.md` L483 | Accurately describes the module sizes, but implies the whole ledger/invoice/extras surface is user-reachable, and says nothing about Facturación/ONVO being unbuilt |

### 1.2 State management: one session key, one form-round-trip, and no draft machinery

Streamlit's projects pages hold exactly one piece of cross-page state:
`st.session_state["selected_project_id"]`. **The Flask port replaces it with a URL** —
`/proyectos/<pid>` *is* the selection — exactly as Phase 21 §1.2 replaced
`maint_selected_property`. Consequences: no `flask.session`, **no `SECRET_KEY`**, no
`wizard/draft.py`-style module (**do not create one**), no blob-compatibility constraint with
Streamlit, and a bookmarkable, back-button-correct detail page.

| Streamlit state | Flask equivalent |
|---|---|
| `p3_new_open` (new-project form toggle) | `hx-get` of a form fragment into an empty target div; "Cancelar" swaps it back to empty |
| `p3_new_client_query` / `p3_new_client_choice` | htmx search fragment, `hx-trigger="keyup changed delay:300ms"`, same pattern as `wizard/_s1_search_results.html` |
| `st.tabs` (nine tabs) | nine URLs under `/proyectos/<pid>/…`, dispatched like `maintenance.py`'s `SECTIONS`/`SECTION_ORDER` |
| Every `st.expander` | plain `<details>` blocks, always in the DOM, no server state |
| Per-row payment widgets `pf_{project}_{payment}_{field}` | one small `<form>` per payment row |
| Per-worker widgets `mod_{project}_{labor}_…` | one `<form>` per worker card / per advance action |

**The one genuinely non-trivial case, and the only place in this phase where an unsaved multi-row
edit must survive a server round trip:** the editable grids — the five expense ledgers, the
promotion budget/schedule tables, and (new) the Facturación line-item table. Streamlit's
`st.data_editor` keeps typed-but-unsaved edits in widget state across reruns; in Flask they live in
the browser DOM, which is fine until something triggers a round trip mid-edit (`+ Fila`, `✕`, a
rate change that must re-total). **Rule: every such handler re-renders the fragment from the
*posted form values*, not from the database** — the context builder takes an optional
`pending_rows` argument parsed with `webapp/wizard_steps/common.py:parse_rows()`, exactly as
`wizard/_s7_costos.html` already does. Nothing is persisted until the explicit save. **No session,
no server-side scratch store, no "draft ledger" table.**

The new Pagos/ONVO screen has **no** such state: the método toggle re-renders one payment block
from posted values, and nothing else is multi-row-editable there.

### 1.3 One `summarize()` per render, and no money arithmetic in Jinja

The function of truth for the P&L **already exists and is already pure**:

```python
calculations.project_finance.summarize(project, payments, expenses, labor, extras) -> dict
```

**Rules:**

1. Every money figure the Presupuesto tab shows comes from **one `summarize()` call per render**,
   fed by **one `get_project_bundle()` call per render**. Any fragment handler that mutates
   something re-calls the context builder (which re-calls both) and renders from that — never from
   handler locals (Phase 20 §1.3).
2. **No arithmetic on money in a Jinja template.** No `{{ a - b }}`, no `{{ x * 1.13 }}`, no
   percentage computed in a filter. Templates receive pre-formatted strings.
3. **Formatting goes through `utils/formatting.py:fmt_usd` / `fmt_pct`** — in Python, in the context
   builder. `fmt_usd(None)` → `"—"`; `fmt_pct` takes 0–100, not 0–1.
4. **`by_category` is the only source for the GASTOS table**, always with all six
   `EXPENSE_CATEGORIES` keys even when empty (`PLAN_PHASE6.md` §4 risk #6).
5. The two figures Streamlit computes *outside* `summarize()` stay outside it, computed once in
   Python: the INGRESOS **extras card** (`Σ extras.amount_usd`, ex-IVA — L117) and each ledger's
   **TOTAL** (`Σ rows.total_with_iva`, the Postgres generated column — L389). Do not "unify" these;
   that would change what the page shows.
6. `labor_balance(row)` is the only source for "Saldo pendiente".
7. **New, and load-bearing for §1.10:** the two new screens get the **same treatment** — every
   Facturación figure comes from one `invoice_summary()` call and every ONVO figure from
   `onvo_breakdown()` / `payments_summary()` (§1.10.4). No per-category subtotal is summed in a
   template; no commission is multiplied in a template. ⚠ And the Pagos/ONVO footer's
   `recibido`/`pendiente` line comes from **`summarize()`**, not from a second sum over the same
   payments — two sources for one number is exactly how the Presupuesto and the Pagos tab would
   come to disagree.

Shape of the shared detail context (built by `projects_common.detail_ctx(pid)`):

```python
{
  "project": {...},                 # raw row
  "bundle": {...},                  # get_project_bundle() output, passed down so tabs don't refetch
  "result": {...},                  # summarize() output, unmodified
  "client_name", "sys_label", "status", "status_label", "contract_str",
  "status_options": [(value, label, is_current), ...],   # PROJECT_STATUSES × STATUS_LABELS
  "proposal_caption": "Promovido desde cotización — proposal_id …" | None,
  "active_tab": "presupuesto" | "banco" | ... | "facturacion" | "pagos",
}
```

### 1.4 Do-not-drop / must-build checklist

Acceptance criteria for the cutover step; re-read at every step boundary. Items 1–34 and 51–53 are
**do-not-drop** (ported behaviour, verified against Streamlit). Items 35–50 are **must-build** (new
construction, verified against §1.10.5's reference numbers — there is nothing to diff against).
⚠ marks a documented decision, a disclosed deviation, or a rule whose violation silently corrupts
money figures.

**Projects list (`pages/03_projects.py`)**

1. Status filter pills `Todos / Activos / Completados / Pausados / Cancelados` → `FILTER_MAP` →
   `list_projects(status=…)`; default `Todos` (L26–33, L235–245).
2. Row order = `list_projects()`'s own `created_at desc` (`projects_db.py` L362). Do not re-sort.
3. Columns `Cliente · Sistema · Contrato · Estado` + a `›` action, with `client_name or "Sin nombre"`,
   `SYSTEM_TYPE_LABELS.get(..., "—")`, `fmt_usd(contract_usd)`, and the `STATUS_BADGE` pairs
   verbatim: `active #dcfce7/#16a34a`, `completed #dbeafe/#1d4ed8`, `paused #fef9c3/#a16207`,
   `cancelled #fee2e2/#dc2626` (L20–25, L108–134).
4. `{n} proyecto(s)` count caption (L254).
5. Empty state: `No hay proyectos. Promueve una cotización ganada o crea uno nuevo con el botón de
   arriba.` (L251).
6. `Error cargando proyectos: {e}` on a failed list (L247) → `admin/_error.html`.
7. `+ Nuevo proyecto` form: client typeahead (`search_clients`) with the
   `(usar texto libre — sin cliente registrado)` first option and `{name} — {empresa}` match labels;
   `Tipo de sistema`; `Contrato (USD, monto total)` and `IVA incluido (USD)` **with their exact
   `help=` strings carried over as `title=`**; `Notas`; `Ingresa un nombre de cliente.` error;
   Crear → `create_project_manual(...)` → land on the new project (L139–211).

**Detail header**

8. `← Proyectos` back link (L574).
9. Title block: client name, then `{sys_label} · Contrato {fmt_usd(contract_usd)}` (L598–603).
10. Status pills over `PROJECT_STATUSES` with `STATUS_LABELS`; a change calls
    `update_project_status()`; **only** `PROJECT_STATUSES` values are ever sent (CHECK constraint)
    (L605–619).
11. `Promovido desde cotización — proposal_id {uuid}` caption, only when `proposal_id` is set
    (L621–622). Verbatim, uuid and all.
12. Tab order: `Presupuesto · Banco · Equipo · Materiales · Mano de obra · Viáticos ·
    Extras (gastos) · Facturación · Pagos` (L30–33). **`Extras (gastos)` keeps its suffix.**
13. `Error cargando proyecto: {e}` and `Proyecto no encontrado.` (L585, L590).

**Presupuesto tab**

14. INGRESOS: four cards — `Monto del contrato`, `IVA incluido`, `Extras (órdenes adicionales)`
    (`Σ extras.amount_usd`), `Gran total` (`result["ingresos_total"]`), the last navy-bordered
    (L116–143).
15. PAGOS block: header `Pago · Monto · Pagado · Fecha · Cuenta bancaria · (acción)`; per row
    `Pago {payment_number}`, `fmt_usd(amount_usd)`, a paid checkbox, a **free-text** date
    (`placeholder="YYYY-MM-DD"` — Streamlit uses `st.text_input`), a bank account field, and a
    `Guardar` calling `update_payment(paid=…, paid_date=paid_date or None,
    bank_account=bank_account or None)` (L148–195). ⚠ `update_payment`, **not**
    `mark_payment_paid` — the checkbox must be able to un-mark. ⚠ See item 50: this block must not
    touch the commission fields.
16. `Sin pagos programados.` when there are none (L150).
17. `+ Agregar pago`: `Pago #` defaulting to `max(payment_number) + 1` and `Monto USD` →
    `add_payment(project_id, int(number), float(amount))` (L197–215).
18. ⚠ `Recibido {fmt_usd(recibido)} de {fmt_usd(ingresos_total)} ({fmt_pct(pct)})` where
    `pct = recibido / ingresos_total * 100`, **and `0.0` when `ingresos_total` is falsy** (L217–227).
    (Streamlit's `$`-escaping there is a LaTeX-bug artifact and must **not** be carried into HTML.)
19. GASTOS table: seven columns `Rubro · Costo · IVA · Costo total · Pagado · Presupuestado ·
    Remanente`, one row per `EXPENSE_CATEGORIES` value **in that order**, all six always rendered
    (L232–254).
20. UTILIDAD: three cards — `Utilidad bruta`, then ⚠ a label that switches to
    `Crédito IVA (a favor)` when `iva_a_pagar < 0`, then `Utilidad neta`; green `#4BAE6A` on
    `#e8f5ee` when `>= 0`, red `#dc2626` on `#fee2e2` when negative (L89–98, L258–267).

**Expense ledgers (Banco / Equipo / Materiales / Viáticos / Extras (gastos))**

21. One shared renderer for all five, filtered by `category` from the already-fetched bundle, in
    `created_at` order (L630–636).
22. Columns `Rubro · Valor USD · IVA · Total · Fecha · Pagado · Comentarios` → `description ·
    amount_usd · iva_rate · total_with_iva · expense_date · paid · notes` (L272, L307–319).
23. ⚠ `IVA` is a two-option select — `0%` / `13%` only — via the exact `_iva_rate_to_label` /
    `_iva_label_to_rate` round-trip (L276–287). ⚠ `Total` is **display-only**, from the generated
    column, and **never in a write payload**.
24. ⚠ Budget-skeleton rows (`amount_usd == 0 and budgeted_usd > 0`) render dimmed with a small
    `presupuesto` pill — the disclosed §0.4 Q5 deviation.
25. Blank-`Rubro` new rows are **skipped, not inserted** (L373–375).
26. TOTAL line: `TOTAL: {fmt_usd(Σ total_with_iva)}`, right-aligned, navy, bold (L389–396).
27. Section heading `{RUBRO_LABELS[category]}` above each ledger (L635).

**Mano de obra**

28. ⚠ **No expense-entry form on this tab.** `PLAN_PHASE6.md` §1.6 and both module docstrings
    explain why: an `add_expense(..., category="mano_de_obra")` path would double-count in
    `_summarize_by_category()`. **Do not add one** (L401–414).
29. One card per worker: `{worker_name} · {role}` (role suffix only when set), then Cotización /
    Total adelantado / Saldo pendiente, the last red when negative (L423–452).
30. Advances table `Adelanto · Monto · Fecha · (Eliminar)`; `Eliminar` → `delete_advance(labor_id,
    number)` ⚠ which renumbers the survivors 1..N (`projects_db.py` L531–557) (L454–484).
31. `Sin adelantos registrados.` / `Sin trabajadores registrados.` empty states (L421, L484).
32. `+ Adelanto`: Monto USD + free-text Fecha → `add_advance(labor_id, amount, date or None)`
    (L486–503).
33. `Editar / eliminar trabajador` → `update_labor(...)` ⚠ with Streamlit's exact fallback
    `worker_name=edit_name.strip() or worker_name` (a blank name keeps the old one); plus
    `Eliminar trabajador` → `delete_labor()` (L505–541).
34. `+ Agregar trabajador` → `add_labor()`, with `Ingresa un nombre para el trabajador.` on a blank
    name (L545–566).

**Facturación — NEW BUILD (§1.10; `REQUIREMENTS.md` §5.5, `PLAN_PHASE6.md` Step 7)**

35. Line-item editor over `project_invoice_items`: `Artículo` (description) · `Categoría`
    (a select over `config.INVOICE_CATEGORIES` = equipos/materiales/servicios) · `Tasa IVA`
    (the same `0%`/`13%` vocabulary as the ledgers) · `Monto` (amount_usd), plus **display-only**
    `IVA` (iva_amount) and `Total` (total_usd).
36. ⚠ `iva_amount` and `total_usd` are Postgres GENERATED columns — display-only, **never in a
    write payload** (`projects_db.py` strips them via `_clean()`; do not bypass it).
37. Per-category summary block: `Equipos` / `Materiales` / `Servicios`, each with subtotal, IVA and
    total — ⚠ **all three always rendered**, even when a category has no rows (same rule as
    `by_category`'s six rubros, and for the same reason).
38. `TOTAL GENERAL` with its own `subtotal + IVA` breakdown shown alongside it.
39. ⚠ Reconciliation line: `Δ = TOTAL GENERAL − (contract_usd + Σ extras.total_with_iva)`, rendered
    green when `|Δ| < 0.01` and amber otherwise, with Δ in `fmt_usd` — plus the caption stating
    that Facturación is a reconciliation view and **never a source for the profit math**
    (`PLAN_PHASE6.md` Step 7). `contract_usd` is already the full total; there is **no
    `* (1 + rate)`** anywhere.
40. ⚠ Nothing on this tab changes `utilidad_bruta` / `iva_a_pagar` / `utilidad_neta`. Asserted, not
    assumed (Step 7's validation).
41. Editing affordances identical to the ledgers (§1.6): save-by-id / insert-when-idless, `+ Fila`
    round-trip from posted values, explicit per-row delete confirm, blank-`Artículo` rows skipped,
    `hx-disabled-elt` on save.
42. `Sin renglones de factura.` empty state, and the summary block still rendering three zeroed
    categories under it.

**Pagos / ONVO — NEW BUILD (§1.10; `REQUIREMENTS.md` §5.6, `PLAN_PHASE6.md` §1.4 + Step 8)**

43. Header line: project and `Contrato total` (`fmt_usd(contract_usd)`).
44. One block per `project_payments` row, in `payment_number` order: método toggle
    (`Transferencia` / `ONVO tarjeta`), `Monto bruto`, `Comisión %`, `IVA sobre comisión %`,
    `Comisión USD`, `IVA USD`, **`Por depositar`**, `Pagado` + `Fecha` + `Cuenta bancaria`, `Notas`.
45. ⚠ The método toggle **sets the two rates and nothing else**: `Transferencia` → `0 / 0`;
    `ONVO tarjeta` → `config.DEFAULT_ONVO_COMMISSION` (0.024) `/ 0.13`. Both remain editable after
    the toggle — the toggle is a convenience over two numbers, exactly as `PLAN_PHASE6.md` §1.4
    designed it. There is **no `method` column** and none is added (§1.10.3).
46. ⚠ Every displayed figure is a **freshly computed** `onvo_breakdown(amount, commission_pct,
    iva_pct)`. `net_deposited` **is** persisted on save (§1.4 of Phase 6: "Persisted value exists
    for reporting/export") but is **never** the source of a displayed number — a stale or NULL
    persisted value must not be able to misreport.
47. Footer: `Total pagado por el cliente` · `Comisión total` · `IVA sobre comisión total` ·
    `Total por depositar` — all from `payments_summary()` over the **paid** payments — and then
    ⚠ `Recibido … / Pendiente …` **from `summarize()`**, not recomputed (§1.3 rule 7).
48. ⚠ Fees never reduce ingresos. `utilidad_bruta` / `utilidad_neta` must **not** move when a
    payment's método changes. This is the single assertion that catches the most likely modelling
    error on this screen (`PLAN_PHASE6.md` Step 8) — Step 8's validation checks it explicitly.
49. ⚠ `Registrar comisión como gasto Banco`, per payment, **never automatic**: inserts one
    `project_expenses` row with `category='banco'`, `amount_usd = comisión + IVA sobre comisión`,
    `iva_rate = 0`, a human-readable description, and `notes` containing the marker
    `onvo:{payment_id}`. It **refuses** (with a visible message, not an exception) if a row carrying
    that marker already exists for the project. A silent automatic write here would double-count
    against a manually entered bank charge.
50. ⚠ **Unclassified payments read as Transferencia with zero fees** — post-migration-048 every
    historical row is `0 / 0` and the screen shows `$0.00` commission, never an implied 2.4%
    (§1.10.3). And the Presupuesto tab's own payment editor (item 15) must **not** send
    `onvo_commission_pct` / `onvo_iva_pct` / `net_deposited` in its `update_payment()` payload, so
    editing a payment there can never silently wipe an ONVO classification made here.

**"Mover a Proyecto" (the §1.9 integration)**

51. Won-proposal promotion form reproducing `01_proposals.py:_render_promotion_block()` L424–581 in
    full: the already-promoted `Ver proyecto →` branch; `Monto del contrato (USD, según cotización)`
    and `IVA incluido en el contrato (USD)` pre-filled from `derive_contract_terms()` **and
    editable**, with their exact help strings; the editable budget-mapping table
    (Concepto / Rubro over `EXPENSE_CATEGORIES` / Presupuesto USD) seeded by `derive_budget_rows()`;
    ⚠ the reconciliation caption explaining budget-total ≠ contract-total *verbatim* (L513–518 — it
    exists because the two numbers genuinely differ and someone will otherwise "fix" it); the
    schedule radio `70/30 · 50/40/10 · Personalizado` with the live preview and the custom editor;
    Confirmar → `promote_to_project(...)` → land on the new project; Cancelar.
52. ⚠ `promote_to_project()`'s already-promoted `ValueError`
    (`Esta propuesta ya fue movida a un proyecto. Solo se puede promover una vez.`) renders inline,
    **never as a 500** (`projects_db.py` L240–250).
53. ⚠ The promotion form performs **no derivation of its own** — `derive_contract_terms()`,
    `derive_budget_rows()`, `payment_schedule_for_preset()` and `promote_to_project()` are the only
    sources. `projects_db.py` L200–201: "This is the single place the §1.5/§1.7 derivation logic
    lives; the UI must not duplicate it."

### 1.5 What this phase is allowed to change outside `webapp/`

Phase 21 allowed exactly one additive DB helper. This phase's scope change makes the boundary wider
— and therefore worth stating precisely. **Exhaustive list:**

| File | Change | Why it is allowed |
|---|---|---|
| `calculations/project_finance.py` | **Additive only**: `invoice_summary()` and `payments_summary()` (§1.10.4). No existing function is edited, no signature changes, no rounding rule changes | The module is the designated home for this app's pure money math (`PLAN_PHASE6.md` §1.2). Putting new money math in a Jinja template or a blueprint instead would violate §1.3 and would be untestable by `scripts/validate_phase6.py`. Streamlit never calls the new functions, so `main`'s behaviour is unaffected |
| `scripts/validate_phase6.py` | **Additive only**: a "Step 7 — Facturación" section and a "Step 8 — ONVO" section | Its own docstring (L5–7) instructs exactly this: "extend it in each build step rather than writing a parallel ad-hoc check" |
| `database/migrations/048_project_payment_commission_truth.sql` | **New file** (§1.10.3) | The only honest way to build Step 8's UI on top of the existing column default. Real finding, not routed around |
| `database/schema.sql` | Mirror 048's default change into the `project_payments` snippet | Repo convention — every migration is mirrored into `schema.sql` |

**Everything else outside `webapp/` is untouched**, and the cutover step asserts it with a scoped
`git diff`. In particular: `database/projects_db.py` needs **no** new function — `update_payment(**fields)`
and `add_payment(..., **kwargs)` already accept the commission columns and route them through
`_clean()`, and `add_invoice_item` / `update_invoice_item` / `delete_invoice_item` /
`list_invoice_items` already exist and already strip the generated columns. The
`onvo:{payment_id}` idempotency guard (item 49) is composed in the blueprint from
`list_expenses(project_id, category="banco")` + `add_expense(...)`, deliberately, to keep
`database/` unmodified; its docstring must say so.

**Query shape, unchanged from the pure-port plan:** one `get_project_bundle()` per detail render
(it already fetches `invoice_items`, so Facturación is free); one `list_projects()` on the list page
and **no per-project bundle enrichment** there (that is Phase 6 Step 9, out of scope, and would
reproduce the dashboard's `1 + 6N` on a second page).

### 1.6 htmx interaction model — Phase 20's three patterns, applied

No new patterns (Phase 20 §1.4, Phase 21 §1.6).

| Streamlit / new interaction | Pattern | Flask shape |
|---|---|---|
| Status filter pills on the list | **pattern 3** | `hx-get /proyectos/?estado=…` → `#subpanel`, `hx-push-url="true"` |
| `›` row button → detail | **plain link** | `<a href="/proyectos/<pid>">` — a real page, a real URL (§1.2) |
| `← Proyectos` | **plain link** | `<a href="/proyectos/">` |
| `+ Nuevo proyecto` toggle | **pattern 2** | `hx-get /proyectos/nuevo` → `#nuevo`; Cancelar swaps an empty fragment back |
| Client typeahead | **pattern 3** | `hx-get /proyectos/nuevo/clientes`, `hx-trigger="keyup changed delay:300ms"` |
| Crear proyecto | **form POST + 303** | → `create_project_manual()` → 303 `/proyectos/<new_id>` |
| Tab switch (nine tabs) | **tab swap** | `hx-get` → `#subpanel`, `hx-swap="innerHTML"`, `hx-push-url="true"` — copy `maintenance/page.html` verbatim, including the `hx-on::after-request` active-class toggle |
| Status pills on the detail header | **form POST + 303** | → `update_project_status()` → 303 back to the current tab |
| Per-payment `Guardar` (Presupuesto block) | **pattern 2** | one `<form>` per row, `hx-post .../pago/<payment_id>` → swap the whole Presupuesto panel, so the Recibido line and UTILIDAD cards can never drift from the row |
| `+ Agregar pago` | **form POST + 303** | → `add_payment()` → 303 `/proyectos/<pid>` |
| Ledger / Facturación `Guardar cambios` | **form POST + 303** | one form per table; updates rows carrying a hidden `id`, inserts rows without one, skips blank-description rows; ⚠ **never deletes by absence** (§0.4 Q4) |
| Ledger / Facturación `+ Fila` | **pattern 2** | `hx-post .../fila` with `hx-include` of the table → re-renders the fragment **from the posted values plus one blank row** (§1.2); nothing persisted |
| Ledger / Facturación row delete | **pattern 2** | `✕` → `hx-get .../eliminar` inline confirm → `POST` → delete → re-render. Same shape as `maintenance/_delete_confirm.html` |
| Labor add/edit/delete, advance add/delete | **form POST + 303** | each its own small form; the two destructive ones go through an inline confirm first — ⚠ Streamlit deletes on the first click; this is a disclosed hardening for money rows (§4) |
| **Pagos/ONVO método toggle** | **pattern 3** | `hx-post .../pago/<id>/metodo` with the block's inputs included → re-renders **that payment's block plus the footer** from posted values (rates prefilled per item 45), persisting nothing until Guardar |
| **Pagos/ONVO `Guardar`** | **pattern 2** | `hx-post .../pago/<id>/onvo` → `update_payment(...)` incl. the freshly computed `net_deposited` → swap the whole Pagos panel (blocks + footer), so no per-block total can drift from the footer |
| **`Registrar comisión como gasto Banco`** | **pattern 2** | `hx-post .../pago/<id>/comision-banco` → guard, insert or refuse → swap the whole Pagos panel with an inline result message |
| `Mover a Proyecto` (proposals side) | **pattern 2 then form POST + 303** | `hx-get /proyectos/promover/<pid>/<vid>` renders the form into the existing `.det-promote` block; budget/schedule tables re-render on `change delay:400ms` from posted values; Confirmar POSTs → 303 `/proyectos/<new_id>` |

⚠ `hx-indicator` + `hx-disabled-elt="this"` on **Confirmar (promotion)**, **Guardar cambios**
(ledger and Facturación), **Guardar (Pagos/ONVO)**, **Registrar comisión como gasto Banco**, and
every delete — each is a multi-row, one-shot or duplicate-prone write.

### 1.7 Route / blueprint structure

Mirrors `webapp/blueprints/maintenance.py`: one module owns routing + tab dispatch, one module per
tab-group owns its logic, each registered onto the same `bp` via `register(bp)` (Phase 21 §5.5's
finding #1 — never create a second `Blueprint` instance, or the nav's `request.blueprint` rule
silently breaks for that module's routes only).

```
webapp/blueprints/projects.py             Blueprint("projects", __name__, url_prefix="/proyectos")
  GET  /                                  list + status filter (?estado=)        (page | partial)
  GET  /nuevo                             manual-create form fragment            (partial)
  GET  /nuevo/clientes                    client typeahead results               (partial)
  POST /                                  create_project_manual()   → 303 /proyectos/<new_id>
  GET  /<pid>                             detail, Presupuesto tab                (page | partial)
  GET  /<pid>/gastos/<categoria>          one of the 5 expense ledgers           (page | partial)
  GET  /<pid>/mano-de-obra                labor tab                              (page | partial)
  GET  /<pid>/facturacion                 Facturación tab                        (page | partial)
  GET  /<pid>/pagos                       Pagos / ONVO tab                       (page | partial)
  POST /<pid>/estado                      update_project_status()   → 303 current tab

webapp/blueprints/projects_budget.py      Presupuesto tab + the Pagos block
  POST /<pid>/pago                        add_payment()                          (→ 303)
  POST /<pid>/pago/<payment_id>           update_payment() — ⚠ item 50: paid/date/bank only (partial)

webapp/blueprints/projects_ledger.py      the 5 shared expense ledgers
  POST /<pid>/gastos/<categoria>          save: update by id + insert new        (→ 303)
  POST /<pid>/gastos/<categoria>/fila     +Fila, re-render from posted values    (partial)
  GET  /<pid>/gasto/<eid>/eliminar        inline delete-confirm fragment         (partial)
  POST /<pid>/gasto/<eid>/eliminar        delete_expense()                       (→ 303)

webapp/blueprints/projects_labor.py       Mano de obra
  POST /<pid>/trabajador                       add_labor()                       (→ 303)
  POST /<pid>/trabajador/<lid>                 update_labor()                    (→ 303)
  GET|POST /<pid>/trabajador/<lid>/eliminar    confirm + delete_labor()
  POST /<pid>/trabajador/<lid>/adelanto        add_advance()                     (→ 303)
  GET|POST /<pid>/trabajador/<lid>/adelanto/<n>/eliminar   confirm + delete_advance()

webapp/blueprints/projects_invoicing.py   Facturación (NEW — §1.10.1)
  POST /<pid>/facturacion                 save: update by id + insert new        (→ 303)
  POST /<pid>/facturacion/fila            +Fila, re-render from posted values    (partial)
  GET  /<pid>/factura/<iid>/eliminar      inline delete-confirm fragment         (partial)
  POST /<pid>/factura/<iid>/eliminar      delete_invoice_item()                  (→ 303)

webapp/blueprints/projects_payments.py    Pagos / ONVO (NEW — §1.10.2)
  POST /<pid>/pago/<payment_id>/metodo         re-render one block from posted values (partial)
  POST /<pid>/pago/<payment_id>/onvo           update_payment(rates, net_deposited, …)(partial)
  POST /<pid>/pago/<payment_id>/comision-banco guarded add_expense(category='banco') (partial)

webapp/blueprints/projects_promote.py     the Cotizaciones ↔ Proyectos integration (§1.9)
  GET  /promover/<pid>/<vid>              promotion form fragment                (partial)
  POST /promover/<pid>/<vid>/tabla        re-render budget/schedule from posted values (partial)
  POST /promover/<pid>/<vid>              promote_to_project()      → 303 /proyectos/<new_id>

webapp/blueprints/projects_common.py      STATUS_LABELS, STATUS_BADGE, RUBRO_LABELS, TAB order,
                                          INVOICE_CATEGORY_LABELS, ONVO_IVA_PCT (=0.13, with the
                                          comment explaining why it is not in config.py),
                                          money helpers over utils.formatting, detail_ctx(pid),
                                          _iva_rate_to_label/_iva_label_to_rate (ported verbatim)
```

Templates, mirroring `webapp/templates/maintenance/`:

```
webapp/templates/projects/page.html             tab shell (clone of maintenance/page.html)
                         list.html              list page shell
                         _list.html             filter + table + count caption   (partial target)
                         _nuevo.html            manual-create form               (partial target)
                         _nuevo_clientes.html   typeahead results                (partial target)
                         _header.html           title, status pills, proposal caption
                         _presupuesto.html      INGRESOS + PAGOS + GASTOS + UTILIDAD
                         _ledger.html           the shared 5-tab ledger          (partial target)
                         _ledger_delete.html    inline confirm                   (partial target)
                         _labor.html            worker cards + forms             (partial target)
                         _labor_delete.html     inline confirm                   (partial target)
                         _facturacion.html      NEW: line items + category summary + Δ line
                         _factura_delete.html   NEW: inline confirm              (partial target)
                         _pagos.html            NEW: per-payment ONVO blocks + footer
                         _promote.html          promotion form                   (partial target)
                         _macros.html           pill() / metric_card()
```

Every panel render is wrapped in `try/except` → `admin/_error.html` (reuse it; do not make a second
error partial), matching `maintenance_overview.py` L44–52.

### 1.8 Calculation logic: reused verbatim, plus two additive pure functions

- **`summarize()`, `labor_balance()` and `onvo_breakdown()` are imported and called unchanged.**
  No extraction, no move, no edit to any existing function. This is the `calculations/*` situation
  from Phase 20 §0.1 and Phase 21 §1.8.
- **Two new pure functions are added to the same module** (§1.10.4) because the new screens need
  aggregation that does not exist yet and must not live in a template or a blueprint.
- **`database/projects_db.py` is reusable verbatim**, including the promotion derivations
  (`derive_contract_terms`, `derive_budget_rows`, `payment_schedule_for_preset`,
  `default_payment_schedule`, `categorize_line_item`), which are already pure functions that happen
  to live in the DB module. The UI calls them; it does not reimplement them (§1.4 item 53).
- **The only Streamlit-free logic living inside a Streamlit page** is `_iva_rate_to_label()` /
  `_iva_label_to_rate()` (L276–287) and `_metric_card()`'s colour rule (L89–98). They are tiny and
  private to that page, so the port **copies** them into `projects_common.py`.
  `pages/04_project_detail.py` stays untouched (§3), so there will briefly be two copies — accepted,
  same reasoning as Phase 21 §1.8.
- ⚠ **`pandas` is not needed anywhere in this port.** Streamlit imports it only to feed
  `st.data_editor`. The Flask tables are plain HTML over `parse_rows()`. Do not introduce a
  DataFrame.

### 1.9 "Mover a Proyecto" — exactly what gets wired, on both sides

Phase 20 §0.3 Q4 deferred this and left a disabled placeholder. Closing it touches **six places**,
all inside `webapp/`:

**Projects side (new, `webapp/blueprints/projects_promote.py`):**

1. `GET /proyectos/promover/<pid>/<vid>` → `proposals_db.get_version(vid)`, then
   `derive_contract_terms(version)` + `derive_budget_rows(version)` → renders
   `projects/_promote.html` (§1.4 item 51). Read-only; writes nothing.
2. `POST /proyectos/promover/<pid>/<vid>/tabla` → re-renders the same fragment from **posted**
   budget/schedule values (§1.2's round-trip rule), so the totals caption and the schedule preview
   track edits without persisting anything.
3. `POST /proyectos/promover/<pid>/<vid>` → builds `budget_rows` (skipping blank-Concepto rows, as
   `01_proposals.py` L562–563 does) and `payment_schedule`, calls `promote_to_project(pid, vid,
   contract_usd, contract_iva_usd=…, budget_rows=…, payment_schedule=…)`, 303s to
   `/proyectos/<new_id>`. A `ValueError` re-renders the fragment with the message inline (item 52).

**Proposals side (edits to already-shipped Phase 20 code):**

4. `webapp/templates/proposals/_detail.html` L79–90 — inside the existing `{% if status == 'won' %}`
   `.det-promote` block, replace the `{% else %}` branch's disabled span + the
   `disponible cuando se migre Proyectos` note with a real button:
   `hx-get="{{ url_for('projects.promover_form', pid=pid, vid=cur_version_id) }}"`,
   `hx-target="#promote-{{ pid }}"`, `hx-swap="innerHTML"`, plus the empty
   `<div id="promote-{{ pid }}"></div>` it targets. Keep the `project_error` and `Ver proyecto →`
   branches. **If `cur_version_id` is empty** (a won proposal with no versions — `_detail_ctx`
   L262 defaults it to `""`), keep a disabled button; do not build a URL with an empty `vid`.
5. `webapp/blueprints/proposals.py` L307–309 — replace the hardcoded `f"/proyectos/{project['id']}"`
   with `url_for("projects.detalle", pid=project["id"])` and delete the "hardcoded because the
   Projects blueprint doesn't exist yet" comment.
6. `webapp/blueprints/proposals.py` L13–14 — the module docstring still says the Projects blueprint
   is a stub. Update it.

**What does *not* change:** `_detail_ctx()`'s existing `get_project_by_proposal()` call and its
`project` / `project_error` keys, `database/projects_db.py`, and `pages/01_proposals.py`.

### 1.10 New construction: Facturación and Pagos/ONVO

This section is the design basis for §1.4 items 35–50 and Steps 0, 7 and 8. It exists because these
two screens have **no Streamlit implementation to port or to diff against** — the porting
discipline the rest of this phase (and Phases 20–21) relies on does not apply, so the rigour has to
come from somewhere else: an explicit design, a verified schema, and hand-computed reference
numbers.

#### 1.10.1 Facturación — schema verdict: **no migration needed**

`project_invoice_items` (schema.sql L230–240) already carries exactly what `REQUIREMENTS.md` §5.5
describes, and the DB layer is already complete and already generated-column-safe:

| §5.5 column | Table column | Notes |
|---|---|---|
| Artículo | `description text NOT NULL` | |
| Categoría | `category text NOT NULL CHECK (category IN ('equipos','materiales','servicios'))` | matches `config.INVOICE_CATEGORIES` exactly |
| Tasa IVA | `iva_rate numeric(4,3) NOT NULL DEFAULT 0` | |
| Monto / Subtotal | `amount_usd numeric(10,2) NOT NULL` | the ex-IVA amount; §5.5's "Monto" and "Subtotal" are the same number |
| IVA | `iva_amount GENERATED ALWAYS AS (amount_usd * iva_rate) STORED` | ⚠ never written |
| Total | `total_usd GENERATED ALWAYS AS (amount_usd * (1 + iva_rate)) STORED` | ⚠ never written |

`add_invoice_item(project_id, description, category, amount_usd, iva_rate)`,
`update_invoice_item(item_id, **fields)`, `delete_invoice_item(item_id)` and
`list_invoice_items(project_id)` all exist, all route through `_clean("project_invoice_items", …)`
which strips both generated columns, and `get_project_bundle()` already fetches the list. **Nothing
in the DB layer changes.**

Two small UI conventions, documented here so they are not re-invented per-row:
- The `Tasa IVA` control reuses the ledgers' `0%` / `13%` select and the same
  `_iva_rate_to_label`/`_iva_label_to_rate` round-trip. (The column is `numeric(4,3)`, so other
  rates are storable; the UI offers the two that exist in Costa Rican practice, exactly as the
  expense ledgers do.)
- A **new** row defaults its rate to `0%` when the chosen category is `equipos` and `13%` otherwise
  — a convenience matching §5.5's own table, fully editable, never enforced.

#### 1.10.2 Pagos/ONVO — schema verdict: **no new column needed, but one migration is required**

`project_payments` (schema.sql L187–200) already carries `onvo_commission_pct numeric(5,4) NOT NULL
DEFAULT 0.024`, `onvo_iva_pct numeric(5,4)`, `net_deposited numeric(10,2)`, `notes text`, plus
`paid` / `paid_date` / `bank_account`. That is the entire §5.6 surface.

**No `method` column is added.** `PLAN_PHASE6.md` §1.4 deliberately models método as *two rates*:
"Bank transfers: `onvo_commission_pct = 0, onvo_iva_pct = 0` → `net_deposited == amount_usd`."
`onvo_breakdown(amount, commission_pct, iva_pct)` takes exactly those two numbers, so a `method`
enum would be a third representation of the same fact and a new way for the three to disagree. The
toggle is a UI affordance that fills the two fields (§1.4 item 45).

**But the existing column default is a live data-integrity problem, and that is what migration 048
is for — see §1.10.3.**

#### 1.10.3 ⚠ The 0.024 default: the finding, and how it is resolved

**The finding.** `project_payments.onvo_commission_pct` is `NOT NULL DEFAULT 0.024`.
`add_payment()` (`projects_db.py` L404–413) never passes it. `update_payment()` is only ever called
by the Presupuesto block with `paid` / `paid_date` / `bank_account`. Grepping the whole repo,
**nothing has ever written or read that column**. Therefore **every `project_payments` row in the
live database currently asserts a 2.4% ONVO commission that no one chose**, alongside
`onvo_iva_pct IS NULL` and `net_deposited IS NULL`. Today that is invisible. **The moment Step 8's
UI reads the column, every historical payment starts displaying a commission and a reduced
"por depositar" that, for a bank transfer, never happened** — on real financial records Oscar
actually bills against, and with a one-click affordance (item 49) that would turn the fiction into
a real `project_expenses` row.

**Why the obvious workarounds are rejected.**
- *Have the UI ignore the column and always show 0 unless the user picks ONVO* — the UI would then
  display something different from what the database says, which is the same class of bug pointed
  the other way, and the first export or report to read the column reintroduces it.
- *Treat `net_deposited IS NULL` as "unclassified" and hide the fees* — correct for display, but it
  leaves a NOT NULL column permanently holding a false value, and "unclassified" becomes an
  invisible third state nobody maintains.
- *Add a `method` column* — a third representation of the same fact (§1.10.2), and it still leaves
  the false 0.024 sitting in the rate column.

**The resolution — `database/migrations/048_project_payment_commission_truth.sql`, run in two
gated halves:**

```sql
-- 048_project_payment_commission_truth.sql
-- Phase 22 §1.10.3. project_payments.onvo_commission_pct has defaulted to 0.024
-- since migration 020 while nothing ever wrote or read it, so every existing row
-- asserts an ONVO commission that was never chosen. Phase 22 builds the UI that
-- finally reads this column, so the data has to stop lying first.

-- (a) Stop future rows from inheriting a commission nobody chose. A payment is a
--     bank transfer until someone says otherwise.
ALTER TABLE project_payments ALTER COLUMN onvo_commission_pct SET DEFAULT 0;
ALTER TABLE project_payments ALTER COLUMN onvo_iva_pct         SET DEFAULT 0;

-- (b) Backfill only rows that provably were never classified by a human: the exact
--     default signature. Rows the new UI has touched (net_deposited IS NOT NULL)
--     are never modified, which also makes this statement safely re-runnable.
UPDATE project_payments
   SET onvo_commission_pct = 0,
       onvo_iva_pct        = 0
 WHERE onvo_commission_pct = 0.024
   AND onvo_iva_pct  IS NULL
   AND net_deposited IS NULL;
```

Guardrails, all mandatory (Step 0 enforces them):

1. **A read-only audit runs first** and is recorded in the step's commit message: total
   `project_payments` rows; how many match the untouched-default signature exactly; and **any row
   that does not** (a different `onvo_commission_pct`, a non-NULL `onvo_iva_pct`, or a non-NULL
   `net_deposited`). If the audit finds even one deviating row, **stop and ask Oscar** — the "all
   0.024 values are defaults" premise would be false for that row and the blanket `UPDATE` would
   destroy a real classification.
2. **Half (b) does not run without Oscar's answer to §0.4 Q8** ("were any historical payments
   genuinely ONVO card?"). Half (a) — the default change — is safe to run regardless and can ship
   first if the answer is slow: it only affects future inserts.
3. **The remediation path is the UI itself.** After the backfill, any payment that really was taken
   by card is re-marked in the new Pagos tab in seconds (toggle → ONVO tarjeta → Guardar), which
   writes the truthful rates *and* `net_deposited`. That is strictly better than leaving a guessed
   2.4% on every row, because it records a human decision instead of a schema default.
4. `database/schema.sql`'s `project_payments` snippet is updated to `DEFAULT 0` in the same commit,
   with a one-line comment pointing at 048 — the repo's standing convention.
5. Nothing is dropped, no column is removed, no NOT NULL is added. The change is reversible by
   setting the default back; the backfilled values are not reversible, which is precisely why
   guardrails 1 and 2 exist.

#### 1.10.4 The two additive pure functions

Both go in `calculations/project_finance.py` (§1.5's rationale), both are `from config import`-only
pure functions over already-fetched dicts, and both follow the module's standing rounding rule —
**round only at named-figure boundaries**.

```python
def invoice_summary(invoice_items: list[dict], project: dict, extras: list[dict]) -> dict:
    """Facturación totals + the contract reconciliation (REQUIREMENTS §5.5,
    PLAN_PHASE6.md Step 7). Returns per-category {subtotal, iva, total} for ALL
    THREE config.INVOICE_CATEGORIES (present even when a category has no rows),
    plus subtotal/iva/total_general and

        delta = total_general - (contract_usd + Σ extras.total_with_iva)

    Facturación is a reconciliation view only — nothing here feeds summarize()."""

def payments_summary(payments: list[dict], commission_of=onvo_breakdown) -> dict:
    """Footer aggregation for the Pagos/ONVO screen (REQUIREMENTS §5.6):
    {gross_paid, commission_total, iva_on_commission_total, net_deposited_total},
    computed over PAID payments only by calling onvo_breakdown() per row — never
    by re-deriving the per-row math. Sums the already-rounded per-payment figures
    (each payment is one real transaction with its own statement line), which is
    what a processor statement adds up to.

    Deliberately does NOT return recibido/pendiente: those come from summarize(),
    so the Presupuesto tab and the Pagos tab cannot disagree (plan §1.3 rule 7)."""
```

Reading `extras[].total_with_iva` in `invoice_summary()` is safe — it is a generated column present
on every fetched row — but the function must tolerate it being absent (`amount_usd * (1 + iva_rate)`
fallback), because `derive_*`-built dicts do not carry it.

**`onvo_breakdown()` is sufficient as-is for the per-payment math** — confirmed by reading it
against `REQUIREMENTS.md` §5.6 and `PLAN_PHASE6.md` §1.4 line by line: it takes the gross, the
commission rate and the IVA rate; it rounds the commission first and computes IVA on the *rounded*
commission (the documented, deliberate choice matching how a processor statement reads); and it
returns gross / commission / iva_on_commission / net_deposited, which is exactly §5.6's four
per-payment figures. It is a finished function that was never called, not a stub. **Do not edit
it** — in particular, do not "fix" the round-then-multiply order, which is what makes the $7,028.08
reference number reproducible.

#### 1.10.5 The oracle for code with no Streamlit to compare against

Three layers, all required:

1. **Pure-function assertions in `scripts/validate_phase6.py`** (additive sections, per §1.5),
   using `PLAN_PHASE6.md`'s own hand-computed fixtures:
   - *Facturación (Step 7's fixture):* items `Equipos $8,000.00 @ 0%`, `Materiales $1,000.00 @ 13%`,
     `Servicios $1,000.00 @ 13%` → per category `8,000.00 / 0.00 / 8,000.00`,
     `1,000.00 / 130.00 / 1,130.00`, `1,000.00 / 130.00 / 1,130.00`; subtotal `10,000.00`,
     IVA `260.00`, **TOTAL GENERAL `10,260.00`**. Against Jorge's contract (`10,320.00`) with the
     Step 6 extra (`$500 @ 13%` → `565.00`) present as a hand-built dict, **Δ = −$625.00** → amber.
     Also assert the empty case: zero items → three zeroed categories, total `0.00`.
   - *ONVO (Step 8's fixture):* `$7,224.00` as Transferencia (`0 / 0`) → commission `0.00`, IVA
     `0.00`, **net `7,224.00`**; the same payment as ONVO tarjeta (`0.024 / 0.13`) → commission
     **`173.38`**, IVA on commission **`22.54`**, **net `7,028.08`**; and
     `payments_summary()` over both-paid variants summing to those same figures.
   - *The invariance assertion:* `summarize()`'s `utilidad_bruta` / `utilidad_neta` are **identical**
     for the transferencia and ONVO variants of the same payment set (fees are a bank cost, not a
     revenue reduction — §1.4 item 48).
2. **A live end-to-end exercise on a QA project** whose `contract_usd` is set to **`$10,320.00`**
   precisely so the hand-computed numbers above transfer: the same three invoice items must produce
   the same per-category block and TOTAL GENERAL in the rendered page, with Δ = `10,260.00 −
   10,320.00` = **−$60.00** (the QA project has no extras; the −$625.00 figure belongs to the
   unit-test fixture, which supplies one).
3. **Cross-screen consistency checks** that only a running app can make: the Pagos footer's
   Recibido/Pendiente equal the Presupuesto's Recibido line to the cent; the Banco ledger's TOTAL
   moves by exactly `commission + IVA` after "Registrar comisión como gasto Banco" and the GASTOS
   `banco` rubro moves with it; Facturación changes move **nothing** on the Presupuesto tab.

---

## 2. Build steps

Eleven steps: **Step 0** (data truth, no UI) then **Steps 1–10**. Each is a vertical slice ending in
something runnable plus a validation you can execute. **Do not start step N+1 until step N's
validation passes.**

Ported steps are validated **side by side with the Streamlit app on the same Supabase project**.
New-construction steps (7, 8) are validated against §1.10.5's reference numbers, because there is no
Streamlit page to compare against. ⚠ **Every write-path validation is performed on purpose-created
QA data only** — see §4, and Step 10 for the cleanup discipline.

---

### Step 0 — ONVO commission data truth (migration 048). No UI.

Done first because Steps 4 and 8 both write `project_payments`, and neither should run against rows
that assert a commission nobody chose (§1.10.3).

**Build**
- A **read-only audit** (a script in `scripts/` or a REPL session — either is fine; record the
  output in the commit message): total `project_payments` rows; rows matching the untouched-default
  signature (`onvo_commission_pct = 0.024 AND onvo_iva_pct IS NULL AND net_deposited IS NULL`); and
  a full dump of **every row that does not match**.
- ⚠ **If any row deviates: stop and ask Oscar before writing the migration.** The premise that all
  0.024 values are schema defaults would be false, and the blanket `UPDATE` would overwrite a real
  classification.
- `database/migrations/048_project_payment_commission_truth.sql` exactly as §1.10.3 specifies, with
  its header comment in the explanatory style of `016_equipment_cost_iva.sql`.
- Mirror the `DEFAULT 0` change into `database/schema.sql`'s `project_payments` block, with a
  one-line pointer to 048.
- ⚠ Run half (a) (the two `ALTER … SET DEFAULT`) immediately. Run half (b) (the `UPDATE`) **only
  after Oscar answers §0.4 Q8**. If the answer is "some were ONVO", get the list, run (b) anyway
  (it is the honest baseline), then re-mark those specific payments through the Step 8 UI once it
  exists — and record which ones in this document.

**Validate**
- Re-run the audit: every row now reads `onvo_commission_pct = 0`, `onvo_iva_pct = 0`, and
  `net_deposited` is unchanged (still NULL everywhere, unless the audit found otherwise).
- Insert a throwaway payment on a QA project via `add_payment()` → it lands with
  `onvo_commission_pct = 0`, not `0.024`. Delete it.
- Re-run the `UPDATE` → it affects **0 rows** (idempotent, per the `net_deposited IS NULL` guard).
- `scripts/validate_phase6.py` still passes (it touches no DB, but run it as the standing smoke
  check).
- Record the before/after row counts here in this document under Step 0 — they are part of the
  Step 10 audit's evidence.

---

### Step 1 — Blueprint shell + projects list (read-only) + nav cutover

**Build**
- `webapp/blueprints/projects.py` with the blueprint, the list route, the `?estado=` filter and
  partial-vs-page dispatch; registered in `webapp/__init__.py:create_app()`.
- `webapp/blueprints/projects_common.py`: `STATUS_LABELS`, `STATUS_BADGE`, `RUBRO_LABELS`,
  `INVOICE_CATEGORY_LABELS`, the tab order, `FILTER_OPTIONS`/`FILTER_MAP`, `ONVO_IVA_PCT`, and the
  `fmt_usd`/`fmt_pct` wrappers. Its docstring carries §1.3's invariant.
- `webapp/templates/projects/list.html` + `_list.html` + `_macros.html`.
- Remove `"projects"` from `dashboard.STUBS` and point `base.html` L24 at `projects.index`, active
  rule `request.blueprint == 'projects'`.

**Validate**
- ⚠ **Baseline first** (§0.3): record the number of projects, their statuses, and for each whether
  it has payments / expenses / labor / invoice items / non-zero `contract_iva_usd`. Put the numbers
  in the commit message — every later step refers back to them and §4's risk assessment depends on
  them.
- Side by side with Streamlit's list: identical project count, identical row order, and for every
  row identical client name, system label, contract string and status badge. Walk **all** rows.
- Each of the five filters returns the same set in both apps; `Todos` equals the sum of the four.
- The nav highlights Proyectos; `GET /projects` (the old stub URL) 404s; `dashboard.STUBS` is empty
  and `dashboard.stub` has no remaining callers (grep).

---

### Step 2 — Manual project creation

**Build**
- `GET /proyectos/nuevo` + `GET /proyectos/nuevo/clientes` + `POST /proyectos` per §1.4 item 7 and
  §1.6, reusing the wizard's typeahead fragment shape.

**Validate**
- Typeahead shows the same matches Streamlit shows, in the same order, with the same
  `{name} — {empresa}` labels and the same free-text first option.
- ⚠ Create a QA project — ⚠ **with `contract_usd = 10,320.00` and `contract_iva_usd = 0`**, so
  Steps 5–8 can reuse §1.10.5's Jorge-derived reference numbers directly. Confirm in Supabase:
  one row, `proposal_id IS NULL`, `version_id IS NULL`, `status='active'`, notes saved, **and zero
  `project_expenses` / `project_payments` rows** (a manual project seeds nothing).
- Selecting a real client match stores **no** `client_id` (no column) but does store that client's
  `name` as `client_name`.
- Blank name → `Ingresa un nombre de cliente.`, nothing written.
- Keep this QA project; Steps 3–8 use it. Do not delete it until Step 10.

---

### Step 3 — Detail shell + Presupuesto tab, read-only

**Build**
- `projects/page.html` (tab shell) + `_header.html` + `_presupuesto.html`, and
  `projects_common.detail_ctx(pid)` per §1.3.
- All nine tab routes exist and dispatch; the six not yet built render a one-line "en construcción"
  placeholder (**including Facturación and Pagos — they get real content in Steps 7 and 8, so do
  not ship Streamlit's `Disponible en el siguiente paso.` copy here**).
- `POST /<pid>/estado` (status pills).
- Presupuesto renders INGRESOS, the PAGOS block **read-only**, GASTOS and UTILIDAD (items 14,19,20).

**Validate**
- `python -m scripts.validate_phase6` passes.
- For **every** project in the Step 1 baseline, side by side with Streamlit: all four INGRESOS
  cards, the Recibido line (including its percentage, to 2 dp), all six GASTOS rows × six columns,
  and all three UTILIDAD cards match **to the cent**. Walk them all; a one-cent difference is a real
  finding.
- ⚠ Find or construct the **negative-`iva_a_pagar`** case and confirm the label reads
  `Crédito IVA (a favor)` with the negative colouring.
- ⚠ Confirm a project with a **non-zero `contract_iva_usd`** renders `utilidad_bruta =
  (contract_usd − contract_iva_usd) − gastos_base`, **not** `contract_usd − gastos_base` — the bug
  `PLAN_PHASE6.md` §1.2 calls "the single most likely bug in this phase". If no live project has
  one, set it temporarily on the QA project via a REPL, compare against Streamlit, then restore
  `0` (Steps 7–8's reference numbers assume `contract_iva_usd = 0`).
- Status pills: move the QA project `active → paused → active`; the list filter follows; only
  `PROJECT_STATUSES` values are accepted server-side.

---

### Step 4 — Pagos block write paths (Presupuesto)

**Build**
- Per-payment `Guardar` (`POST /<pid>/pago/<payment_id>` → `update_payment`) and `+ Agregar pago`
  (`POST /<pid>/pago` → `add_payment`) per items 15–18.

**Validate**
- On the QA project add **Pago 1 `$7,224.00`** and **Pago 2 `$3,096.00`** (Jorge's 70/30 split on
  `$10,320.00` — Step 8 reuses these exact amounts). The `Pago #` default is `max + 1` each time.
- Mark Pago 1 paid with a date and a bank account → the Recibido line reads
  `Recibido $7,224.00 de $10,320.00 (70.00%)`, matching `scripts/validate_phase6.py`'s Jorge case,
  and Streamlit agrees on refresh. ⚠ **Un-mark it** → `recibido` returns to `$0.00`.
- Blank date and blank bank account persist as `NULL`, not `""`.
- ⚠ Post-Step-0 check: the two new rows carry `onvo_commission_pct = 0`, `onvo_iva_pct = 0`,
  `net_deposited IS NULL`.
- ⚠ **Item 50 check:** saving from this block leaves `onvo_commission_pct` / `onvo_iva_pct` /
  `net_deposited` untouched — verify the payload, then re-verify after Step 8 by classifying a
  payment as ONVO there and then saving it from *here*.
- Double-click Guardar → one write, no duplicate.

---

### Step 5 — The five expense ledgers

**Build**
- `projects_ledger.py` + `_ledger.html` + `_ledger_delete.html` per items 21–27 and §1.6. One
  renderer, five categories, `<categoria>` validated against `EXPENSE_CATEGORIES` minus
  `mano_de_obra` (404 otherwise).

**Validate**
- ⚠ On the QA project's **Equipo** ledger reproduce `scripts/validate_phase6.py`'s Step 4 fixture:
  `Equipo FV`, `$3,679.30`, IVA `0%`, Pagado ✓ → ledger TOTAL `$3,679.30`; Supabase
  `total_with_iva = 3679.30`; Presupuesto `equipo` row costo `3,679.30` / IVA `0.00` / costo total
  `3,679.30` / pagado `3,679.30` / remanente `presupuestado − 3,679.30`; and **utilidad bruta
  `$6,640.70`, IVA a pagar `$0.00`, utilidad neta `$6,640.70`** — the script's own Step 4 numbers,
  now end to end through the UI.
- Edit the row to IVA `13%` → `total_with_iva` = `4157.61`, GASTOS `iva` = `478.31`, `iva_a_pagar`
  goes negative (→ `Crédito IVA`). Set it back to `0%` afterwards.
- ⚠ A blank-Rubro added row inserts nothing (item 25).
- ⚠ `+ Fila` **after typing into two unsaved rows** → both typed rows survive with their values
  (§1.2's round-trip rule — the easiest thing here to get wrong, and the symptom is silently losing
  an operator's typing).
- ⚠ Confirm no write payload contains `total_with_iva`.
- Delete: `✕` → inline confirm; Cancelar leaves the row; Sí removes exactly that row and the TOTAL
  and Presupuesto figures follow.
- ⚠ Confirm delete-by-absence does not exist: submit Guardar cambios with one row's inputs removed
  from the DOM (dev tools) → that row is **untouched** (§0.4 Q4).
- Budget-skeleton dimming (item 24): verify on a promoted project after Step 9, or by setting
  `budgeted_usd > 0, amount_usd = 0` on a QA row now.
- Walk all five categories; each shows only its own rows; `Extras (gastos)` keeps its suffix.

---

### Step 6 — Mano de obra + adelantos

**Build**
- `projects_labor.py` + `_labor.html` + `_labor_delete.html` per items 28–34.

**Validate**
- ⚠ Reproduce the script's Step 5 fixture: worker `Cuadrilla instalación`, cotización `$1,380.00`;
  adelanto 1 `$460.00` (2026-01-15); adelanto 2 `$460.00` → total adelantado `$920.00`, saldo
  pendiente `$460.00`, Supabase `total_advanced = 920.00`, `advances` with two objects numbered 1
  and 2 — and Presupuesto `mano_de_obra` costo `$920.00` with **utilidad bruta `$5,720.70`** (the
  script's Step 5 number, given the Equipo expense from Step 5 above).
- Delete adelanto 1 → `total_advanced` back to `460.00` ⚠ **and the survivor renumbered to 1**.
- ⚠ Edit the worker with a blank name → the old name is kept (item 33).
- Saldo pendiente goes red when advances exceed the cotización; undo.
- ⚠ Grep `webapp/` for `add_expense(` with `mano_de_obra` → zero hits (item 28).
- Delete the worker → the `mano_de_obra` rubro returns to its prior value. ⚠ Then **re-add** the
  worker and both advances, because Step 8's invariance assertion is cleanest with a non-trivial
  P&L in place.

---

### Step 7 — Facturación (new build)

**Build**
- `calculations/project_finance.py`: add `invoice_summary()` per §1.10.4 — additive, pure, no edits
  to existing functions.
- `scripts/validate_phase6.py`: add the "Step 7 — Facturación" section with §1.10.5's fixture
  (including the empty-items case).
- `webapp/blueprints/projects_invoicing.py` + `projects/_facturacion.html` +
  `_factura_delete.html`, per items 35–42 and §1.6.

**Validate**
- `python -m scripts.validate_phase6` passes, **including the new section**, before any UI check.
- ⚠ On the QA project (contract `$10,320.00`, no extras) add the three reference items:
  `Equipos $8,000.00 @ 0%`, `Materiales $1,000.00 @ 13%`, `Servicios $1,000.00 @ 13%`. The rendered
  page must show per-category `8,000.00 / 0.00 / 8,000.00`, `1,000.00 / 130.00 / 1,130.00`,
  `1,000.00 / 130.00 / 1,130.00`; subtotal `10,000.00`; IVA `260.00`; **TOTAL GENERAL
  `$10,260.00`**; and **Δ = −$60.00 in amber** (§1.10.5 layer 2 — the −$625.00 figure is the unit
  test's, which supplies an extra the UI cannot create).
- Set the Servicios item to `$1,060.00 @ 13%` → Δ moves to `+$7.80` and the badge **must stay
  amber** (|Δ| ≥ 0.01); then set it so Δ is exactly `0.00` → the badge turns green. Restore.
- ⚠ **Invariance:** before/after all of the above, the Presupuesto tab's utilidad bruta / IVA a
  pagar / utilidad neta are **byte-identical** (item 40).
- Empty state: delete all three items → `Sin renglones de factura.` plus a three-row zeroed summary
  and Δ = `−$10,320.00` (amber). Re-add them.
- ⚠ Generated columns: confirm an update succeeds (Postgres would reject the statement outright if
  `iva_amount`/`total_usd` were in the payload) **and** read the handler to confirm they are not
  sent.
- `+ Fila` round-trip, blank-Artículo skip, and the delete-confirm flow behave exactly as the
  ledgers' equivalents (item 41) — run the same three checks Step 5 ran.
- The category select rejects anything outside `INVOICE_CATEGORIES` server-side (the column has a
  CHECK constraint; a tampered POST must produce a friendly error, not a 500).

---

### Step 8 — Pagos / ONVO (new build)

⚠ Depends on Step 0 having run. Do not build this on top of un-backfilled rows.

**Build**
- `calculations/project_finance.py`: add `payments_summary()` per §1.10.4 — additive, pure.
- `scripts/validate_phase6.py`: add the "Step 8 — ONVO" section with §1.10.5's fixture, **including
  the utilidad-invariance assertion**.
- `webapp/blueprints/projects_payments.py` + `projects/_pagos.html`, per items 43–50 and §1.6:
  the método toggle, the per-payment breakdown, the footer, the guarded
  `Registrar comisión como gasto Banco`.

**Validate**
- `python -m scripts.validate_phase6` passes, including the new section — in particular
  `commission 173.38 / iva 22.54 / net 7,028.08` and the transferencia case's
  `0.00 / 0.00 / 7,224.00`.
- ⚠ Live, on the QA project's **Pago 1 ($7,224.00)**: it opens as **Transferencia** with
  `$0.00` commission, `$0.00` IVA, **por depositar `$7,224.00`** — ⚠ *not* an implied 2.4%
  (item 50 / §1.10.3; this is the check that proves the Step 0 migration did its job end to end).
- Toggle to **ONVO tarjeta** → the rates prefill `2.4%` / `13%` and the block shows commission
  **`$173.38`**, IVA sobre comisión **`$22.54`**, por depositar **`$7,028.08`**. Guardar → Supabase
  shows `onvo_commission_pct = 0.024`, `onvo_iva_pct = 0.13`, `net_deposited = 7028.08`.
- ⚠ **Invariance (item 48):** utilidad bruta / neta on the Presupuesto tab are **identical** before
  and after that toggle+save. This is the assertion that catches the most likely modelling error on
  this screen.
- Edit the commission to a hand value (e.g. `3%`) → figures recompute; the persisted
  `net_deposited` follows on save. ⚠ Confirm the displayed figure comes from a fresh
  `onvo_breakdown()` and not from the stored column: set `net_deposited` to a wrong value via a
  REPL, reload → the page shows the correct computed number, not the corrupted stored one (item 46).
- Footer: `Total pagado por el cliente $7,224.00`, `Comisión total $173.38`, `IVA sobre comisión
  $22.54`, `Total por depositar $7,028.08` — and ⚠ the `Recibido / Pendiente` line **equals the
  Presupuesto tab's Recibido line to the cent** (§1.10.5 layer 3). Mark Pago 2 paid → both move
  together.
- ⚠ `Registrar comisión como gasto Banco` → exactly one new `project_expenses` row, `category
  = 'banco'`, `amount_usd = 195.92`, `iva_rate = 0`, `notes` containing `onvo:<payment_id>`; the
  Banco ledger TOTAL and the GASTOS `banco` rubro both move by `$195.92`; utilidad bruta drops by
  exactly `$195.92` (a real bank cost, unlike the fee itself). **Click it again → refused with a
  visible message, still one row.**
- ⚠ Round-trip with the Presupuesto block (item 50): after classifying Pago 1 as ONVO, save it from
  the **Presupuesto** tab's row form → `onvo_commission_pct` / `onvo_iva_pct` / `net_deposited`
  are **unchanged**.
- A project with zero payments renders an empty-state footer of zeros, not a crash.

---

### Step 9 — "Mover a Proyecto": the Cotizaciones integration

**Build**
- All six edits in §1.9 — three new routes, the `_detail.html` swap, the `url_for()` fix and the
  docstring fix.

**Validate**
- ⚠ **On a purpose-created QA proposal only** (§4): create a small proposal through the Flask
  wizard, take it to **Ganada**, then promote it. Do **not** exercise this on a real won proposal —
  promotion is one-shot per proposal and there is no UI to undo it.
- The form pre-fills `contract_usd` / `contract_iva_usd` with exactly what Streamlit's form shows
  for the same version, and the budget table has one row per cost line item with the same
  `categorize_line_item()` categories and per-row totals.
- The reconciliation caption's two figures match Streamlit's; the text is verbatim.
- Each schedule preset produces the same amounts Streamlit produces, including ⚠ the
  last-installment rounding absorption (`payment_schedule_for_preset()` L156–163); `Personalizado`
  round-trips edited amounts.
- Editing a budget row's Rubro then hitting `+ Fila` preserves the edit (§1.2).
- Confirmar → exactly one `projects` row; one `project_expenses` row per budget row with
  `amount_usd = 0` and `budgeted_usd` set; the payment schedule rows, all `paid = false` ⚠ **and
  `onvo_commission_pct = 0`** (Step 0's default change, now proven on the promotion path too); the
  browser lands on `/proyectos/<new_id>`.
- ⚠ Re-open the same won proposal → `Ver proyecto →` points at the real project; a hand-crafted
  POST to the promote endpoint returns the inline `Esta propuesta ya fue movida a un proyecto…`
  message, **not a 500** and **not a second row**.
- Grep `webapp/`: zero occurrences of `disponible cuando se migre`, zero hardcoded `/proyectos/`
  strings outside `url_for()`.
- Open the promoted project's ledgers → budget-skeleton rows present, dimmed, with the
  `presupuesto` pill (item 24); the GASTOS `presupuestado` column sums to the promoted budget.

---

### Step 10 — Cutover

**Build**
- Sweep `dashboard.STUBS` (now empty — *working assumption: keep the empty dict and the `stub`
  route; removing them is a one-line change with no benefit*) and confirm no stub links remain.
- ⚠ Fix `webapp/blueprints/dashboard.py`'s `PHASES` list (L8–18): it still shows Fases 4/5/6 as
  "Pendiente" on the landing page. Phase 20's and Phase 21's audits both found this and correctly
  scoped it out; **this phase owns it**, because it is the last phase to touch the nav and because
  "Fase 6 — Módulo Proyectos: Pendiente" is now visibly wrong on the landing page of the app this
  phase just finished. Keep the fix to the status strings.
- Walk the **entire §1.4 checklist (53 items)** against the running app and record the result in
  this document under a new "Built" section — the same way `PLAN_PHASE20_PROPOSALS_JINJA.md` §5 and
  `PLAN_PHASE21_MAINTENANCE_JINJA.md` §5 do. Mark each PASS (live) / PASS (code) / FAIL / WAIVED
  with evidence, and state the legend. ⚠ For items 35–50 the evidence must cite §1.10.5's reference
  numbers, not "matches Streamlit" — there is no Streamlit to match.
- **Fix the documentation drift this phase uncovered** — a deliverable, not a courtesy:
  - `PHASES.md` L24: Phase 6 is **not** "✅ Complete" as written. Replace with an accurate status:
    Steps 1–5 shipped in Streamlit, Step 9 partial, Step 6 (extras editor) still unbuilt, and
    **Steps 7–8 built in Flask by Phase 22**, not in Streamlit — so the Streamlit page still shows
    two placeholders and the Flask page does not.
  - Add a Phase 22 row to `PHASES.md`'s table pointing at this document, naming the port **and** the
    two new screens **and** migration 048.
  - `CONTEXT.md`: add a "Flask/Jinja2 + htmx port of Proyectos" section in the same table format as
    the Cotizaciones (L26–40) and Mantenimiento (L44–59) sections, including §0.2's unbuilt-steps
    reality, the new-construction scope, and §1.10.3's migration with its before/after row counts.
  - `CONTEXT.md` L483: correct the `projects_db.py` row, which implies the invoice/extras surface
    was already user-reachable.
  - `REQUIREMENTS.md`: §5.6's schema snippet shows `onvo_commission_pct numeric(5,4) DEFAULT 0.024`.
    Update it to `DEFAULT 0` with a pointer to migration 048, so the requirements doc stops
    documenting the behaviour this phase deliberately removed.
- ⚠ **QA-data cleanup, verified twice.** Delete every QA project, QA proposal and QA
  expense/labor/invoice row created across Steps 2–9, and re-confirm the database is back at
  Step 1's recorded baseline (project count; no row in any `project_*` table carrying a `QA` marker;
  **no leftover `onvo:` banco expense**). ⚠ There is **no delete-project function** — deleting a QA
  project requires a direct `delete()` on `projects` (children cascade). Record exactly what was
  deleted.
- Raise §0.4 Q7 (fate of the two Streamlit pages) with Oscar, and — now that the Flask app has
  Facturación and Pagos while Streamlit does not — note explicitly that the two apps are **no longer
  feature-equivalent**, which is new information for that decision. **Do not delete the Streamlit
  pages in this step.**

**Validate**
- A full pass over all 53 checklist items with recorded evidence; nothing unaddressed.
- `python -m scripts.validate_phase6` passes with **all six** sections (4 original + Facturación +
  ONVO).
- One complete real-world exercise, end to end, in Flask only, on a fresh QA project: create it →
  add a payment and mark it paid → enter two expenses in two ledgers (one at 13%) → add a worker and
  two advances → add three invoice items and check Δ → classify the payment as ONVO and register its
  commission as a Banco expense → confirm every figure on the Presupuesto, Facturación and Pagos
  tabs against a hand-computed set → change the status to `completed` → confirm the list filter
  follows → delete the QA project and re-verify the baseline.
- ⚠ Scoped diff check: `git diff <phase-21-cutover-sha>..HEAD -- calculations/ database/ pages/
  scripts/` shows **exactly** §1.5's allowed set — two added functions in
  `calculations/project_finance.py`, two added sections in `scripts/validate_phase6.py`, the new
  `048` migration, the `schema.sql` mirror, **and nothing else**. `pages/` must be empty in that
  diff. (Use the phase-local diff, not `main..main_jinja`, which includes Phases 20–21 — Phase 21
  §5.4 learned this the hard way.)
- Every nav item in `base.html` points at a real blueprint; no stub remains anywhere in the app.
- ⚠ Active-nav check on **all ten** project URLs (list + nine tabs), not a sample — Phase 21 §5.5's
  finding #1 applies with five companion modules here instead of three.

---

## 3. Explicit non-goals

- **The INGRESOS extras editor (Phase 6 Step 6).** Oscar's Q3 decision named Facturación and
  Pagos/ONVO; it did not name this. The Presupuesto's extras card stays read-only and
  `add_extra`/`update_extra`/`delete_extra` keep their zero call sites. Facturación's reconciliation
  line reads `project_extras` and is correct with an empty list (it just means Δ compares against
  the bare contract).
- **Phase 6 Step 9's unbuilt half**: no per-project financial columns on the list, no client search
  box. Four columns and a status filter.
- **Any ONVO *API* integration.** This phase records a commission percentage the operator types in.
  It does not call ONVO, does not read a settlement file, and shares no code with VRM Monitor's
  Phase 16 ONVO Pay work (`vrm_api/onvo.py`, a different product in a different repo) — §0.1.
- **Any change to an existing function in `calculations/project_finance.py` or
  `database/projects_db.py`.** Additions only, and only the two functions §1.5 lists. Do not "fix"
  the unused `mark_payment_paid()`, do not delete the now-finally-used invoice CRUD, do not touch
  `onvo_breakdown()`'s round-then-multiply order, and do not change any rounding rule.
- **Any schema change beyond migration 048**, and 048 itself adds no column, drops nothing and
  tightens no constraint (§1.10.3).
- **Project deletion from the UI.** `PLAN_PHASE6.md` §3's non-goal holds: cancel via status. QA
  cleanup happens through SQL/a REPL, deliberately not through a route this phase adds.
- **Receipt uploads / Supabase Storage / any file I/O**, and **no invoice PDF**. Facturación is a
  log that reconciles against the contract, not a document generator. `receipt_path` stays NULL.
- **CRC display.** USD only — `utils/currency.py`'s cache-poisoning bug (`PLAN_PHASE6.md` §4 risk
  #2) is still unfixed and is still a reason not to walk into this for a cosmetic feature.
- **A `clients` foreign key on `projects`**, or any use of the typeahead's `client_id` beyond
  resolving a display name.
- **A Projects ↔ maintenance-property link** (Phase 21 §3 repeated this; it still holds).
- **Fixing the dashboard's `1 + 6N` project KPI query**, or its stale `PHASES` list beyond the
  status strings (Step 10).
- **Backporting Facturación / Pagos to Streamlit.** `pages/04_project_detail.py` keeps its two
  placeholders and is not modified. The two apps stop being feature-equivalent as of this phase, and
  that is a deliberate, documented consequence (Step 10 / §4).
- **Deleting `pages/03_projects.py` / `pages/04_project_detail.py`** or any other Streamlit file
  (§0.4 Q7).
- **Auth, multi-user, concurrency control.** Single internal operator, same as Phase 20 §3 and
  Phase 21 §3.

---

## 4. Risks and tradeoffs

**This is the highest-stakes phase of the three ports, and the scope change raised the stakes
again**: it is the first one to modify shared non-UI code, the first to ship a data migration
against real financial rows, and the first to ship UI with no Streamlit counterpart to check
against. Mantenimiento's worst case was a destroyed visit history; this phase's worst cases are a
corrupted financial record on a real billed project, a permanent un-deletable project row, and a
screen that asserts a commission that was never charged.

1. ⚠ **The 0.024 default is a live correctness problem, not a curiosity — and Step 0 is the only
   thing standing between it and Oscar's books.** Every existing `project_payments` row asserts a
   2.4% ONVO commission nobody chose (§1.10.3). Step 8 builds the first UI that reads that column
   and gives it a one-click "turn this into a Banco expense" button. If Step 0 is skipped, deferred,
   or half-run, the app will show fabricated commissions on real historical payments and offer to
   book them as real expenses. **Step 0 runs first, its audit is recorded, and its `UPDATE` half
   does not run without Oscar's answer to §0.4 Q8.** If the audit finds a row that does *not* match
   the untouched-default signature, the whole premise is wrong for that row — stop, do not
   improvise.
2. **Promotion is one-shot and has no undo.** `promote_to_project()` is guarded by a partial unique
   index, so a proposal can be promoted exactly once, ever — and **there is no delete path for a
   project** (§0.1). Testing "Mover a Proyecto" on a real won proposal permanently attaches a junk
   project to it, removable only by hand-written SQL. Step 9's validation is scoped to a QA
   proposal; Step 10 requires verified cleanup. **This is the one place where a mistake is not
   merely a bug.**
3. **Every ledger / invoice / labor delete is a hard delete.** `delete_expense`,
   `delete_invoice_item`, `delete_labor` and `delete_advance` remove rows outright; `projects`
   cascades to all five child tables. No soft delete, no undo, no backup step anywhere. §1.6 adds
   inline confirms in front of the destructive actions (a disclosed deviation — Streamlit deletes on
   the first click) for exactly this reason.
4. **The `utilidad_bruta` IVA double-count** is, per `PLAN_PHASE6.md` §1.2, "the single most likely
   bug in this phase" — and the Flask port adds a new way to introduce it: computing a figure in a
   Jinja template instead of taking it from `summarize()`. §1.3 rules 1–3 and 7 exist solely to
   prevent this. `scripts/validate_phase6.py` catches the math regression but **cannot** catch a
   template rendering the right number from the wrong source.
5. **Two new screens with no Streamlit oracle.** Every other screen in this phase (and every screen
   in Phases 20–21) could be validated by rendering the same rows in both apps. Facturación and
   Pagos/ONVO cannot. Their entire correctness argument rests on §1.10.5's three layers —
   hand-computed pure-function assertions, a live QA exercise deliberately seeded with a
   `$10,320.00` contract so those same numbers transfer, and cross-screen consistency checks. **A
   coder who validates these two screens by "it looks right" has not validated them.** This also
   means the two new `calculations/` functions are the first money math in this repo written without
   a workbook behind it: their reference numbers come from `PLAN_PHASE6.md`'s own worked examples,
   which were themselves derived from the Jorge Ramírez `Finanzas` workbook — trace them there if
   anything looks off, rather than re-deriving.
6. **Deletion-by-absence in a form-diffed table.** The natural HTML translation of
   `st.data_editor`'s `deleted_rows` is "any DB id missing from the POST body was deleted" — turning
   a truncated POST, a JS error or a `MAX_CONTENT_LENGTH` rejection into silent data loss on a money
   table. §0.4 Q4 forbids it; Steps 5 and 7 both test for it explicitly.
7. **Two independent computations of the same money, deliberately preserved.** A ledger's TOTAL is
   `Σ total_with_iva` (Postgres generated, rounded per row) while the Presupuesto's `costo_total` is
   `round(Σ amount + Σ amount×rate, 2)` (Python, rounded once). Facturación adds the same split
   (generated `iva_amount`/`total_usd` per row vs `invoice_summary()`'s Python aggregation). They
   agree today and can diverge by a cent on adversarial inputs. Streamlit has the same split (§1.3
   rule 5) — **preserve** it rather than "unify" it, because unifying changes what at least one
   surface displays.
8. **Fees must never touch the P&L except through an explicit expense row.** The commission is a
   bank cost, not a revenue reduction: `summarize()` is unchanged, and the only path from an ONVO
   fee into utilidad is the operator clicking "Registrar comisión como gasto Banco" (item 49), which
   writes an ordinary `banco` expense with an idempotency marker. Two things can go wrong here and
   both are checked: making the write automatic (double-counts against a manually entered bank
   charge) and subtracting the fee from `ingresos` (item 48's invariance assertion).
9. **Modifying shared, `main`-visible code for the first time in this porting effort.** Phases 20
   and 21 kept `calculations/` untouched (Phase 21 allowed one additive DB helper). This phase adds
   two functions to `calculations/project_finance.py`, two sections to `scripts/validate_phase6.py`
   and a migration that changes a column default the Streamlit app also inserts through. The
   additions are inert for Streamlit (it never calls them), but **the migration is not** — after
   Step 0, a payment added from the *Streamlit* Presupuesto tab also lands with
   `onvo_commission_pct = 0`. That is the desired behaviour and is strictly more truthful than
   before, but it is a real behaviour change on `main`'s data path and must be named as such in the
   Step 10 documentation.
10. **The two apps stop being feature-equivalent.** After this phase the Flask app has two screens
    the Streamlit app does not. Every prior "if in doubt, check Streamlit" instinct now has two
    exceptions, and §0.4 Q7 (deleting the Streamlit pages) acquires an argument it did not have
    before. Flag it in the cutover rather than letting a future reader discover it by finding a tab
    that exists in one app and not the other.
11. **The validation oracle for the *ported* half may still be thin.** §0.3 flags that nobody has
    checked how many real projects with real ledger data exist. If the answer is "one or two, mostly
    empty", most of items 1–34 get validated on QA data, which proves the code matches the spec but
    not that it matches Streamlit's rendering of real history. Step 1's baseline makes that gap
    visible rather than implicit.
12. **Nine tabs, six modules, one nav rule.** Phase 21 §5.5 found that a companion module
    accidentally creating its own `Blueprint` would silently break `request.blueprint == 'projects'`
    for that module's routes only. With six companion modules here (vs. three there), the same
    failure is likelier and just as quiet. Step 10 checks the active-nav class on all ten URLs.
