from __future__ import annotations
"""
`vrm_api`'s own, independent tenancy check (PLAN_PHASE14.md §1.3, §1.2 rule 4).

`victron-monitor/web/lib/server/db/sites.ts:assertOwnsSite()` already checks
ownership before Next.js ever calls this API. This module re-derives the
same fact from `vrm.sites` directly anyway, on purpose: `vrm_api` holds the
same secret-key privilege Next.js does, and "the caller already checked" is
not something this process can see or verify — a bug in the Next.js layer, a
leaked `PIPELINE_API_KEY`, or a future caller that isn't Next.js at all would
otherwise have an unguarded door straight to another customer's telemetry.
Two independent implementations of the same rule, in the two processes that
hold privilege, is the one place "defence in depth" genuinely earns its keep
in this design — see PLAN_PHASE14.md §1.3's own framing of it.

This is deliberately NOT a shared import from the TypeScript side (which it
structurally can't be — different language, different process) and
deliberately NOT a copy-paste of the TS logic's *comments*; it is a second,
from-scratch implementation of the same one-sentence rule: a site belongs to
a customer only if `vrm.sites.customer_id` says so.
"""
from database.supabase_client import get_client

SCHEMA = "vrm"


class NotAuthorized(Exception):
    """Raised when `customer_id` does not own the requested resource, or the
    resource/customer doesn't exist at all. Deliberately one exception for
    both cases — see `main.py`'s handler for why the two are not
    distinguished in the response."""


def _t(name: str):
    return get_client().schema(SCHEMA).table(name)


def get_customer(customer_id: str) -> dict:
    """The customer row, or `NotAuthorized` if `customer_id` doesn't name a
    real customer. Every endpoint that takes a `customer_id` calls this
    first — a `customer_id` a caller made up is refused the same way an
    unowned `site_id` is, rather than surfacing "customer not found" as a
    different kind of error a caller could use to enumerate ids."""
    rows = _t("customers").select("*").eq("id", customer_id).limit(1).execute().data
    if not rows:
        raise NotAuthorized(f"No such customer {customer_id!r}.")
    return rows[0]


def find_customer_site(customer_id: str, site_id_or_name: str) -> dict | None:
    """Existing-site lookup, used by `routers/ingest.py` to tell "re-ingest
    an existing site" apart from "this is a new site's display name" — the
    same one-field-does-both behaviour `pages/06_vrm_monitor.py:tab_upload()`
    already has (a typed name that may or may not already exist). Returns
    `None` rather than raising: "not an existing site of this customer's" is
    the expected, common case (a first upload), not an authorization
    failure."""
    rows = (_t("sites").select("*").eq("customer_id", customer_id)
            .eq("site_id", site_id_or_name).limit(1).execute().data)
    return rows[0] if rows else None


def assert_owns_site(customer_id: str, site_id: str) -> dict:
    """Throws `NotAuthorized` unless `site_id` belongs to `customer_id`.
    Returns the site row on success so callers that need it (report
    generation, available-dates) don't pay for a second query."""
    rows = (_t("sites").select("*").eq("customer_id", customer_id)
            .eq("site_id", site_id).limit(1).execute().data)
    if not rows:
        raise NotAuthorized(f"Customer {customer_id!r} does not own site {site_id!r}.")
    return rows[0]
