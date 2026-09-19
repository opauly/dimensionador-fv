"""Flask-side wizard state store (Phase 20 Step 3, PLAN_PHASE20_PROPOSALS_JINJA.md
§1.1). Streamlit-free, sits beside wizard/state.py, does NOT replace it —
wizard/state.py is still what the Streamlit app on `main` uses.

Flask has no rerun and no per-user process memory, so unlike Streamlit's
two-tiered session_state (durable `wizard_*` keys occasionally mirrored to
Supabase by autosave(), plus a much larger set of transient `w{N}*_` widget
keys that autosave() never writes) this module collapses BOTH tiers into the
single persisted `proposal_versions.data` blob:

    {
      "meta": {..., "step_reached": int},
      "client": {...}, "site": {...}, "utility": {...},
      "consumption": {...}, "equipment": {...}, "costs": {...},
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

_SECTIONS = ("meta", "client", "site", "utility", "consumption", "equipment", "costs")


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
    §1.2: completed steps stay clickable)."""
    blob = load(version_id)
    current = blob.get("meta", {}).get("step_reached", 0) or 0
    blob["meta"] = {**blob.get("meta", {}), "step_reached": max(current, n)}
    save(version_id, blob)


def scratch(blob: dict, key: str) -> dict:
    """blob["scratch"].setdefault(key, {}) — the Flask analogue of a
    Streamlit w{N}*_ transient key, except it lives IN the persisted blob so
    there is no tier-2 state to lose (PLAN §1.1). Mutates and returns the
    nested dict in place; caller still owns calling save()/patch() to persist
    the change."""
    return blob.setdefault("scratch", {}).setdefault(key, {})
