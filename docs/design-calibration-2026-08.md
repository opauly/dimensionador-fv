# Design calibration from fleet data — 2026-08

First calibration of the static design-tier model (`calculations/sizing_off_grid.py`)
against measured performance of installed systems, instead of judgement alone.

This document is the reference for the **continuous design-calibration feature**
(PHASES.md Phase 10 / REQUIREMENTS.md §Design calibration). It records the
method, the traps, the constants derived, and — importantly — which conclusions
are solid and which are provisional, so a later automated version does not
re-derive them from scratch or silently inherit the weak ones.

---

## 1. Dataset

| | |
|---|---|
| Sites | 9 (6 hybrid, 3 off-grid), all Victron + Pylontech, Costa Rica |
| Requested window | Sep 2025 – Aug 2026 (12 months) |
| **Actually usable** | **2026-02-06 → 2026-08-08, ~183 days/site** |
| Resolution | 1-minute |
| Source | VRM portal CSV export → `victron/vrm_csv.py` |
| Design params | Supabase `monitoring.sites` (`pv_kwp`, `battery_nominal_kwh`, `battery_dod_pct`) |

### VRM retention wall — read this before requesting more data

Every site's data begins at **exactly 2026-02-06**, ~6 months before the export
date, regardless of the range requested. Older rows exist in the file but every
signal is null. **VRM retains 1-minute data for ~6 months only.**

Consequence: **Sep/Oct/Nov — the lowest-irradiance months, which drive
worst-case sizing — cannot be obtained at 1-minute resolution.** The Feb–Aug
window we do have sits ~6% *above* the annual mean.

Workarounds, in order of preference:
1. Export the older window at **15-minute or hourly** resolution. VRM keeps
   downsampled data much longer. Loses precise outage detection (needs 1-min),
   keeps daily energy / SoC / yield — which is what calibration needs.
2. Re-export in **December**, when Sep–Nov falls inside the 6-month window.
3. Two-tier standing practice: 1-min for the rolling 6 months, hourly archive
   for everything older.

---

## 2. Method, and the traps that produce plausible wrong answers

Each of these cost a wrong conclusion before being caught. They are the most
valuable part of this document.

| Trap | Symptom | Correct approach |
|---|---|---|
| **Mean PR vs peak W/kWp** | Three healthy arrays classified as faulty | *Mean* PR mixes in curtailment and dead days. **Peak W/kWp is the capability test.** Healthy = ≥700 W/kWp; suspect <600 |
| **Monitoring gap ≠ zero generation** | Karen "produced nothing" for 43% of days | A gateway outage logs ~24 rows/day with **every** signal null (PV, load, SoC, battery power). A genuinely dark site still logs load and SoC. Exclude, don't count as zero |
| **Curtailment vs fault** | Low delivered yield on a healthy array | Compare **battery-hungry days (min SoC < 45%) against battery-full days**. If yield doesn't rise when the battery is starving, it is supply-limited (fault). If it does, it was demand-limited (curtailment — fine, but the system is over-built) |
| **`Grid alarm` is useless for outages** | Zero outages reported forever | Flat `Grid ok` in all 9 exports even while AC input reads 0.00 V for hours. **Use AC-input voltage absence.** Fixed in `victron/vrm_csv.py::_grid_outages()` |
| **Hour-boundary NaN rows** | One 33-hour event became 33 hourly ones | VRM emits an all-NaN row at each exact hour. Any state machine must let NaN **inherit the previous state** |
| **Off-grid ≠ permanent outage** | Villalobos showed 159 days of "blackout" | Sites whose AC input is never energised have no grid to lose. Skip outage analysis (genset blips can still appear — villalobos has one on AC-in) |
| **Yield counters skip NaN, integration doesn't** | Fake 45% "measurement discrepancy" | `pv_yield_kwh_*` means are over non-null days; integrated `pv_kwh` is over all days. Never compare their means directly |
| **Sibling sites cross-validate** | — | Sites on one feeder show identical outage timestamps to the second. Events appearing at only one site are local (breaker, low voltage), not utility |

### Diagnostic order that works

1. Coverage / blind-day accounting → how much data is real
2. Peak W/kWp → is the array capable
3. Hungry-vs-full day comparison → curtailment or fault
4. PR vs PVGIS → delivery against resource
5. Cycles/day + min-SoC distribution → is the battery working or idle
6. Rolling multi-day minimum yield → the low-sun design case

---

## 3. Constants derived

