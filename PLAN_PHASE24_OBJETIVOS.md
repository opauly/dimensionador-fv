# Phase 24 — Objetivos: a goals step that produces an equipment-free "sweet spot" recommendation, then checks the chosen design against it

**Status:** plan revised 2026-10-06 — every open question from the first draft is now answered (§0.3, §0.5) except one design
detail Oscar asked to have explained first: the shape of the range around the sweet spot (§0.5 Q9, §1.2). Ready to build Steps 1–2.
The renumber in §1.5 is still the riskiest part of the phase and is isolated as its own verified Step 2.
**Author:** architect pass (this session), 2026-10-04, revised 2026-10-05 and 2026-10-06
**Branch:** `main_jinja` (worktree `Claude-main_jinja`)
**Builds on:** the wizard shipped by `PLAN_PHASE20_PROPOSALS_JINJA.md`; the calibrated static design-tier model already in
`calculations/sizing_off_grid.py` (`OffGridDesignTier` / `HybridDesignTier`, calibrated in `docs/design-calibration-2026-08.md`);
Phase 23's pattern for plan → verified build steps → audit checklist.
**Filename convention:** `24` confirmed as the next free number — `PHASES.md`'s table ends at row 23.

---

## Goal

Today the wizard sizes a design **from whatever equipment the engineer picks**, then recommends a scenario tied to that equipment.
Nothing in the wizard asks what the system is *for*, and the assumptions that decide whether a design is "enough" — autonomy,
reserve, PV coverage, inverter headroom — are hardcoded constants the user never sees.

Phase 24 adds an **Objetivos** step (all three system types) where those goals are stated explicitly. The goals then do two jobs:

1. **Input to a recommendation block that exists before any equipment is chosen** — the best design for these goals and this load
   profile, the "sweet spot": PV kWp, inverter kW, battery kWh (Off-Grid/Hybrid) or PV kWp / inverter kW (Grid Zero), computed from
   the loads, the irradiance and the goals alone.
2. **Yardstick for a goals-vs-design check** — once equipment is chosen in Step 6 (unchanged), a pass / warn / fail strip shows
   whether that selection meets the sweet spot and the goals, and by how much, so Oscar can decide to keep it or pick something
   else. Everything in Step 6 and after stays exactly as it is today.

An AI-written sanity note sits on top of the deterministic numbers. It comments; it never calculates.

"Done" means: for each system type, Oscar can state goals once, see a target he can sanity-check against his own judgement, pick
equipment as today, and see per row whether the design meets each goal and by how much — with the target block and the check strip
unable to disagree with each other because they share one set of formulas (§1.3).

---

## 0. Confirmed context (do not re-derive)

### 0.1 What exists today

