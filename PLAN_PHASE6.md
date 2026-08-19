# Phase 6 — Projects Module: Build Plan

**Status:** ready for the coder agent
**Author:** architect agent, 2026-08-15
**Spec sources:** `REQUIREMENTS.md` §5 (+ §3.2, §8), `PHASES.md` "Phase 6 — Projects Module"
**Reference workbook:** `Finanzas - Jorge Ramírez (FV).xlsx` (not in repo; behaviour is transcribed into §5)

---

## Goal

A won proposal can be promoted to a **Project** in one click, opening a database-backed
financial workspace that reproduces the `Finanzas` workbook: a Presupuesto dashboard
(ingresos / pagos / gastos por rubro / utilidad), six expense ledgers, worker advance
tracking, an electronic-invoice log, and ONVO client-payment tracking. "Done" means the
Jorge Ramírez reference project can be created from his Off-Grid proposal and reproduces
the reference numbers exactly (see validation in every step below).

---

## 0. Confirmed context (do not re-derive)

| Fact | Where |
|---|---|
| All five project tables already exist **live in Supabase, empty** | `database/schema.sql` L170–236 |
| `project_expenses.total_with_iva`, `project_invoice_items.iva_amount`/`total_usd` are **GENERATED** columns | schema.sql |
| `project_labor.total_advanced` is a plain numeric — nothing writes it yet | schema.sql L223 |
| `projects.status` CHECK = `active\|completed\|paused\|cancelled` | schema.sql L179 |
| Everything in `database/projects_db.py` and `pages/03_projects.py` / `pages/04_project_detail.py` is a stub | those files |
| The `won` transition hook to hang "Mover a Proyecto" off | `pages/01_proposals.py` L346–377 |
| CRUD reference module to copy in shape | `database/proposals_db.py` |
| Constants already defined: `PROJECT_STATUSES`, `EXPENSE_CATEGORIES`, `INVOICE_CATEGORIES`, `DEFAULT_ONVO_COMMISSION`, `BRAND_*` | `config.py` |
| Proposal cost breakdown shape | `wizard/off_grid.py` L2029–2042 / `wizard/grid_zero.py` L1585 |

**Proposal cost blob shape** (`proposal_versions.data["costs"]`), confirmed in both wizards:

```python
{
  "line_items": [
     {"item": str, "item_en": str, "qty": float|None, "unit_cost": float,
      "total": float, "iva_pct": float, "specs": str, "specs_en": str}, ...
  ],
  "subtotal_usd": float,   # ex-IVA
  "iva_usd": float,
  "total_usd": float,
  "cost_per_wp": float,
}
```

`proposal_versions.total_usd` is the denormalized grand total (IVA-inclusive).
Note `line_items[].total` may be absent on very old rows — fall back to `qty * unit_cost`
(with `qty=None` meaning 1, exactly as `_row_subtotal()` does in the wizard).

**Repo conventions the coder must follow:**
- `from __future__ import annotations` as the *first* line of every new `.py` (Python 3.9 compat, repo-wide).
- No ORM. `get_client()` singleton from `database/supabase_client.py`, direct
  `.table(x).insert/select/update/delete().execute()`.
- Small pure helpers (`_now()`), module docstring after the `__future__` import.
- Money formatting via `utils/formatting.py` (`fmt_usd`, `fmt_pct`, `fmt_crc`). **`fmt_pct`
  expects 0–100, not 0–1** — pass `70.0`, not `0.70`.
- UI idioms from `pages/01_proposals.py`: `st.pills` for state transitions, HTML grid rows +
  a narrow button column for tables, `st.rerun()` after writes, `try/except` → `st.error(f"Error: {e}")`.
  No `st.dialog` anywhere in the repo today — do not introduce it; use an inline container/expander.

---

## 1. DB-layer decisions (resolved — these are not open questions)

### 1.1 INGRESOS "Extras" gets its own table: `project_extras`

**Decision:** new table (migration 020), *not* reuse of `project_invoice_items`, *not* client-side only.

Reasoning:
- `project_invoice_items` is the **factura electrónica log** — it *decomposes* what is invoiced
  into Equipos/Materiales/Servicios. Its rows sum to (roughly) the contract itself. If extras
  were stored there, you could not tell "a line that breaks down the base contract" from
  "an additional work order that *increases* the contract", and any `ingresos = contract_usd + Σ items`
  formula would double count.
- Extras are revenue events with their own attributes the invoice table has no place for:
  approval date, whether they were actually invoiced, free-text justification.
- They cannot be purely client-side: they are user-entered data that must persist.
- They cannot live on `projects` (there is only a `notes` text column, and jsonb-on-parent
  breaks the relational pattern every other ledger follows).

```sql
project_extras (
  id          uuid PK,
  project_id  uuid REFERENCES projects(id) ON DELETE CASCADE,
  description text NOT NULL,
  amount_usd  numeric(10,2) NOT NULL,          -- ex-IVA
  iva_rate    numeric(4,3)  NOT NULL DEFAULT 0,
  total_with_iva numeric(10,2) GENERATED ALWAYS AS (amount_usd * (1 + iva_rate)) STORED,
  approved    boolean NOT NULL DEFAULT true,
  extra_date  date,
  notes       text,
  created_at  timestamptz DEFAULT now()
)
```

