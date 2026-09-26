# Phase 23 — Distribución de utilidad en Cotizaciones: un solo margen general, repartido proporcionalmente al costo de cada ítem

**Status:** plan drafted, all open questions resolved — ready for the coder agent
**Author:** architect pass (this session), 2026-09-25
**Branch:** `main_jinja` (worktree `Claude-main_jinja`)
**Builds on:** the Cotizaciones costs step shipped by `PLAN_PHASE20_PROPOSALS_JINJA.md` (Step 7 of both
wizards) and the Proyectos financial data shipped by Phase 6 / `PLAN_PHASE22_PROJECTS_JINJA.md`
(`calculations/project_finance.py`), used here only as a source for suggesting a default margin.
**Spec source:** `calculations/profit-distribution-quotation-system.md` (Oscar's own written spec) —
**superseded by this revision**, see the note directly below.
**Filename convention:** `23` confirmed as the next free number — `PHASES.md`'s phase table (L16–39)
ends at row 22; `database/migrations/` ends at `048_project_payment_commission_truth.sql`, so this
phase's migration is `049_...`.

---

## Revision note (2026-09-25) — this plan replaces the fixed-anchor/residual design, not just amends it

The first pass at this plan followed `calculations/profit-distribution-quotation-system.md` literally:
a fixed $ anchor per equipment model, a fixed % margin anchor per scaling category, and one residual
line solving backwards to hit a target total. Oscar reviewed it and asked for something simpler
instead: **one overall margin field**, with the app auto-distributing that profit across every item
proportionally to its own cost — no per-category anchors, no residual, no target-total backsolve.

This is a deliberate, informed trade-off, not an oversight: the original spec's whole argument was
"stop recomputing the distribution per quote, so identical items can't drift between quotes for no
visible reason" (the Casa Refugio incident — same panel, $121.30 in one quote, $133.34 in the next).
A single margin dial recomputed per quote **can** still make the same panel show two different prices
across two quotes, if the margin differs between them. Confirmed with Oscar and accepted: the
difference now always traces to one visible, deliberately-typed number (the margin field) rather than
to silently-different distribution logic — which keeps the spec's real goal (nothing is ever
untraceable) without keeping its specific mechanism. What both designs still share: **no line item is
ever labeled "Utilidad"** — profit is embedded in every item's shown price instead.

---

## Goal

The Cotización costs table gets exactly one new input: an overall profit margin. Every cost line that
should carry profit shows `precio = costo_real × (1 + margen)`; the one exception is a flat pass-through
fee that never gets marked up. No line item is ever labeled "Utilidad," and the total the client sees
is simply whatever falls out of summing the marked-up lines — never a number the estimator has to
force by hand.

---

## 0. Confirmed context (do not re-derive)

### 0.1 Where the Cotizaciones costs table actually lives — unchanged from the first pass

Two step-7 modules exist, not three — Hybrid has no cost step of its own, it delegates to Off-Grid's
verbatim (`webapp/blueprints/wizard.py` L66: `7: {"grid_zero": gz_s7_costs, "off_grid": og_s7_costs,
"hybrid": og_s7_costs}`):

| Module | System types | Line items today |
|---|---|---|
| `webapp/wizard_steps/gz_s7_costs.py` | Grid Zero | Paneles, Inversores, Monitoreo (equipment); Diseño Eléctrico y Administración, Mano de obra, Materiales eléctricos, Transporte de equipo, Permiso de Interconexión (services) |
| `webapp/wizard_steps/og_s7_costs.py` | Off-Grid + Hybrid | Paneles, Inversor/cargador, Baterías, Controlador de carga, Monitoreo (equipment); Diseño y gestión, Mano de obra, Materiales eléctricos, **Estructura de montaje** (hardcoded inline in `_seed_line_items()` L259–263, not catalog-sourced) |

Both modules' `_finalize(blob, items)` is "the one place every action derives the footer from" (their
own docstrings) — this phase's calc-engine change lands entirely inside that one function in each
module, same as the first pass planned.

`proposals/generator.py`'s `cost_items` builder (L470–491, feeds the client-facing PDF) whitelists
fields explicitly (`item`, `item_en`, `qty`, `specs`, `specs_en`, `total`) rather than spreading the
whole line-item dict, so a new internal-only field (`real_cost`, `markup_eligible`) cannot leak into
the client PDF by construction, unaffected by this revision.