| Fact | Where |
|---|---|
| The wizard is a fixed 8-step sequence (1 Cliente, 2 Tipo e idioma, 3 Sitio, 4 Cargas/Distribuidora, 5 Demanda/Consumo, 6 Equipos, 7 Costos, 8 Revisión) dispatched through dicts keyed by step number and system type | `webapp/blueprints/wizard.py` L53–78 (`STEP_MODULES`, `STEP_TEMPLATES`) |
| Hybrid delegates Steps 6–8 to the Off-Grid modules (`og_s6_equipment`, `og_s7_costs`, `og_s8_review`) — only Steps 4–5 differ | same dispatch table |
| **A calibrated static design-tier model already exists**: three tiers per system type (Mínimo / Recomendado / Máxima), each a policy bundle — Off-Grid: `reserve_soc_pct`, `autonomy_days`, `pv_design_factor`, `solar_resource_basis`, `inverter_loading_target_pct`, `growth_energy_pct`, `growth_peak_pct`, `expansion_provision`; Hybrid: `reserve_soc_pct`, `backup_nights`, `cycling_nights`, `battery_basis`, `pv_coverage`, `inverter_islanded_loading_target_pct`, growth, expansion | `calculations/sizing_off_grid.py` L860–1050 |
| `generate_design_scenarios()` / `generate_design_scenarios_hybrid()` already accept a `tiers=` argument and size battery, PV array and inverter from loads + the tier policy, then fit them to the chosen equipment | same file L1140, L1314 |
| **…but they are not wired into production.** Their only caller is the Streamlit TEST page (`pages/02b_new_proposal_test.py` → `wizard/design_scenarios_test.py`). Production Step 6 — Streamlit *and* this Flask port — still runs the legacy day-by-day `generate_reliability_scenarios()` | `webapp/wizard_steps/og_s6_equipment.py` L401; `wizard/design_scenarios_test.py` docstring |
| The tier constants are explicitly **PROVISIONAL** (off-grid rests on 3 installed sites, one with a degraded array) and produce larger quotes than anything in service | comment block above `_OFF_GRID_DESIGN_TIERS` |
| `autonomy_days` is **already a user input** — Off-Grid Step 4 (Cargas) stores `consumption.autonomy_days` (0.5–7 days, half-day steps, default 1.0) and Step 6 passes it to the legacy generator | `webapp/wizard_steps/og_s4_loads.py` L219–244; `og_s6_equipment.py` L384 |
| Grid Zero sizing takes `panel_count` as an **input** (`size_system(...)`); there is no equipment-independent sizing function for it. Its zero-export logic is the daytime-consumption fraction (an AI estimate, `ai/daytime_fraction.py`, computed in Step 6) | `calculations/sizing_grid_zero.py`; `gz_s6_equipment.py` (`coverage_ai`) |
| Reusable check outputs already exist: inverter loading % + headroom flag, `assess_growth_readiness()`, `run_daily_energy_balance_check()`, `estimate_hybrid_savings_pct()`, `monthly_savings_table()` | `sizing_off_grid.py`, `sizing_grid_zero.py` |
| Load estimation is **deterministic code on purpose** — the estimator's own docstring records an AI-computed estimate that said 265 kWh/day for a house needing ~100 | `calculations/load_profile_off_grid.py` L9 |
| Convention: a Flask blueprint never holds an AI prompt; every prompt lives under `ai/` (Phase 20 §1.7) | `ai/daytime_fraction.py` docstring |

### 0.2 Why this changes the shape of the work

Oscar's goals map almost one-to-one onto the **existing tier policy fields** — autonomy → `autonomy_days`, depth of discharge →
`reserve_soc_pct`, inverter headroom → `inverter_loading_target_pct`, growth → `growth_*_pct`. So Objetivos is best understood as
**an editable, user-owned tier** (a "custom tier"), with the three calibrated tiers as one-click presets — not a new parallel concept.
That keeps the constants calibrated against fleet data as the starting point instead of inventing a second set.

The calibrated model is not in production (Step 6 still uses the legacy simulation), so the check strip will sometimes judge a
legacy scenario against calibrated policy. Oscar's direction (2026-10-05) is that Step 6 and everything after it stay as they are,
so the strip states that plainly rather than hiding it (§1.4).

### 0.3 Decisions confirmed with Oscar (2026-10-04)

1. **All three system types**, each with goals specific to it.
2. **A new "Objetivos" step in the wizard** (not a sub-block inside Equipos).
3. Goals serve **both** as inputs to the initial suggestion block **and** as the yardstick for a goals-vs-design check of the chosen
   equipment/scenario.
4. The initial block is **AI-driven** in the sense of an AI-assisted initial check — numbers stay deterministic (Oscar accepted
   the recommendation to use AI for commentary only; see §1.6).
5. *(2026-10-05)* The block is a **recommendation made with no equipment selected** — "the best take for the objectives and the load
   profile, the sweet spot" — which Oscar then compares against whatever he selects in Step 6. **All the rest remains the same**:
   Step 6's scenarios, Step 7 costs and Step 8 review are not modified (this resolves Q1 as option A).
6. *(2026-10-05)* **`main_jinja` only; the Streamlit wizard is retired** — no compatibility with it is built or preserved (this
   resolves Q8).
7. *(2026-10-06)* **Objetivos is the only place design goals are entered.** Off-Grid's autonomy-days field leaves Step 4 (Q2).
8. *(2026-10-06)* **Grid Zero's main goal is bill reduction as a percentage of kWh, not colones** (Q3). The goal is measured on
   energy, so it needs no tariff; the existing colones read-outs elsewhere in the wizard are unaffected.
9. *(2026-10-06)* **The step is mandatory: the app does not let a draft move on without proper objectives set** (Q4). Defaults
   pre-fill the fields but never count as "set" until the user confirms them (§1.8). This replaces the earlier assumption that a
   skipped step silently keeps calibrated defaults.
