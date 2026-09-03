# Fleet Dashboard Phase 3 — Anomaly Detection: Build Plan

**Status:** ready for the coder agent
**Author:** planned in conversation with Oscar, 2026-09-03
**Spec sources:** `PHASES.md` Phase 19 (Admin Fleet Health Dashboard — Phases 1–2.5 already
shipped; this doc is Phase 19's own missing Phase 3), `REQUIREMENTS.md` §4.8
**Relationship to other docs:** reuses exclusion rules and the PR-vs-PVGIS concept from
`docs/design-calibration-2026-08.md` (Phase 11) — see "Why not reuse Phase 11 directly" below
for why this is a new, narrower function rather than a call into that one.

---

## 0. Confirmed context (do not re-derive)

| Fact | Where verified |
|---|---|
| `vrm.site_snapshots` is latest-only — one row per site, upserted ~every 15 min, **not** a history table | migration 031's own header comment |
| Trend/history lives in `vrm.energy_daily` (daily grain) and `vrm.daily_health` (daily health score via a Postgres trigger) | migration 012, `monitoring.compute_daily_health()` pattern |
| Live snapshot signals available: `pv_power_w`, `load_power_w`, `battery_power_w`, `grid_power_w`, `soc_pct` — every one NULLABLE, NULL means "this site doesn't publish this signal," never a fabricated 0 | migration 031 |
| Multi-charger sites get `pv_power_w = NULL` **always** (Victron's stats endpoint can't disambiguate multiple PV-producing instances) — a real `0.0` on a single-charger site is a genuine measured zero, never confused with the structural NULL case | `aea03c8`, Fleet Dashboard Phase 2 |
| Only **7 of 13** real `source='vrm_api'` sites have `pv_kwp` set (live query, 2026-09-03) | see below |
| `calculations/pvgis.py` already fetches + caches per-site daily/monthly irradiance (built Phase 2, reused by Phase 11) | existing code |
| Phase 11's exclusion rules (drop partial days, drop all-signal-null days, drop faulty arrays for PV calibration) are the established "don't fabricate an anomaly from bad data" pattern in this codebase | `docs/design-calibration-2026-08.md` §8 |
| No ML model, no training — decided 2026-09-03. Fleet is ~13 sites (too small to train anything trustworthy without overfitting), and this codebase's own established rule is that AI/ML is used only for bounded classification/extraction with a checkable answer, never for the core physics/energy math | this conversation |

```
Sites with pv_kwp set today (2026-09-03):
  roberto-villalobos-rancho-dulila   7.39
  emtec-cr-emtec-cr                  2.48
  vista-atenas-2-floor-pool          19.3
  karen-montealegre-proyecto-km-ukiyo 10.6
  rebeca-ruiz-el-encino-casona        8.8
  rebeca-ruiz-el-encino-apartamento   4.72
  rebeca-ruiz-el-encino-casita        9.44

Sites WITHOUT pv_kwp (6 of 13) — excluded from 3c until backfilled:
  vista-atenas-vista-atenas-lp-m1-houses
  vista-atenas-vista-atenas-lp-m2-studios
  test-portal-qa-proyecto-gv   (also: should this even be in scope? looks like a QA fixture)
  karen-montealegre-proyecto-km-ukiyo-guarda
  rebeca-ruiz-el-encino-cabana
  jorge-ramirez-proyecto-jr
```

**Action item for Oscar, parallel to this build, not blocking it:** backfilling `pv_kwp` for the
6 sites above (where it's a real, missing site, not the QA fixture) directly widens 3c's coverage
with zero code change.

---

## 1. Decisions locked (from the planning conversation)

- **Three sub-phases** (3a quiet drift, 3b unexpected silence, 3c underperformance vs. design),
  built in that priority order: **3b first** (self-contained, lowest risk, most operationally
  urgent — a dark site is worse than a slowly-declining one), then **3a**, then **3c** (most
  data-quality-gated, waits least on nothing else).
- **Dashboard only for v1** — no email/notification. A new section on `/admin/fleet` (fleet-wide
  counts by type) and the per-site drill-down (active anomalies with their `detail`).
- **Separate signal, not folded into `daily_health`** — a new table and new logic, doesn't touch
  `monitoring.compute_daily_health()` or its trigger. Lower blast radius; nothing else depends on
  this table yet.
- **No ML, no training.** Every check below is deterministic and explainable — a flagged site
  comes with a number you can act on ("PR dropped from 0.81 to 0.62 over 14 days"), not a score.
- **Scope: `source='vrm_api'` sites only**, matching Phases 1–2.5's existing boundary. Revisit if
  `monitoring`-schema (Node-RED/CSV-origin) sites ever need this — not now.

### Why not reuse Phase 11 directly

Phase 11 answers "what should we quote next time" — a fleet-wide, hand-reviewed calibration pass
producing new sizing-tier constants, explicitly never auto-applied. This phase answers "is this
one site behaving differently than it used to, right now" — an ongoing, unattended, per-site
check. Different question, different cadence, different consumer (an engineer reviewing tier
constants vs. an ops dashboard). They share exclusion rules and the PR concept because those are
just correct engineering, not because this phase depends on Phase 11 being built (it isn't).

---

## 2. Schema

**Migration number: placeholder `03X`** — `037` is currently claimed by Phase 10's own plan
(`PHASES.md`, the site-maintenance-register migration). Whichever of the two phases actually gets
built first takes `037`; the other renumbers. Check `database/migrations/` immediately before
creating this file.

```sql
CREATE TABLE vrm.site_anomalies (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  site_id       text NOT NULL REFERENCES vrm.sites(site_id) ON DELETE CASCADE,
  anomaly_type  text NOT NULL CHECK (anomaly_type IN ('quiet_drift', 'unexpected_silence', 'underperformance')),
  detected_at   timestamptz NOT NULL,
  cleared_at    timestamptz,        -- NULL = still active
  detail        jsonb,              -- e.g. {"pr_recent": 0.62, "pr_baseline": 0.81, "days_flagged": 9}
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ON vrm.site_anomalies (site_id) WHERE cleared_at IS NULL;
```

One open row per `(site_id, anomaly_type)` at a time — a new detection while one is already open
updates `detail` in place rather than opening a duplicate row; a check that no longer finds the
condition sets `cleared_at`. Same open/cleared shape `vrm.alarm_events` already uses, so the
dashboard query pattern is familiar.

---

## 3. Phase 3b — Unexpected silence

**Goal:** a site reporting a real, persistent zero during hours it has historically produced.

- New function in `victron/vrm_live.py` (alongside `fetch_live_snapshot()`) or a new
  `victron/anomaly_silence.py` — call it right after each site's snapshot is upserted in
  `POST /v1/vrm-fleet/refresh-snapshots` (`vrm_api/routers/vrm_fleet.py:post_refresh_snapshots()`).
  Zero extra VRM API cost — reuses the diagnostics call already being made, same reasoning the live
  alarm-detection work (`bf9a142`) already established.
- **Only a real `0.0` counts.** `pv_power_w IS NULL` (structural — multi-charger sites, or any
  site that simply doesn't publish PVP) is excluded entirely, never treated as a silence signal.
- "Should be producing" window: derive per-site from its own `energy_daily` history (has this site
  historically had non-trivial generation at this local hour on recent days?), not a fixed
  sunrise/sunset heuristic — a shaded or unusually-oriented array's real productive window may not
  match a generic clear-sky window.
- **Debounce:** flag only after 2 consecutive ~15-minute checks read a real zero during that
  window (~30 min sustained), to survive one bad poll.
- Clears automatically the next time a non-zero (or NULL, i.e. back to "can't tell") reading comes in.

---

## 4. Phase 3a — Quiet drift

**Goal:** a site whose output has been trending down relative to its *own* recent history — the
case that motivated this phase (a site that still looks fine on today's health score, but has
been quietly declining for weeks).

**Deliberately does not require `pv_kwp`**, unlike a naive PR-vs-PVGIS approach — that would only
cover 7 of 13 sites. Instead:

1. For each site with enough valid history (≥30 valid days in `vrm.energy_daily`, Phase 11's
   exclusion rules applied — drop partial days, drop all-signal-null days), compute daily
   generation (kWh).
2. Season-adjust using **PVGIS's relative shape only** (the ratio of a given day's expected
   irradiance to that site's own trailing-year average irradiance) — not an absolute
   irradiance-to-kWp conversion. This uses the site's own trailing generation average as its own
   implicit capacity proxy, so no `pv_kwp` is needed and a wrong/stale `pv_kwp` can't corrupt it.
3. Rolling 14-day mean of season-adjusted output vs. a longer trailing baseline (prior ~90 days).
   Flag only on a **sustained** drop (e.g. ≥7 of the last 14 days below a starting threshold —
   exact number below is a first guess, not locked, see §6) — guards against a single cloudy week
   reading as drift.
4. Runs daily, piggybacking on the existing daily sync cadence (same job that already updates
   `vrm.energy_daily`/`vrm.daily_health`) rather than a new schedule.

---

## 5. Phase 3c — Underperformance vs. design

**Goal:** a site currently delivering meaningfully below what its installed `pv_kwp` should — a
static "never performed to spec" check, distinct from 3a's "declining over time."

- **Genuinely requires `pv_kwp`** — no substitute exists for "what should this size of array
  produce." Scoped to the 7 sites that have it today; the other 6 are skipped, not flagged, not
  guessed at (same "no data is better than fabricated data" posture as everywhere else in this
  pipeline).
- Compares a site's best-recent-day peak (or a smoothed recent max) against PVGIS's clear-sky
  expectation for that `pv_kwp` — the same "capability" half of Phase 11's own
  peak-W/kWp-vs-mean-PR discriminator, applied per-site rather than fleet-wide.
- Shares the PR-computation core with 3a where it makes sense (both ultimately compute
  actual-vs-PVGIS-expected) — write one utility function, parameterize by whether `pv_kwp` is
  available (3a: self-baseline mode; 3c: design-relative mode), rather than duplicating the PVGIS
  plumbing twice.
- Runs daily, same cadence as 3a.

---

## 6. Validation

- **3a/3c backtest against Phase 11's own labeled examples** (villalobos = array-fault, guarda =
  over-built, casona = well-matched) for whichever of those sites are `source='vrm_api'` with
  enough history — if the detector disagrees with a calibration that was already carefully
  hand-verified, the detector is wrong, not the label.
- **3b:** confirm live that a real site's deliberate/simulated daytime zero fires after the
  debounce window, and that a multi-charger site's structural `NULL` never fires, across a full
  refresh-snapshots cycle.
- **All three fail closed on insufficient history** — a site with `<30` valid days produces no
  flag, not a guessed one, for either 3a or 3c.
- **Dashboard:** fleet-wide anomaly counts by type on `/admin/fleet`, active anomalies with their
  `detail` on the per-site drill-down — verified against real data, not a fixture.

---

## 7. Open items still needing Oscar's judgment

1. **Threshold tuning** (3a's drop %/sustained-days, 3b's debounce window, 3c's underperformance
   %) — the numbers in this doc are starting points, not locked. Needs a first real pass against
   fleet data before trusting them; expect to start conservative (fewer false positives, tune
   looser afterward) rather than the reverse.
2. **`test-portal-qa-proyecto-gv`** — looks like a QA fixture, not a real site. Confirm whether it
   should be excluded from anomaly detection entirely (recommend: yes, same as it presumably
   already is from customer-facing surfaces) rather than backfilling `pv_kwp` for it.
3. **`pv_kwp` backfill** for the 6 real sites missing it (§0) — not blocking, but directly widens
   3c's real coverage whenever it happens.
