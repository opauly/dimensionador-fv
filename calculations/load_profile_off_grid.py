from __future__ import annotations
"""
Off-Grid load profile estimation. Phase 5.

Design source: tools/off-grid-wizard-load-profile-approach.md (Casa Principal
quote, 2026-07). Off-grid customers give load name + quantity + nameplate watts
only — never usage hours. Naively multiplying nameplate power by an assumed
"hours used" wildly overstates real consumption (a naive Casa Principal
calculation gave 265.7 kWh/day for a house that actually needed ~100 kWh/day).

Core principle: classify each load into one of 5 categories (AI, constrained
to the enum — a natural-language classification task), then estimate its
daily kWh deterministically per category (plain code, never AI) — for speed,
cost, reproducibility, and auditability. A quote must not change between runs
of the same inputs.

Every reference table here is versioned (suffix _V1) — Costa Rican appliance
benchmarks and regional defaults change deliberately with a version bump,
never drift silently. These v1 tables are a first pass (loosely calibrated
from the Casa Principal session and general CR residential experience) and
should be refined against real metered data as it becomes available — flagged
inline wherever a constant is a placeholder rather than a sourced figure.
"""
import json
import re
from datetime import datetime, timezone

CATEGORIES = [
    "fixed_cycling",     # 1. refrigerator, freezer, water pump — nameplate ≠ average draw
    "behavior_driven",   # 2. lighting + general receptacles ONLY (see note below)
    "climate_driven",    # 3. A/C, heating, dehumidification
    "discretionary",     # 4. EV charger, pool/jacuzzi, irrigation
    "ignition_only",     # 5. gas water heater/cooktop control circuits
    "appliance",         # 6. operated appliances — microwave, TV, hotplate, washer
]

# Note on 2 vs 6 (scope change 2026-07-28, on user direction): behavior_driven
# used to absorb every "small appliance" too — its tier descriptions literally
# read "TV, computadora, lavadora, cocina eléctrica ocasional". That made the
# aggregate carry most of a home's appliance energy while exposing no wattage
# at all, so appliances were invisible to inverter sizing and impossible to
# quote individually.
#
# Now: behavior_driven = lighting + receptacle background load only (the
# always-on plug side of a house — computadora, router, reloj, cargadores),
# sized per line via duty-hours (see BEHAVIOR_DUTY_HOURS_DAY_V1). Anything
# the occupant switches on to do a task (microondas, plantilla, cafetera, TV,
# lavadora, licuadora) is category 6 and gets itemized with its own kWh/día
# AND its own watts, same as behavior_driven lines now that the aggregate
# model is gone (v3, 2026-08-07).

CONFIDENCE_MEASURED = "measured"            # real submetered data (not wired up yet)
CONFIDENCE_API = "api_calculated"           # derived from real location data via a documented formula
CONFIDENCE_BENCHMARK = "benchmark"          # industry-standard lookup table, not location-specific
CONFIDENCE_USER_CONFIRMED = "user_confirmed"  # customer answered an intake question directly
CONFIDENCE_DEFAULT = "default_assumed"      # no better source — must stand out in the UI

# Spanish display labels for the 5 categories — used by the wizard's manual
# category-override selector, so the engineer can correct a classification
# without needing to know the internal enum values.
CATEGORY_LABELS_ES: dict[str, str] = {
    "fixed_cycling":   "Cíclica fija (refrigerador, bomba de agua)",
    "behavior_driven": "Uso general (iluminación, tomacorrientes)",
    "climate_driven":  "Climatización (A/C, calefacción)",
    "discretionary":   "Discrecional (EV, piscina, riego)",
    "ignition_only":   "Solo encendido (a gas)",
    "appliance":       "Electrodomésticos (microondas, TV, lavado)",
}

# ── Common loads catalog (v1) ────────────────────────────────────────────────
# Pre-filled picklist for the wizard's "add from common loads" control, so the
# engineer isn't typing every load from scratch and doesn't have to remember
# which category applies. name/nameplate_kw are typical CR residential values
# — always editable once added to the table.
#
# Appliances (category "appliance") carry BOTH their own kWh/día — from
# APPLIANCE_USE_KWH_DAY_V1 — and their own watts, so they size panels, battery
# and inverter alike. The two "Iluminación" entries below get the same
# treatment now (own kWh/día via BEHAVIOR_DUTY_HOURS_DAY_V1, own watts) —
# there's no longer a separate zero-energy "watts-only" case for any category.
COMMON_LOADS_CATALOG_V1: list[dict] = [
    {"name": "Refrigerador",         "nameplate_kw": 0.50, "category": "fixed_cycling"},
    {"name": "Congelador",           "nameplate_kw": 0.30, "category": "fixed_cycling"},
    {"name": "Bomba de agua",        "nameplate_kw": 0.75, "category": "fixed_cycling"},
    {"name": "Bomba de pozo",        "nameplate_kw": 1.10, "category": "fixed_cycling"},
    {"name": "Aire acondicionado",   "nameplate_kw": 1.50, "category": "climate_driven"},
    {"name": "Ventilador",           "nameplate_kw": 0.08, "category": "climate_driven"},
    {"name": "Deshumidificador",     "nameplate_kw": 0.30, "category": "climate_driven"},
    {"name": "Cargador de auto eléctrico", "nameplate_kw": 7.00, "category": "discretionary"},
    {"name": "Bomba de piscina",     "nameplate_kw": 1.00, "category": "discretionary"},
    {"name": "Jacuzzi",              "nameplate_kw": 1.50, "category": "discretionary"},
    {"name": "Bomba de riego",       "nameplate_kw": 0.75, "category": "discretionary"},
    {"name": "Calentador de agua a gas", "nameplate_kw": 0.05, "category": "ignition_only"},
    {"name": "Cocina a gas",         "nameplate_kw": 0.05, "category": "ignition_only"},
    # Electrodomésticos — own kWh/día (APPLIANCE_USE_KWH_DAY_V1) and own watts.
    {"name": "Microondas",           "nameplate_kw": 1.50, "category": "appliance"},
    {"name": "Plantilla eléctrica",  "nameplate_kw": 1.00, "category": "appliance"},
    {"name": "Cafetera",             "nameplate_kw": 0.75, "category": "appliance"},
    {"name": "Pantalla TV",          "nameplate_kw": 0.045, "category": "appliance"},
    {"name": "Lavadora",             "nameplate_kw": 0.50, "category": "appliance"},
    {"name": "Licuadora",            "nameplate_kw": 0.40, "category": "appliance"},
    # Uso general — own kWh/día via BEHAVIOR_DUTY_HOURS_DAY_V1, own watts.
    {"name": "Iluminación exterior", "nameplate_kw": 0.10, "category": "behavior_driven"},
    {"name": "Iluminación interior", "nameplate_kw": 0.02, "category": "behavior_driven"},
]