10. *(2026-10-06)* **Goals are internal only** — never in the client PDF (Q5).
11. *(2026-10-06)* **Grid Zero's daytime fraction is computed on first view of Objetivos** (Q6), and cached so it is not recomputed
    on every visit.
12. *(2026-10-06)* **Drafts already past Step 5 when this ships open with default goals** (Q7) and are not blocked (§1.8).

### 0.4 Working assumptions

- None outstanding. The two assumptions of the first draft (skipped goals keep defaults; goals stay out of the PDF) were replaced by
  Oscar's decisions 9 and 10 above.

### 0.5 Open questions for Oscar

1. ~~Which policy model owns the check?~~ **Resolved 2026-10-05: option A.** Objetivos edits the calibrated tier fields, the
   recommendation block uses the calibrated formulas, and Step 6 keeps its legacy scenarios untouched. Making goals drive Step 6's
   scenarios stays out of scope (§3).
2. ~~Where does autonomy live?~~ **Resolved 2026-10-06: Objetivos only.** Step 4's field is removed; old drafts keep reading their
   saved `consumption.autonomy_days` as the fallback value for Objetivos' autonomy goal, so there is never a second live value.
3. ~~Grid Zero's goal set.~~ **Resolved 2026-10-06:** the main goal is the **monthly kWh reduction %**; the maximum DC/AC ratio and
   an optional cap on system kWp stay as secondary fields.
4. ~~Defaults when a goal is skipped.~~ **Resolved 2026-10-06: a goal cannot be skipped** — the step is mandatory (§1.8). The
   Mínimo / Recomendado / Máxima presets remain the entry point that pre-fills the fields.
5. ~~Goals in the PDF?~~ **Resolved 2026-10-06: internal only.**
6. ~~Grid Zero's daytime fraction timing.~~ **Resolved 2026-10-06: compute on first view of Objetivos**, cached.
7. ~~Existing drafts.~~ **Resolved 2026-10-06: default goals**, not blocked (§1.8).
8. ~~Does the Streamlit wizard stay in use?~~ **Resolved 2026-10-05: retired.** The step-progress compatibility layer a shared
   draft would have needed is dropped (§1.5). Deleting the Streamlit files is a separate action, not part of this phase — and note
   that `wizard/draft.py` and `wizard/state.py` are imported by the Flask app, so `wizard/` cannot simply be removed.
9. **How should the range around the sweet spot work?** *(Oscar asked how it would work — similar to the current scenarios?
   based on Objetivos?)* **Proposed:** three columns per quantity — **Piso · Punto óptimo · Techo** — like the current
   Mínimo / Recomendado / Máxima scenarios but with no equipment, and **centered on Oscar's own goals** rather than on fixed
   presets. The middle column is exactly his goals. The outer two apply the *same step sizes the calibrated tiers have between
   Mínimo→Recomendado and Recomendado→Máxima* to his values (for example off-grid autonomy 2.0 / 2.25 / 2.5 days means ∓0.25 day
   around whatever autonomy he entered), clamped to each field's valid range. Why not simply show the Mínimo and Máxima presets:
   once a goal is customised beyond a preset (say 4 days of autonomy) the sweet spot would land above the "ceiling", which is
   incoherent. Reading: below the Piso the goals are not met; above the Techo the extra capacity is over-building. *Pending
   Oscar's reaction to this explanation.*

---

## 1. Design

### 1.1 Goal fields per system type

The Objetivos step opens with a preset selector (Mínimo aceptable / Recomendado / Máxima autonomía + crecimiento) that fills the
fields from the calibrated tier; every field stays editable. Editing any field marks the set "Personalizado".

