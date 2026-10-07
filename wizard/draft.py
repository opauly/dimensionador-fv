"""Flask-side wizard state store (Phase 20 Step 3, PLAN_PHASE20_PROPOSALS_JINJA.md
§1.1). Streamlit-free, sits beside wizard/state.py, does NOT replace it —
wizard/state.py is still what the Streamlit app on `main` uses.

Flask has no rerun and no per-user process memory, so unlike Streamlit's
two-tiered session_state (durable `wizard_*` keys occasionally mirrored to
Supabase by autosave(), plus a much larger set of transient `w{N}*_` widget
keys that autosave() never writes) this module collapses BOTH tiers into the
single persisted `proposal_versions.data` blob:

    {
      "meta": {..., "step_reached": int, "wizard_rev": int},   # read via effective_step_reached()
      "client": {...}, "site": {...}, "utility": {...},
      "consumption": {...}, "equipment": {...}, "costs": {...}, "objectives": {...},
      "proposal_text": "...",
      "scratch": {"s5": {...}, "s6": {...}, ...},   # Flask-only, see below
    }

Every mutation is a save — there is no debounce, no timer, no background
thread. A request loads the blob, patches one section, writes it, renders.
That is Streamlit's rerun cycle with Supabase as the store.

BLOB-COMPATIBILITY CONSTRAINT — do not violate this. `main`'s Streamlit app
reads and writes the very same `proposal_versions.data` rows this module
does. `wizard/state.py:load_draft()` only ever copies the seven known keys
(meta/client/site/utility/consumption/equipment/costs/proposal_text) into
session_state, and `proposals/generator.py:build_from_wizard_blob()` only
ever reads those same seven keys — so adding a `scratch` section here is
additive and safe in both directions. This module must NEVER change the
meaning, key names or units of any of the seven existing sections. A draft
created in Flask must open cleanly in Streamlit and vice versa (a build/
validation gate, not an aspiration).

One real, ACCEPTED asymmetry from that additive-safety guarantee: Streamlit's
autosave() always rewrites the whole blob from session_state, which has no
`scratch` concept — so if a draft is opened in Streamlit and Streamlit saves
it again (advancing a step, editing a field, anything that calls
autosave_if_possible()), `scratch` is silently dropped from that write. This
module tolerates that: load() always re-defaults a missing `scratch` to {}
rather than erroring, so resuming in Flask after such a round-trip just means
the scratch data for the in-progress step needs recomputing (e.g. re-running
the PVGIS fetch, or re-running a scenario calculation) — never a crash and
never bad data in the seven durable sections.

CONCURRENCY — last-write-wins on a whole-blob update. save() overwrites
proposal_versions.data outright; patch() does a read-modify-write of one
section within a single request. There is no optimistic locking. This is
acceptable ONLY because there is a single internal operator and every
handler's read-modify-write happens inside one HTTP request — do not assume
this is safe the day a second concurrent editor is introduced.
"""
from __future__ import annotations

_SECTIONS = ("meta", "client", "site", "utility", "consumption", "equipment", "costs", "objectives")
# "objectives" (Phase 24) is an additive eighth section: the design goals confirmed in the Objetivos step. Nothing
# else reads it (proposals/generator.py only reads the original seven), so goals never reach the client PDF.

# Wizard step numbering revision. Rev 2 (Phase 24) inserted Objetivos as Step 6, so Equipos/Costos/Revisión moved
# from 6/7/8 to 7/8/9. `meta.wizard_rev` says which numbering a draft's `meta.step_reached` is written in; a draft
# without the marker predates the insert and is mapped on read by `effective_step_reached()`. Nothing outside this
# module should read `meta.step_reached` directly.
WIZARD_REV = 2
_LEGACY_STEP_TO_REV2 = {6: 7, 7: 8, 8: 9}


def effective_step_reached(meta: dict | None) -> int:
    """The furthest unlocked step, in the CURRENT (rev 2) numbering.

    A draft stamped `wizard_rev == WIZARD_REV` is trusted as stored. One without the stamp was written under the
    old 1-8 numbering: steps 1-5 are unchanged, and 6/7/8 (Equipos/Costos/Revisión) become 7/8/9, so an old draft
    resumes on the same CONTENT it was on rather than silently landing on the new step 6, and can only reach the
    new Review through Costos. The converted value is persisted (with the stamp) the next time `set_step()` runs,
    so each old draft is converted exactly once."""
    meta = meta or {}
    raw = meta.get("step_reached", 1) or 1
    if meta.get("wizard_rev") == WIZARD_REV:
        return raw
    return _LEGACY_STEP_TO_REV2.get(raw, raw)


def _empty_blob() -> dict:
    blob: dict = {key: {} for key in _SECTIONS}
    blob["proposal_text"] = ""
    blob["scratch"] = {}
    return blob


def load(version_id: str) -> dict:
    """get_version() + defaults for every missing section — a version row
    fresh out of create_proposal() has data={}, and a draft saved before
    `scratch` existed (or last saved by Streamlit, see module docstring)
    won't have one either. Never raises on a missing/malformed section;
    always returns a fully-shaped blob."""
    from database.proposals_db import get_version

    row = get_version(version_id)
    raw = (row or {}).get("data") or {}

    blob = _empty_blob()
    for key in _SECTIONS:
        value = raw.get(key)
        if isinstance(value, dict):
            blob[key] = value
    if isinstance(raw.get("proposal_text"), str):
        blob["proposal_text"] = raw["proposal_text"]
    if isinstance(raw.get("scratch"), dict):
        blob["scratch"] = raw["scratch"]
    return blob


def save(version_id: str, blob: dict) -> None:
    """Persist the whole blob in one upsert. Every mutation is a save."""
    from database.proposals_db import upsert_version

    total_usd = (blob.get("costs") or {}).get("total_usd")
    upsert_version(version_id, blob, total_usd)


def patch(version_id: str, section: str, values: dict) -> dict:
    """Read-modify-write ONE section and persist. Merges `values` into the
    existing section (rather than replacing it outright) so a caller that
    only knows about part of a section — e.g. Step 2 patching just
    system_type + language into `meta`, leaving `step_reached` untouched —
    can't accidentally blank out fields it didn't pass. Returns the new full
    blob so the caller's build_context(blob) has everything it needs without
    a second read (PLAN §1.3)."""
    blob = load(version_id)
    if section == "proposal_text":
        blob["proposal_text"] = values if isinstance(values, str) else blob["proposal_text"]
    else:
        blob[section] = {**blob.get(section, {}), **(values or {})}
    save(version_id, blob)
    return blob


def set_step(version_id: str, n: int) -> None:
    """Write meta.step_reached, monotonically — resuming an earlier,
    already-completed step via the breadcrumb must never lower it (PLAN
    §1.2: completed steps stay clickable). Always writes in the current
    numbering and stamps `wizard_rev`, converting an old draft in place."""
    blob = load(version_id)
    current = effective_step_reached(blob.get("meta"))
    blob["meta"] = {**blob.get("meta", {}), "step_reached": max(current, n), "wizard_rev": WIZARD_REV}
    save(version_id, blob)


def scratch(blob: dict, key: str) -> dict:
    """blob["scratch"].setdefault(key, {}) — the Flask analogue of a
    Streamlit w{N}*_ transient key, except it lives IN the persisted blob so
    there is no tier-2 state to lose (PLAN §1.1). Mutates and returns the
    nested dict in place; caller still owns calling save()/patch() to persist
    the change."""
    return blob.setdefault("scratch", {}).setdefault(key, {})
