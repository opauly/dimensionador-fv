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


class BrandingFields(BaseModel):
    """The shape of `vrm.customers.branding` (PLAN_PHASE17.md §4.1) —
    documented in three places, this being one: this model, the
    `COMMENT ON COLUMN vrm.customers.branding` in migration 026, and the Zod
    schema `lib/server/db/branding.ts` will carry once Step 5 builds the
    settings page's write path. Every key optional — a missing key falls
    back to the Pauly & Co default individually, never all-or-nothing
    (`vrm_api/branding.py:resolve_branding()`'s own rule). Not currently
    used to validate an inbound request in this API — Step 5's write path is
    server-only Next.js code writing directly to Supabase, the same pattern
    `updateCustomerProfile()` already uses for the rest of `vrm.customers`.
    This model exists so the shape has one Python-side name to import from,
    should a future admin/API write path need it, rather than a shape that
    only ever exists as three independently-typed copies."""
    company_name: str | None = None
    logo_storage_path: str | None = None
    primary_color: str | None = None
    contact_name: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    website: str | None = None


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


class ReportsRunDueRequest(BaseModel):
    """PLAN_PHASE17.md §3.4 — batched on purpose, since a report is slow
    (an Anthropic call + a weather fetch + a WeasyPrint render). Body-only,
    no query params, matching every other POST in this router."""

    max_sites: int = 10


class ReportRunSiteResult(BaseModel):
    site_id: str
    status: str
    error: str | None = None


class ReportsRunDueOut(BaseModel):
    """§3.4's response shape. `remaining > 0` means the wall-clock budget or
    `max_sites` was hit before every due site could be reached this call —
    the workflow's own bounded loop (§3.8) keeps calling until this is 0."""

    sites_checked: int
    processed: int
    remaining: int
    results: list[ReportRunSiteResult]


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


class FleetSnapshotsRefreshOut(BaseModel):
    """`POST /v1/vrm-fleet/refresh-snapshots`'s response — the Fleet
    Dashboard Phase 2 (2026-08-30) live-snapshot sweep. Counts only, same
    reasoning `BillingTrialRemindersOut`/`BillingPruneSignupsOut` give for
    their own shape: a cron log line that says how much it did is the only
    visibility this job gets."""

    checked: int
    refreshed: int
    skipped: int
    failed: int
    # Live alarm/critical-alert transitions recorded this sweep (2026-09-01)
    # — see vrm_fleet.py:_apply_live_alarm_state()'s own docstring. Usually
    # 0 on any given sweep; a nonzero count means something actually
    # started or cleared in the last ~15 minutes.
    alarm_transitions: int = 0


class SiteShapeOut(BaseModel):
    """`GET /v1/vrm-fleet/site-shape`'s response — Fleet Dashboard Phase 2.5
    (2026-08-30). 24 hour-of-day buckets (index 0 = midnight local time),
    fetched fresh from VRM on every call (`victron/vrm_shape.py`), never
    stored. `None` per-hour where that site published nothing usable for
    that bucket — `grid` is `None` for every hour on a site with no
    physical grid meter, same convention `FleetOverviewRow.live_grid_power_w`
    already uses for a single instantaneous reading."""

    solar: list[float | None]
    load: list[float | None]
    battery: list[float | None]
    grid: list[float | None]


class SiteSavingsOut(BaseModel):
    """`GET /v1/vrm-fleet/site-savings`'s response — Fleet Dashboard Phase
    2.5 (2026-08-31). Relays `victron/savings.py:compute_weekly_savings()`'s
    own result verbatim (the exact function the PDF report already calls,
    not a second implementation) for the requested today/week/month window.
    `amount`/`currency`/`basis_count` are all `None` together when that
    function has no basis to compute one — never a fabricated $0."""

    amount: float | None
    currency: str | None
    basis_count: int | None
    days_with_data: int