# ── Category 6: operated appliances (v1) ────────────────────────────────────
# kWh/day per unit. Derived from the usage patterns the user specified
# (2026-07-28): microondas 3 usos × ~5 min a 1.5 kW; plantilla ~45 min a 1 kW;
# cafetera ~25 min a 0.75 kW; TV ~10 h a 45 W ("siempre prendida"). Like the
# fixed_cycling table these are kWh/día benchmarks, NOT nameplate × hours the
# customer is asked to supply — the taxonomy's "never ask for horas de uso"
# rule applies here too.
APPLIANCE_USE_KWH_DAY_V1: dict[str, float] = {
    "microondas": 0.40, "microwave": 0.40,
    "plantilla eléctrica": 0.75, "plantilla electrica": 0.75, "plantilla": 0.75,
    "cocina eléctrica": 0.75, "cocina electrica": 0.75,
    "cafetera": 0.30, "coffee maker": 0.30,
    "pantalla tv": 0.45, "tv": 0.45, "televisor": 0.45, "pantalla": 0.45,
    "lavadora": 0.50, "washer": 0.50,
    "secadora": 1.50, "dryer": 1.50,
    "licuadora": 0.05, "blender": 0.05,
    # Kitchen small-appliance receptacle circuit (NEC 210.11(C)(1)-style) —
    # not one named appliance but a rotating mix of countertop devices
    # (tostadora, licuadora, cafetera) plugged in over the day. Estimated
    # closer to the lighter end of this table (similar order of magnitude to
    # microondas/cafetera individually) since the circuit is rarely loaded
    # continuously — v1, not yet calibrated, same caveat as every other
    # figure in this table.
    "tomacorriente de cocina": 0.45, "tomacorrientes de cocina": 0.45,
    "tomacorriente cocina": 0.45, "tomacorrientes cocina": 0.45,
    # Electric instant/point-of-use water heater ("ducha eléctrica" /
    # "calentador de paso") — the overwhelmingly common water-heating fixture
    # in Costa Rican homes, NOT a gas unit. Bare "calentador de agua" (no
    # "a gas"/"gas" qualifier) must resolve here, not to ignition_only —
    # see the ignition_only note below and _CLASSIFY_PROMPT for why this
    # was a real misclassification, not just a naming edge case. High
    # instantaneous power (commonly 3500-6000 W) but brief per-use duration
    # (~10-15 min shower) — estimated at one bathroom's typical daily use.
    "calentador de agua": 1.00, "ducha eléctrica": 1.00, "ducha electrica": 1.00,
    "calentador de paso": 1.00, "calentador eléctrico": 1.00, "calentador electrico": 1.00,
    # Combo washer+dryer unit ("centro de lavado") — both functions in one
    # machine, used together per cycle. Estimated as lavadora + secadora
    # combined (this table's own values for each function separately).
    "centro de lavado": 2.00, "lavado y secado": 2.00,
    # Electric oven — baking, similar usage-intensity basis to "cocina
    # eléctrica" above (often the same kitchen circuit/appliance in practice).
    "horno de cocina": 0.70, "horno eléctrico": 0.70, "horno electrico": 0.70,
    # Garbage disposal — high-power motor (~500-1000 W) but seconds-to-a-
    # couple-minutes per use, several times/day. Small total energy, same
    # order of magnitude as licuadora (another brief high-power motor use).
    "triturador de alimentos": 0.05, "triturador de basura": 0.05, "disposal": 0.05,
    # Range hood / grease extractor fan — runs during cooking, moderate fan
    # motor, cumulative ~20-40 min/day across meals.
    "extractor de grasa": 0.12, "campana extractora": 0.12, "extractor de cocina": 0.12,
}
_APPLIANCE_USE_DEFAULT_KWH_DAY_V1 = 0.30  # unmatched appliance — flagged default_assumed

# ── Category 1: fixed/cycling appliance benchmarks (v1) ─────────────────────
# kWh/day per unit, independent of nameplate watts (nameplate is starting draw).
APPLIANCE_BENCHMARKS_KWH_DAY_V1: dict[str, float] = {
    "refrigerador": 1.2, "refrigeradora": 1.2, "nevera": 1.2, "refrigerator": 1.2,
    "congelador": 1.0, "freezer": 1.0,
    "bomba de agua": 0.8, "water pump": 0.8,
    "bomba de piscina": 2.5, "pool pump": 2.5,
    "bomba de pozo": 1.0,
}
_APPLIANCE_DEFAULT_KWH_DAY_V1 = 1.0  # unmatched fixed/cycling load — flagged default_assumed

# ── Category 2: behavior-driven — per-line duty hours (v3) ──────────────────
# v3 (2026-08-07, on user direction): replaced the v2 per-espacio aggregate
# (num_bedrooms × flat kWh/día/espacio) with a per-line estimate — each
# behavior_driven load gets its own daily energy from
# connected_power_kw × duty_hours_day × quantity, same formula shape as
# every other category's line-level estimate, rather than a single lump
# figure the whole house shared regardless of what was actually listed.
#
# The aggregate model broke down specifically when a home's loads were split
# across two independent tables (critical/backup panel vs. main panel, for
# Hybrid systems) — each table computed its own "espacios" aggregate with no
# way to tell whether the two were meant to partition the house (no overlap)
# or both represent the whole house (redundant), and nothing in the UI or
# code disambiguated it. Per-line duty hours sidesteps the question entirely:
# each line's energy depends only on that line's own inputs, so there's
# nothing to double-count or drop across a table split.
#
# Matched the same way as APPLIANCE_USE_KWH_DAY_V1 — longest-key-first
# keyword lookup — via estimate_behavior_duty_hours() below.
BEHAVIOR_DUTY_HOURS_DAY_V1: dict[str, float] = {
    "iluminación exterior": 6.0, "iluminacion exterior": 6.0,
    "iluminación interior": 4.5, "iluminacion interior": 4.5,
    "iluminación": 5.0, "iluminacion": 5.0, "luces": 5.0,
    "tomacorriente de telecomunicaciones": 24.0, "tomacorrientes de telecomunicaciones": 24.0,
    "tomacorriente": 3.0, "tomacorrientes": 3.0,  # general/background receptacle use
    "computadora": 6.0, "computador": 6.0, "laptop": 6.0,
    "router": 24.0, "módem": 24.0, "modem": 24.0,  # always on
    "reloj": 24.0, "cargadores": 2.0, "cargador": 2.0,
}
_BEHAVIOR_DUTY_HOURS_DEFAULT_V1 = 3.0  # unmatched behavior_driven load — flagged default_assumed