| Constant | Value | Confidence | Evidence |
|---|---|---|---|
| Healthy-array PR vs PVGIS | **0.88** used (0.93 measured) | High | casona runs 0.93 while exporting 49% (≈uncurtailed, so a true capability read). 0.88 carries soiling/degradation margin |
| Low-sun derate (% of own mean yield) | 1d **50%**, 2d **63%**, 3d **67%**, 5d **72%**, 7d **74%** | Good | 1-in-50 rolling windows, 3 healthy arrays. Weather property → transferable from hybrid to off-grid |
| Night load fraction (18:00–06:00) | median **40%**, range 17–54% | High | 9 sites. Dominant battery input — should be entered per site, not defaulted |
| Reserve SoC actually configured | **25 / 38 / 40%** | High | Mode of daily min-SoC. Nothing runs near 67% |
| Hybrid cycling window / night load | **0.97 – 2.91** | High | casona 0.97 (best), apartamento 1.34, m1 1.54, m2 1.77, m3 2.91 (over-built) |
| Hybrid PV coverage | **1.32 – 2.14** | High | Above ~1.75 unusable without export |
| Off-grid PV coverage | **3.11 – 4.19** | Medium | 3 sites, one with a compromised array |
| Non-exporting coverage ceiling | **~1.75×** | High | m1 at 2.14 harvests no more than m3 at 1.32 |
| Equivalent full cycles/day, healthy | **0.4 – 0.7** | High | <0.2 over-built, >0.9 under-built |

### The two structural findings

**A. Export capability decouples PV sizing from PV utilisation.**
casona and apartamento have the *identical* 0.42 kWp per kWh/day. casona
exports 49% of output and returns PR 0.93; apartamento has no export path and
returns 0.48. For a non-exporting site, PV beyond what load + battery can
absorb is **capex that never becomes kWh**.

**B. `backup_autonomy_hours` was the wrong model.**
The old tiers sized for 6/12/36 h of uninterrupted drain. Measured outages are
**p90 ≈ 60–75 min, worst ≈ 5 h**. And during a 33-hour island at
vista-atenas-lp-m3 the pack **never dropped below 72% SoC** — it drained
overnight and recovered to 100% by midday with the grid still down. PV recharges
the bank every day an outage runs, so **the binding case is one night, not N
hours.** Replaced by `cycling_nights` (the layer that actually sizes the
battery) and `backup_nights` (the resilience promise).

**C. Recharge is an energy non-issue but a timing risk.**
Refilling the bank does not add net demand — the battery returns what it took,
minus round-trip losses of ~4% of daily load, which the 1.3–1.7× coverage
absorbs comfortably. What coverage does *not* guarantee is that the surplus
arrives **inside the solar window, alongside the daytime load, on the same
day**. Measured as *recharge headroom* = (generation − daytime load) ÷ (night
discharge ÷ η):

| site | headroom | reaches float | grid |
|---|---|---|---|
| rebeca-ruiz-apartamento | **0.61** | **0% of 183 days** | 26% |
| roberto-villalobos (off-grid) | 0.98 | 67% | — |
| vista-atenas-lp-m1 / m2 | 1.43 | ~70% | ~10% |
| vista-atenas-lp-m3 | 2.14 | 89% | 2.3% |
| rebeca-ruiz-casona | 2.17 | 32% | 22% |

Now checked per tier (`recharge_headroom`, `recharge_ok`). Two caveats kept
deliberately visible in the code:
- **casona breaks the pattern** (ample headroom, still 22% grid) because *its*
  constraint is battery size, not recharge — window/night of 0.97, the
  tightest in the fleet. PV and battery are **not substitutes** for
  time-shifting: adding array to a battery-limited hybrid just increases
  export or curtailment.
- The check validates **design intent, not the installation**. It runs on the
  assumed PR of 0.88; apartamento's real 0.61 headroom comes from an array
  delivering PR 0.48. Catching that needs measured PR, i.e. the calibration
  loop (Phase 11), not the quoting engine.

**D. Backup uses the full DoD window, not the reserve slice.**
The Victron setting is *"minimum SoC **unless grid fails**"* — during an outage
the reserve is released down to the real cutoff. Sizing backup against
`(reserve − floor)` made casona, the best-performing site in the fleet, come out
**2.67× larger** than what is installed and working, and re-created the tier
inversion (a lower tier's thinner reserve shrinks that denominator faster than
its smaller `backup_nights` shrinks the numerator). Against the full DoD window
both layers grow monotonically with tier, so **the inversion cannot occur by
construction**.

---

## 4. Tier values shipped

Hybrid (`_HYBRID_DESIGN_TIERS`):

| | reserve SoC | cycling_nights | backup_nights | PV coverage | was |
|---|---|---|---|---|---|
| T1 Mínimo | 25% | 1.00 | 1.0 | 1.30 | 20% / 6 h |
| T2 Recomendado | 35% | 1.25 | 1.5 | 1.50 | 45% / 12 h |
| T3 Máxima | 45% | 1.60 | 2.0 | 1.70 | 67% / 36 h |