### 0.2 The math: "distribute profit proportionally to each item's cost weight" is the same thing as "apply one uniform % markup to every item's cost"

Worth stating explicitly since it's what makes this design simple to build. If `total_profit` is split
across items in proportion to each item's own cost (`peso_i = costo_i / costo_total`):

```
profit_i = total_profit × (costo_i / costo_total)
precio_i = costo_i + profit_i = costo_i × (1 + total_profit / costo_total) = costo_i × (1 + margen)
```

`total_profit / costo_total` is the same ratio for every item — call it `margen`. So there is no
weighting loop to build: **every eligible line's shown price is just its own real cost times `(1 +
margen)`**, where `margen` is the one field Oscar types (or accepts as suggested). The subtotal, IVA,
and total the client sees are then whatever falls out of summing those already-marked-up lines — the
total is an **output** of this phase's design, never an input to solve backwards from (unlike the
superseded residual design, which needed a target total and a circularity-resolving formula). This
also means **no reconciliation assert and no negative-residual warning are needed** — there is no
residual line whose value could go negative, and nothing to reconcile against, because nothing is
being solved backwards.

### 0.3 Equipment catalog `cost_usd` is real distributor cost — confirmed, and it needs no new column

Same fact the first pass found (`database/equipment_db.py` sources `cost_usd` straight into the quote
line item's `unit_cost`; the admin form labels it "Costo (USD)"). Under this design that's exactly the
right field to use directly as `costo_real` in §0.2's formula — **no `sale_price_usd` anchor column is
needed at all**, which was the first pass's biggest schema addition. This phase changes zero equipment
table schema.

### 0.4 Decisions confirmed with Oscar (2026-09-25)

1. **One overall margin field, app-suggested, editable, proportional-by-weight distribution** — §0.2
   shows this collapses to a uniform `costo × (1+margen)` rule.
2. **Equipment catalog prices are real distributor cost** (§0.3) — used directly, no separate anchor.
3. **"Diseño Eléctrico y Administración" / "Diseño y gestión" gets a small notional real cost**
   (e.g. estimated design/admin hours × rate) instead of being dropped — it then participates in the
   markup exactly like every other line, with no special "residual" role left to play. Its notional
   cost reuses the existing `service_defaults.unit_cost_usd` default (already the field this row seeds
   from today) — no new column needed, just a nonzero default value going forward instead of `0.00`.
4. **"Permiso de Interconexión" (the flat $1,000 government interconnection fee) stays pass-through,
   no markup** — it is bought and passed straight through, not resold at a margin. This is the one
   line excluded from §0.2's formula.
5. **"Estructura de montaje" moves into the shared `service_defaults` catalog for all three system
   types** (carried over unchanged from the first pass's own §0.5 finding — orthogonal to the
   anchor-vs-uniform-margin question, still correct here). Consequence: `og_s7_costs.py`'s hardcoded
   append (L259–263) must be deleted once the catalog carries it universally, or Off-Grid/Hybrid quotes
   would show it twice; `gz_s7_costs.py` needs no equivalent change since its catalog loop already
   picks up any enabled, applicable row automatically.

---

## 1. Resolved design

### 1.1 Schema — migration `049_cost_distribution_markup.sql`

No equipment-table changes. `service_defaults` gains one boolean flag and one new catalog row:

```sql
-- Step 1's first action, unchanged from the first pass: confirm the live column type of
-- service_defaults.system_types (no committed migration defines it) before writing SQL against it.

ALTER TABLE service_defaults ADD COLUMN IF NOT EXISTS markup_eligible boolean NOT NULL DEFAULT true;

UPDATE service_defaults SET markup_eligible = false WHERE item = 'Permiso de Interconexión';

-- Confirmed §0.4 item 3: give the residual-turned-ordinary "Diseño" rows a nonzero starting real cost
-- instead of 0.00, so they aren't priced at $0 under the new formula. Placeholder value — Oscar sets
-- the real number; this is only a safe non-zero seed so the line isn't blank on a fresh quote.
UPDATE service_defaults SET unit_cost_usd = 300.00
  WHERE item IN ('Diseño Eléctrico y Administración', 'Diseño y gestión') AND unit_cost_usd = 0;