# ── Category 5: ignition-only (v1) ──────────────────────────────────────────
IGNITION_KWH_DAY_V1 = 0.08

# ── Category 4: discretionary — CR regional defaults (v1), used only when no
# intake answer is given for that load. Matched by keyword list rather than a
# single substring key — multi-word Spanish load names don't reliably contain
# a fixed-order phrase (e.g. "Bomba de piscina" vs a key like
# "piscina_bomba_filtro"), and short ambiguous tokens like bare "ev" would
# false-positive-match unrelated words (e.g. "nevera" contains "ev") — every
# keyword below is a distinctive whole word/phrase to avoid that. ────────────
DISCRETIONARY_DEFAULTS_V1: list[dict] = [
    {
        "keywords": ["cargador ev", "cargador de auto eléctrico", "ev charger", "vehículo eléctrico", "carro eléctrico"],
        "kwh_day": 8.0, "basis": "~30 km/día promedio CR, eficiencia EV típica",
    },
    {
        "keywords": ["jacuzzi", "spa", "hidromasaje"],
        "kwh_day": 3.0, "basis": "uso típico 1-2h/día, calentador eléctrico",
    },
    {
        "keywords": ["piscina", "pool"],
        "kwh_day": 2.5, "basis": "8h/día ciclo de filtrado típico",
    },
    {
        "keywords": ["riego", "irrigación", "irrigation"],
        "kwh_day": 1.0, "basis": "riego residencial típico, ciclo corto diario",
    },
]
_DISCRETIONARY_DEFAULT_KWH_DAY_V1 = 2.0

# ── Category 3: climate-driven constants (v1) ───────────────────────────────
# First-pass degree-day model — NOT yet calibrated against real CR metered
# A/C data (per the source doc's "open items", this is the highest-leverage
# piece to refine once real consumption data exists). Documented explicitly
# so it's clear this is an estimate, not a validated formula.
_CDD_BASE_TEMP_C = 24.0          # comfortable indoor set point assumption
_CDD_TO_HOURS_FACTOR_V1 = 0.8    # hours of compressor runtime per °C-day of CDD
_AC_DUTY_CYCLE_V1 = 0.6          # compressor on-time fraction while "running"
_MAX_AC_HOURS_DAY = 12.0

# ── Pre-classified common Costa Rican load names (v1) ───────────────────────
# Checked before any AI call — covers the overwhelming majority of real load
# lists deterministically, so AI classification (and its cost/latency) is
# only invoked for genuinely novel/ambiguous names.
_PRECLASSIFIED_V1: dict[str, str] = {
    "refrigerador": "fixed_cycling", "refrigeradora": "fixed_cycling", "nevera": "fixed_cycling",
    "congelador": "fixed_cycling", "freezer": "fixed_cycling",
    "bomba de agua": "fixed_cycling", "bomba de pozo": "fixed_cycling",
    # behavior_driven = lighting + the always-on receptacle background load.
    # Computadora/router/reloj stay here deliberately: they're plug loads that
    # sit on continuously — not task appliances the occupant switches on.
    "iluminación": "behavior_driven", "iluminacion": "behavior_driven", "luces": "behavior_driven",
    "tomacorriente": "behavior_driven", "tomacorrientes": "behavior_driven",
    "iluminación exterior": "behavior_driven", "iluminacion exterior": "behavior_driven",
    "iluminación interior": "behavior_driven", "iluminacion interior": "behavior_driven",
    "computadora": "behavior_driven", "computador": "behavior_driven", "laptop": "behavior_driven",
    "router": "behavior_driven", "módem": "behavior_driven", "modem": "behavior_driven",
    "reloj": "behavior_driven", "cargadores": "behavior_driven",
    # appliance = operated on demand to do a task — own kWh/día AND own watts.
    "microondas": "appliance", "lavadora": "appliance", "secadora": "appliance",
    "tv": "appliance", "televisor": "appliance", "pantalla tv": "appliance",
    "pantalla": "appliance", "licuadora": "appliance", "cafetera": "appliance",
    "plantilla eléctrica": "appliance", "plantilla electrica": "appliance",
    "plantilla": "appliance", "cocina eléctrica": "appliance", "cocina electrica": "appliance",
    # Kitchen receptacle circuits are a real exception to the generic
    # "tomacorriente(s)" → behavior_driven rule above: NEC 210.11(C)(1)-style
    # "small appliance circuits" are dedicated to countertop appliances
    # (tostadora, licuadora, cafetera) switched on to do a task, not the
    # always-on background plug load (router, cargadores) the Uso General
    # aggregate models — a kitchen receptacle circuit behaves like the other
    # "appliance" entries above, not like a bedroom/living-room outlet.
    "tomacorriente de cocina": "appliance", "tomacorrientes de cocina": "appliance",
    "tomacorriente cocina": "appliance", "tomacorrientes cocina": "appliance",
    # Electric instant/point-of-use water heater ("ducha eléctrica" /
    # "calentador de paso") — bare "calentador de agua" (no "a gas"/"gas"
    # qualifier) is the overwhelmingly common case in Costa Rica and must
    # land here, NOT in ignition_only below. The longer, explicit
    # "calentador de agua a gas" phrase still wins for genuine gas units —
    # both entries are in this same "specific" priority group, sorted
    # longest-first, so the more specific phrase is checked before this one.
    "calentador de agua": "appliance", "ducha eléctrica": "appliance", "ducha electrica": "appliance",
    "calentador de paso": "appliance", "calentador eléctrico": "appliance", "calentador electrico": "appliance",
    "centro de lavado": "appliance", "lavado y secado": "appliance",
    "horno de cocina": "appliance", "horno eléctrico": "appliance", "horno electrico": "appliance",
    "triturador de alimentos": "appliance", "triturador de basura": "appliance", "disposal": "appliance",
    "extractor de grasa": "appliance", "campana extractora": "appliance", "extractor de cocina": "appliance",
    "aire acondicionado": "climate_driven", "a/c": "climate_driven", "ac": "climate_driven",
    "minisplit": "climate_driven", "split": "climate_driven", "calefacción": "climate_driven",
    "deshumidificador": "climate_driven",
    "cargador ev": "discretionary", "cargador de auto eléctrico": "discretionary", "ev charger": "discretionary",
    "jacuzzi": "discretionary", "spa": "discretionary", "hidromasaje": "discretionary",
    "bomba de piscina": "discretionary", "piscina": "discretionary",
    "riego": "discretionary", "irrigación": "discretionary",
    # Gas units — deliberately just the control/ignition circuit's negligible
    # electrical draw, NOT the appliance's heating output (that comes from
    # gas). Requires an explicit "a gas" — see the "calentador de agua"
    # (electric) entries above for the far more common non-gas case.
    "calentador de agua a gas": "ignition_only", "cocina a gas": "ignition_only",
    "secadora a gas": "ignition_only",
}