Reserve SoC is an **engineer decision, not a fitted value**. T1 sits on the
observed configured floor (25% at casona). **T2's 35% has no installed system
running at it** — the fleet's real configured floors are 25% (casona, which
already imports 22% from grid — mildly under-batteried even there) and 38–40%
(the three Vista meters, comfortable); 35% is a deliberate interpolation
between them, chosen for T2 specifically because it's the default/recommended
sale and the safer end of the gap. **T3's 45% is above anything in the
fleet** — a deliberate product choice for the maximum-resilience tier. The
cost is real and worth stating to a client: a higher reserve shrinks the daily
cycling window, so the same `cycling_nights` needs a larger bank, and the
battery is exercised less. (Revised 2026-08-10 from an initial 25/40/50 pass
— see the back-test below for why T2 moved down and T3 stayed put relative to
the off-grid side.)

Off-grid (`_OFF_GRID_DESIGN_TIERS`) — **provisional**:

| | reserve SoC (sizing headroom) | autonomy days | PV coverage | days to empty | was |
|---|---|---|---|---|---|
| T1 | 25% | 2.00 | 3.00 | 2.53 | 20% / 1.0 d / 1.10 |
| T2 | 35% | 2.25 | 3.25 | 3.56 | 30% / 1.5 d / 1.20 |
| T3 | 50% | 2.50 | 3.50 | 4.75 | 40% / 2.5 d / 1.40 |

**Off-grid reserve is aligned to the hybrid numbers (25/35/50) but does not
mean the same thing.** On a hybrid it is a real inverter setting — the pack
stops there and the grid takes over. Off-grid systems have no min-SoC setting;
nothing enforces this line. Here it is pure sizing headroom: capacity bought
and deliberately kept out of the stated autonomy.

**Why T2 moved (40→35) and T3 didn't (kept at 50, not 40).** Back-tested
against karen-montealegre-guarda's real load (3.01 kWh/day, 4.97 kWh Pylontech
units) — the fleet's one real fault-survival case (a 3-day total PV outage
needing >2.76 days-to-empty to survive):

| reserve | T2 (autonomy 2.25d) | T3 (autonomy 2.5d) |
|---|---|---|
| 25% | 2 units, 2.86d (0.10d spare) | — |
| 30–40% | 3 units, 4.29d (1.53d spare) | 3 units, 4.29d (1.53d spare) |
| 45–50% | — | 4 units, 5.72d (2.96d spare) |

Battery count is a ceiling function, so 30/35/40% all land on the *identical*
3-unit bank for T2 — 35% gives exactly the same protection as 40% did, at no
cost. But that same plateau means **T3 at 40% would collapse onto T2's own
bank** — "máxima autonomía" buying nothing extra over "recomendado" for this
load. T3 needed to stay at 45%+ to actually clear into the next unit bracket;
50% (unchanged) was kept rather than trimmed to the minimum 45%, since it was
already the tested, above-fleet value with no observed downside.

What it buys is **fault tolerance, not weather margin** — weather is already
covered on the PV side (at 3.0× coverage a 3-day low-sun run at the measured
67% derate still delivers ~2.0× load). The one real failure in the fleet was
guarda hitting 5% SoC during a **3-day total PV outage** (0.00 kWh/day —
equipment fault, not clouds); its 2.76 days-to-empty were not enough. T2 and
above now survive that event.

Cost, stated plainly: T2 lands at **4.11× nominal per kWh/day of load**, T3 at
**5.48×**, against an installed fleet spanning **1.79–3.19×**. Every off-grid
quote is therefore larger than anything currently in service. A deliberate
service-response decision (remote sites, slow visits), not a fitted value.

**UI wording**: calling this "reserva SoC" on an off-grid quote implies a
setting the client does not have. Prefer describing the days-to-empty it buys.

Off-grid PV coverage is sized against **annual** yield × PR, not worst-month:
the 3.0–3.5 factor already contains the seasonal margin, so applying worst-month
too would double-count. Worst month is checked separately as an adequacy gate
(`worst_month_covers_load`).

### Back-test against installed systems

T2 output ÷ what is actually on the roof:

| site | kWp ratio | battery ratio | outcome |
|---|---|---|---|
| vista-atenas-lp-m1 | 0.68 | **1.00** | works (over-panelled) |
| vista-atenas-lp-m2 | 0.77 | **1.00** | works |
| vista-atenas-lp-m3 | 1.02 | **0.89** | works |
| rebeca-ruiz-casona | 0.85 | 1.67 | works (best in fleet) |
| rebeca-ruiz-apartamento | 1.05 | 1.50 | works (26% grid) |
| karen-montealegre | 1.17 | 1.60 | never stressed |
| karen-montealegre-guarda | 1.33 | 1.50 | fault days only |
| roberto-villalobos | 1.34 | 2.00 | **stressed** (array at ~70%) |

