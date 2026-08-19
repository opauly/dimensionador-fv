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
    # Bug-fix pass 2026-08-18 (Bug 3): `monitoring.sites.owner` — populated on
    # all 25 current rows, the real person's name (e.g. "Karen Montealegre"),
    # sometimes matching a `vrm.customers.name` exactly when the same person
    # is both an Oscar-monitored site and a VRM Monitor customer. `None` for
    # `schema="vrm"` rows (that schema's own `customer_id` FK already answers
    # "whose site is this," so `list_sites()` below never bothers reading an
    # `owner`-shaped column there) — `/admin/reports` uses this to narrow the
    # `monitoring` site picker by the selected customer's name; see that
    # page's own `AdminReportsManager.tsx` for the filter itself.
    owner: str | None = None


class SitesOut(BaseModel):
    sites: list[SiteSummaryOut]


# ──────────────────────────────────────────────────────────────────────
# PLAN_PHASE15.md §8 Step 4 — vrm_link.py / vrm_sync.py request/response
# models. `extra="forbid"` everywhere a request body exists, same reasoning
# as `SiteFieldsIn` above: nothing here doubles as a passthrough dict.
# ──────────────────────────────────────────────────────────────────────
class VrmLinkValidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: str
    token: str


class VrmInstallationOut(BaseModel):
    id_site: int
    name: str | None = None
    identifier: str | None = None


class VrmLinkValidateOut(BaseModel):
    """`POST /v1/vrm-link/validate`'s response — PLAN_PHASE15.md §3.1 step 1:
    "nothing is written to Postgres or Vault." Deliberately never includes
    the token that was validated — see `vrm_api/secrets.py`'s module
    docstring, rule 2, which this response shape must never violate even
    though `validate` itself never touches that module."""

    vrm_user_id: str
    vrm_account_email: str | None = None
    installations: list[VrmInstallationOut]


class VrmLinkMapping(BaseModel):
    """One customer decision from PLAN_PHASE15.md §3.1 step 2's mapping UI:
    "ignore" is simply omitting an installation from `mappings` — there is
    no explicit ignore action to model. `site_name_or_id` reuses
    `IngestPreviewRequest`'s own ambiguous-by-design field (matched against
    an existing site by `tenancy.find_customer_site()`, treated as a new
    site's display name otherwise) rather than inventing a second way to
    say "existing site or new site" — see `routers/vrm_link.py`'s own
    docstring for why."""

    model_config = ConfigDict(extra="forbid")

    vrm_installation_id: int
    site_name_or_id: str
    site_fields: SiteFieldsIn = SiteFieldsIn()


class VrmLinkConnectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: str
    token: str
    mappings: list[VrmLinkMapping] = []


class VrmLinkSiteResult(BaseModel):
    vrm_installation_id: int
    site_id: str
    site_is_existing: bool


class VrmLinkConnectOut(BaseModel):
    vrm_user_id: str
    vrm_account_email: str | None = None
    sites: list[VrmLinkSiteResult]


class VrmLinkDisconnectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: str


class VrmLinkDisconnectOut(BaseModel):
    sites_reverted: int


class VrmLinkSiteStatus(BaseModel):
    site_id: str
    display_name: str
    vrm_last_synced_at: str | None = None
    vrm_last_sync_error: str | None = None
    vrm_sync_enabled: bool


class VrmLinkStatusOut(BaseModel):
    """`GET /v1/vrm-link/status`'s response — PLAN_PHASE15.md §2.5 rule 2's
    most concrete instance: "the one place in the whole product it would be
    easiest to accidentally leak one [a token]." No field here can ever
    carry one, by construction — connection *state* only."""

    connected: bool
    vrm_account_email: str | None = None
    connected_since: str | None = None
    token_revoked_at: str | None = None
    token_last_error: str | None = None
    sites: list[VrmLinkSiteStatus]


class VrmSyncRequest(BaseModel):
    """`POST /v1/vrm-sync`'s request body. Deliberately has NO field that
    could carry a VRM installation id — PLAN_PHASE15.md §3.2 control 3's
    primary control is that no such field exists; the installation id
    always comes from the already-ownership-checked `vrm.sites` row for
    `site_id`, never from a caller. `routers/vrm_sync.py`'s own tamper-test
    validation greps this model for exactly that absence."""

    model_config = ConfigDict(extra="forbid")

    customer_id: str
    site_id: str
    start: str
    end: str


