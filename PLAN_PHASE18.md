# Phase 18 — Personalized report modules for Growth/Fleet

**Status:** Scoped 2026-08-26. **In progress**, on `feature/personalized-reports` (never `main`
until reviewed and merged deliberately — the risk of a mistake here is degrading EVERY existing
customer's report, not just Growth/Fleet's). **Author:** Claude, 2026-08-26, decisions recorded
directly from Oscar's answers in chat.
**Builds on:** [`PLAN_PHASE17.md`](PLAN_PHASE17.md) (`resolve_branding()`'s exact tier-gating
shape, §4 — this phase's `resolve_report_modules()` mirrors it deliberately; the
`report_schedule`/`default_report_schedule` per-site/per-customer column pattern, §5.3/§5.4,
reused verbatim for module selection).
**Plan doc convention:** same shape as PLAN_PHASE17 — decisions with their reasoning first, then
vertical build steps, each with its own verification gate.

---

## Goal

Growth/Fleet installer accounts can already white-label a report's *appearance* (Phase 17's
Branding tab — logo, colors, contact info). This phase lets those same tiers choose which
*content* modules appear in a given site's report, instead of every site getting the same fixed
set — and, separately, catalogs what new content the VRM API can support beyond what's rendered
today, verified against real installations rather than assumed.

**Why tier-gated, not universal:** the marketing page currently sells the opposite promise to
everyone else — "computed once and shown consistently everywhere." Personalization is a
deliberate carve-out for paying tiers who manage many client sites and want more control over
the deliverable, not a walk-back of that consistency promise for Starter/owner accounts.

## Decisions

- **Phase 1 scope is toggling, not new content.** Make the report's existing ~9 optional blocks
  individually selectable per site, with a layout that reflows correctly for any combination.
  Proving the flexible-layout mechanism is the hard, risky part; adding new modules on top of it
  is comparatively cheap once it exists — so no new module *types* ship in Phase 1.
- **The 12 modules split 3 fixed + 9 selectable.** KPI header, the AI narrative, and the daily
  solar-vs-consumption bar chart are mandatory — they're the report's identity, and making them
  optional buys nothing while complicating the "always render *something*" guarantee. The other
  9 (energy mix, battery health, grid quality, events, SOC chart, solar performance, weather,
  four-week trend, tariff savings) are selectable.
- **Selection lives per-site, with a per-customer default** — identical shape to
  `report_schedule`/`default_report_schedule` (migration 026): a site with no explicit selection
  behaves exactly as today (every module on), and a customer's default only ever applies to a
  *new* site, never retroactively.
- **Entitlement is enforced once, server-side.** A single `resolve_report_modules(customer,
  site)` function is the only place selection is resolved; both `build_report_data()` and the
  web app call it rather than re-deriving the tier check independently (exact shape of
  `resolve_branding()`/`getBrandingAccess()`, Phase 17 §4).
- **A live VRM API diagnostics probe (2026-08-26, read-only, `VRM_ADMIN_TOKEN`, never
  persisted) found 467 real attribute codes across all 13 current installations** — this
  corrected several assumptions in this project's own code comments (see §7, Module inventory)
  and grounds Phase 2's candidate list in verified fact rather than documentation claims.

## §1 — Schema

`database/migrations/028_report_module_selection.sql`. Two columns, mirroring migration 026's
`report_schedule`/`default_report_schedule` exactly:
- `vrm.sites.report_modules text[]` — `NULL` (every existing site, and any site never opted in)
  means "use the full default set," i.e. today's exact behavior. A `CHECK` constraint enforces
  every array element is one of the 9 known module ids — an invalid module id is unrepresentable
  at the database layer, not just rejected by the UI.
- `vrm.customers.default_report_modules text[]` — applied to a customer's *new* sites at
  creation only, never retroactively, same rule `default_report_schedule` already follows.