# ──────────────────────────────────────────────────────────────────────
# PLAN_PHASE16.md §5.1–5.3 / §8 Step 3 — routers/billing.py request/response
# models. `extra="forbid"` on every request body, same reasoning as
# `SiteFieldsIn` above. Restated for billing specifically (§6.4 control 3):
# NONE of these models has a field that lets an ONVO object id travel INTO
# this API from a caller — every mutation takes only `vrm.plans.id` /
# `vrm.customers.id` / a `payment_method_id` the caller obtained directly
# from ONVO client-side (never generated or looked up on the caller's
# behalf), and `routers/billing.py` re-verifies that one exception with a
# fresh `GET /v1/payment-methods/{id}` before ever trusting it. A response
# model, by contrast, is allowed to carry an ONVO id back OUT when the SDK
# genuinely needs one to render (`BillingSubscribeOut`,
# `BillingPaymentMethodSessionOut` — both documented inline below) — that is
# the one deliberate, narrow exception to "no ONVO id in a response" (§5.1).
# ──────────────────────────────────────────────────────────────────────
class BillingStatusOut(BaseModel):
    """`GET /v1/billing/status`'s response (§5.1). No ONVO id anywhere in
    this shape — the browser has no legitimate use for
    `onvo_customer_id`/`onvo_subscription_id` from this endpoint. Also the
    common "fresh state" response every mutation endpoint in this router
    returns after it reconciles, so the browser never has to guess what
    changed from a request it just made (§4.4's post-mutation trigger)."""

    customer_id: str
    plan_key: str | None = None
    # `f"billing.plan.{plan_key}"` — an i18n lookup key for `t(lang, key)`
    # (`lib/i18n/strings.ts`), not a literal label; this API has no concept
    # of the visitor's language. `None` when the customer has no plan yet.
    plan_label_key: str | None = None
    billing_status: str | None = None
    provisioning_state: str
    status: str | None = None
    billing_interval: str | None = None
    currency: str | None = None
    amount_minor: int | None = None
    current_period_end: str | None = None
    cancel_at_period_end: bool = False
    trial_end: str | None = None
    # Display-only mirror fields (§6.2) — never used in any decision.
    pm_brand: str | None = None
    pm_last4: str | None = None
    pm_exp_month: int | None = None
    pm_exp_year: int | None = None
    billing_address: dict = {}
    site_limit: int | None = None
    active_sites: int = 0
    over_limit: bool = False


class BillingPlanOut(BaseModel):
    """One `vrm.plans` row (§5.1). Deliberately no `onvo_product_id`/
    `onvo_price_id` — same reasoning §5.5 step 4 already states for the
    public signup plan list ("no reason for the public internet to hold a
    map of our ONVO catalogue"), applied here too even though this endpoint
    is authenticated."""

    id: str
    plan_key: str
    plan_label_key: str
    billing_interval: str
    currency: str
    amount_minor: int
    site_limit: int | None = None
    self_serve: bool
    is_current: bool


class BillingPlansOut(BaseModel):
    plans: list[BillingPlanOut]


class BillingInvoiceOut(BaseModel):
    id: str
    status: str | None = None
    currency: str | None = None
    total_minor: int | None = None
    subtotal_minor: int | None = None
    original_total_minor: int | None = None
    period_start: str | None = None
    period_end: str | None = None
    attempt_count: int | None = None
    last_payment_attempt: str | None = None
    next_payment_attempt: str | None = None


class BillingInvoicesOut(BaseModel):
    invoices: list[BillingInvoiceOut]
    has_more: bool