| System type | Goal fields (all editable) |
|---|---|
| **Off-Grid** | autonomy days · margen ante falla de FV (`reserve_soc_pct`, worded as the code comment advises — *not* "reserva SoC", since an off-grid system has no min-SoC setting) · PV coverage factor (× daily load) · solar-resource basis (average month / worst month) · inverter loading ceiling % (headroom) · growth energy % · growth peak % · expansion provision (none / one / two) |
| **Hybrid** | reserve SoC % (a real inverter setting here) · backup nights · cycling nights · battery basis (critical / critical + comfort / whole building) · PV coverage target · islanded inverter loading ceiling % · growth · expansion · **monthly kWh reduction target %** (same kWh basis as Grid Zero; the existing `estimate_hybrid_savings_pct()` read-out is colones-based, so the achieved value comes from its `self_consumed_kwh_month` ÷ whole-home kWh instead) |
| **Grid Zero** | **monthly kWh reduction target %** (main goal; annual average of the monthly reduction) · maximum DC/AC ratio · optional cap on system kWp |

Depth of discharge: the battery chemistry's own rated DoD is an *equipment* property, so it is not a goal — the goal is the reserve
window (`reserve_soc_pct`), and the check strip reports whichever of the two is stricter, same rule `generate_design_scenarios()`
already applies.

### 1.2 The equipment-free recommendation block ("sweet spot")

Shown on the Objetivos step itself, before Equipos exists in the flow. Computed on every render from `consumption` (loads, daily
kWh, peak), Step 3 irradiance and the goals — never persisted, so it can't go stale. The headline number per quantity is the
**sweet spot** (the goals as stated). It is shown as three columns — **Piso · Punto óptimo · Techo** — where the outer two are the
goals shifted by the calibrated tiers' own step sizes and clamped to each field's range (Q9: centered on Oscar's goals, not on
fixed presets, so a customised goal can never put the sweet spot outside its own band). Read as "below the Piso the goals are not
met; above the Techo you are over-building". Formulas are the ones in `generate_design_scenarios*()`, minus the "fit to the
chosen equipment" part:

- **Off-Grid** — PV kWp = daily kWh × PV factor ÷ (**annual-average** daily yield × healthy-array PR 0.88) — the factors were
  measured that way, so the solar-resource basis (average / worst month) is an adequacy *gate*, not the sizing basis ·
  battery nominal kWh = daily kWh × autonomy days ÷ (usable window × round-trip η 0.95 × inverter η 0.96), usable window =
  min(100 − reserve SoC, **reference DoD 80%**) · inverter kW = peak demand ÷ loading ceiling. Growth is *not* folded into the
  equipment size — consistent with the calibrated generators it is reported as expansion readiness.
  *(Corrected 2026-10-06 against the code: the first draft had the worst-month basis, no PR, and a growth-inflated inverter.)*
- **Hybrid** — battery from backup/cycling nights × night-load basis; PV from the coverage target × healthy-array PR; inverter from
  the islanded loading ceiling — as `generate_design_scenarios_hybrid()`.
- **Grid Zero (new — no existing function)** — smallest kWp whose **kWh reduction** meets the goal under the **same average-month
  zero-export model Step 6 already uses** (`gen = kWp × average monthly kWh/kWp`; useful = min(gen, average monthly kWh ×
  daytime fraction)), so the sweet spot and Step 6's numbers can never diverge. kWp = goal % × average monthly kWh ÷ average
  monthly kWh/kWp; the attainable ceiling is simply the daytime fraction. The daytime fraction is computed on first view of
  Objetivos and cached (Q6). Inverter kW = kWp ÷ max DC/AC ratio. No tariff is involved. If the goal exceeds what daytime consumption can absorb without
  storage, the block says so ("techo alcanzable sin baterías: X %") instead of returning an impossible kWp — and the step will
  not confirm such a goal without the user acknowledging it (§1.8).

Each figure is displayed as "target ≈ N" with the assumption it rests on visible beside it (e.g. "cobertura 3.25×"). The
chemistry's real depth of discharge is unknown before equipment is chosen, so the battery figure assumes the generators' own
**80% reference DoD**, stated beside the number; the actual rating is applied in the check strip.

### 1.3 One set of formulas

The target block and the check strip must not be able to disagree, and the Off-Grid/Hybrid formulas already exist inside
`generate_design_scenarios*()`. So the formula core is **lifted out into pure functions** (new `calculations/design_targets.py`) that
both the target block and the existing generators call — behaviour-preserving for the generators (§4 checklist item 1 pins their
output before and after). Grid Zero's new sizing function lives in the same module.

### 1.4 The goals-vs-design check strip

