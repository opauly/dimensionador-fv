# Off-Grid Wizard — Load Profile Estimation Approach

**Purpose of this document:** capture the design logic worked out during the Casa Principal quote so it can be carried into the Dimensionador FV wizard as a proper product, not re-derived from scratch each time. Written to be self-contained — a future session (or a developer) should be able to build from this without needing the original chat history.

## The problem

Off-grid proposals define connected loads as **name + quantity + power (nameplate)**. That's it. Customers almost never know or provide usage hours, duty cycles, or timing. But battery and panel sizing need **daily kWh per load**, not connected watts — and naively multiplying nameplate power by an assumed "hours used" wildly overstates real consumption (we saw this directly: a naive calculation gave 265.7 kWh/day for a house that actually needed ~100 kWh/day once realistically estimated).

The wizard's job is to close that gap reliably, for any project, without requiring data the customer doesn't have.

## Core principle: classify, then estimate — never guess uniformly

The mistake to avoid is treating every load the same way ("nameplate × some hours × some coincidence factor"). Different load types have fundamentally different *sources of truth* for their real energy use, and the wizard should route each load to the right one instead of applying one generic method to everything.

## The five-category taxonomy

| # | Category | Examples | What actually determines its energy use | Estimation source |
|---|---|---|---|---|
| 1 | **Fixed/cycling appliance** | Refrigerator, freezer | Appliance type & size class. Nameplate watts ≈ starting draw, not average — using it directly overstates consumption. | Deterministic lookup table (DOE/ENERGY STAR-style kWh/day by type+size) |
| 2 | **Behavior-driven** | Lighting, general receptacles, kitchen/laundry circuits, dishwasher, microwave | Household size and home tier. NEC-style demand figures (VA/ft²) are code-minimum wiring safety numbers, not energy estimates — they overstate real use by ~3x. | Deterministic formula: kWh/day per ft² or per bedroom, tiered by home class |
| 3 | **Climate-driven** | A/C, space heating, dehumidification | Actual local climate — cooling/heating degree days, equipment efficiency. This is the highest-leverage, highest-error category: naive nameplate-hours sizing was 2x too high here versus a climate-adjusted estimate. | **Real API-sourced climate data**, converted via degree-day methodology |
| 4 | **Discretionary/variable** | EV chargers, pool/jacuzzi, irrigation | Occupant choices no spec sheet or climate model can infer (driving distance, how often the spa gets used). This was consistently the single biggest swing factor in every estimate this session. | Targeted intake questions → deterministic regional default with explicit wide uncertainty if unanswered |
| 5 | **Ignition-only** | Gas water heater, gas cooktop, gas dryer control circuit | Negligible; brief control/ignition draw only. | Fixed small default (~0.05–0.1 kWh/unit/day), no further sophistication needed |

## Where AI fits — and where it deliberately doesn't

