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

## §4 — Layout reflow (the real risk)

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