Generated column mirrors `project_expenses` deliberately, so the same "never write a generated
column" rule applies uniformly.

### 1.2 Utilidad bruta / neta / IVA a pagar are computed, in a new pure module

**Decision:** no stored aggregates. All of §5.3's derived figures are computed in
`calculations/project_finance.py` — a pure module (no Streamlit, no DB) taking already-fetched
rows and returning a dict. It goes in `calculations/` for the same reason
`datasheet_parser.py` lives there (REQUIREMENTS.md §12 decision #20): that's where this repo
puts logic, not `ai/` or `utils/`. Pure + no I/O is what makes the tester agent's job possible.

Formulas (exact — the coder must not improvise). **Revised 2026-08-17** (migration 022,
following the §1.5 revision — see that section for the full reasoning): `contract_usd` is now
the full quoted total, not an ex-IVA base, so `ingresos_base` can no longer just add it in
directly — `contract_iva_usd` (the real dollar amount of IVA already embedded in it) has to be
stripped out first to compare like with like against `gastos_base` (genuinely ex-IVA):

```
ingresos_base   = (contract_usd - contract_iva_usd) + Σ extras.amount_usd     # both sides ex-IVA
iva_repercutido = contract_iva_usd + Σ (extras.amount_usd * extras.iva_rate)
ingresos_total  = ingresos_base + iva_repercutido
                # == contract_usd + Σ extras.total_with_iva — sanity-check this equality in tests

gastos_base     = Σ expenses.amount_usd + Σ labor.total_advanced
iva_soportado   = Σ (expenses.amount_usd * expenses.iva_rate)
gastos_total    = gastos_base + iva_soportado

utilidad_bruta  = ingresos_base - gastos_base        # BOTH sides ex-IVA
iva_a_pagar     = iva_repercutido - iva_soportado
utilidad_neta   = utilidad_bruta - iva_a_pagar

recibido        = Σ payments where paid = true (amount_usd)
pendiente       = ingresos_total - recibido
```

`contract_iva_rate` (the original column) is **not used anywhere in this formula set** — it's
vestigial after the §1.5 revision, kept only for schema compatibility. Do not reintroduce it into
`project_finance.py`.

**Critical:** `utilidad_bruta` uses `amount_usd`/`(contract_usd - contract_iva_usd)`, **never**
`total_with_iva` or raw `contract_usd`. IVA appears exactly once, in `iva_a_pagar`. Using
`total_with_iva` (or un-adjusted `contract_usd`) in the gross-profit line double-counts tax and is
the single most likely bug in this phase.

Rounding: round to 2 dp only at the *end* of each named figure, never intermediate.

### 1.3 `total_advanced` is written by Python; `balance_pending` is **not** added as a column

**Decision:** `add_advance()` reads the labor row, appends `{number, amount, date}` to the
`advances` jsonb array, recomputes `total_advanced = round(Σ amounts, 2)`, and writes both in a
single `.update()`. `balance_pending` stays a derived value computed in
`calculations/project_finance.py` as `quoted_amount - total_advanced`.

Reasoning: a Postgres GENERATED column cannot aggregate over a jsonb array (generated expressions
must be immutable and cannot contain subqueries/aggregates) — so `total_advanced` *has* to be
written by application code regardless. Given that, adding a stored `balance_pending` column just
to avoid one subtraction in Python buys nothing and creates a second place the schema can drift.
`add_advance()` is the single writer; there is no other code path that mutates advances.

REQUIREMENTS.md §5.7 shows `balance_pending` as a generated column. **The live schema wins** —
part of Step 1 is correcting §5.7 to match reality rather than leaving the doc lying.

### 1.4 ONVO math: computed in Python at write time, persisted, and recomputed for display

`net_deposited` is a plain nullable numeric — something must write it. Decision:

```python
# calculations/project_finance.py
def onvo_breakdown(amount_usd, commission_pct, iva_pct):
    commission = round(amount_usd * commission_pct, 2)
    iva        = round(commission * iva_pct, 2)
    net        = round(amount_usd - commission - iva, 2)
    return {"gross": amount_usd, "commission": commission,
            "iva_on_commission": iva, "net_deposited": net}
```

- IVA is charged **on the commission**, not on the payment (REQUIREMENTS §5.6: "Commission 2.4%
  / IVA on commission / Por depositar").
- Round the commission first, then compute IVA on the rounded commission — deterministic, and
  matches how a payment processor's statement actually reads.
- `add_payment()` / `update_payment()` persist `net_deposited` from this helper.
- The UI **always displays a freshly computed** breakdown from the same helper, so a NULL or
  stale persisted value can never silently misreport. Persisted value exists for reporting/export.
- Bank transfers: `onvo_commission_pct = 0`, `onvo_iva_pct = 0` → `net_deposited == amount_usd`.
  The payments UI has a método toggle (Transferencia / ONVO tarjeta) that sets these; ONVO
  defaults to `DEFAULT_ONVO_COMMISSION` (0.024) and `iva_pct = 0.13`.
- ONVO fees do **not** reduce `ingresos`. They are a bank cost. The ONVO tab offers an explicit
  per-payment "Registrar comisión como gasto Banco" button that inserts a `project_expenses` row
  with `category='banco'` and `notes` containing the marker `onvo:{payment_id}`; the function
  refuses if a row with that marker already exists (idempotency guard). Never automatic — a
  silent write here would double-count against a manually entered bank charge.

### 1.5 `contract_usd` semantics — REVISED 2026-08-17, supersedes the original version below

**Original decision (superseded):** `contract_usd` as the ex-IVA base, with a *blended*
`contract_iva_rate` derived as `iva_usd / subtotal_usd` so `contract_usd * (1 + rate)`
reconstructed the real quoted total. Implemented in Step 2, then caught live: on a real mixed-rate
quote (Oscar Pauly's Grid Zero — equipment/permits at 0%, labor/materials/services at 13%) this
produced a technically-reconciling but meaningless "8.10% IVA" field. User correction: **"the
purpose of having items at 0%/13% IVA is for invoicing... blended does not work. we should keep
the overall project cost as quoted."**

**Revised decision:** IVA in this app is per line item, not per contract — `Facturación`
(`project_invoice_items`, Step 7) is where the real 0%/13% breakdown belongs, matching how CR
invoicing actually works (exempt equipment, taxed services, as separate invoice lines). At the
contract-summary level there's nothing to decompose: `contract_usd` is simply the real quoted
**grand total** (already correctly summing every item plus whatever tax applies to it), and
`contract_iva_rate` stays `0` — there's no additional tax to layer on top of a number that already
includes it.

```python
costs = version["data"].get("costs", {})
contract_usd = float(costs.get("total_usd") or version.get("total_usd") or 0)
contract_iva_rate = 0.0
```

Jorge's Off-Grid quote (no taxed items at all) is unaffected either way: `contract_usd = 10,320.00`,
`rate = 0` — still exactly what PHASES.md's validation expects. Oscar Pauly's Grid Zero quote now
seeds `contract_usd = 12,674.00` (the real total, was wrongly `11,725.00` under the old logic),
`rate = 0`. The promotion form shows both fields pre-filled and **editable**, relabeled
"Monto del contrato (según cotización)" / "IVA adicional sobre el contrato (%)" (help text
clarifies the latter is normally 0) so the UI no longer implies a base+rate decomposition that
doesn't apply here.

**Consequence for the budget-row reconciliation caption**: the seeded `project_expenses` budget
rows sum to each item's own pre-tax `total` (§1.7, unchanged) — that sum is a **cost** estimate and
will *not* equal `contract_usd` (a **revenue** total that includes tax on the taxable items) whenever
a quote has any 13%-rate items. This was never actually the same number; the old blended rate just
coincidentally made them equal. The promotion form now labels both figures separately instead of
implying they should match.

### 1.6 Mano de obra: one source of truth, no double counting

`project_labor` is the authoritative record for labor cost. Rule:

- Presupuesto rubro **Mano de obra — actual** = `Σ project_labor.total_advanced` +
  `Σ project_expenses[category='mano_de_obra'].amount_usd`.
- The MOD tab exposes **no expense-entry form** — the only way to record labor cash is an
  adelanto on a worker row. The second term therefore only ever picks up the zero-amount budget
  seed row (contributes 0.00) unless a human deliberately adds one elsewhere.
- Budget for the rubro still comes from `Σ project_expenses[category='mano_de_obra'].budgeted_usd`,
  same as every other rubro.

This must be commented in `project_finance.py` — it is the non-obvious bit a future reader will
otherwise "fix" into a double count.

### 1.7 Budget seeding: expense rows carry the budget

At promotion, each proposal line item becomes a `project_expenses` row with
`amount_usd = 0`, `paid = false`, `budgeted_usd = line total`, `iva_rate = 0`
(the expense IVA is what *we* pay on the cost, not what we charge — set it when the real invoice
arrives). Category is assigned by this keyword map, applied case-insensitively against `item`:

| Match (substring, lowercase, accent-insensitive) | Category |
|---|---|
| `panel`, `inversor`, `bateria`, `controlador`, `monitoreo`, `cargador` | `equipo` |
| `estructura`, `material`, `cable`, `proteccion`, `tuberia`, `canaliza` | `materiales` |
| `mano de obra`, `instalacion`, `montaje` | `mano_de_obra` |
| `transporte`, `viatico`, `hospedaje` | `viaticos` |
| anything else (`permiso`, `diseño`, `tramite`, …) | `extras` |

The mapping is **shown as an editable table in the promotion form before anything is written**,
so a misclassification is fixed once, by hand, at the only moment it matters. Do not try to make
the keyword map exhaustive.

Consequence: each ledger tab opens pre-populated with zero-amount "budget skeleton" rows. That is
intended (it is the workbook's Presupuestado column) — render rows where `amount_usd == 0 and
budgeted_usd > 0` dimmed, with a small `presupuesto` pill, so they read as placeholders.

### 1.8 Migration trail

The projects tables exist only in `schema.sql`, with no migration behind them. Migration 020 is
written to close that gap: it re-declares all five tables with `CREATE TABLE IF NOT EXISTS`
(verbatim from schema.sql — no-ops against the live DB), then adds the genuinely new objects.
From here on the projects tables have a migration trail like everything else.

---

## 2. Build steps

Each step is a vertical slice: it ends with something the engineer can actually use, and a
validation you can run before starting the next one. Do not start step N+1 until step N's
validation passes.

---

### Step 1 — Schema completion + doc sync

**Build**
- `database/migrations/020_projects_extras.sql`:
  - `CREATE TABLE IF NOT EXISTS` for `projects`, `project_payments`, `project_expenses`,
    `project_labor`, `project_invoice_items` (copy verbatim from `schema.sql` L172–235).
  - `CREATE TABLE IF NOT EXISTS project_extras (...)` per §1.1 above.
  - `ALTER TABLE ... ADD COLUMN IF NOT EXISTS created_at timestamptz DEFAULT now()` on
    `project_payments`, `project_expenses`, `project_labor`, `project_invoice_items`
    (deterministic list ordering; `projects` already has one).
  - `CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_proposal_unique ON projects(proposal_id) WHERE proposal_id IS NOT NULL;`
    — enforces REQUIREMENTS §3.2 "only one version per proposal can be promoted".
  - `CREATE INDEX IF NOT EXISTS idx_project_extras_project_id ON project_extras(project_id);`
  - Header comment in the same explanatory style as `016_equipment_cost_iva.sql`.
- Mirror `project_extras` + the `created_at` columns + the unique index into `database/schema.sql`.
- `REQUIREMENTS.md` §5.7: delete the `balance_pending` generated column from the `project_labor`
  snippet, add a one-line note that it is derived in `calculations/project_finance.py`; add
  `project_extras` to the snippet; add a sentence to §5.3 stating that INGRESOS "Extras" is
  `project_extras`, distinct from the `extras` *expense* category.

**Validate**
- Run the migration against Supabase. Then run it a second time — it must be a clean no-op
  (idempotency is the whole point of the IF NOT EXISTS style).
- `select * from project_extras limit 1;` returns zero rows, no error.
- `insert into project_extras(project_id, description, amount_usd, iva_rate) ...` with a bogus
  project_id fails on FK (proves the constraint), and `total_with_iva` is rejected if supplied
  explicitly (proves it's generated).

---

### Step 2 — `projects_db.py` + promote-to-project + manual creation + minimal projects list

The first usable slice: mark a proposal won → promote → see the project. Also covers creating a
project with no proposal at all (see §6) — same tables, a second entry point.

**Build**
- `database/projects_db.py` — full implementation, shaped exactly like `proposals_db.py`
  (`from __future__ import annotations` first line, `_now()` helper, `get_client()`, no ORM).
  **Keep every existing function signature byte-for-byte**; add new ones alongside:
  - existing: `promote_to_project`, `get_project`, `list_projects`, `update_project_status`,
    `add_payment`, `mark_payment_paid`, `list_payments`, `add_expense`, `list_expenses`,
    `add_labor`, `add_advance`, `list_labor`, `add_invoice_item`, `list_invoice_items`
  - add: `update_project`, `update_payment`, `delete_payment`, `update_expense`, `delete_expense`,
    `update_labor`, `delete_labor`, `update_invoice_item`, `delete_invoice_item`,
    `add_extra`, `list_extras`, `update_extra`, `delete_extra`,
    `get_project_bundle(project_id)` → `{"project":…, "payments":[…], "expenses":[…], "labor":[…], "invoice_items":[…], "extras":[…]}`
    (one call per tab render, so the dashboard isn't six round-trips scattered through the UI).
  - `promote_to_project(proposal_id, version_id, contract_usd)`: fetches the proposal + version
    itself (for `client_name`, `system_type`, cost blob), raises a clear `ValueError` if a project
    already exists for that proposal, inserts `projects`, then bulk-inserts the seeded
    `project_expenses` budget rows and the seeded `project_payments` schedule. Accept optional
    keyword args for `contract_iva_rate` (vestigial), `contract_iva_usd` (real, §1.2/§1.5 — added
    migration 022), the (already engineer-reviewed) budget rows, and the payment schedule,
    defaulted so the bare 3-arg call still works.
  - **Never include generated columns in any insert/update payload**
    (`total_with_iva`, `iva_amount`, `total_usd` on invoice items, `total_with_iva` on extras) —
    Postgres errors out. Filter payload dicts explicitly; add a module-level
    `_GENERATED = {...}` set and strip it in one shared `_clean(payload)` helper.
- `pages/01_proposals.py`: inside `_render_detail_panel`, when `status == "won"`, render a
  promotion block below the status row (`st.pills(["Mover a Proyecto"])` matching the existing
  pill idiom, or an existing-project link if one exists). Clicking expands an inline
  `st.container` form showing: contract base + IVA rate (pre-filled per §1.5, editable), the
  editable budget-mapping table (`st.data_editor`, columns: Concepto / Rubro (selectbox over
  `EXPENSE_CATEGORIES`) / Presupuesto USD), and a payment-schedule preset picker
  (70/30 default · 50/40/10 · personalizado). Confirm → `promote_to_project(...)` →
  `st.success` → `st.switch_page("pages/04_project_detail.py")` with
  `st.session_state["selected_project_id"]` set (same pattern as `_open_version()`).
  Do **not** disturb the existing prospect-promotion logic at L359–369.
- `pages/03_projects.py`: replace the stub. Header + `st.pills` status filter (Todos / Activos /
  Completados / Pausados / Cancelados) + one HTML grid row per project (client name · system type ·
  contract · status badge) with a `›` button column, `st.switch_page` to the detail page.
  Reuse the `_pill()` / row-grid markup style from `01_proposals.py`; give projects their own
  `STATUS_LABELS`/`STATUS_BADGE` maps (Activo / Completado / Pausado / Cancelado).

**Validate — Jorge Ramírez**
1. Open his Off-Grid proposal, transition to **Ganada**.
2. "Mover a Proyecto" → form pre-fills contract base **$10,320.00**, IVA rate **0**, and a budget
   table with one row per proposal line item summing to $10,320.00.
3. Confirm with the 70/30 preset. Verify in Supabase:
   - `projects`: 1 row, `contract_usd = 10320.00`, `contract_iva_rate = 0`, `status = 'active'`,
     `client_name` and `system_type = 'off_grid'` copied from the proposal.
   - `project_payments`: 2 rows — `7224.00` and `3096.00`, both `paid = false`.
   - `project_expenses`: one row per line item, all `amount_usd = 0`, `Σ budgeted_usd = 10320.00`.
4. Attempt to promote the same proposal again → friendly error, no second row (unique index holds).
5. Project appears in `pages/03_projects.py` and opens the (still stub) detail page.

---

### Step 3 — `project_finance.py` + Presupuesto dashboard + PAGOS

**Build**
- `calculations/project_finance.py` — pure, no imports from `database/` or `streamlit`:
  - `summarize(project, payments, expenses, labor, extras) -> dict` implementing §1.2 exactly,
    returning every named figure plus `by_category` (per rubro: `costo`, `iva`, `costo_total`,
    `pagado`, `presupuestado`, `remanente`) covering all six `EXPENSE_CATEGORIES` even when empty.
  - `labor_balance(row) -> float` (§1.3).
  - `onvo_breakdown(...)` (§1.4).
  - `remanente = presupuestado - costo_total` per rubro.
- `pages/04_project_detail.py`: replace the stub. Header card (client · system type · status pills
  over `PROJECT_STATUSES` · back link to the list), then `st.tabs([...])` with the nine tabs
  wired up but only **Presupuesto** implemented in this step:
  `Presupuesto · Banco · Equipo · Materiales · Mano de obra · Viáticos · Extras · Facturación · Pagos`.
  Load once via `get_project_bundle()`.
  - **INGRESOS** block: `contract_usd` (full total, §1.5) · `contract_iva_usd` (IVA already
    included, informational) · extras subtotal (0 for now) · gran total (`ingresos_total`).
  - **PAGOS** block: one row per payment (número · monto · pagado toggle · fecha · cuenta ·
    guardar), a "+ Agregar pago" form, and a "Recibido X de Y (Z%)" line using `fmt_usd`/`fmt_pct`.
  - **GASTOS** block: the six-rubro table from `by_category` (all zeros at this point).
  - **UTILIDAD** block: utilidad bruta / IVA a pagar / utilidad neta as three metric cards using
    `BRAND_GREEN` for positive, red for negative.
- `scripts/validate_phase6.py` — no DB, no Streamlit. Feeds hand-built dicts into
  `summarize()`/`onvo_breakdown()` and asserts the reference numbers below. Extend it in each
  later step. This is the tester agent's primary artifact.

**Validate — Jorge Ramírez (the PHASES.md reference case)**
- Mark Pago 1 **$7,224.00** paid, date set, bank account `BAC`. Zero expenses entered.
- Dashboard must show:
  - Total ingresos **$10,320.00**, recibido **$7,224.00 (70.00%)**, pendiente **$3,096.00**
  - Total gastos **$0.00**
  - **Utilidad bruta $10,320.00 · IVA a pagar $0.00 · Utilidad neta $10,320.00**
- `scripts/validate_phase6.py` asserts the same three figures from `summarize()` with no DB.

---

### Step 4 — Expense ledgers (Banco / Equipo / Materiales / Viáticos / Extras)

**Build**
- One shared renderer, `_render_expense_ledger(project_id, category, rows)` in
  `pages/04_project_detail.py`, used by five tabs. Columns per REQUIREMENTS §5.4:
  Rubro (description) · Valor USD · IVA · Total · Fecha · Pagado · Comentarios.
- Editing pattern: `st.data_editor(..., num_rows="dynamic", key=f"ed_{category}")` over a
  DataFrame carrying a hidden `id` column (excluded via `column_order`), plus an explicit
  **Guardar cambios** button. On save, read `st.session_state[f"ed_{category}"]` and dispatch on
  its `added_rows` / `edited_rows` / `deleted_rows` keys → `add_expense` / `update_expense` /
  `delete_expense`, then `st.rerun()`. Do not attempt a value-level DataFrame diff.
- Do **not** show `total_with_iva` as editable — display-only, computed by Postgres, and never in
  the write payload.
- Running TOTAL row at the bottom of each ledger (`fmt_usd`).
- Wire the real numbers into the Presupuesto GASTOS table (already reading `by_category`).
- The `Extras` **expense** tab is labelled `Extras (gastos)` to disambiguate from INGRESOS extras,
  which live in the Presupuesto tab, not in a tab of their own.

**Validate — Jorge Ramírez**
- In the **Equipo** tab add: descripción `Equipo FV`, valor **$3,679.30**, IVA 0%, pagado ✓.
- Ledger TOTAL shows **$3,679.30**; Supabase `total_with_iva = 3679.30`.
- Presupuesto → GASTOS row `Equipo FV`: costo **3,679.30**, IVA **0.00**, costo total **3,679.30**,
  pagado **3,679.30**, presupuestado = the seeded equipment budget,
  **remanente = presupuestado − 3,679.30** (assert the relation, not a hardcoded number — the
  budget depends on the actual proposal line items).
- **Utilidad bruta $6,640.70 · IVA a pagar $0.00 · Utilidad neta $6,640.70.**
- Add the same case to `scripts/validate_phase6.py`.

---

### Step 5 — Mano de obra + adelantos

**Build**
- MOD tab: one card per worker — nombre · rol · cotización · adelantos list · total adelantado ·
  **saldo pendiente** (from `labor_balance()`). "+ Agregar trabajador" form
  (`add_labor`), "+ Adelanto" form per worker (monto + fecha → `add_advance`), edit/delete.
- `add_advance()` per §1.3: append to jsonb, recompute `total_advanced`, single `.update()`.
  Advance `number` is `len(advances) + 1`.
- No expense-entry form on this tab (§1.6). Add the §1.6 comment in `project_finance.py`.
- Wire `Σ total_advanced` into the Presupuesto's `mano_de_obra` rubro.

**Validate**
- Worker `Cuadrilla instalación`, cotización **$1,380.00**; adelanto 1 **$460.00** (2026-01-15),
  adelanto 2 **$460.00**.
- Row shows total adelantado **$920.00**, saldo pendiente **$460.00**; Supabase
  `total_advanced = 920.00` and `advances` has 2 objects with `number` 1 and 2.
- Presupuesto rubro Mano de obra costo = **$920.00**; utilidad bruta drops by exactly $920.00.
- Delete one advance (if delete is implemented) → `total_advanced` back to 460.00. No orphan drift.

---

### Step 6 — INGRESOS extras (revenue) + full IVA a pagar

**Build**
- Presupuesto → INGRESOS gains an "Extras (órdenes adicionales)" sub-table: descripción · monto ·
  IVA · total · fecha · notas, with add/edit/delete via the same data_editor+Guardar pattern.
- `summarize()` already accounts for extras — verify both the `ingresos` and `iva_repercutido`
  terms now move.
- Gran total income line = `ingresos_base + iva_repercutido`.

**Validate**
- On the Jorge project (equipo expense $3,679.30 + labor $920.00 present), add extra
  `Orden adicional — traslado de tablero`, **$500.00 @ 13%**.
- Expect: ingresos base **$10,820.00**, IVA repercutido **$65.00**, gran total **$10,885.00**,
  utilidad bruta **$6,220.70** (10,820.00 − 4,599.30), IVA a pagar **$65.00**,
  utilidad neta **$6,155.70**.
- Delete the extra → all figures return to the Step 5 values exactly.
- Same case asserted in `scripts/validate_phase6.py`.

---

### Step 7 — Facturación

**Build**
- Line-item editor over `project_invoice_items`: artículo · categoría (selectbox over
  `INVOICE_CATEGORIES`) · tasa IVA · monto. `iva_amount` and `total_usd` are display-only
  (generated) and **must not appear in write payloads**.
- Category summary block per §5.5: Equipos / Materiales / Servicios each with subtotal, IVA, total;
  then TOTAL GENERAL.
- **Reconciliation line** (this is the cross-check that makes §1.1's decision safe):
  `Δ = TOTAL GENERAL − (contract_usd + Σ extras.total_with_iva)` — `contract_usd` is already the
  full total (§1.5 revision), no `* (1 + rate)` needed. Show green when `|Δ| < 0.01`, amber
  otherwise, with the delta in `fmt_usd`. Facturación is never a source for the profit math —
  only a reconciliation view.

**Validate**
- Add: `Equipos` **$8,000.00 @ 0%**, `Materiales` **$1,000.00 @ 13%**, `Servicios` **$1,000.00 @ 13%**.
- Per-category: Equipos 8,000.00 / 0.00 / 8,000.00 · Materiales 1,000.00 / 130.00 / 1,130.00 ·
  Servicios 1,000.00 / 130.00 / 1,130.00.
- TOTAL GENERAL **$10,260.00** (subtotal 10,000.00 + IVA 260.00).
- Reconciliation Δ vs 10,885.00 (contract 10,320.00 + extra 565.00) = **−$625.00** → amber badge.
- Confirm utilidad bruta/neta are **unchanged** by anything on this tab.

---

### Step 8 — Client payments / ONVO tab

**Build**
- Pagos tab per §5.6: header row (proyecto · contrato total), then one block per payment —
  método toggle (Transferencia / ONVO tarjeta), monto bruto, comisión %, IVA sobre comisión %,
  comisión USD, IVA USD, **por depositar**, pagado toggle + fecha + cuenta bancaria, notas.
- All figures from `onvo_breakdown()`; `net_deposited` persisted on write.
- Footer breakdown: total pagado por el cliente · comisión total · IVA sobre comisión total ·
  total por depositar · recibido vs pendiente.
- Per-payment "Registrar comisión como gasto Banco" button with the `onvo:{payment_id}`
  idempotency guard (§1.4).

**Validate**
- Jorge's Pago 1 ($7,224.00) as **Transferencia**: comisión $0.00, IVA $0.00,
  por depositar **$7,224.00**.
- Switch it to **ONVO tarjeta** (2.4% + 13% IVA): comisión **$173.38**, IVA sobre comisión
  **$22.54**, por depositar **$7,028.08**. `net_deposited = 7028.08` persisted.
- Utilidad bruta must **not** change when the método changes (fees are a bank cost, not a revenue
  reduction) — this is the assertion that catches the most likely modelling error here.
- Click "Registrar comisión como gasto Banco" → one `banco` expense of $195.92
  (173.38 + 22.54) appears; click again → refused, still one row.
- `onvo_breakdown` cases asserted in `scripts/validate_phase6.py`.

---

### Step 9 — Projects list polish + wiring + docs

**Build**
- `pages/03_projects.py` cards per §5.8: contract · recibido (amount + %) · gastos vs presupuesto ·
  utilidad. Search box (client name) + status filter, matching `01_proposals.py`'s layout.
  Use `get_project_bundle()` per project only if the list is small; otherwise compute list-level
  aggregates with a few grouped queries — do not N+1 the whole bundle per card.
- Status transitions on the detail header via `st.pills` (active → completed/paused/cancelled,
  paused → active) → `update_project_status`.
- `app.py`: replace the hardcoded `—` in the "Proyectos activos" card with
  `len(list_projects(status="active"))`, wrapped in the same `try/except` as the proposal counts.
- Docs: `PHASES.md` status table row 6 → ✅ Complete; `CONTEXT.md` "Phase completed"/"Phase next";
  a `REQUIREMENTS.md` changelog entry (v3.8 → v3.9) recording the §1.1–§1.7 decisions.

**Validate**
- Projects list shows the Jorge card: contract $10,320.00 · recibido $7,224.00 (70.00%) ·
  gastos $4,599.30 · utilidad $6,220.70 (with the Step 6 extra present).
- Home dashboard "Proyectos activos" reads 1.
- Move status to `completed` → card moves under the Completados filter, no error, CHECK constraint
  never violated (only `PROJECT_STATUSES` values are offered).

---

## 3. Explicit non-goals for Phase 6

- **No receipt uploads.** `project_expenses.receipt_path` stays NULL; Supabase Storage wiring for
  receipts is out of scope.
- **No CRC display toggle.** USD only. (See the `utils/currency.py` bug in Risks — do not walk
  into it for a cosmetic feature.)
- ~~No projects created without a proposal.~~ **Struck 2026-08-15 — see §6.** Manual creation
  (no proposal) is in scope for Step 2, alongside promotion.
- **No project deletion from the UI.** Cancel via status instead.
- **No PDF/Excel export** of the Presupuesto.
- **No maintenance register.** That is Phase 10 (REQUIREMENTS §4.7) and shares only the nav item.
- **No multi-currency, no cost/price margin modelling** beyond presupuestado-vs-actual.
- **No `clients` foreign key on `projects`.** The client is reachable via
  `projects.proposal_id → proposals.client_id`; `client_name` is already denormalized for display.

---

## 4. Risks / tradeoffs

1. **Generated columns are the most likely runtime failure.** Including `total_with_iva`,
   `iva_amount`, or invoice `total_usd` in any insert/update payload makes Postgres reject the
   whole statement. The `_clean(payload)` helper in Step 2 exists specifically to prevent this;
   it must be used by every write function, not just the obvious ones.
2. **`utils/currency.py` has a latent cache-poisoning bug.** `get_exchange_rate()` writes
   `json.dumps({...})` (a *string*) into the jsonb `app_settings.value` column, so the next read
   gets a `str` and `cache.get("cached_at")` raises `AttributeError` — outside the `try`, so it
   propagates. This is why the CRC toggle is a non-goal. Fix it separately, not in Phase 6.
3. **Budget seeding uses selling prices as budgets.** Proposal line items are what the client is
   charged; equipment `cost_usd` in the catalog doubles as both cost and price today. So
   "remanente" reads as *margin remaining on that rubro*, not *unspent cost budget*. That matches
   how the workbook is actually used, but it is a real semantic the engineer should confirm
   (see open question 1).
4. **Keyword-based category mapping will misclassify custom line items.** Mitigated entirely by
   making the mapping editable in the promotion form. Resist the urge to grow the keyword table.
5. **`total_advanced` correctness depends on `add_advance()` being the only writer.** Single-user
   app, so no concurrency risk; but any future bulk-edit path over `project_labor.advances` must
   recompute it. Comment this at the top of the labor section of `projects_db.py`.
6. **`by_category` must enumerate all six `EXPENSE_CATEGORIES`**, not just categories with rows,
   or the Presupuesto table silently loses rubros as soon as the project starts empty.
7. **Rounding.** Round only at named-figure boundaries. Rounding intermediates makes the
   $7,028.08 ONVO assertion drift by a cent and turns a validation into a debugging session.
8. **9 tabs is a lot of Streamlit state.** Namespace every widget key with the project id and the
   tab (`f"{project_id}_{category}_..."`), or switching projects will resurrect the previous
   project's editor state — a failure mode this repo has already hit (see the `_clear_wizard()`
   helper in `01_proposals.py`).
9. **Two `fmt_usd()`/`fmt_crc()` results in the same `st.caption()`/`st.markdown()` call (no
   `unsafe_allow_html`) triggers Streamlit's LaTeX math rendering**, since it parses `$...$` pairs
   as inline math — the two literal `$` signs become math delimiters, silently eating the text
   between them and mangling spacing (e.g. "Pago 2" collapses to "Pago2"). Hit twice already in
   Step 3 alone (the payment-schedule caption in `pages/01_proposals.py`, the "Recibido X de Y"
   caption in `pages/04_project_detail.py`) — **every remaining step has running-total captions
   with 2+ money figures** (ledger ledger totals in Steps 4-9, the ONVO breakdown in Step 8), so
   expect to hit this again. Fix: escape with `.replace("$", "\\$")` on the composed string before
   passing to `st.caption`/`st.markdown`, or build the string with `unsafe_allow_html=True` HTML
   instead (HTML-embedded `$` signs render fine, as the Presupuesto INGRESOS cards already do) —
   either works, just don't pass a plain string with 2+ literal `$` to a non-HTML markdown call.

---

## 5. Open questions — resolved with the user (2026-08-15)

1. **`budgeted_usd` seeding** → **seed from the quote**, editable at promotion. (as planned)
2. **Negative `IVA a pagar`** → **use the default**: `utilidad_neta` follows the §5.3 formula
   arithmetically, but the figure is labelled "Crédito IVA" and coloured differently when negative
   so it's never mistaken for profit.
3. **Payment-schedule presets** → **yes, 70/30 is the standing default**, with 50/40/10 and
   custom available.
4. **`completed` status** → **use the default**: label only, ledgers stay editable.

## 6. New requirement — projects without a proposal (added 2026-08-15)

**"We should be able to open a project that doesn't necessarily have a proposal. Sometimes minor
or different scope-related projects are won."** This changes §3's non-goal #3 — struck below —
and adds a second creation path alongside promotion.

**Decision:** `projects.proposal_id`/`version_id` are already nullable in the live schema (no
`NOT NULL`, confirmed in schema.sql L172–176) — no schema change needed. The partial unique index
from Step 1 (`WHERE proposal_id IS NOT NULL`) already tolerates any number of `proposal_id IS NULL`
rows, so manual projects don't need special-casing there either.

- **New DB function** (Step 2): `create_project_manual(client_name, system_type, contract_usd, contract_iva_rate=0.0, contract_iva_usd=0.0, client_id=None, notes=None) -> dict` (signature updated for the §1.2/§1.5 `contract_iva_usd` addition). Inserts a bare `projects` row
  (`proposal_id=None`, `version_id=None`, `status='active'`) — no seeded `project_expenses` budget
  rows and no seeded `project_payments` schedule, since there is no proposal cost blob to derive
  them from. The engineer adds budget lines and a payment schedule by hand from the Presupuesto tab,
  exactly as they'd fill in a blank workbook.
- **New UI** (Step 2, `pages/03_projects.py`): a "**+ Nuevo proyecto**" button next to the status
  filter, separate from the promotion flow on the proposals page. Opens an inline form: client
  (typeahead search against `clients_db.search_clients()` — reusing the same lookup
  `wizard/common.py`'s Step 2 already uses — falling back to free-text `client_name` with no
  `client_id` if no match, same "not every client needs a formal record" tolerance the wizard
  already has for prospects) · system type (`SYSTEM_TYPES` selectbox) · contract amount · IVA rate
  · notes. Confirm → `create_project_manual(...)` → `st.switch_page` to the detail page.
- **Everywhere else is unchanged**: `get_project_bundle()`, `project_finance.summarize()`, and all
  six ledger tabs work identically whether `proposal_id` is set or not — none of them read
  `proposal_id`. The only UI difference is the (already-planned) detail-page header link "Ver
  propuesta" — render it only when `proposal_id is not None`.
- **Non-goal #3 in §3 is struck**: "No projects created without a proposal" no longer applies.
  The remaining non-goals (no receipt uploads, no CRC toggle, no deletion, no export, no
  maintenance register, no multi-currency) are unaffected.

**Validate (added to Step 2):**
- "+ Nuevo proyecto" → client "Ferretería Los Robles" (no match in `clients` → free-text),
  `off_grid`, contract `$1,850.00`, IVA 0. Confirm.
- `projects` row created with `proposal_id IS NULL`, `version_id IS NULL`.
- Detail page opens with zero expense/payment rows (no budget skeleton — nothing to seed from) and
  no "Ver propuesta" link.
- Appears in the projects list identically to a promoted project; status transitions and every
  ledger tab work the same as the Jorge Ramírez case, just starting from an empty Presupuesto
  instead of a pre-seeded one.
