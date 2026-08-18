from __future__ import annotations
"""
Pydantic request/response models for `vrm_api`'s HTTP surface.

`SiteFieldsIn` is the one model worth reading closely: it is this API's half
of PLAN_PHASE14.md §1.2 rule 4's "typed field whitelists, enforced twice."
`victron-monitor/web/lib/server/db/sites.ts` already whitelists what a
customer-facing request may set on a site; this model re-states the same
whitelist on the API side, with `extra="forbid"`, because `site_fields` is
the one place in this API's request bodies that reaches an
`upsert_site(customer_id, site_id, display_name, **fields)`-shaped
passthrough (`victron/ingest.py`) — without a whitelist here, a bug (not
even malice) two calls upstream in Next.js could put `customer_id` or
`battery_usable_kwh` into that dict and this API would forward it unchanged.
"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SiteFieldsIn(BaseModel):
    """Same column whitelist as `sites.ts`'s `SiteUpdateFields`
    (PLAN_PHASE14.md §Step 4) — deliberately excludes `customer_id`,
    `site_id`, `vrm_installation_id` (derived from the CSV, not caller-set),
    and `battery_usable_kwh` (GENERATED, migration 019 — Postgres itself
    rejects a write to it, but this model rejects it one step earlier, with
    a clearer error than a Postgres error string would be)."""

    model_config = ConfigDict(extra="forbid")

    display_name: str | None = None
    pv_kwp: float | None = None
    battery_nominal_kwh: float | None = None
    battery_dod_pct: float | None = None
    system_type: Literal["grid_zero", "off_grid", "hybrid"] | None = None
    report_language: Literal["es", "en"] | None = None
    location: str | None = None
    timezone: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    country: str | None = None
    savings_rate: float | None = None
    savings_currency: str | None = None
    exports_to_grid: bool | None = None
    active: bool | None = None


class IngestPreviewRequest(BaseModel):
    customer_id: str
    # Matches an existing site's site_id (re-ingest) or, if it doesn't, is
    # treated as a new site's display name (vrm_api/tenancy.py:
    # find_customer_site() decides which — see routers/ingest.py).
    site_name_or_id: str
    storage_path: str
    # The browser's original filename (e.g. "997979_0_Emtec_log_....csv"),
    # separate from `storage_path`'s own filename — Step 6's upload route
    # renames the object to `{uuid}.csv` before it ever reaches Storage
    # (PLAN_PHASE14.md §1.5's own path convention, "so a re-upload of the
    # same site never collides on name"), which would otherwise silently
    # blank out `vrm_csv.py:installation_id()` (parsed from the *filename*,
    # `<id>_<n>_<site>_log_...`) and `ingestion_log.filename`'s audit value.
    # Optional/blank-default only so an old caller that never sent it still
    # parses; every real caller (the Next.js proxy) always sends it.
    filename: str = ""
    site_fields: SiteFieldsIn = SiteFieldsIn()


class IngestCommitRequest(BaseModel):
    job_id: str


class ReportRequest(BaseModel):
    """`schema` is a reserved-looking name in Pydantic v1 (BaseModel.schema())
    but not v2 — aliased anyway for clarity that this is the wire field name,
    not a model-introspection method."""

    model_config = ConfigDict(populate_by_name=True)

    customer_id: str
    site_id: str
    start: str
    end: str
    schema_: Literal["vrm", "monitoring"] = Field(alias="schema")
    # Who is asking. Set by Next.js from the resolved session role, never
    # taken from anything a browser sends directly. `schema_="monitoring"` is
    # only accepted when actor="admin" (PLAN_PHASE14.md §Step 5) — that gate
    # is enforced in routers/reports.py, not here, so the 403 it produces
    # carries a clear reason rather than a generic 422.
    actor: Literal["customer", "admin"]


class JobCreated(BaseModel):
    job_id: str


class JobOut(BaseModel):
    id: str
    kind: str
    status: str
    customer_id: str | None = None
    site_id: str | None = None
    params: dict | None = None
    result: dict | None = None
    error: str | None = None
    created_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


class LimitsOut(BaseModel):
    # PLAN_PHASE14.md §1.11: served here, never duplicated as a hardcoded TS
    # constant, so the Detallado/Overview boundary can't drift between the
    # API and the web app.
    max_custom_range_days: int
    max_overview_range_days: int


class AvailableDatesOut(BaseModel):
    dates: list[str]


class SiteSummaryOut(BaseModel):
    """The small, cross-schema site shape `GET /v1/sites` returns (PLAN_PHASE14.md
    §2 Step 7's admin report picker — `monitoring` sites have no `vrm.customers`
    owner and no Next.js-side table to list them from, unlike `vrm` sites, which
    `victron-monitor/web/lib/server/db/admin.ts:listAllSites()` already reads
    directly). Deliberately thin: this is a picker's option list, not a full
    site record — nothing here duplicates report math or tenancy-sensitive
    fields."""

    site_id: str
    display_name: str


class SitesOut(BaseModel):
    sites: list[SiteSummaryOut]