-- Confirmed §0.4 item 5 (carried over from the first pass): fold the Off-Grid-only hardcoded
-- "Estructura de montaje" row into the catalog, for all three system types — system_types left NULL,
-- which both step-7 modules' existing filter (`not r.get("system_types") or "<type>" in
-- r["system_types"]`) already reads as "applies everywhere."
INSERT INTO service_defaults (item, item_en, unit_cost_usd, iva_pct, specs, specs_en, enabled,
  sort_order, system_types, markup_eligible)
VALUES ('Estructura de montaje', 'Mounting structure', 0, 0.13, 'Arreglo de módulos', 'Module array',
  true, 25, NULL, true)
ON CONFLICT (item) DO NOTHING;
```

**Quote blob** (`costs`, a JSON column, no migration): gains one new field, `margin_pct` (e.g. `0.28`
for 28%), replacing the superseded design's `target_total_usd` entirely. Nothing else about the line
item shape changes — the existing `unit_cost` field is simply *reinterpreted* as "real cost" for every
`markup_eligible` row, exactly as it already behaves for `Permiso de Interconexión` today (typed
directly, no markup applied). No new per-line field (like the superseded design's `real_cost`) is
needed, because there's no longer a separate "typed cost" vs. "typed shown price" distinction to make —
there's one typed number (cost) and one computed number (shown price).

### 1.2 Calc engine — small addition to `_finalize()`, not a rewrite

```python
def _shown_price(unit_cost: float, item_name: str, margin_pct: float, eligible: dict[str, bool]) -> float:
    """costo_real × (1 + margen) for every markup-eligible row; pass-through otherwise (§0.4 item 4)."""
    if not eligible.get(item_name, True):   # unknown/custom rows default eligible=True
        return unit_cost
    return round(unit_cost * (1 + margin_pct), 2)
```

`_finalize()` becomes: look up `eligible = {row["item"]: row.get("markup_eligible", True) for row in
_load_service_defaults()}` (equipment rows are never in `service_defaults`, so they default eligible —
correct, since equipment always carries the markup per §0.4 item 1) → for every line, replace
`unit_cost` with `_shown_price(unit_cost, item["item"], margin_pct, eligible)` **before** the existing
per-row subtotal/IVA/total loop, which otherwise runs byte-for-byte unchanged. `margin_pct` comes from
`blob["costs"].get("margin_pct") or 0.0` — a fresh or old-shape draft with no margin set yet behaves
exactly like today (0% markup, i.e. today's actual "equipment and everything else priced near raw
cost" reality), so no draft breaks.

No reconciliation assert, no negative-residual warning, no circularity resolution — §0.2 already showed
why none of those are needed under this design.

### 1.3 Suggested default margin — one pure function, reusing existing Proyectos data

Following this codebase's pure/impure split (`calculations/*` never imports `database`):

- **New read function**, `database/projects_db.py:list_margin_benchmark_rows(system_type: str | None =
  None) -> list[dict]`: for every project (optionally filtered), returns `{system_type, ingresos_base,
  gastos_base}` — both already computed per-project by `calculations/project_finance.py:summarize()`,
  just read back across projects instead of for one.
- **New pure function**, `calculations/pricing_benchmarks.py:suggest_margin_pct(rows, system_type) ->
  float | None` — average `(ingresos_base - gastos_base) / gastos_base` across comparable past
  projects, prioritizing same-`system_type` rows, returning `None` (UI falls back to a blank/0% field)
  when there's no comparable history yet. Always reports the sample size `n` used, so the UI can show
  "sugerido con N proyectos comparables" rather than presenting a thin sample as authoritative.

Per-line real-cost suggestions (the first pass's other benchmarking function) are **not** part of this
revision's core ask — the estimator still types each line's real cost by hand, exactly as they already
type a price by hand today; only the interpretation of that number changes (cost, not shown price), and
only the markup on top of it becomes automatic. Left as a clearly-scoped future enhancement, not built
now (§3).

### 1.4 UI changes

- **Costs step template** (`webapp/templates/wizard/_s7_gz_costs.html` and the Off-Grid/Hybrid
  equivalent — exact filenames confirmed at Step 1): add one **Margen de utilidad (%)** input,
  pre-filled by §1.3's suggestion when available, with a caption naming the sample size; the existing
  cost column's header changes from an implicit "precio" to an explicit **Costo real**; add one new
  read-only **Precio mostrado** column showing the computed `costo × (1+margen)` (or `= costo` for
  `Permiso de Interconexión`, visibly marked "sin margen" so the estimator isn't confused about why
  that one row never moves when the margin field changes).
- **Admin catalog** (`_services_panel.html`): no new per-item margin field (there's no per-category
  anchor anymore) — only exposes whatever default `unit_cost_usd` each service seeds a fresh quote
  with, same as today, plus the new `markup_eligible` toggle (defaulting on, off only for Permiso).
- **Recompute wiring**: same live-recompute htmx pattern already in place (`paso/7/tabla` POST on field
  blur) — the margin field joins the same round trip, no new interaction model.

### 1.5 Validation

The only thing worth asserting explicitly: every `markup_eligible` row's shown price equals `round(costo
× (1+margen), 2)` and `Permiso de Interconexión`'s shown price always equals its typed cost exactly,
verified directly rather than assumed — there's no backwards-solved figure left in this design that
could silently disagree with its own inputs.

---

## 2. Build steps

**Step 1 — Schema — ✅ done and verified 2026-09-26** (migration `049_cost_distribution_markup.sql`
applied by Oscar via the Supabase SQL Editor, `python -m tools.run_migration_049` passing all 4 checks:
`markup_eligible` present on all 6 rows, `false` only on Permiso de Interconexión, Diseño's starting
cost is $300 (Oscar's placeholder, editable anytime via admin), Estructura de montaje present with
`system_types=NULL`.)
*Build:* confirm `service_defaults.system_types`'s live column type; write and apply migration
`049_cost_distribution_markup.sql` (§1.1); fold "Estructura de montaje" into the catalog for all three
system types; set a real (not placeholder) default `unit_cost_usd` for the two Diseño rows with Oscar.
*Validate:* every `service_defaults` row has the correct `markup_eligible` value (`false` only for
Permiso de Interconexión); the new Estructura row is visible to all three system types via the existing
`_load_service_defaults()` filter.

**Step 2 — Calc engine + UI — ✅ core done and verified 2026-09-26** (`_shown_price()` +
`_finalize()` change landed in both `gz_s7_costs.py` and `og_s7_costs.py`; `og_s7_costs.py`'s
hardcoded Estructura append deleted; Margen field + Costo real/Precio mostrado columns added to both
templates. **Real bug found and fixed during verification**: `database/equipment_db.py:
list_service_defaults()` explicitly whitelisted its selected columns and had never been updated to
include the new `markup_eligible` field — every row silently came back with it missing, so every row
defaulted to markup-eligible and Permiso de Interconexión was getting marked up too. Fixed by adding
`markup_eligible` to that `.select()`; re-verified live (screenshot + a direct Python round-trip)
that Permiso now stays flat at cost while every other line scales with the margin field. Admin `_services_panel.html`/`admin_services.py` `markup_eligible` toggle also added (both the
batch-edit table and the single add/edit form) and verified via a direct server-side POST round
trip (toggled Estructura de montaje off then back on, confirmed against the live DB both times).)


*Build:* `_shown_price()` and the `_finalize()` change (§1.2) in both `gz_s7_costs.py` and
`og_s7_costs.py`; delete `og_s7_costs.py`'s hardcoded Estructura append (§0.4 item 5); `margin_pct`
added to the `costs` blob shape; the Margen input + Costo real / Precio mostrado columns (§1.4) on both
wizards' templates.
*Validate:* a fresh Grid Zero and a fresh Off-Grid/Hybrid quote each show exactly one "Estructura de
montaje" line; setting the margin field to e.g. 20% marks up every eligible line by exactly 20% and
leaves Permiso de Interconexión untouched; a quote drafted before this phase (no `margin_pct` in its
blob) opens and computes identically to today (0% markup); the client-facing PDF's `cost_items` still
only ever carries the existing whitelisted fields (§0.1), re-verified live against a generated PDF.

**Step 3 — Suggested margin — ✅ done and verified 2026-09-26** (`database/projects_db.py:
list_margin_benchmark_rows()` + `calculations/pricing_benchmarks.py:suggest_margin_pct()` built;
wired into both wizards' `build_context()` so a draft that has never had `margin_pct` set gets the
suggested value pre-filled, with a caption naming the sample size and whether it's same-system-type
or a mixed fallback. Verified with synthetic rows (correct same-type averaging, correct fallback
when no same-type history exists, correct skip of a zero-cost row) and against the live DB: this
Supabase project currently has **0 rows in `projects`** (no quote has been promoted to a project
yet), so `suggest_margin_pct()` correctly returns `None` everywhere today and the field falls back
to a blank/0% default with no suggestion shown — confirmed live in the browser, no crash, no
misleading number. The suggestion will start appearing automatically once real projects exist.)

**Step 4 — Rollout + documentation — ✅ done 2026-09-26** (`PHASES.md` gained a Phase 23 row;
`CONTEXT.md` gained a matching "Cotizaciones: single-margin profit distribution" section, in the same
Status/Plan/What's-NOT-decided/Run-it table format Phases 20–22 used, explicitly flagging that
`calculations/profit-distribution-quotation-system.md` no longer matches what shipped. §4's checklist
walked below — 6 of 7 items clean, 1 pre-existing unrelated bug found and flagged, not fixed.)

---

## 3. Non-goals (explicitly out of scope this phase)

- **Per-category fixed margin anchors and the target-total residual design** — the entire first pass's
  mechanism, deliberately superseded (see the Revision note).
- **Preventing price drift across quotes when the margin differs** — explicitly accepted (§ Revision
  note); the one guarantee kept is that any such drift traces to the one visible margin field, never to
  silently different logic.
- **Per-line real-cost benchmarking suggestions** — deferred (§1.3); the estimator still types each
  line's real cost by hand, same as today.
- **Retroactively re-pricing any already-sent quote.**
- **Deciding the actual default `unit_cost_usd` for the two Diseño rows, or the actual `markup_eligible`
  set beyond Permiso** — Step 1 seeds safe placeholders; Oscar sets the real numbers afterward through
  the existing admin UI.

## 4. Do-not-drop checklist — walked 2026-09-26, all 7 addressed

1. ✅ **Verified live.** `Permiso de Interconexión` is the only row with `markup_eligible = false`
   (both a direct DB read and both step-7 modules' rendered output confirmed this, including after a
   real admin-panel round trip).
2. ✅ **Verified live + via direct Python round-trip.** Every eligible line's shown price equals
   `round(costo_real × (1+margen), 2)` exactly, checked at `margen=0` (reproduces pre-phase totals —
   confirmed the QA fixture's total was unchanged at $1,550) and `margen=0.20`.
3. ✅ **Verified via direct seed check.** Both `gz_s7_costs._seed_line_items()` and
   `og_s7_costs._seed_line_items()` produce exactly one "Estructura de montaje" row each.
4. ✅ **Verified live.** The pre-existing QA fixture (predates this phase, no `margin_pct` in its
   saved blob) opened, rendered, and computed correctly with `margin_pct` defaulting to 0.
5. ✅ **Verified by code inspection.** `proposals/generator.py`'s `cost_items` builder (L470–491)
   whitelists `item`/`item_en`/`qty`/`specs`/`specs_en`/`total` explicitly — this phase added no new
   keys to that whitelist, so `margin_pct`/`markup_eligible`/`unit_price_shown` cannot reach it.
6. ✅ **Fixed 2026-09-26** (same day, separate follow-up commit from the rest of this phase).
   Margin logic itself never special-cased Hybrid — the bug was upstream, in item selection:
   `og_s7_costs.py:_load_service_defaults()`'s filter hardcoded the literal string `"off_grid"`
   rather than reading the draft's actual system type, so a real Hybrid quote (which also routes
   through this same module) was filtered as if it were Off-Grid — silently dropping "Permiso de
   Interconexión" even though the catalog explicitly tags it `system_types=['grid_zero','hybrid']`.
   Predates Phase 23 (the hardcoded string was never touched by this phase's own edits) — found
   while auditing this checklist item, fixed as a scoped follow-up rather than folded silently into
   the profit-distribution change. Fix: `_load_service_defaults()`, `_get_current_prices()` and
   `_refresh_prices_core()` all gained a `system_type` parameter, threaded through every call site
   from a new `_system_type(blob)` helper reading `blob["meta"]["system_type"]`. Verified directly:
   `_seed_line_items()` for a synthetic Off-Grid blob still correctly excludes Permiso; the same for
   a Hybrid blob now correctly includes it, and its `markup_eligible=False`/`unit_price_shown=1000.0`
   still hold correctly even with a nonzero margin applied.
7. ✅ Both `CONTEXT.md` (new section, above) and this plan's own Revision note flag that
   `calculations/profit-distribution-quotation-system.md` no longer matches what shipped.