# Precomputed once, longest-key-first within each group, so a specific
# phrase always outranks a shorter keyword it happens to contain — e.g.
# "secadora a gas" (ignition_only) must win over the shorter "secadora"
# (appliance) it contains, the same way estimate_appliance_use() below
# already sorts APPLIANCE_USE_KWH_DAY_V1 longest-first for "plantilla
# eléctrica" vs bare "plantilla". Split into two groups (everything else,
# then behavior_driven) because behavior_driven's generic receptacle/
# lighting keywords ("tomacorriente", "iluminación") must always be
# checked last regardless of length — Costa Rican circuit schedules often
# name a receptacle by what plugs into it ("Tomacorriente para
# microondas"), and the generic keyword must not shadow the specific one.
_PRECLASSIFIED_SPECIFIC_V1 = sorted(
    ((k, v) for k, v in _PRECLASSIFIED_V1.items() if v != "behavior_driven"),
    key=lambda kv: -len(kv[0]),
)
_PRECLASSIFIED_GENERIC_V1 = sorted(
    ((k, v) for k, v in _PRECLASSIFIED_V1.items() if v == "behavior_driven"),
    key=lambda kv: -len(kv[0]),
)

_MODEL = "claude-haiku-4-5-20251001"

# Fallback when the AI classifier fails or returns something unrecognized —
# "appliance" gives the load _APPLIANCE_USE_DEFAULT_KWH_DAY_V1 flagged
# CONFIDENCE_DEFAULT, which surfaces in the wizard's "revísalas antes de
# continuar" banner. (Both "appliance" and "behavior_driven" now produce a
# real, visible-if-default estimate rather than a silent zero — this choice
# is no longer load-bearing the way it was before the v3 per-line rewrite.)
_CLASSIFY_FALLBACK = "appliance"

_CLASSIFY_PROMPT = """Classify this Costa Rican residential electrical load name into EXACTLY ONE of these 5 categories. Respond with ONLY the category key, nothing else.

Categories:
- fixed_cycling: refrigerator, freezer, water pump — appliances with a fixed duty cycle regardless of behavior
- behavior_driven: lighting and always-on receptacle background load ONLY (general outlets, computer, router, clock, phone chargers). Do NOT put task appliances here.
- climate_driven: A/C, space heating, dehumidifier
- discretionary: EV charger, pool/jacuzzi/spa equipment, irrigation — occupant-choice driven
- ignition_only: ONLY when the name explicitly says gas/LP ("a gas", "gas", "LP") — gas water heater, gas stove, gas dryer control circuits (negligible electrical draw). A water heater with NO gas/LP wording is electric (very common in Costa Rica as a "ducha eléctrica"/"calentador de paso" point-of-use heater) and must NOT go here — classify it as appliance instead.
- appliance: appliances switched on to perform a task — microwave, electric hotplate/cooktop, coffee maker, TV, washing machine, dryer, blender, toaster, iron, electric water heater/shower (no gas wording), oven, garbage disposal, range hood/grease extractor

Load name: "{name}"

Answer with only one of: fixed_cycling, behavior_driven, climate_driven, discretionary, ignition_only, appliance"""