Placed with Step 6 (Equipos, now Step 7). A row per quantity — PV, battery, inverter — and per goal, status ✅ cumple / ⚠️ justo / ❌ no cumple, with the achieved number, the sweet spot, the band and the delta, so Oscar can tell "meets it" from "close enough" from "choose something else". Fed by the chosen
equipment and scenario already in the blob (`equipment.chosen_scenario` for Grid Zero; `equipment.array`, `battery_bank`,
`inverter_qty` for Off-Grid/Hybrid):

| Goal | Achieved value comes from |
|---|---|
| PV kWp vs target | chosen array kWp |
| Autonomy / backup nights | chosen battery bank usable kWh ÷ daily (or night) load |
| Inverter headroom | existing `inverter_load_ratio_pct` |
| Growth readiness | existing `assess_growth_readiness()` |
| kWh reduction % (Hybrid, Grid Zero) | Grid Zero: `size_system()` net consumption vs. consumption; Hybrid: `estimate_hybrid_savings_pct()`'s `self_consumed_kwh_month` ÷ whole-home kWh (kWh basis, not its colones `savings_pct`) |
| DC/AC ratio (Grid Zero) | chosen kWp ÷ chosen inverter kW |

Under Q1 option A, the strip also states when it is judging the legacy scenario against the calibrated policy, so a "no cumple" is
read as "this scenario was not built for these goals", not as a bug.

### 1.5 Step placement and renumbering — the phase's biggest risk

Objetivos goes between Demanda/Consumo (5) and Equipos, so Equipos, Costos and Revisión become Steps **7, 8, 9**. Steps 1–5 do not
move. A read-only audit of everything that depends on the 1–8 numbering found:

**What breaks silently if the renumber is done naively**
- **`meta.step_reached`** is a bare integer meaning "furthest step unlocked", read in four places (`wizard.py` guard and `abrir`,
  `proposals.py` "Continuar" link, `shell.html` breadcrumb). There is no schema/version field on the draft blob and no migration
  mechanism for it. After a naive renumber an old draft saved at 7 (Costos) resumes on Equipos, one saved at 8 (Review) resumes on
  Costos, and — because the guard allows `n <= step_reached + 1` — an old step-8 draft can jump straight to the new Review,
  never visiting Objetivos while the breadcrumb marks it done.
- **21 routes** for Equipos/Costos/Revisión carry a literal path (`/paso/6/...`, `/paso/7/...`, `/paso/8/...`) **and** a literal
  `_guard(vid, N)`; templates reach them through endpoint names, so the templates mostly survive, but a route moved without its
  guard number silently loses its step-ahead protection. `paso_post` branches on literal `n == 6` / `n == 7`, and the new step needs
  its own branch or it falls through to the generic `else` and never advances.
- **Three parallel structures** must shift in lockstep — `STEP_MODULES`, `STEP_TEMPLATES` (`wizard.py` L55–78) and the two label
  lists in `webapp/wizard_steps/common.py` — otherwise the breadcrumb and the content disagree or a step renders `not_built.html`.
- Two raw f-string URLs build `/paso/<step_reached>` (`proposals.py` L306, L423).
- User-facing text naming steps: "Paso 6" in `_s5og_demanda.html` (L50, 52, 79) and `_s4h_body.html` (L12) becomes "Paso 7";
  "Paso 7" in `admin/_services_panel.html` (L30, 40) becomes "Paso 8". References to Pasos 3–5 are unaffected.

**No Streamlit compatibility is needed** (Oscar, 2026-10-05), which removes what would otherwise have been the plan's most
intricate piece: no dual-written numbering, no legacy mirror, no worry about a Streamlit autosave rewriting the value.

**Decision — one numbering, one marker, one helper.**
1. Draft progress stays in `meta.step_reached`, now in the new 1–9 numbering, and a new `meta.wizard_rev = 2` marker says which
   numbering a draft is in.
2. A single helper (`draft.effective_step_reached(meta)`) returns the step in the new numbering: if `wizard_rev` is absent the draft
   is old, so map `1–5 → same, 6 → 7, 7 → 8, 8 → 9`; otherwise trust the stored value. It is used by **all four read sites**
   (`wizard.py` guard and `abrir`, `proposals.py` "Continuar" link, `shell.html` breadcrumb) — none reads the raw field any more.