class VrmSyncSiteResult(BaseModel):
    site_id: str
    status: str
    error: str | None = None


class VrmSyncRunDueOut(BaseModel):
    sites_checked: int
    results: list[VrmSyncSiteResult]


# ──────────────────────────────────────────────────────────────────────
# PLAN_PHASE15.md §3.3 / §8 Step 4b — vrm_fleet.py request/response models.
# Oscar's OWN VRM fleet (read with `VRM_ADMIN_TOKEN`), never a customer's —
# see `routers/vrm_fleet.py`'s own module docstring for the full reasoning.
# `extra="forbid"` everywhere a request body exists, same reasoning as
# `SiteFieldsIn` above.
# ──────────────────────────────────────────────────────────────────────
class VrmFleetLinkedSiteOut(BaseModel):
    """One `vrm.sites` row already linked to a given installation
    (PLAN_PHASE15.md §1.1: `UNIQUE (customer_id, vrm_installation_id)`, not a
    global unique — so a single installation can legitimately be linked
    under more than one `customer_id` at once, e.g. an installer's own
    self-serve link coexisting with an admin fleet link under a different
    tenant. A list, not a single optional object, on purpose."""

    customer_id: str
    customer_name: str | None = None
    site_id: str
    site_display_name: str
    vrm_sync_enabled: bool
    vrm_last_synced_at: str | None = None


class VrmFleetInstallationOut(BaseModel):
    id_site: int
    name: str | None = None
    identifier: str | None = None
    links: list[VrmFleetLinkedSiteOut] = []
    # Bug-fix pass 2026-08-18 (Bug 1): a genuinely useful pre-fill for the
    # link form, sourced from `monitoring.sites` — see
    # `routers/vrm_fleet.py:_monitoring_suggestions_by_installation()`'s own
    # docstring for the full reasoning. `None` when no match was found
    # (most installations, by construction — only 13 of 25 `monitoring.sites`
    # rows have `monitoring_urls` populated at all, and fewer still are
    # VRM-flavored). Reuses `SiteFieldsIn` as a RESPONSE shape here (its
    # whitelist happens to be exactly the fields worth suggesting) — never
    # auto-applied, only offered; the admin still has to accept or override
    # every value in the link form.
    suggested_fields: SiteFieldsIn | None = None


class VrmFleetInstallationsOut(BaseModel):
    installations: list[VrmFleetInstallationOut]


class VrmFleetLinkRequest(BaseModel):
    """`POST /v1/vrm-fleet/link`'s body. Create-or-reuse on BOTH customer and
    site (PLAN_PHASE15.md §3.3) — the one place in `vrm_api` that legitimately
    calls `victron.ingest.upsert_customer()`, because there is no self-serve
    customer session here whose tenant-creation authority needs protecting
    (unlike `routers/ingest.py:_do_commit()`'s own TODO on exactly this
    point) — see `routers/vrm_fleet.py`'s own docstring."""

    model_config = ConfigDict(extra="forbid")

    vrm_installation_id: int
    # Exactly one of these two must be set — checked in the route handler
    # (not a pydantic validator) so the 400 it raises can carry the same
    # typed, customer-safe `{"code": ...}` shape every other check in this
    # router uses.
    customer_id: str | None = None
    new_customer_name: str | None = None
    # Same ambiguous-by-design field `VrmLinkMapping.site_name_or_id` and
    # `IngestPreviewRequest.site_name_or_id` already use: matched against an
    # existing site of the resolved customer by `tenancy.find_customer_site()`
    # first; treated as a new site's display name otherwise.
    site_name_or_id: str
    site_fields: SiteFieldsIn = SiteFieldsIn()


class VrmFleetLinkOut(BaseModel):
    customer_id: str
    customer_is_existing: bool
    site_id: str
    site_is_existing: bool


class VrmFleetSyncRequest(BaseModel):
    """`POST /v1/vrm-fleet/sync`'s body. No `customer_id` field — unlike
    `VrmSyncRequest`, there is no single "requesting customer" in this flow
    to check `site_id` against (PLAN_PHASE15.md §3.3: "that check does not
    apply here — there is no single owning customer in this flow, by
    design"). `routers/vrm_fleet.py` reads the site's own `customer_id`
    straight off the `vrm.sites` row instead."""

    model_config = ConfigDict(extra="forbid")

    site_id: str
    start: str
    end: str