No tier-entitlement CHECK at the database layer — same reasoning branding uses: a `CHECK`
constraint must be immutable and can't join against a customer's current plan, so entitlement
stays purely in `resolve_report_modules()` (§2), not the schema.

## §2 — Entitlement gate

`resolve_report_modules(customer, site)`, alongside `vrm_api/branding.py:resolve_branding()`.
Returns the full 9-module default for anyone not Growth/Fleet-installer-entitled, or the site's
own `report_modules` (falling back to the customer's `default_report_modules`, falling back to
"all") otherwise.

## §3 — Backend: thread selection through

All 9 optional blocks' data is already computed unconditionally in `build_report_data()` —
nothing there changes. `render_html()` (`victron/weekly_report.py:780`) accepts a `selected:
set[str]` and skips building any block not in it.

## §4 — Layout reflow

**Narrower than originally scoped** — Step 3's implementation found that
`row2`/`row3` already use the generic `two_block_row_svg`/`single_block_row_svg`
pairing functions, so full independent per-module toggling for 8 of the 9
modules shipped in Step 3 itself, not deferred here. What was left:

1. ~~A real full-width, 3-way (solar/battery/grid) energy-mix donut~~ —
   **done**: `report_svg.py:energy_mix_full_svg_3way()`, wired into
   `render_html()`'s `energy_mix`-without-`battery_health` case on a
   `has_batt` system. All 9 modules are now fully independent.
2. Page 2's header (`weekly_report.html`) always renders regardless of
   whether anything below it is selected — a customer who deselects every
   page-2 module (SOC chart, row3, trend, savings) still gets a
   near-blank second page. Found live during Step 3's own verification —
   real, but low-priority; not fixed yet.

Today's layout is fixed pairs (`row1`=energy-mix+battery, `row2`=grid+events,
`row3`=perf+weather), each hand-sized together via `S.uniform_row_size()`
(`victron/report_svg.py:123`); every chart-type block (KPI, bar chart, donut, SOC chart, trend)
is its own bespoke fixed-size SVG function — there is no "drop any block into any slot"
primitive today. Replace the fixed pairing with a packing pass: iterate selected blocks in a
fixed priority order, pack two half-width (info-block-shaped) blocks per row where possible, let
each full-width chart take its own row — reusing `single_block_row_svg`/`two_block_row_svg`/
`uniform_row_size()` exactly as they exist, since only the pairing logic changes. **Prototype in
isolation first** — render every combination worth caring about to PDF before wiring into the
real pipeline, to catch WeasyPrint orphan-row/gap issues while cheap to fix.

## §5 — Frontend: selection UI