def _normalize(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


def _keyword_matches(keyword: str, text: str) -> bool:
    """
    Word-boundary match, not a raw substring check — a short/generic key
    like "ac" (meant for the "A/C" shorthand) is otherwise a substring of
    completely unrelated Spanish words: "tomacorriente" and "iluminación"
    both contain the letters "ac" consecutively with no boundary around
    them, so a plain `"ac" in key` check silently misclassifies any
    receptacle/lighting circuit as climate_driven. Same false-positive risk
    already called out for DISCRETIONARY_DEFAULTS_V1's keyword lists (bare
    "ev" matching inside "nevera") — this generalizes that same protection
    to every keyword table in this module. Multi-word phrases ("bomba de
    agua") still match correctly since \\b also sits at whitespace/word
    boundaries, not just string edges.
    """
    return re.search(r"\b" + re.escape(keyword) + r"\b", text) is not None


def _get_classification_cache() -> dict[str, str]:
    from database.supabase_client import get_client

    try:
        result = (
            get_client()
            .table("app_settings")
            .select("value")
            .eq("key", "load_classification_cache_v1")
            .single()
            .execute()
        )
        if result.data:
            v = result.data["value"]
            return v if isinstance(v, dict) else json.loads(v)
    except Exception:
        pass
    return {}


def _store_classification_cache(cache: dict[str, str]) -> None:
    from database.supabase_client import get_client

    payload = {
        "key": "load_classification_cache_v1",
        "value": json.dumps(cache),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        get_client().table("app_settings").upsert(payload, on_conflict="key").execute()
    except Exception:
        pass


def classify_load_category(load_name: str) -> str:
    """
    Maps a free-text load name to one of the 5 CATEGORIES.

    Checks the versioned hardcoded table first, then a persisted cache
    (Supabase app_settings), and only calls AI (constrained to the enum) for
    a genuinely new name — result is cached afterward so the same name never
    risks a different answer on a later run, per the doc's determinism
    requirement. Falls back to _CLASSIFY_FALLBACK if the AI call fails or
    returns something outside the enum.

    Two-pass keyword match, not a single pass in dict order: Costa Rican
    circuit schedules commonly name a receptacle by what plugs into it
    ("Tomacorriente para microondas"), so the generic "tomacorriente"
    keyword (behavior_driven) and a specific one ("microondas", appliance)
    are both substrings of the same name. Checking behavior_driven's generic
    receptacle/lighting keywords first would swallow the specific match
    every time — a microwave circuit would silently read as background plug
    load and get behavior_driven's duty-hours estimate instead of its own
    appliance benchmark, a real, silent misclassification even though both
    now produce a non-zero kWh/día. Specific categories are checked first;
    the generic behavior_driven markers only apply when nothing more
    specific matched.
    """
    key = _normalize(load_name)

    for known, category in _PRECLASSIFIED_SPECIFIC_V1:
        if _keyword_matches(known, key):
            return category
    for known, category in _PRECLASSIFIED_GENERIC_V1:
        if _keyword_matches(known, key):
            return category

    cache = _get_classification_cache()
    if key in cache:
        return cache[key]

    try:
        import anthropic
        import os

        client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        response = client.messages.create(
            model=_MODEL,
            max_tokens=20,
            messages=[{"role": "user", "content": _CLASSIFY_PROMPT.format(name=load_name)}],
        )
        answer = response.content[0].text.strip().lower()
        category = next((c for c in CATEGORIES if c == answer), None)
        if category is None:
            category = _CLASSIFY_FALLBACK
    except Exception:
        category = _CLASSIFY_FALLBACK

    cache[key] = category
    _store_classification_cache(cache)
    return category


# ── Illustrative hourly shape (visualization only — never used for sizing) ──
# AI generates a *relative* 24h intensity shape per category, purely to help
# an engineer see when load likely overlaps with solar production vs. battery
# discharge. The category's own kWh/día (computed deterministically above)
# is never touched — only how that fixed daily total is *distributed* across
# the 24 hours for the chart. Hardcoded fallback shapes cover every category
# so this never blocks the page if the AI call fails or times out.
_DEFAULT_HOURLY_SHAPES: dict[str, list[float]] = {
    "fixed_cycling": [1.0] * 24,  # fridge/pumps: roughly constant duty cycle
    "climate_driven": [
        0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.4, 0.4, 0.4, 0.4,
        0.7, 0.7, 0.7, 0.7, 1.0, 1.0, 1.0, 1.0, 0.8, 0.8, 0.8, 0.5, 0.5, 0.5,
    ],  # A/C: afternoon heat peak
    "behavior_driven": [
        0.3, 0.2, 0.2, 0.2, 0.2, 0.3, 0.6, 0.8, 0.6, 0.4,
        0.4, 0.4, 0.4, 0.4, 0.5, 0.5, 0.6, 0.8, 1.0, 1.0, 1.0, 0.9, 0.7, 0.4,
    ],  # lighting + always-on outlets: morning + evening peaks
    "appliance": [
        0.1, 0.05, 0.05, 0.05, 0.05, 0.1, 0.5, 0.9, 0.7, 0.5,
        0.4, 0.6, 0.9, 0.6, 0.4, 0.4, 0.5, 0.8, 1.0, 0.9, 0.7, 0.4, 0.2, 0.1,
    ],  # cooking/laundry/TV: breakfast, midday and evening meal peaks
    "discretionary": [
        0.6, 0.6, 0.5, 0.4, 0.3, 0.2, 0.2, 0.2, 0.3, 0.4,
        0.6, 0.7, 0.7, 0.6, 0.5, 0.4, 0.3, 0.3, 0.4, 0.6, 0.8, 1.0, 0.9, 0.7,
    ],  # EV/pool/irrigation: midday + evening/overnight charging
    "ignition_only": [0.1] * 24,  # gas appliances: negligible electrical draw
}

_HOURLY_SHAPE_PROMPT = """You are estimating an ILLUSTRATIVE (not exact) hourly usage pattern for a Costa Rican residential or small-business property, for a data-visualization aid only — this shape is never used for energy sizing calculations, only to help an engineer see roughly when each type of load tends to draw power during the day.

Categories present: {categories}
Load names on site: {load_names}

For each category, provide 24 relative intensity weights (0.0 to 1.0, one per hour, starting at hour 0 = midnight) reflecting typical daily usage patterns for that category in this context. Respond with ONLY a JSON object mapping each category key to a list of exactly 24 numbers — no other text, no markdown fences.

Example shape (format only, not real values): {{"fixed_cycling": [0.9, 0.9, ...24 numbers total...], "climate_driven": [0.2, 0.2, ...24 numbers total...]}}

Categories must be exactly these keys where present: fixed_cycling, behavior_driven, climate_driven, discretionary, ignition_only, appliance."""


def estimate_hourly_shape_illustrative(
    categories: list[str], load_names: list[str] | None = None
) -> dict[str, list[float]]:
    """
    AI-generated illustrative 24h relative-intensity shape per category, for
    visualization only. Falls back to _DEFAULT_HOURLY_SHAPES per-category if
    the AI call fails, times out, or returns malformed/incomplete data for
    a given category — every category always gets *some* shape.
    """
    cats = [c for c in dict.fromkeys(categories) if c in _DEFAULT_HOURLY_SHAPES]
    if not cats:
        return {}

    shapes: dict[str, list[float]] = {}
    try:
        import anthropic
        import os

        client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        prompt = _HOURLY_SHAPE_PROMPT.format(
            categories=", ".join(cats),
            load_names=", ".join(load_names) if load_names else "(not specified)",
        )
        response = client.messages.create(
            model=_MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
        parsed = json.loads(text)
        for cat in cats:
            values = parsed.get(cat)
            if (
                isinstance(values, list) and len(values) == 24
                and all(isinstance(v, (int, float)) and 0 <= v <= 1 for v in values)
            ):
                shapes[cat] = [float(v) for v in values]
    except Exception:
        pass

    for cat in cats:
        if cat not in shapes:
            shapes[cat] = _DEFAULT_HOURLY_SHAPES[cat]
    return shapes


# ── Category-specific deterministic estimators ──────────────────────────────

def estimate_fixed_cycling(load_name: str, quantity: int) -> dict:
    key = _normalize(load_name)
    match = next((v for k, v in APPLIANCE_BENCHMARKS_KWH_DAY_V1.items() if k in key), None)
    if match is not None:
        return {
            "kwh_day": round(match * quantity, 2),
            "confidence": CONFIDENCE_BENCHMARK,
            "source_detail": f"Tabla de referencia v1: {match} kWh/día/unidad",
        }
    return {
        "kwh_day": round(_APPLIANCE_DEFAULT_KWH_DAY_V1 * quantity, 2),
        "confidence": CONFIDENCE_DEFAULT,
        "source_detail": f"Sin coincidencia en tabla de referencia — default {_APPLIANCE_DEFAULT_KWH_DAY_V1} kWh/día/unidad",
    }


def estimate_appliance_use(load_name: str, quantity: int) -> dict:
    """
    Category 6 — appliances the occupant switches on to do a task.

    Same shape as estimate_fixed_cycling(): a kWh/día benchmark per unit, not
    nameplate × hours. Nameplate watts still matter, but they're carried
    separately on the profile line (connected_power_kw) for inverter sizing —
    a 1.5 kW microwave run 15 min/day is a big inverter load and a small
    energy load, and the two numbers must not be conflated.

    Longest-key-first matching so "plantilla eléctrica" wins over a bare
    "plantilla", and "pantalla tv" over "tv" — plain `k in key` iteration order
    would otherwise let a short key shadow a more specific one.
    """
    key = _normalize(load_name)
    match = next(
        (v for k, v in sorted(APPLIANCE_USE_KWH_DAY_V1.items(), key=lambda kv: -len(kv[0])) if k in key),
        None,
    )
    if match is not None:
        return {
            "kwh_day": round(match * quantity, 2),
            "confidence": CONFIDENCE_BENCHMARK,
            "source_detail": f"Tabla de electrodomésticos v1: {match} kWh/día/unidad",
        }
    return {
        "kwh_day": round(_APPLIANCE_USE_DEFAULT_KWH_DAY_V1 * quantity, 2),
        "confidence": CONFIDENCE_DEFAULT,
        "source_detail": (
            f"Sin coincidencia en tabla de electrodomésticos — default "
            f"{_APPLIANCE_USE_DEFAULT_KWH_DAY_V1} kWh/día/unidad"
        ),
    }


def estimate_ignition_only(quantity: int) -> dict:
    return {
        "kwh_day": round(IGNITION_KWH_DAY_V1 * quantity, 2),
        "confidence": CONFIDENCE_BENCHMARK,
        "source_detail": f"Consumo de encendido/control únicamente: {IGNITION_KWH_DAY_V1} kWh/día/unidad",
    }


def estimate_discretionary(load_name: str, user_answer_kwh_day: float | None = None) -> dict:
    """
    user_answer_kwh_day: a structured kWh/day figure already derived from an
    intake-question answer (e.g. "I drive ~40km/day" converted upstream to a
    kWh/day estimate) — the AI's role stops at extracting that structured
    number; this function never calls AI itself.
    """
    if user_answer_kwh_day is not None:
        return {
            "kwh_day": round(user_answer_kwh_day, 2),
            "confidence": CONFIDENCE_USER_CONFIRMED,
            "source_detail": "Respuesta directa del cliente a pregunta de uso",
        }

    key = _normalize(load_name)
    match = next(
        (entry for entry in DISCRETIONARY_DEFAULTS_V1 if any(kw in key for kw in entry["keywords"])),
        None,
    )
    if match is not None:
        return {
            "kwh_day": round(match["kwh_day"], 2),
            "confidence": CONFIDENCE_DEFAULT,
            "source_detail": f"Default regional CR (sin respuesta del cliente): {match['basis']}",
        }
    return {
        "kwh_day": round(_DISCRETIONARY_DEFAULT_KWH_DAY_V1, 2),
        "confidence": CONFIDENCE_DEFAULT,
        "source_detail": f"Sin coincidencia en defaults regionales — genérico {_DISCRETIONARY_DEFAULT_KWH_DAY_V1} kWh/día",
    }


def estimate_behavior_duty_hours(load_name: str) -> tuple[float, bool]:
    """
    Default daily duty-hours for a behavior_driven line, by keyword —
    longest-key-first so "iluminación exterior" wins over bare "iluminación",
    same pattern as estimate_appliance_use(). Returns (hours, matched) so the
    caller can flag an unmatched name as default_assumed rather than
    benchmark confidence.
    """
    key = _normalize(load_name)
    match = next(
        (v for k, v in sorted(BEHAVIOR_DUTY_HOURS_DAY_V1.items(), key=lambda kv: -len(kv[0])) if _keyword_matches(k, key)),
        None,
    )
    if match is not None:
        return match, True
    return _BEHAVIOR_DUTY_HOURS_DEFAULT_V1, False


def estimate_behavior_line(
    load_name: str, quantity: int, connected_power_kw: float, duty_hours_day: float | None = None,
) -> dict:
    """
    Category 2 — lighting + always-on receptacle background load, sized per
    line (v3 — see BEHAVIOR_DUTY_HOURS_DAY_V1 above for why this replaced
    the old per-espacio aggregate).

    duty_hours_day: engineer override (from the wizard's editable column) —
    when given, used as-is at CONFIDENCE_USER_CONFIRMED. When None, the
    default is looked up by keyword (estimate_behavior_duty_hours()).
    """
    if duty_hours_day is not None:
        kwh_day = round(connected_power_kw * duty_hours_day * quantity, 2)
        return {
            "kwh_day": kwh_day,
            "duty_hours_day": duty_hours_day,
            "confidence": CONFIDENCE_USER_CONFIRMED,
            "source_detail": f"{connected_power_kw} kW × {duty_hours_day} h/día × {quantity} (horas ajustadas por el ingeniero)",
        }

    hours, matched = estimate_behavior_duty_hours(load_name)
    kwh_day = round(connected_power_kw * hours * quantity, 2)
    return {
        "kwh_day": kwh_day,
        "duty_hours_day": hours,
        "confidence": CONFIDENCE_BENCHMARK if matched else CONFIDENCE_DEFAULT,
        "source_detail": (
            f"{connected_power_kw} kW × {hours} h/día × {quantity} (tabla de uso general v1)"
            if matched else
            f"{connected_power_kw} kW × {hours} h/día × {quantity} (sin coincidencia — default {_BEHAVIOR_DUTY_HOURS_DEFAULT_V1} h/día)"
        ),
    }


# ── Category 3: climate-driven, Open-Meteo climate normals ──────────────────

def _climate_cache_key(lat: float, lon: float) -> str:
    return f"climate_normals_{lat:.3f}_{lon:.3f}"


def get_cached_climate_normals(lat: float, lon: float) -> dict | None:
    from database.supabase_client import get_client

    try:
        result = (
            get_client()
            .table("app_settings")
            .select("value")
            .eq("key", _climate_cache_key(lat, lon))
            .single()
            .execute()
        )
        if result.data:
            v = result.data["value"]
            return v if isinstance(v, dict) else json.loads(v)
    except Exception:
        pass
    return None


def _store_climate_cache(lat: float, lon: float, data: dict) -> None:
    from database.supabase_client import get_client

    payload = {
        "key": _climate_cache_key(lat, lon),
        "value": json.dumps(data),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        get_client().table("app_settings").upsert(payload, on_conflict="key").execute()
    except Exception:
        pass


def fetch_climate_normals(lat: float, lon: float) -> dict | None:
    """
    Fetches daily MAX temperature climate normals from Open-Meteo (free, no
    API key) — averaged from its historical archive rather than an LLM's
    recollection of "typical temperatures", per the doc's explicit warning
    against that. Cached in Supabase by lat/lon (mirrors calculations/pvgis.py).

    Uses daily max, not the 24h mean: A/C runtime is driven by peak daytime
    heat, and Costa Rica's tropical nights are cool enough that the 24h mean
    pulls well below any reasonable cooling threshold even in genuinely hot
    towns — a first version of this function used temperature_2m_mean and
    computed 0 kWh/day of A/C use for Atenas (a well-known hot valley town
    where A/C is very much needed), which is a real bug, not just imprecise.

    Returns {"avg_max_temp_c": float, "source": "open-meteo"} or None on
    failure — callers must fall back to a default-assumed confidence tag,
    never guess a number themselves.
    """
    cached = get_cached_climate_normals(lat, lon)
    if cached:
        return cached

    try:
        import requests

        # Historical daily max temperature, last full calendar year, as a
        # simple climate-normal proxy (a full multi-year normal is a future
        # refinement — see module docstring on v1 tables).
        resp = requests.get(
            "https://archive-api.open-meteo.com/v1/archive",
            params={
                "latitude": lat,
                "longitude": lon,
                "start_date": "2025-01-01",
                "end_date": "2025-12-31",
                "daily": "temperature_2m_max",
                "timezone": "America/Costa_Rica",
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        temps = [t for t in data.get("daily", {}).get("temperature_2m_max", []) if t is not None]
        if not temps:
            return None

        avg_max_temp_c = round(sum(temps) / len(temps), 1)
        result = {"avg_max_temp_c": avg_max_temp_c, "source": "open-meteo"}
        _store_climate_cache(lat, lon, result)
        return result
    except Exception:
        return None


def estimate_climate_driven(
    quantity: int,
    connected_power_kw: float,
    lat: float | None,
    lon: float | None,
) -> dict:
    """
    Degree-day based A/C estimate. First-pass model (v1, not yet calibrated
    against real CR metered A/C data — see module docstring): estimates daily
    compressor runtime hours from cooling degree-days, then applies a duty
    cycle factor to connected power.
    """
    climate = fetch_climate_normals(lat, lon) if (lat and lon) else None

    if climate is None:
        # No API data available — flagged prominently as default_assumed,
        # per the doc: this must not look as confident as an API-calculated figure.
        hours = 6.0
        confidence = CONFIDENCE_DEFAULT
        source_detail = "Sin datos climáticos (API no disponible) — 6h/día genérico"
    else:
        cdd = max(0.0, climate["avg_max_temp_c"] - _CDD_BASE_TEMP_C)
        hours = min(_MAX_AC_HOURS_DAY, cdd * _CDD_TO_HOURS_FACTOR_V1)
        confidence = CONFIDENCE_API
        source_detail = (
            f"CDD={cdd:.1f}°C-día (máx. promedio anual {climate['avg_max_temp_c']}°C, base {_CDD_BASE_TEMP_C}°C) "
            f"× {_CDD_TO_HOURS_FACTOR_V1} h/°C-día — Open-Meteo, modelo v1 sin calibrar"
        )

    kwh_day = round(quantity * connected_power_kw * hours * _AC_DUTY_CYCLE_V1, 2)
    return {"kwh_day": kwh_day, "confidence": confidence, "source_detail": source_detail}


# ── Power demand factors (v2 — per line) ─────────────────────────────────────
# A different question from every kWh/día estimator above: those answer "how
# much energy does this load use per day"; this answers "how much of its
# installed (nameplate) power is actually drawing at the same instant as
# everything else" — the number that should drive inverter sizing and AC
# breaker selection, not the raw Σ nameplate. Summing nameplate power across
# a load list with many circuits systematically overstates simultaneous draw,
# the same failure mode the kWh taxonomy above was built to fix for energy —
# this is the power-side equivalent.
#
# v2 (2026-08-07, on user direction): replaced the old category-level
# flat/"largest+rest" dispatch with one editable factor PER LINE — matches
# a real NEC-style circuit schedule (each circuit gets its own demand factor,
# not a factor shared by every circuit of the same type) and lets the
# engineer override any single line without changing every other line in its
# category. DEMAND_FACTOR_DEFAULTS_V1 below is only a starting value shown
# in the wizard's editable column — compute_demand_load() always reads each
# line's OWN factor (falling back to this table only when a line genuinely
# has none set, e.g. an old saved draft from before this field existed).
#
# v1, first-pass values — NOT yet calibrated against real installs, same
# caveat as every other _V1 table in this module.
DEMAND_FACTOR_DEFAULTS_V1: dict[str, float] = {
    "fixed_cycling": 0.95,     # always-ready, short/near-random duty cycles
    "behavior_driven": 0.70,   # lighting + receptacles: not every fixture/outlet fires at once
    "ignition_only": 1.0,      # negligible magnitude regardless — no diversity needed
    "appliance": 0.55,         # kitchen/laundry tasks — rarely several run together
    "climate_driven": 0.65,    # multiple A/C units can coincide on hot afternoons
    "discretionary": 0.80,     # big standalone loads (EV/pool/jacuzzi), least likely to cancel out
}
_DEMAND_FACTOR_DEFAULT_FALLBACK = 0.70  # unclassifiable/unknown category — never silently drop load


def default_demand_factor_pct(category: str | None) -> float:
    return DEMAND_FACTOR_DEFAULTS_V1.get(category, _DEMAND_FACTOR_DEFAULT_FALLBACK)


def compute_demand_load(lines: list[dict]) -> dict:
    """
    Translates installed (nameplate) power into demanded (design) power,
    summing PER LINE — each line carries `category`, `quantity`,
    `connected_power_kw`, and its own `demand_factor_pct` (set by
    build_load_profile(); falls back to default_demand_factor_pct(category)
    for older lines saved before this field existed).

    Returns:
        {
          "categories": [ {category, installed_kw, demand_kw,
                            factor_applied}, ... ] — factor_applied is that
                         category's blended (demand/installed) ratio across
                         its lines, sorted by installed_kw descending, only
                         categories actually present in `lines`,
          "total_installed_kw": float,
          "total_demand_kw": float,
          "blended_factor": float,  # total_demand_kw / total_installed_kw
        }
    """
    by_cat: dict[str, dict[str, float]] = {}
    total_installed = 0.0
    total_demand = 0.0
    for line in lines:
        cat = line.get("category")
        kw = float(line.get("connected_power_kw") or 0) * int(line.get("quantity") or 1)
        factor = line.get("demand_factor_pct")
        factor = float(factor) if factor is not None else default_demand_factor_pct(cat)
        demand = kw * factor

        entry = by_cat.setdefault(cat, {"installed_kw": 0.0, "demand_kw": 0.0})
        entry["installed_kw"] += kw
        entry["demand_kw"] += demand
        total_installed += kw
        total_demand += demand

    categories = [
        {
            "category": cat,
            "installed_kw": round(v["installed_kw"], 3),
            "demand_kw": round(v["demand_kw"], 3),
            "factor_applied": round(v["demand_kw"] / v["installed_kw"], 3) if v["installed_kw"] > 0 else 0.0,
        }
        for cat, v in by_cat.items()
    ]

    return {
        "categories": sorted(categories, key=lambda c: -c["installed_kw"]),
        "total_installed_kw": round(total_installed, 3),
        "total_demand_kw": round(total_demand, 3),
        "blended_factor": round(total_demand / total_installed, 3) if total_installed > 0 else 0.0,
    }


# ── Main entry point ─────────────────────────────────────────────────────────

def build_load_profile(
    loads: list[dict],
    lat: float | None = None,
    lon: float | None = None,
    discretionary_answers: dict[str, float] | None = None,
) -> dict:
    """
    loads: [{"name": str, "quantity": int, "nameplate_kw": float,
             "category": str | None, "demand_factor_pct": float | None,
             "duty_hours_day": float | None}, ...].
           "category" is optional: if the engineer has already picked one of
           CATEGORIES (e.g. via the wizard's manual override selector, or a
           row added from COMMON_LOADS_CATALOG_V1), it's used as-is and
           classify_load_category() (the AI call) is skipped entirely for
           that line — cheaper and removes any classification uncertainty.
           "demand_factor_pct" is optional (None -> default_demand_factor_pct
           (category) is used) — an engineer override of how much of this
           line's installed power draws simultaneously with everything else
           (peak-side, read later by compute_demand_load(), not used here).
           "duty_hours_day" is optional, for EVERY category (not just
           behavior_driven) — when given, it's an explicit engineer override
           that replaces whatever category-specific estimator would have run
           with a plain connected_power_kw × duty_hours_day × quantity
           calculation. When omitted, each category still uses its own
           specialized estimator (benchmark table, degree-day model, etc.) as
           before, and the line reports a BACKED-OUT duty_hours_day (that
           estimator's own kwh_day ÷ power ÷ quantity) purely for display —
           so the wizard's Horas/día column never shows a bare gap, without
           pretending every category is secretly hours-based internally.
    discretionary_answers: optional {load_name: kwh_day} already extracted
           from intake-question answers (AI's role stops at extraction, see
           estimate_discretionary docstring).

    Returns:
        {
          "lines": [ {load_name, category, quantity, connected_power_kw,
                      estimated_kwh_day, demand_factor_pct, duty_hours_day,
                      confidence, source_detail}, ... ] — duty_hours_day is
                      None only when connected_power_kw is 0 (division has
                      nothing to back out from),
          "total_kwh_day": float,
          "total_kwh_day_diversified": float,  # sum(estimated_kwh_day *
                      # demand_factor_pct) — this is what battery/PV sizing
                      # (generate_design_scenarios[_hybrid]()) is fed, not
                      # the raw total, since not every line's duty-hours
                      # window actually coincides with every other line's.
        }
    """
    discretionary_answers = discretionary_answers or {}
    lines: list[dict] = []

    for load in loads:
        name = load["name"]
        qty = int(load.get("quantity") or 1)
        kw = float(load.get("nameplate_kw") or 0)

        override = load.get("category")
        category = override if override in CATEGORIES else classify_load_category(name)
        demand_factor_pct = load.get("demand_factor_pct")
        demand_factor_pct = float(demand_factor_pct) if demand_factor_pct is not None else default_demand_factor_pct(category)
        duty_override = load.get("duty_hours_day")

        if category == "behavior_driven":
            est = estimate_behavior_line(name, qty, kw, duty_override)
            duty_hours_day = est["duty_hours_day"]
        else:
            if category == "fixed_cycling":
                base_est = estimate_fixed_cycling(name, qty)
            elif category == "appliance":
                base_est = estimate_appliance_use(name, qty)
            elif category == "ignition_only":
                base_est = estimate_ignition_only(qty)
            elif category == "discretionary":
                base_est = estimate_discretionary(name, discretionary_answers.get(name))
            elif category == "climate_driven":
                base_est = estimate_climate_driven(qty, kw, lat, lon)
            else:
                base_est = {"kwh_day": 0.0, "confidence": CONFIDENCE_DEFAULT, "source_detail": "Categoría desconocida"}

            if duty_override is not None and kw > 0:
                kwh_day_val = round(kw * duty_override * qty, 2)
                est = {
                    "kwh_day": kwh_day_val,
                    "confidence": CONFIDENCE_USER_CONFIRMED,
                    "source_detail": f"{kw} kW × {duty_override} h/día × {qty} (horas ajustadas por el ingeniero)",
                }
                duty_hours_day = duty_override
            else:
                est = base_est
                duty_hours_day = round(est["kwh_day"] / (kw * qty), 2) if kw > 0 and qty > 0 else None

        lines.append({
            "load_name": name,
            "category": category,
            "quantity": qty,
            "connected_power_kw": kw,
            "estimated_kwh_day": est["kwh_day"],
            "demand_factor_pct": round(demand_factor_pct, 3),
            "duty_hours_day": duty_hours_day,
            "confidence": est["confidence"],
            "source_detail": est["source_detail"],
        })

    total = round(sum(l["estimated_kwh_day"] for l in lines), 2)
    # Diversified per spec: not every line's duty-hours window coincides with
    # every other line's — same demand_factor_pct already used for peak kW
    # (compute_demand_load()), applied here to the daily energy total instead.
    total_diversified = round(sum(l["estimated_kwh_day"] * l["demand_factor_pct"] for l in lines), 2)

    return {"lines": lines, "total_kwh_day": total, "total_kwh_day_diversified": total_diversified}