3. `nueva` stamps `wizard_rev = 2` on every new draft at creation, so only genuinely old drafts are ever remapped. The marker and
   remapped value of an old draft are persisted the next time it is saved (`set_step` already loads and saves the whole
   blob), so each old draft is converted exactly once and never re-mapped.
4. The guard keeps its `n <= reached + 1` rule over the new numbering. An old step-8 draft maps to 9 only if it was truly at Review;
   an old step-7 draft (Costos) maps to 8 and reaches Review only through Costos. Objetivos is **skipped but counted as done** for
   any draft that was already past it, which is correct because defaults apply (§0.4) and the check strip works without a visit.

**Making the mechanical edit safe**
- Replace the literal step numbers in `wizard.py` with named constants (`STEP_OBJETIVOS = 6`, `STEP_EQUIPOS = 7`, `STEP_COSTOS = 8`,
  `STEP_REVISION = 9`) used by routes, guards, the `n ==` branches and the `n=` literals in `render_template` calls.
- Add an import-time assertion that, for every system type, `STEP_MODULES` keys, `STEP_TEMPLATES` keys and the label list length all
  describe the same 1..9 sequence — a lockstep mismatch fails at startup, not in front of a user.
- Endpoint names (`paso6_equipo`, `paso7og_tabla`, …) are left as they are — renaming them would touch every template for no
  behavioural gain — with a comment mapping each to its new step.
- `nueva_version` copies the old blob (including the stale reached value) and sends the user to Step 1; this plan carries that
  behaviour forward unchanged and does not fix it.

**Cross-step data.** The scratch keys (`s5`, `s6`, `s4og`, `s5og`, `s6og`, `mp`) are identity-based, not positional, so they do not
move. Grid Zero Step 6 reads `scratch["s5"]["loads_data"]` — which also means Grid Zero's loads are already available to Objetivos
(relevant to §0.5 Q6).

### 1.6 The AI note