The instruction to "use AI and API calls whenever useful" needs a precise answer per step, not a blanket yes. Two different jobs are being conflated if this isn't split out: **interpreting ambiguous input** (AI's strength) vs. **calculating a number that has a real, checkable answer** (should never be left to an LLM's pattern-matching when a deterministic source exists).

**Good fits for AI (Claude):**
- **Load-name classification.** Customer load lists arrive as free text with inconsistent naming ("A/C" / "Aire Acondicionado" / "Split Unit" / "HVAC"). Mapping arbitrary text to the 5-category taxonomy is a natural-language classification task — a good, bounded fit for an LLM call, *constrained to output one of the 5 enumerated categories* (never free text).
- **Structured extraction from free-text intake answers.** If a customer answers "I drive to San José most days" instead of a number, AI can convert that to a structured estimate (approximate km/day) which then feeds a deterministic formula. The AI's job stops at extraction; the energy math after that point is still deterministic.
- **Sanity-check / anomaly flagging.** A review pass over the assembled profile that flags "this line looks unusual relative to the rest of the house" — the same role I was playing manually all session when flagging A/C and EV as the dominant uncertainty sources. This is pattern recognition over an already-computed result, not the computation itself.
- **Client-facing narrative generation.** Turning the structured, numeric load profile into readable proposal language. Text can legitimately vary between runs; this is presentation, not calculation.

**Should NOT be AI (must be deterministic):**
- **The actual energy math** — lookups, degree-day formulas, unit conversions. Once inputs are classified/extracted, this should be plain code, for speed, cost, reproducibility, and auditability. A quote that changes slightly every time it's regenerated from the same inputs is a real problem for a business tool.
- **Climate/solar data itself.** Never let an LLM recall "typical temperatures" for a location from training data as the basis for a real quote — that data can be stale, imprecise for less-documented locations, or simply wrong. Always pull from a real API. (This session had to fall back to web search + judgment for Casa Principal's climate because no API access was available — that's a limitation to engineer around in the wizard, not a pattern to keep.)

## Concrete API integration points

| Data need | Recommended source | Notes from this session |
|---|---|---|
| Solar resource (HSP, monthly production) | PVGIS (`re.jrc.ec.europa.eu`) | Covers Europe/Africa/Asia/parts of Americas. **Watch the database choice** — ERA5 (coarse reanalysis) gave a yield ~40% lower than expected for Costa Rica; NSRDB is the better satellite-derived option for the Americas where available. Confirm which is used before trusting output. |
| Temperature / cooling degree days | NASA POWER API, or Open-Meteo climate API | Global coverage, free, well-documented — needed for the Category 3 (climate-driven) load estimates. Not yet integrated into any tool this session; this is the next concrete build item. |
| Horizon/shading | PVGIS auto-calculates from a global DEM | Coarse — can overstate distant-ridge shading. Treat as a first-pass flag requiring site confirmation, not ground truth. |
| Geocoding / location context | Any standard reverse-geocoding API | Useful for a friendly location label and for climate-zone classification, not just raw coordinates. |

## Data model sketch

Each load entry the wizard produces should carry its category, its estimate, and — critically — **where the estimate came from**, so the output is auditable rather than a black box:

```json
{
  "load_name": "Aire acondicionado",
  "category": "climate_driven",
  "quantity": 6,
  "connected_power_kw": 3.0,
  "estimated_kwh_day": 27.0,
  "confidence": "api_calculated",
  "source_detail": "CDD-based estimate, NASA POWER climate normals for 9.887,-84.177; SEER 18 default assumed (no equipment spec provided)",
  "hourly_shape_ref": "ac_mild_highland_v1"
}
```

**Confidence tag values** (visible in the final output, not buried):
- `measured` — from real submetered data (eGauge/Emporia-derived, once that pipeline exists)
- `api_calculated` — derived from real location data via a documented formula
- `benchmark` — industry-standard lookup table, not location-specific
- `user_confirmed` — customer answered an intake question directly
- `default_assumed` — no better source available; flagged prominently, should visually stand out in the proposal rather than look as confident as the other four

## Determinism & reliability requirements

For the same inputs (same load list + same coordinates + same intake answers), the wizard must always produce the same output. That requires:

1. **Versioned, pinned reference tables** — appliance benchmarks and regional defaults change deliberately and get a version bump, never drift silently.
2. **Cached API responses per location** — climate/solar data fetched once per project and reused (for both panel sizing and load estimation), refreshed on a defined schedule, not re-fetched with natural variance on every run.
3. **Constrained AI classification** — forced to select from the enumerated category list, and cached once a load name has been classified so repeated runs (or reuse across projects) don't risk different answers to the same input.
4. **AI-generated text is the only place variation is acceptable** — proposal narrative can differ between runs; the numbers behind it must not.

## What real metered data (eGauge/Emporia) can and can't contribute

From the earlier discussion — worth keeping close to this taxonomy since it maps directly onto it:

- **Portable to a shape library** (Categories 1, 2, part of 4): normalized (0–1, not absolute) hourly shapes for fridge cycling, dishwasher/laundry cycles, EV charging curve shape, general lighting/receptacle timing relative to sunrise/sunset. Normalize before storing — the shape transfers, the magnitude usually doesn't.
- **Not portable** (Category 3): A/C data from a different climate zone is actively misleading, not just imprecise. Only use metered A/C data from a genuinely comparable climate (similar elevation/latitude), and even then treat it as a secondary check against the degree-day calculation, not a replacement for it.

## Open items / next build steps

1. Stand up the NASA POWER (or equivalent) climate API integration for Category 3 — highest-leverage missing piece.
2. Build the initial benchmark tables for Categories 1, 2, and 5 (can be researched/drafted with AI assistance, but should ship as static versioned data, not a live AI call).
3. Design the intake question set for Category 4 (EV, pool/spa, irrigation) — keep it to 2–3 short questions per discretionary load type.
4. Define the classification prompt/schema for mapping free-text load names to the 5 categories, with the enumerated-output constraint.
5. If/when eGauge or Emporia export data is shared, build the shape-normalization pipeline for Categories 1/2/4 as described above.
