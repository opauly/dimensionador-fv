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
# still sized as ONE per-espacio aggregate. Anything the occupant switches on
# to do a task (microondas, plantilla, cafetera, TV, lavadora, licuadora) is
# category 6 and gets itemized with its own kWh/día AND its own watts.
# BEHAVIOR_KWH_PER_BEDROOM_DAY_V1 was recalibrated downward to match — see the
# comment there before touching either table.

CONFIDENCE_MEASURED = "measured"            # real submetered data (not wired up yet)
CONFIDENCE_API = "api_calculated"           # derived from real location data via a documented formula
CONFIDENCE_BENCHMARK = "benchmark"          # industry-standard lookup table, not location-specific
CONFIDENCE_USER_CONFIRMED = "user_confirmed"  # customer answered an intake question directly
CONFIDENCE_DEFAULT = "default_assumed"      # no better source — must stand out in the UI
CONFIDENCE_POWER_ONLY = "power_only"        # line contributes peak W only; its kWh lives in the behavior_driven aggregate

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
# and inverter alike. They are deliberately NOT part of the "Uso general"
# aggregate anymore (see the CATEGORIES note above).
#
# The two "Iluminación" entries are the one remaining behavior_driven exception:
# their ENERGY stays inside the per-espacio aggregate (listing them changes no
# kWh), but they still emit a line carrying real watts, because the aggregate is
# a pure kWh/día figure with no wattage attached and Step 6's inverter-headroom
# check sums watts across profile lines. The wizard labels those lines
# "⚡ Solo potencia (W)" with kWh/día = 0 so the zero reads as intentional.
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
    # Watts-only: energy stays in the "Uso general" aggregate.
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

# ── Category 2: behavior-driven — aggregate, not per-line (v2) ──────────────
# kWh/day per espacio, tiered by home class. All loads classified
# behavior_driven collapse into ONE aggregate figure using this table, rather
# than being sized individually — the taxonomy doc is explicit that
# NEC-style per-circuit demand figures are code-minimum wiring safety
# numbers, not energy estimates, and overstate real use by ~3x.
#
# v2 (2026-07-28) — RECALIBRATED DOWN from v1's 1.5/2.5/4.0 because the scope
# of this category shrank: it used to cover appliances too (its own tier text
# said "TV, computadora, lavadora, cocina eléctrica ocasional"), which now live
# in category "appliance" and are itemized. What remains here is ONLY lighting
# plus the always-on receptacle background load — computadora, router, reloj,
# cargadores. Leaving v1's numbers in place after moving appliances out would
# double-count them, which is the whole reason these dropped.
#
# ⚠️ These two tables are coupled: raising APPLIANCE_USE_KWH_DAY_V1 coverage
# (moving more load types into category 6) means this table should come down
# again, and vice versa. Don't tune one without checking the other.
BEHAVIOR_KWH_PER_BEDROOM_DAY_V1: dict[str, float] = {
    "basic": 0.5,
    "standard": 0.8,
    "premium": 1.3,
}
_DEFAULT_HOME_CLASS = "standard"

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
    # sit on continuously, which is exactly what "tomacorrientes" means in the
    # per-espacio aggregate — not task appliances the occupant switches on.
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

# Fallback when the AI classifier fails or returns something unrecognized.
# Deliberately "appliance", NOT "behavior_driven" (which it was before the
# 2026-07-28 scope split): behavior_driven lines now contribute 0 kWh because
# their energy lives in the per-espacio aggregate, so falling back there would
# make an unclassifiable load silently vanish from the sizing. "appliance"
# instead gives it _APPLIANCE_USE_DEFAULT_KWH_DAY_V1 flagged
# CONFIDENCE_DEFAULT, which surfaces in the wizard's "revísalas antes de
# continuar" banner — visible and reviewable rather than a silent zero.
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
    requirement. Falls back to 'behavior_driven' (the most common, most
    benign-to-overestimate-slightly category) if the AI call fails or
    returns something outside the enum.

    Two-pass keyword match, not a single pass in dict order: Costa Rican
    circuit schedules commonly name a receptacle by what plugs into it
    ("Tomacorriente para microondas"), so the generic "tomacorriente"
    keyword (behavior_driven) and a specific one ("microondas", appliance)
    are both substrings of the same name. Checking behavior_driven's generic
    receptacle/lighting keywords first would swallow the specific match
    every time — a microwave circuit would silently read as background plug
    load, with 0 kWh/día in build_load_profile() (its energy goes to the
    aggregate instead of its own appliance estimate) and no watts wrong, but
    a real, silent misclassification. Specific categories are checked first;
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