New sub-section on `/app/branding` (gated the same way the branding form itself already is),
per site — a checklist of the 9 modules with the same "confirm before saving" pattern just built
for schedules (`app/(portal)/app/sites/SiteForm.tsx`'s `scheduleChanged`/`scheduleConfirmed`).

## §6 — Verification (non-negotiable before merge)

- Regression: a site with no explicit `report_modules` renders **byte-for-byte identical** to
  its current report — generate one real report before and after, diff the PDF.
- Golden path: toggle a real Growth/Fleet test site through several combinations (all on, all
  off, representative subsets), visually confirm no overlapping/empty-gap layout.
- Confirm a non-entitled tier's selection (if one somehow gets written) is ignored by
  `resolve_report_modules()` — entitlement enforced server-side, not just hidden in the UI.

## §7 — Module inventory (Phase 2, deferred)

Not started. Real candidates, verified against the live diagnostics probe rather than assumed —
kept here as the backlog for whenever Phase 2 is picked up, not scoped into steps yet.

**From data already ingested but never surfaced** (`database/migrations/012_vrm_schema.sql`'s
real columns vs. every field `build_report_data()`/`_rows()` actually reads):
1. Per-tracker PV yield (`YT0`-`YT3` etc.) — real and available on a *single* multi-tracker
   charger (confirmed live on the three Vista Atenas installations, 4 trackers each); still
   genuinely blocked across *separate* charger devices, as `vrm_series.py`'s docstring states.
2. Average SOC trend (`avg_soc`) — today only min/max are read.
3. System capacity timeline (`pv_kwp_snapshot`, `battery_kwh_snapshot`).
4. ~~Full temperature range~~ — **shipped 2026-08-26 on `main`** (commit `7d06f3c`): the
   battery-health "Avg temperature" row was displaying `max_temp`, a real mislabeling bug, now
   fixed to show the genuine average. Applies to every tier immediately, independent of this
   phase.
5. Full alarm category coverage beyond today's two scored categories (Low Battery, Overload) —
   see item 9 below; folded into Critical alerts rather than the scored total.
6. Data completeness indicator (`hours_covered`, `complete_day`).
7. Operator/installer notes (`daily_health.notes`) — the column exists but nothing anywhere in
   the codebase writes to it; would need a real write path (an admin/installer UI) built first,
   not just a display toggle.

**Verified live against all 13 real installations (2026-08-26)**, correcting/extending the
above:
- A real grid meter exists on at least one site (Emtec): full per-phase voltage/current/power/
  power-factor/energy-to-net/energy-from-net, frequency, PEN voltage (`gpn` — a real
  neutral-earth bonding fault signal), phase sequence. Materially better than today's
  inverter-side `IV1`/`IV2`/`IF1` approximation. **Offer only where a real meter is detected.**
- Generator run-hours exist today (`Gt`, "Accumulated time for generic Generator") on 4 of 13
  installations (all El Encino) — no fuel level or running-state signal exists for any
  installation, so this module stays a single "hours run this period" stat, not a richer panel.
  **Offer only where `Gt` is published.**
- Tank monitoring is real on one site (El Encino Casita): capacity, fluid type, custom name,
  status — no clearly-numeric fill-level code found in the diagnostics snapshot; verify a real
  level reading exists via the `stats` endpoint before committing to a level-over-time chart.
  **Offer only where a tank sensor is detected.**
- Battery detail is far richer than a simple temperature module: per-module (0/1/2) voltage/
  temperature/current/cell-imbalance alarms, pack-level max/min cell voltage/temperature.
- GPS lat/lng (`lt`/`lg`) published directly by VRM on 7 of 13 installations — tangential to
  report modules, relevant to `vrm.sites.latitude`/`longitude` currently being entered by hand.

9. **Critical alerts** (Oscar's priority call, 2026-08-26) — DC ripple (`eR`/`eR1`-`eR3`), cell
   imbalance (`ACI`/`ACI0`-`ACI2`), and temperature faults (`AHT`/`ALT`/`AHCT`/`ALCT`, pack and
   per-module) are all confirmed published via the VRM API (12-13 of 13 installations) — safety-
   relevant, since any can precede a shutdown. Deliberately NOT folded into the scored health-
   score/Events total: `victron/vrm_csv.py`'s own comment states widening the *scored* alarm
   categories is "a deliberate, cross-path change" that would make health scores mean different
   things across ingestion paths if done carelessly. This shows them as their own separate,
   clearly-labeled section instead. Needs new capture work first: `victron/vrm_series.py`'s
   `ALARM_CATEGORIES` only maps `eL`/`eO1`/`eO2` into `vrm.alarm_events` today for a
   VRM-API-connected site — none of these three signals are captured into the database at all
   yet on that path (the CSV path at least logs them internally via
   `unscored_alarm_summary()`, just never renders them). **Highest-priority Phase 2 item.**

Needing new data ingestion entirely (bigger, separate lift — no schema support today):
sub-daily/peak-demand load profile (only daily-grain data is stored).

---

## Phase 2 — built (2026-08-29), on `feature/report-modules-phase2`

Scope, per Oscar's own decisions in chat: critical alerts (item 9 above) plus the three
hardware-conditional modules — grid meter detail, generator runtime, tank level — all four
**unconditionally selectable** on every site, never hidden behind a per-site hardware-presence
check. His own words: "my intention is to have all wired in, even if my sites have no data...
if no data has been received, then we should show the module in 0." This is a real departure
from this document's own original Phase 2 framing above ("only where a real meter/generator/
tank exists") — superseded by that instruction once a live probe showed the practical reason
hardware-gating would have been the wrong default anyway (next paragraph).

**A live 90-day probe (2026-08-29) found generator runtime and tank level are registered but
silent on every real installation.** `Gt` (generator) is listed in VRM diagnostics on 4 El
Encino installations; `tc`/`tf`/`ts` (tank) on El Encino Casita — but a 90-day `get_stats()`
check against all of them returned zero actual data points on every one. Critical alerts and
grid meter detail, by contrast, are both confirmed LIVE with real current samples (checked
against Vista Atenas LP M3 and Emtec respectively). Given generator/tank read as "no data" on
every real site today regardless of gating, hardware-presence gating would only have added a
detection mechanism with nothing yet to detect — Oscar's "wire it in for a future subscriber"
instruction turned out to be the simpler AND the correct call, not just the more ambitious one.

**No numeric tank fill-percentage code exists on any real installation.** Only capacity (`tc`,
m³), fluid type (`tf`), and status (`ts`) are registered anywhere. `tank_level_pct` reads from a
speculative code (`tl`, following Victron's own naming pattern for the sibling fields) that has
never been seen on real data — documented as unconfirmed in `victron/vrm_series.py`'s own
comment. Requesting an unpublished code from `get_stats()` just returns no data, so this costs
nothing if wrong.

**Schema (migration 029):** a new `vrm.critical_alerts` table — deliberately NOT `vrm.
alarm_events`, since `vrm.count_alarm_episodes()` counts every row in that table unconditionally
and a health score must never move because of these three categories (this document's own
Decisions section on why critical alerts are separate, above). Six new nullable columns on
`vrm.energy_daily` (`generator_hours`, `grid_meter` jsonb, `tank_capacity_m3`/`tank_fluid_type`/
`tank_status`/`tank_level_pct`) — NULL on every pre-existing row and every CSV-sourced row with
no equivalent signal, same pattern migration 012's own `pv_yield_kwh_sc0`/`sc1` already
established. `report_modules`/`default_report_modules`'s CHECK constraints widened from 9 to 13
known ids via a dynamic `DO` block that looks up each constraint's real name rather than
assuming migration 028's Postgres-default naming was exactly right.

**Both ingestion paths, not just the API one** — Oscar's explicit instruction ("fetch the
correct values... from the API and CSV uploads"). `victron/vrm_series.py` (API path): critical
alerts follow the exact `ALARM_CATEGORIES`/`alarm_episode_events()` pattern already used for
scored alarms, just written to a separate output key; generator/grid-meter/tank codes are
fetched in the same batched `get_stats()` call as everything else, no extra round trip.
`victron/vrm_csv.py` (CSV path): a parallel `CRITICAL_ALARM_CATEGORIES` re-groups 3 of
`UNSCORED_ALARM_SIGNALS`' existing entries into discrete WARNING/CLEARED episodes instead of
only a sample-count summary; generator/grid-meter/tank CSV column names are a best-effort
inference from Victron's own API `description` strings (device name `"Grid meter"` is already
confirmed correct from existing code; the specific voltage/current/power-factor descriptions and
the generator/tank device names are NOT verified against a real CSV export — none of Oscar's
real sites have this hardware to produce one) — flagged explicitly in that module's own comment,
and safe to be wrong: `_pick_all()` simply finds nothing and the column reads `None`, same as any
other absent signal.

**Rendering:** two new report rows — Critical Alerts + Grid Meter Detail (row 4), Generator
Runtime + Tank Level (row 5) — each independently selectable via the same `want_X` two-block/
single-block pattern rows 2-3 already use, joining the same `uniform_row_size()` pass so a report
that includes them doesn't get a visibly different font size. Every one of the four always
renders something (a real reading, a zero count, or an explicit "not detected" line) rather than
being hidden — the render-time expression of Oscar's "always wired in" instruction.

**Web UI — preview + description per checkbox**, a brand-new requirement added when this phase
was authorized ("I want the modules checkboxes to show a preview of each one and a brief
description"). Resolved as a **static illustrative thumbnail** (one fixed SVG icon per module,
identical across every site) plus a one-sentence description — chosen over a live per-site
mini-render specifically to avoid computing real report data just to populate a selection form.
`lib/reportModuleThumbnails.tsx` is the one shared, presentational-only file both
`SiteForm.tsx` (customer) and `AdminSiteEditForm.tsx` (admin) import — a deliberate, narrow
exception to this codebase's usual "duplicate module-id lists across that boundary" rule, since
icons/descriptions carry no entitlement logic to drift.

**Default rollout — a real, caught-before-shipping regression.** The first pass added all 4 new
ids to `ALL_MODULES` and left `resolve_report_modules()`'s non-entitled fallbacks and
`render_html()`'s `selected=None` fallback both returning "the full module set" verbatim, exactly
as Phase 1 did. Two problems, found during this phase's own verification pass rather than by a
later live test:

1. **A row-sizing regression independent of the rollout question.** `uniform_row_size()` sizes
   the whole report's font uniformly by measuring every group of rows passed to it — Phase 2's
   four new row groups were being added to that measurement UNCONDITIONALLY, before the
   `want_critical`/`want_grid_meter`/`want_generator`/`want_tank` selection flags were even
   computed. That means an existing customer's report — one that never selects any Phase 2
   module — could still get a different (likely smaller) font size than before this phase shipped,
   purely because unrendered rows were being measured. Fixed by computing the four `want_*` flags
   BEFORE building `groups`, and only appending each new row group when its module is actually
   selected — the same discipline `savings_rows`' own conditional append already modeled.
2. **"Full default set" now meant something different than it used to.** `ALL_MODULES` growing
   from 9 to 13 meant every non-customizing customer (Starter/owner tier, and any Growth/Fleet
   installer who's never touched their selection) would gain 4 new report sections the moment this
   shipped — three of them (grid meter, generator, tank) pure "not detected" boilerplate for the
   near-totality of real sites, which have none of that hardware. Resolved with Oscar (2026-08-29):
   a new `DEFAULT_MODULES` constant (the original 9 plus `critical_alerts` only) is what every
   non-customizing fallback returns now — critical alerts are safety-relevant enough to show
   everyone by default (the same way the Events section already shows "Total Alarm Episodes: 0"
   for a clean week), but the 3 hardware-conditional modules stay strictly opt-in. `ALL_MODULES`
   itself is unchanged (13 — the full set of ids a customer CAN select); only what "nothing
   customized yet" resolves to changed. The web UI's own "pre-check everything on first open"
   default (`SiteForm.tsx`/`AdminSiteEditForm.tsx`) was updated to match — a fresh site's
   checklist opens with the same 10 checked, not all 13.

**Verification:** unit-level exercise of `_phase2_rows()`/`render_html()` against both real and
synthetic data (empty grid meter, empty tank, populated critical-alert counts); `tools/
run_migration_029.py` run clean against production after Oscar applied the migration; a real
`build_report_data()`/`render_pdf()` pass against `vista-atenas-2-floor-pool`'s actual data
confirming (a) `selected=None` now equals `DEFAULT_MODULES` byte-for-byte, (b) a report selecting
exactly the original 9 modules renders with no trace of any Phase 2 content, and (c) every
selection combination (all 13, the new 4 alone, defaults) renders without error; `npx tsc
--noEmit` clean on the web app after all frontend changes.