Tier monotonicity: **OK on all 9 sites**.

casona reads 1.67 because T2 specifies a 35% reserve while casona runs 25% — a
higher reserve genuinely needs more battery for the same nightly cycling. casona
also imports 22% from grid, so it *is* slightly under-batteried; the model is
not wrong to exceed it.

---

## 5. Site diagnoses (fleet health, separate from calibration)

| site | verdict | evidence |
|---|---|---|
| rebeca-ruiz-casona | Healthy, best-matched | PR 0.93, 0.70 cycles/day, 1 day <20% SoC in 183 |
| vista-atenas-lp-m2/m3 | Healthy | PR 0.63/0.81, cycles 0.60/0.50 |
| vista-atenas-lp-m1 | Healthy, **over-panelled** | 2.14× coverage, PR 0.51 — surplus not harvested |
| rebeca-ruiz-apartamento | Healthy array, grid-leaning | PR_p98 0.92 but 26% grid import |
| karen-montealegre | **Monitoring outage** — array is fine | Peak **831 W/kWp** (best in fleet); 66/155 days all-signal-null, blocks Mar 1–24 and Jun 21–Jul 27 |
| karen-montealegre-guarda | Healthy array, **heavily over-built** | Peak 665 W/kWp; battery full 136/161 days; 3-day PV fault Aug 1–3 caused the only near-miss |
| **roberto-villalobos** | **Array underperforming ~70–75%** | Peak 543 W/kWp vs 728–831 healthy; charger 1 sustains ~43% of charger 0; 7 days <20% SoC |
| rebeca-ruiz-cabana | Dormant / array offline | 0.9 kWh/day load, PR 0.02 |

**Villalobos matters for calibration**: its design (3.11× coverage, 1.70
batt/load) sits between karen (2.21, fine) and guarda (3.03, fine). Its stress
is attributable to the array, not the design — which is why the off-grid
constants below are **not** fitted to its outcomes.

---

## 6. Open assumptions — do not treat as measured

1. **Seasonality is modelled, not measured.** No Sep–Nov data (see §1). Per
   PVGIS shape, worst month ≈ **0.82 × annual mean**, and the Feb–Aug sample
   sits ~6% above annual → measured yields carry roughly **−6% annual /
   −23% worst-month**. Measured PR of 0.88–0.93 validates PVGIS's *level*,
   which is decent but not conclusive support for its *shape*.
2. **Off-grid rests on 3 sites, one with a compromised array, one barely
   loaded, one missing 43% of its data.** The off-grid constants are derived
   from hybrid-measured physics plus an explicit no-backstop margin — a
   principled model, not a fit to off-grid outcomes.
3. **`pv_kwp` in Supabase is assumed correct.** Every per-kWp metric depends
   on it. Villalobos' verdict flips entirely if its array is physically
   smaller than the 7.39 kWp on record.
4. **Critical-load share** in the back-test harness was approximated at 55% of
   the home; real quotes use the engineer's actual critical-load list.
5. **Only Victron + Pylontech, only Costa Rica**, only residential/small
   commercial.

---

## 7. What would most improve the next calibration

1. **Hourly export of Sep 2025 – Jan 2026** — closes the seasonal gap, the
   single biggest hole.
2. **Fix villalobos' array** — unblocks off-grid calibration; it is the only
   off-grid site that gets genuinely exercised.
3. **More off-grid sites** — duration does not fix n=3.
4. **Fix karen's monitoring link** — 37 consecutive blind days on an off-grid
   site is an operational risk independent of calibration.
5. **Record `exports_to_grid` per site** in the proposal, not just in
   monitoring — it changes the PV rule materially (§3.A).

---

## 8. Reproducing this

```
vrm_exports/<site-slug> <type>.csv      # 1-min VRM export, filename joins to site_id
victron/vrm_csv.py::parse_export()      # → per-day rows + outages
monitoring.sites                        # pv_kwp, battery_nominal_kwh, battery_dod_pct
calculations/pvgis.py::fetch_irradiance # per-site monthly kWh/kWp for PR
```

Exclusion rules applied before any statistic:
- drop partial days (`complete_day == False`)
- drop all-signal-null days (gateway offline)
- drop sites with <0.2 equivalent cycles/day from battery calibration (idle)
- drop sites with peak <600 W/kWp from PV calibration (array fault)