- New `ai/design_review.py` (a prompt never lives in the blueprint). Input: the deterministic numbers only — loads summary, goals,
  target block, and (once equipment exists) the check strip. Output: at most three short Spanish observations ("el pico parece alto
  para estas cargas", "la autonomía domina el tamaño de la batería").
- The prompt forbids introducing any number not in the input; the UI labels the result "Comentario de IA — no es un cálculo".
- Triggered by a button, not automatically; result cached in the blob keyed by a hash of its inputs, so reopening a quote costs
  nothing and a changed goal invalidates it. Model choice (a small bounded-classification model, as `daytime_fraction.py` does) is
  confirmed at build.
- Failure (no API key, timeout) shows nothing and never blocks the step.

### 1.7 Persistence

A new durable blob section `objectives` holds the goals (a flat dict plus the preset name). The target block is derived, not stored.
The AI note is stored as `objectives.ai_note = {input_hash, text}`.

`wizard/draft.py`'s `load()` rebuilds the blob from an allow-list and **silently drops any unknown top-level key**, so `objectives`
must be added to `_SECTIONS` and `_empty_blob` — otherwise it is lost on the next load + save. The module's own docstring forbids
changing the *meaning* of the seven existing sections (a rule written for Streamlit, now moot but still a good habit); adding an
eighth is additive and compatible. `proposals/generator.py` reads only the seven fixed sections and so ignores goals (intended — they are internal, §0.4).
Old drafts have no `objectives` key and are read as calibrated defaults — no migration of existing rows is required.

### 1.8 Gating — the step is mandatory

Oscar's rule: the app does not let a draft go into the next step without proper objectives set.

- **What "set" means.** `objectives.confirmed = true`, written only by a successful Siguiente on the Objetivos step. Pre-filled
  preset values do not count: the user must pick a preset or edit the fields and confirm. Changing any goal afterwards clears
  `confirmed` until it is re-confirmed, so the check never runs against goals nobody approved.
- **What "proper" means.** Every field present and inside its valid range; coherence checks between fields (for example reserve +
  usable window cannot exceed 100%); and for the kWh-reduction goal, a value above the achievable ceiling (§1.2) is accepted only
  after an explicit acknowledgement ("entiendo que requiere baterías o excede el consumo diurno"), because the goal may be a
  deliberate choice but must not be reached by accident. *(This is my reading of "proper"; adjust if you want unattainable goals
  blocked outright.)*
- **Enforced on the server, not just in the button.** The step's Siguiente stays disabled until the form is valid, **and** the
  step guard refuses any request for Step 7 or later (including a direct URL, and every htmx action route of Equipos, Costos and
  Revisión) while the draft's objectives are neither confirmed nor grandfathered.
- **Grandfathering (Q7).** A draft converted from the old numbering (§1.5) whose `step_reached` was already past the old Step 5 has
  no `objectives` and is treated as confirmed with the default goals, tagged `objectives.source = "default"`. It is not blocked;
  the check strip shows a visible "objetivos por defecto" note with a link to open Objetivos and set real ones. A draft converted
  while at or before the old Step 5 gets no grandfathering and meets the gate normally.
- **The placeholder in Step 2 does not gate.** The gate arrives with the real step in Step 3, so the renumber can be verified on
  its own first.

---

## 2. Build steps

**Step 1 — Formula core + goal defaults (no UI). — ✅ done and verified 2026-10-06** (`calculations/design_targets.py`; the two
generators now call its shared formulas. Golden outputs captured from the **pre-refactor** generators on 8 fixtures — three
Off-Grid, three Hybrid and a custom tier each, spanning both meets-limits and misses-limits outcomes — are byte-identical after the
lift (`python -m scripts.validate_phase24`, offline); a mutation check confirmed the golden comparison fails when a lifted formula is
altered. 32 hand-derived checks cover the targets, the bands, Grid Zero's ceiling/cap behaviour and goal validation. Provisional
values flagged in the code for confirmation when the form is built: the per-field `GOAL_RANGES`, Grid Zero's pre-fill rule and its
±10-point band spacing — Grid Zero has no calibrated tiers to read them from.)
*Original scope:*
*Build:* `calculations/design_targets.py` — the lifted Off-Grid and Hybrid formulas, the new Grid Zero target function, and goal-default
loaders reading the calibrated tiers; the existing `generate_design_scenarios*()` rewired to call the shared functions.
*Validate:* golden test — `generate_design_scenarios*()` output identical before and after for a fixed set of fixtures (including
the Jorge Ramírez off-grid reference); target functions hand-checked against the same fixtures; Grid Zero "unattainable goal" case.

**Step 2 — The renumber, with a placeholder step (no Objetivos content yet).** **— ✅ done and verified 2026-10-06** (Equipos/Costos/Revisión are now
7/8/9; Objetivos is a non-gating placeholder at 6. Offline harness in `scripts/validate_phase24.py` — database stubbed in memory, 19
checks: every old draft saved at steps 1–8 opens exactly what it could before, shifted, and lands on its own content when it asks for
too much; old drafts convert once on first save and are never lowered; all 21 action routes at steps 7–9 moved and each rejects a
request one step too far (a deliberately broken guard number is caught); new drafts are stamped; the lockstep check fails loudly in
both directions; no code under `webapp/` reads the raw stored integer. Live: a real draft saved at old step 8 resumed on Review
(9), its Costos recompute posts to `/paso/8/tabla`, the placeholder advanced it to Equipos (7) and the database now holds
`step_reached 9, wizard_rev 2`; the proposals-list "Continuar" link points at `/paso/9`.)
*Build:* the `meta.wizard_rev` marker + `draft.effective_step_reached()` used at all four read sites, converting old drafts once
(§1.5); the named step
constants and the import-time lockstep assertion; Objetivos registered as Step 6 rendering a "próximamente" placeholder that just
advances; every route path, `_guard` number, `n ==` branch and `n=` literal for Equipos/Costos/Revisión moved to 7/8/9; both label
lists; the `proposals.py` "Continuar" link; the user-facing "Paso 6/7" strings.
*Validate (before any Objetivos work starts):* drafts saved at each old step 1–8 resume on the correct *content* (Equipos,
Costos, Review) with the breadcrumb right; an old step-7 draft reaches Review only through Costos; a converted draft is not
converted twice; a full fresh quote of each system type runs 1→9 end to end including the PDF and lock; every moved route's
guard rejects a step-ahead request.

**Step 3 — The Objetivos step (inputs + sweet-spot block).**
*Build:* per-system-type step module + template replacing the placeholder, preset selector, per-field range validation, live
recompute of the sweet-spot block (same htmx pattern as the other steps), `objectives` added to `_SECTIONS`, Step 4's autonomy field
retired per Q2, the gating and grandfathering of §1.8 (including the server-side guard on Step 7+), Grid Zero's daytime fraction
computed and cached on first view.
*Validate:* all three system types, fresh quote end to end; a draft cannot reach Equipos without confirmed objectives — by button,
by direct URL, and by an htmx action route; editing a goal after confirming blocks again; a grandfathered old draft is not blocked
and shows the "objetivos por defecto" note; Off-Grid has exactly one autonomy value; a kWh goal above the achievable ceiling
requires the acknowledgement.

**Step 4 — The goals-vs-design check strip.**
*Build:* strip component placed with the Equipos step; per-goal achieved values wired from the chosen equipment/scenario; the
explicit "legacy scenario vs calibrated goals" note under Q1-A.
*Validate:* a design that clearly meets, one that clearly misses, one borderline — per system type — each hand-computed.

**Step 5 — The AI note.**
*Build:* `ai/design_review.py`, the button + cache, the "not a calculation" label.
*Validate:* with the API key present and absent; cache hit/miss on a changed goal; the prompt cannot be made to produce an
out-of-input number (adversarial input pass).

**Step 6 — Rollout + documentation.**
*Build:* `PHASES.md` row, `CONTEXT.md` section, stale step-number references in docstrings/docs fixed (§4 item 7).
*Validate:* §4 checklist walked.

---

## 3. Non-goals

- Making goals **drive** Step 6's scenario generation (Q1 option B) — a separate, deliberate phase.
- Putting goals or the AI note in the client PDF (Q5, pending).
- Per-goal optimization or auto-selecting equipment — equipment selection stays a human decision, as in `generate_design_scenarios()`'s own
  docstring.
- Changing the calibrated tier constants themselves, or re-running the fleet calibration.
- Any Streamlit compatibility, or deleting the Streamlit files — retired per Oscar; the deletion itself is a separate, deliberate
  commit (and `wizard/draft.py` / `wizard/state.py` are still imported by the Flask app, so `wizard/` stays).

## 4. Do-not-drop checklist (for the Step 6 audit)

1. `generate_design_scenarios()` and `generate_design_scenarios_hybrid()` return byte-identical results before and after the formula
   lift, on pinned fixtures.
2. The target block and the check strip share the same formula functions — verified by grep, not by assumption.
3. A quote drafted before this phase opens, resumes at the correct step, and shows a working check strip from calibrated defaults.
4. Off-Grid has exactly one autonomy value (Q2) — no remaining read of a second source except the documented fallback.
5. No AI-generated number reaches any calculation or the PDF; the AI note is display-only.
6. Hybrid gets Hybrid goals (not Off-Grid's) while still sharing Steps 6–8's modules.
7. Every step-number reference from the dependency audit is updated or confirmed unaffected — routes, guards, `n ==` branches, `n=`
   literals, label lists, the `proposals.py` f-string URLs, and the user-facing "Paso N" strings (§1.5).
8. Grid Zero's unattainable-goal message appears instead of an impossible target.
9. Draft progress: an old draft saved at each of steps 1–8 resumes on the right content; no draft reaches Review without passing
   through Costos; a converted draft carries `wizard_rev = 2` and is never re-mapped; `step_reached` is monotonic.
10. The import-time lockstep assertion exists and fails loudly when `STEP_MODULES`, `STEP_TEMPLATES` and the label lists diverge
    (verified by temporarily breaking one).
11. No code path reads the raw `meta.step_reached` any more — every consumer goes through `effective_step_reached()` (verified by
    grep).
12. Steps 6 (Equipos), 7 (Costos) and 8 (Review) — now numbered 7, 8, 9 — behave identically to before apart from their numbering:
    same scenarios, same cost table, same PDF for the same inputs (compared on a pinned fixture quote).
13. Gating is server-side: a direct request to any Step 7+ route is refused for a draft with unconfirmed, non-grandfathered
    objectives, and a grandfathered draft is never blocked.
14. The kWh-reduction goal is measured on energy only — no tariff or colones figure enters the Objetivos block or its check row.
15. Goals and the sweet-spot block never reach the client PDF (checked on a generated PDF, as in Phase 23).