def estimate_behavior_aggregate(num_bedrooms: int, home_class: str = _DEFAULT_HOME_CLASS) -> dict:
    """
    ALL loads classified behavior_driven collapse into this one aggregate —
    not sized per individual load line — per the taxonomy doc.
    """
    per_bedroom = BEHAVIOR_KWH_PER_BEDROOM_DAY_V1.get(home_class, BEHAVIOR_KWH_PER_BEDROOM_DAY_V1[_DEFAULT_HOME_CLASS])
    kwh_day = round(per_bedroom * max(1, num_bedrooms), 2)
    return {
        "kwh_day": kwh_day,
        "confidence": CONFIDENCE_BENCHMARK,
        "source_detail": f"{per_bedroom} kWh/día/espacio × {num_bedrooms} espacios (nivel '{home_class}', tabla v1)",
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


# ── Power demand factors (v1) ────────────────────────────────────────────────
# A different question from every kWh/día estimator above: those answer "how
# much energy does this load use per day"; this answers "how much of its
# installed (nameplate) power is actually drawing at the same instant as
# everything else" — the number that should drive inverter sizing and AC
# breaker selection, not the raw Σ nameplate. Summing nameplate power across
# a load list with many circuits systematically overstates simultaneous draw,
# the same failure mode the kWh taxonomy above was built to fix for energy —
# this is the power-side equivalent, reusing the same 6-category taxonomy
# rather than inventing a second classification system.
#
# Two factor shapes, chosen per category by how loads in it actually behave:
#   - Flat: one factor applied to the category's total installed power.
#     Fits categories where individual loads are small and diversity comes
#     from how many happen to be on, not from any one dominant item.
#   - Largest-plus-rest: the single largest line in the category counts at
#     100% (the one most likely to be running), the rest of the category's
#     installed power gets a lower factor. Mirrors the NEC Table 220.55-style
#     "largest + diversified remainder" method used for multiple appliances/
#     motors that rarely all peak together — fits categories with a few
#     distinct, individually significant loads.
#
# v1, first-pass values — NOT yet calibrated against real installs, same
# caveat as every other _V1 table in this module. Must be visibly flagged in
# the UI, engineer-overridable, never presented as more precise than it is.

DEMAND_FACTOR_FIXED_CYCLING_V1 = 0.95  # always-ready, short/near-random duty cycles
DEMAND_FACTOR_BEHAVIOR_V1 = 0.70       # lighting + receptacles: not every fixture/outlet fires at once
DEMAND_FACTOR_IGNITION_V1 = 1.0        # negligible magnitude regardless — no diversity needed

# category -> factor applied to the REST of that category's installed power,
# after its single largest line is counted at 100%.
DEMAND_CLUSTER_REST_FACTOR_V1: dict[str, float] = {
    "appliance": 0.55,        # kitchen/laundry tasks — rarely several run together
    "climate_driven": 0.65,   # multiple A/C units can coincide on hot afternoons
    "discretionary": 0.80,    # big standalone loads (EV/pool/jacuzzi), least likely to cancel out
}

DEMAND_METHOD_FLAT = "flat"
DEMAND_METHOD_CLUSTER = "largest_plus_rest"

_DEMAND_FLAT_FACTORS_V1: dict[str, float] = {
    "fixed_cycling": DEMAND_FACTOR_FIXED_CYCLING_V1,
    "behavior_driven": DEMAND_FACTOR_BEHAVIOR_V1,
    "ignition_only": DEMAND_FACTOR_IGNITION_V1,
}


def compute_demand_load(lines: list[dict]) -> dict:
    """
    Translates installed (nameplate) power into demanded (design) power per
    category, from the same `lines` list build_load_profile() returns —
    each line already carries `category`, `quantity`, `connected_power_kw`.

    Returns:
        {
          "categories": [ {category, installed_kw, demand_kw,
                            factor_applied, method}, ... ], sorted by
                         installed_kw descending — only categories actually
                         present in `lines`,
          "total_installed_kw": float,
          "total_demand_kw": float,
          "blended_factor": float,  # total_demand_kw / total_installed_kw
        }
    """
    by_cat: dict[str, list[float]] = {}
    for line in lines:
        cat = line.get("category")
        kw = float(line.get("connected_power_kw") or 0) * int(line.get("quantity") or 1)
        by_cat.setdefault(cat, []).append(kw)

    categories = []
    total_installed = 0.0
    total_demand = 0.0
    for cat, kws in by_cat.items():
        installed = round(sum(kws), 3)
        if cat in _DEMAND_FLAT_FACTORS_V1:
            factor = _DEMAND_FLAT_FACTORS_V1[cat]
            demand = round(installed * factor, 3)
            method = DEMAND_METHOD_FLAT
        elif cat in DEMAND_CLUSTER_REST_FACTOR_V1:
            rest_factor = DEMAND_CLUSTER_REST_FACTOR_V1[cat]
            largest = max(kws) if kws else 0.0
            rest = installed - largest
            demand = round(largest + rest * rest_factor, 3)
            factor = round(demand / installed, 3) if installed > 0 else rest_factor
            method = DEMAND_METHOD_CLUSTER
        else:
            # No factor table for this category (shouldn't happen — every
            # CATEGORIES entry is covered above) — never silently drop load,
            # same principle the kWh estimators use for unclassifiable input.
            factor, demand, method = 1.0, installed, DEMAND_METHOD_FLAT

        categories.append({
            "category": cat, "installed_kw": installed, "demand_kw": demand,
            "factor_applied": factor, "method": method,
        })
        total_installed += installed
        total_demand += demand

    return {
        "categories": sorted(categories, key=lambda c: -c["installed_kw"]),
        "total_installed_kw": round(total_installed, 3),
        "total_demand_kw": round(total_demand, 3),
        "blended_factor": round(total_demand / total_installed, 3) if total_installed > 0 else 0.0,
    }


# ── Main entry point ─────────────────────────────────────────────────────────

def build_load_profile(
    loads: list[dict],
    num_bedrooms: int,
    home_class: str = _DEFAULT_HOME_CLASS,
    lat: float | None = None,
    lon: float | None = None,
    discretionary_answers: dict[str, float] | None = None,
) -> dict:
    """
    loads: [{"name": str, "quantity": int, "nameplate_kw": float,
             "category": str | None}, ...] — no usage-hours field, per the
           doc's core premise that customers don't have that data reliably.
           "category" is optional: if the engineer has already picked one of
           CATEGORIES (e.g. via the wizard's manual override selector, or a
           row added from COMMON_LOADS_CATALOG_V1), it's used as-is and
           classify_load_category() (the AI call) is skipped entirely for
           that line — cheaper and removes any classification uncertainty.
    discretionary_answers: optional {load_name: kwh_day} already extracted
           from intake-question answers (AI's role stops at extraction, see
           estimate_discretionary docstring).

    Returns:
        {
          "lines": [ {load_name, category, quantity, connected_power_kw,
                      estimated_kwh_day, confidence, source_detail}, ... ],
          "behavior_aggregate": {kwh_day, confidence, source_detail} — always
                      present (see note below), never None,
          "total_kwh_day": float,
        }
    """
    discretionary_answers = discretionary_answers or {}
    lines: list[dict] = []
    behavior_load_count = 0

    for load in loads:
        name = load["name"]
        qty = int(load.get("quantity") or 1)
        kw = float(load.get("nameplate_kw") or 0)

        override = load.get("category")
        category = override if override in CATEGORIES else classify_load_category(name)

        if category == "behavior_driven":
            # Energy still comes from the single aggregate below, never per-line
            # (see estimate_behavior_aggregate() and the taxonomy doc). But the
            # line IS emitted, carrying estimated_kwh_day=0.0 and its real
            # connected_power_kw — because peak watts and energy size different
            # things. The aggregate is a pure kWh/día figure with no wattage
            # attached, so before this a listed 1500 W microwave contributed
            # 0 W to Step 6's inverter-headroom check (which sums
            # connected_power_kw across profile lines). Emitting a zero-energy
            # line lets the inverter see the real connected load without
            # double-counting the kWh. Engineers can still override the 0 in
            # Step 5's editable kWh/día column if a given site genuinely needs
            # that load itemized instead of aggregated.
            behavior_load_count += 1
            lines.append({
                "load_name": name,
                "category": category,
                "quantity": qty,
                "connected_power_kw": kw,
                "estimated_kwh_day": 0.0,
                "confidence": CONFIDENCE_POWER_ONLY,
                "source_detail": (
                    "Energía ya incluida en 'Uso general' (agregado por espacio) — "
                    "esta línea solo aporta potencia (W) al dimensionamiento del inversor"
                ),
            })
            continue
        elif category == "fixed_cycling":
            est = estimate_fixed_cycling(name, qty)
        elif category == "appliance":
            est = estimate_appliance_use(name, qty)
        elif category == "ignition_only":
            est = estimate_ignition_only(qty)
        elif category == "discretionary":
            est = estimate_discretionary(name, discretionary_answers.get(name))
        elif category == "climate_driven":
            est = estimate_climate_driven(qty, kw, lat, lon)
        else:
            est = {"kwh_day": 0.0, "confidence": CONFIDENCE_DEFAULT, "source_detail": "Categoría desconocida"}

        lines.append({
            "load_name": name,
            "category": category,
            "quantity": qty,
            "connected_power_kw": kw,
            "estimated_kwh_day": est["kwh_day"],
            "confidence": est["confidence"],
            "source_detail": est["source_detail"],
        })

    # Always computed, regardless of whether any load was actually classified
    # behavior_driven — every house has general lighting/outlet consumption
    # whether or not the customer thought to list it as a "load". An earlier
    # version only included this when behavior_load_count > 0, which silently
    # dropped general-use consumption entirely for any load list that didn't
    # happen to mention lighting/outlets (a common omission) — a real
    # undercount, not just a missing line item.
    agg = estimate_behavior_aggregate(num_bedrooms, home_class)
    behavior_aggregate = {
        "category": "behavior_driven",
        "load_count": behavior_load_count,
        "kwh_day": agg["kwh_day"],
        "confidence": agg["confidence"],
        "source_detail": agg["source_detail"],
    }

    total = round(sum(l["estimated_kwh_day"] for l in lines) + behavior_aggregate["kwh_day"], 2)

    return {"lines": lines, "behavior_aggregate": behavior_aggregate, "total_kwh_day": total}