class BillingSubscribeRequest(BaseModel):
    """`POST /v1/billing/subscription`'s body (§5.2, corrected at Step 5,
    2026-08-20 — see `routers/billing.py:post_subscription()`'s own
    docstring for the full "why"). `plan_id` is OUR OWN `vrm.plans.id`,
    never an ONVO `priceId` (§6.4). There is deliberately NO
    `payment_method_id` field here any more: the ONVO subscription this
    endpoint creates comes back with no payment method attached at all
    (confirmed live: `status: trialing`, NOT `incomplete` as §5.2 point 3's
    prose says — see `routers/billing.py:post_subscription()`'s own
    docstring for the full correction) — the SDK widget that collects the
    card needs a real `subscriptionId` to render in the first place, so a
    browser cannot possibly hold a `payment_method_id` before calling this
    endpoint. The card is attached afterward, by the SDK widget itself
    against the `onvo_subscription_id` this endpoint returns, and only ever
    confirmed by a subsequent reconcile (`POST /v1/billing/refresh`) —
    never by anything this request body carries."""

    model_config = ConfigDict(extra="forbid")

    customer_id: str
    plan_id: str


class BillingSubscribeOut(BaseModel):
    """The one deliberate, documented exception to 'no ONVO id in a
    response' — the ONVO web SDK genuinely needs these two to render
    against (§5.2 step 5: 'the minimum the SDK needs, and nothing else').
    `onvo_subscription_id` is the just-created subscription — no payment
    method is attached to it yet (its real ONVO `status` is `trialing`
    immediately, not `incomplete` — see `routers/billing.py:
    post_subscription()`'s own docstring)."""

    onvo_subscription_id: str
    onvo_customer_id: str
    publishable_key: str


class BillingPaymentMethodSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: str


class BillingPaymentMethodSessionOut(BaseModel):
    """`POST /v1/billing/payment-method/session`'s response (§5.3, corrected
    at Step 5, 2026-08-20 alongside `BillingSubscribeRequest`) — the
    replace-card path for a customer who ALREADY has a live subscription
    (first-time subscribe gets its `onvo_subscription_id` straight from
    `BillingSubscribeOut` and never calls this endpoint at all). Carries
    `onvo_subscription_id` for the same reason `BillingSubscribeOut` does:
    the SDK widget will not render a working card form without a real
    `subscriptionId` to attach the new card to (§5.2 point 3). Refused with
    `no_active_subscription` if the customer has no live subscription — see
    `routers/billing.py:post_payment_method_session()`."""

    onvo_subscription_id: str
    onvo_customer_id: str
    publishable_key: str


class BillingPaymentMethodRequest(BaseModel):
    """`POST /v1/billing/payment-method`'s body (§5.3) — attaches an
    already-known `payment_method_id` to the customer's current
    subscription, re-verifying it (`_verify_payment_method()`) before
    trusting it (§6.4 control 3). NOT part of the corrected SDK-widget flow
    (§5.2 point 3 / §5.3, Step 5 2026-08-20): the widget itself attaches a
    newly-entered card to the `subscriptionId` it was given, and the
    browser only ever learns that happened via a reconcile
    (`POST /v1/billing/refresh`), never by calling this endpoint with an id
    it extracted from the widget's `onSuccess`. Left in place, tenancy-
    checked and working, as a lower-level primitive — not currently called
    by any `victron-monitor/web` route."""

    model_config = ConfigDict(extra="forbid")

    customer_id: str
    payment_method_id: str


class BillingChangeRequest(BaseModel):
    """`POST /v1/billing/subscription/change`'s body (§5.3, Q3 final
    answer: cancel-and-restart, no proration, both directions immediate).
    `confirm` is the over-site-limit guard's second call (§5.3's own
    `requires_confirmation` flow) — the first call without it, when the
    target plan's site_limit is below the customer's active site count,
    is refused with `over_site_limit` (see `routers/billing.py`)."""

    model_config = ConfigDict(extra="forbid")

    customer_id: str
    plan_id: str
    confirm: bool = False


class BillingCancelRequest(BaseModel):
    """`POST /v1/billing/subscription/cancel`'s body (§5.3, Q4).
    `mode='at_period_end'` is the only customer-reachable value in v1's UI;
    `mode='immediate'` is implemented (and still tenancy-checked exactly
    like every other action here) but has no admin caller yet — Step 6 is
    expected to be what actually exposes it to Oscar as a support action."""

    model_config = ConfigDict(extra="forbid")

    customer_id: str
    mode: Literal["at_period_end", "immediate"]


class BillingResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: str


class BillingAddressIn(BaseModel):
    """ONVO's own billing-address shape (`billing.address` on a payment
    method — §3.2, §0.2b finding 1's own note that this is the only place
    ONVO actually carries a billing address), mirrored field-for-field."""

    model_config = ConfigDict(extra="forbid")

    city: str | None = None
    country: str | None = None
    line1: str | None = None
    line2: str | None = None
    postalCode: str | None = None
    state: str | None = None


class BillingAddressRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: str
    address: BillingAddressIn


class BillingRefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: str


class BillingReconcileDueResult(BaseModel):
    customer_id: str
    ok: bool
    error: str | None = None


class BillingReconcileDueOut(BaseModel):
    """`POST /v1/billing/reconcile-due`'s response (§4.4's scheduled-sweep
    trigger, §8 Step 3's own note: this step only needs the endpoint to
    exist and work — Step 4 wires up who calls it, e.g. GitHub Actions
    `cron:`)."""

    checked: int
    results: list[BillingReconcileDueResult]


class BillingWebhookEventRequest(BaseModel):
    """`POST /v1/billing/webhook-event`'s body (§4.1, §4.2, §8 Step 4) —
    sent ONLY by `victron-monitor/web/app/api/webhooks/onvo/route.ts`, after
    that route has already verified `X-Webhook-Secret` in constant time and
    rate-limited the request (§6.5). A request that fails EITHER of those
    checks never reaches this endpoint at all — see that route's own header
    comment for why (the wrong-secret rejection happens entirely in the
    Next.js layer, including writing its own `vrm.billing_events` row, so a
    forged delivery is visible without ever touching `vrm_api`).

    `secret_ok` is still a real field here, forwarded from whatever the
    Next.js layer determined, rather than this endpoint assuming `True`
    unconditionally — belt-and-suspenders: if a bug in that route ever DID
    forward a rejected delivery, this endpoint still records it faithfully
    (`secret_ok=False`) and does no further processing, rather than trusting
    it (see `routers/billing.py:post_webhook_event()`).

    `payload` is ONVO's own webhook body, forwarded as-is and never
    validated against a schema of ONVO's fields — only `type` and `data`
    are read, defensively, and only to resolve which customer to re-read
    (§4.2: 'the handler extracts the id only from data ... it never reads
    status, amount, or any other field from the payload into a column')."""

    model_config = ConfigDict(extra="forbid")

    secret_ok: bool
    payload: dict


class BillingWebhookEventOut(BaseModel):
    """Deliberately minimal (§6.5: 'the response body is {"ok":true} or
    nothing... never confirm whether the event resolved to a known
    customer')."""

    ok: bool = True


class BillingTrialRemindersOut(BaseModel):
    """`POST /v1/billing/trial-reminders`'s response — the daily "your
    trial ends tomorrow" sweep (`vrm_api/billing.py:
    send_trial_ending_reminders()`, 2026-08-29). Counts only, same
    reasoning `BillingPruneSignupsOut` gives for its own shape."""

    checked: int
    sent: int
    skipped: int
    failed: int


class BillingPruneSignupsOut(BaseModel):
    """`POST /v1/billing/prune-signups`'s response (§3.7/§3.8, §8 Step 7) —
    the retention sweep for `vrm.signup_requests` and `vrm.rate_limits`.
    Counts only, for the same reason `BillingReconcileDueOut` reports
    `checked`/`results` rather than nothing: a cron log line that says how
    much it did is the only visibility this job gets."""

    signup_requests_deleted: int
    rate_limits_deleted: int
