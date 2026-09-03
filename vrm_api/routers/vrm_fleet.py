from __future__ import annotations
"""
`vrm_api`'s router for Oscar's OWN VRM fleet — a second, parallel token
model to `vrm_link.py`'s customer self-serve one (PLAN_PHASE15.md §3.3).

`vrm_link.py`/`vrm_sync.py` answer "can a customer connect and pull their
own VRM account." This router answers a different question: "can Oscar keep
his existing install-everything-himself workflow (the same role CSV upload
already plays, `pages/06_vrm_monitor.py`'s 'Cargar' tab / the Next.js
`/admin` panel), just pulling from Victron's VRM cloud instead of a CSV
file." Both ship; neither replaces the other (§3.3).

── Why this is safe without reopening §0.5 Q6 ("no, admin does not paste a
   customer's token") ──────────────────────────────────────────────────────
§0.5 Q6 was about Oscar becoming custodian of a CUSTOMER'S OWN credential —
a liability transfer. This is different: it is Oscar's OWN token, which he
already holds, read the same way every other platform-wide credential in
this product is (`os.environ["VRM_ADMIN_TOKEN"]`, alongside
`PIPELINE_API_KEY`/`RESEND_API_KEY`) — never a `vrm.customers`/Vault-backed
per-tenant secret, because there is exactly one of these, not one per
customer. No customer's credential is ever touched by this module.

── Storage — a platform secret, not a Vault-per-customer one (§3.3) ────────
`VRM_ADMIN_TOKEN` lives in the shared root `.env`, read via `os.environ`
exactly like every other credential `vrm_api` reads through
`database.supabase_client`'s bare `load_dotenv()` — there is no separate
`vrm_api/.env` file (checked before writing this module; see §3.3's own
"corrected 2026-08-18" note). Never logged, never returned from an endpoint,
never written into `vrm.jobs.params` (`post_sync()` below builds `params` by
hand, the same discipline `vrm_sync.py:post_sync()` already uses for the
customer path — see that module's own docstring).

── Authorization — admin-role check only, and it is Next.js's job, not
   this router's (§3.3, coder correction) ──────────────────────────────────
This router carries the exact same `dependencies=[Depends(require_pipeline_key)]`
every other `vrm_api` router already has, and NOTHING MORE. There is no
`assertOwnsSite()`/per-role check inside `vrm_api` itself for this flow — by
design: there is no single owning "requesting customer" to check a `site_id`
against (a fleet sync's site could belong to any customer). The actual
"is this an admin" gate is entirely Next.js's `requireAdmin()`/
`requireAdminForRoute()` (`lib/server/auth.ts`), which every route under
`app/(admin)/admin/vrm-fleet/` and `app/api/admin/pipeline/vrm-fleet/*`
calls as its first statement — the same proven pattern every existing
`/admin/*` page and `app/api/admin/pipeline/*` route already uses (e.g.
`app/(admin)/admin/upload/`). A non-admin session never reaches this router
at all; it never gets far enough to matter that this router itself has no
opinion on roles.

── The one legitimate `upsert_customer()` call site in `vrm_api` ───────────
`routers/ingest.py:_do_commit()`'s own docstring explains why a
customer-initiated request must never create/rename a tenant
(PLAN_PHASE14.md §1.12 rule 1) and leaves a TODO for "an admin-initiated
upload." `post_link()` below is that admin-only path, for THIS flow: there
is no self-serve customer session here whose tenant-creation authority needs
protecting — the entire router is only reachable via an admin fleet-browse
UI. `victron.ingest.upsert_customer()`/`upsert_site()` (create-or-reuse by
slug/site_id, exactly as `pages/06_vrm_monitor.py`'s own manual site form
and `tab_upload()`'s CSV path already use) are called directly, matching
`/admin/customers`' own tenant-creation authority on the Next.js side.
"""
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import ValidationError

from database.supabase_client import get_client

from victron import ingest as victron_ingest
from victron.anomaly_drift import check_quiet_drift, check_underperformance
from victron.anomaly_silence import check_unexpected_silence
from victron.vrm_live import fetch_live_snapshot
from victron.vrm_remote import VrmRemoteAuthError, VrmRemoteClient
from victron.vrm_series import DEFAULT_TZ_NAME
from victron.vrm_savings import fetch_site_savings
from victron.vrm_shape import RANGE_DAYS, fetch_site_shape

from vrm_api import jobs, secrets, tenancy
from vrm_api.deps import require_pipeline_key
from vrm_api.routers.vrm_sync import _do_sync
from vrm_api.schemas import (
    FleetAnomalyDetectDailyOut,
    FleetSnapshotsRefreshOut,
    JobCreated,
    SiteFieldsIn,
    SiteSavingsOut,
    SiteShapeOut,
    VrmFleetInstallationOut,
    VrmFleetInstallationsOut,
    VrmFleetLinkedSiteOut,
    VrmFleetLinkOut,
    VrmFleetLinkRequest,
    VrmFleetSyncRequest,
)

logger = logging.getLogger("vrm_api.vrm_fleet")

# Bug-fix pass 2026-08-18 (Bug 1) — a bad, live report on a real customer
# happened because linking an installation through this router collected no
# site metadata at all (`system_type` silently defaulted to 'hybrid',
# location/lat/lng/pv_kwp/battery_* all NULL). `SiteFieldsIn` on
# `VrmFleetLinkRequest`/`post_link()` closes that gap (both already existed —
# only the Next.js form never sent it, fixed in `VrmFleetManager.tsx`). This
# regex is the OTHER half of the fix: a genuinely useful pre-fill, not just
# an empty form — see `_monitoring_suggestions_by_installation()` below.
# Deliberately loose (substring/regex match, not a strict URL parse) per the
# bug report: matches e.g.
# "https://vrm.victronenergy.com/installation/156868/dashboard".
_VRM_INSTALLATION_URL_RE = re.compile(r"/installation/(\d+)/")

router = APIRouter(prefix="/v1/vrm-fleet", tags=["vrm-fleet"],
                   dependencies=[Depends(require_pipeline_key)])

SCHEMA = "vrm"

# See post_refresh_snapshots()'s own comment on energy_daily_by_site — kept
# equal to victron/anomaly_silence.py's own _LOOKBACK_DAYS by convention,
# not by import (a plain int literal, not worth a cross-module constant).
_ANOMALY_ENERGY_LOOKBACK_DAYS = 30

# See post_detect_anomalies_daily()'s own comment on energy_daily_by_site —
# needs to comfortably cover anomaly_drift.py's own
# _BASELINE_WINDOW_DAYS (90) + _RECENT_WINDOW_DAYS (14) = 104, with a little
# slack for a site whose most recent valid day isn't literally yesterday
# (a sync gap, etc.) so the baseline window doesn't quietly shrink below
# that module's own _MIN_BASELINE_VALID_DAYS floor. Restated here rather
# than imported, same "OK to duplicate a small literal across a module
# boundary" call _ANOMALY_ENERGY_LOOKBACK_DAYS above already makes.
_DRIFT_ENERGY_LOOKBACK_DAYS = 120


def _t(name: str):
    return get_client().schema(SCHEMA).table(name)


def _admin_token() -> str:
    """`VRM_ADMIN_TOKEN` from the shared root `.env` (§3.3's corrected
    storage note — no separate `vrm_api/.env`). Raised as a clean 500
    (never a token, never a raw env-lookup error) rather than a
    `KeyError`/`None`-token crash deep inside `VrmRemoteClient`."""
    token = os.environ.get("VRM_ADMIN_TOKEN")
    if not token:
        logger.error("vrm-fleet: VRM_ADMIN_TOKEN is not set in the environment.")
        raise HTTPException(status_code=500, detail={"code": "vrm_admin_token_missing"})
    return token


_MONITORING_SUGGESTION_COLUMNS = (
    "system_type", "location", "latitude", "longitude", "pv_kwp",
    "battery_nominal_kwh", "battery_dod_pct", "timezone", "report_language",
)


def _monitoring_suggestions_by_installation() -> dict[int, SiteFieldsIn]:
    """Oscar's own `monitoring` schema (a different, older product —
    Node-RED-monitored sites, predating VRM Monitor) often already has real,
    human-entered settings for the exact same physical installation being
    linked here: many of his fleet installations are sites he already
    monitors via Node-RED too. `monitoring.sites.monitoring_urls` is a
    `text[]` that, for some rows, embeds the site's VRM dashboard URL
    (`https://vrm.victronenergy.com/installation/<id>/dashboard`) — the
    installation id is right there in the URL.

    Confirmed live 2026-08-18: `monitoring.sites` id 7
    (`site_id='karen-montealegre'`) has
    `monitoring_urls=['https://vrm.victronenergy.com/installation/156868/
    dashboard']`, matching VRM installation 156868 exactly, with real
    `system_type='off_grid'`/`location`/`latitude`/`longitude`/`pv_kwp`/
    `battery_nominal_kwh`/`battery_dod_pct` — the correct values for the site
    that got linked with none of that filled in (this bug-fix pass's
    originating bug). This is what makes the pre-fill genuinely useful
    rather than just an empty form the second time too.

    ONE query for the whole fleet, not one per installation (called once by
    `get_installations()`, not from `post_link()` or per-row) — `not_every
    installation will have a match` (only 13 of 25 `monitoring.sites` rows
    have `monitoring_urls` populated at all, and fewer still are
    VRM-flavored vs. eGauge/SolarWeb/SMA links) is expected and fine; a
    non-match simply isn't a key in the returned dict. Never auto-applied —
    `VrmFleetInstallationOut.suggested_fields`'s own docstring is the
    "admin confirms, nothing writes until they click" contract this
    function's result feeds into.
    """
    rows = (get_client().schema("monitoring").table("sites")
           .select("monitoring_urls," + ",".join(_MONITORING_SUGGESTION_COLUMNS))
           .not_.is_("monitoring_urls", "null")
           .execute().data or [])
    out: dict[int, SiteFieldsIn] = {}
    for row in rows:
        urls = row.get("monitoring_urls") or []
        id_site: int | None = None
        for url in urls:
            m = _VRM_INSTALLATION_URL_RE.search(url or "")
            if m:
                id_site = int(m.group(1))
                break
        if id_site is None or id_site in out:
            # First match wins on a duplicate (not expected in practice —
            # one physical installation, one monitoring.sites row).
            continue
        values = {col: row.get(col) for col in _MONITORING_SUGGESTION_COLUMNS
                  if row.get(col) is not None}
        try:
            out[id_site] = SiteFieldsIn(**values)
        except ValidationError:
            # A monitoring row with a value outside vrm.sites' own
            # vocabulary (e.g. a system_type/report_language SiteFieldsIn
            # doesn't accept) must not break the whole installations list —
            # that installation just gets no suggestion, same as if
            # monitoring_urls hadn't matched at all.
            logger.warning(
                "vrm-fleet: monitoring.sites suggestion for installation "
                "%s failed validation, skipping.", id_site,
            )
    return out


@router.get("/installations", response_model=VrmFleetInstallationsOut)
def get_installations() -> VrmFleetInstallationsOut:
    """Oscar's whole VRM fleet, live from Victron, plus each installation's
    link state — never cached/stored here, the same "fetched live, before
    anything is stored" spirit `vrm_link.py:post_validate()` has for the
    customer path (PLAN_PHASE15.md §3.1 step 1), even though this endpoint
    itself writes nothing either way."""
    client = VrmRemoteClient(_admin_token())
    try:
        me = client.get_me()
        user = me.get("user") or {}
        vrm_user_id = user.get("id")
        if vrm_user_id is None:
            raise HTTPException(
                status_code=502,
                detail={"code": "vrm_unexpected_response",
                       "message": "Victron VRM API did not return a user id."},
            )
        installations = client.list_installations(vrm_user_id, extended=True)
    except VrmRemoteAuthError as exc:
        # VRM_ADMIN_TOKEN itself is bad/expired/revoked — a platform-config
        # problem, not a per-customer one (contrast vrm_link.py's
        # customer-facing 400 for the same underlying exception type). The
        # exception's own text is already token-free (vrm_remote.py's own
        # rule), so it is safe to log verbatim server-side.
        logger.error("vrm-fleet: VRM_ADMIN_TOKEN rejected by Victron — %s", exc)
        raise HTTPException(
            status_code=502,
            detail={"code": "vrm_admin_token_invalid",
                   "message": "Victron rejected the admin VRM token."},
        ) from None

    records = [r for r in (installations.get("records") or [])
              if isinstance(r, dict) and r.get("idSite") is not None]
    id_sites = [r["idSite"] for r in records]

    # Join against vrm.sites (PLAN_PHASE15.md §3.3's own bullet for this
    # endpoint: "for each, whether it is already linked ... by joining
    # against vrm.sites.vrm_installation_id"). One installation id can map
    # to MORE than one site row (§1.1's per-customer-not-global unique) —
    # grouped into a list per installation, not squashed to one.
    links_by_installation: dict[int, list[VrmFleetLinkedSiteOut]] = {}
    if id_sites:
        site_rows = (_t("sites")
                    .select("site_id,display_name,customer_id,vrm_installation_id,"
                           "vrm_sync_enabled,vrm_last_synced_at")
                    .in_("vrm_installation_id", id_sites).execute().data or [])
        customer_ids = sorted({r["customer_id"] for r in site_rows})
        customer_names: dict[str, str] = {}
        if customer_ids:
            customer_names = {
                c["id"]: c["name"]
                for c in (_t("customers").select("id,name")
                         .in_("id", customer_ids).execute().data or [])
            }
        for row in site_rows:
            links_by_installation.setdefault(row["vrm_installation_id"], []).append(
                VrmFleetLinkedSiteOut(
                    customer_id=row["customer_id"],
                    customer_name=customer_names.get(row["customer_id"]),
                    site_id=row["site_id"],
                    site_display_name=row["display_name"],
                    vrm_sync_enabled=bool(row.get("vrm_sync_enabled")),
                    vrm_last_synced_at=row.get("vrm_last_synced_at"),
                )
            )

    # One query for every installation on this page, not N+1 (Bug 1's own
    # instruction — "prefer computing it once per installation list").
    suggestions = _monitoring_suggestions_by_installation()

    out = [
        VrmFleetInstallationOut(
            id_site=r["idSite"], name=r.get("name"), identifier=r.get("identifier"),
            links=links_by_installation.get(r["idSite"], []),
            suggested_fields=suggestions.get(r["idSite"]),
        )
        for r in records
    ]
    return VrmFleetInstallationsOut(installations=out)


@router.post("/link", response_model=VrmFleetLinkOut)
def post_link(body: VrmFleetLinkRequest) -> VrmFleetLinkOut:
    """Create-or-reuse on BOTH customer and site (PLAN_PHASE15.md §3.3) —
    unlike `vrm_link.py`'s customer connect flow, which only ever creates a
    *site* under an already-existing (self-serve, already-authenticated)
    customer. Nothing here re-validates the installation against Victron
    (unlike `vrm_link.py:post_connect()`'s re-validate-before-write step) —
    there is no customer-pasted token whose validity could have changed
    between two requests; the installation id came straight from this same
    router's own `get_installations()` moments earlier.
    """
    if bool(body.customer_id) == bool(body.new_customer_name):
        raise HTTPException(
            status_code=400,
            detail={"code": "exactly_one_customer_field_required",
                   "message": "Provide exactly one of customer_id or new_customer_name."},
        )

    if body.customer_id:
        customer = tenancy.get_customer(body.customer_id)
        customer_is_existing = True
    else:
        # upsert_customer() itself is create-or-reuse by slug — look the
        # slug up FIRST so the response can honestly say which one happened,
        # the same "site_is_existing" honesty VrmLinkSiteResult/
        # VrmLinkConnectOut already give the customer connect flow.
        slug = victron_ingest.slugify(body.new_customer_name)
        pre_existing = (_t("customers").select("id").eq("slug", slug)
                        .limit(1).execute().data)
        customer = victron_ingest.upsert_customer(body.new_customer_name)
        customer_is_existing = bool(pre_existing)

    existing_site = tenancy.find_customer_site(customer["id"], body.site_name_or_id)
    site_id = (existing_site["site_id"] if existing_site
              else victron_ingest.make_site_id(customer["slug"], body.site_name_or_id))

    site_fields = body.site_fields.model_dump(exclude_none=True)
    display_name = site_fields.pop("display_name", None) or body.site_name_or_id
    # Not part of SiteFieldsIn's whitelist (schemas.py's own comment:
    # vrm_installation_id is "derived, not caller-set") — set here,
    # programmatically, the one place that's actually true, same as
    # vrm_link.py:post_connect()'s equivalent line.
    site_fields["vrm_installation_id"] = body.vrm_installation_id
    site_fields["source"] = "vrm_api"
    site_fields["vrm_sync_enabled"] = True

    try:
        victron_ingest.upsert_site(customer["id"], site_id, display_name, **site_fields)
    except Exception as exc:  # noqa: BLE001 — translate the one expected
        # Postgres conflict (§1.1's UNIQUE (customer_id, vrm_installation_id))
        # into a typed, customer-safe 409 rather than a raw 500; anything
        # else re-raises to main.py's generic handler unchanged.
        msg = str(exc).lower()
        if "idx_vrm_sites_customer_installation" in msg or "vrm_installation_id" in msg:
            raise HTTPException(
                status_code=409,
                detail={"code": "installation_already_linked_to_customer",
                       "vrm_installation_id": body.vrm_installation_id},
            ) from None
        raise

    return VrmFleetLinkOut(
        customer_id=customer["id"], customer_is_existing=customer_is_existing,
        site_id=site_id, site_is_existing=bool(existing_site),
    )


@router.post("/sync", response_model=JobCreated)
def post_sync(body: VrmFleetSyncRequest, background_tasks: BackgroundTasks) -> JobCreated:
    """Same job machinery as `POST /v1/vrm-sync` (`jobs.create_job`/
    `jobs.run_job`, the shared `vrm_sync._do_sync()` work function) — no
    duplicated sync logic. The one real difference: no
    `tenancy.assert_owns_site()`, because there is no single owning
    "requesting customer" in this flow to check `site_id` against — this
    router looks the site up directly and uses whatever `customer_id` it
    already has (PLAN_PHASE15.md §3.3's own framing, restated in this
    module's docstring).
    """
    rows = _t("sites").select("*").eq("site_id", body.site_id).limit(1).execute().data
    if not rows:
        raise HTTPException(status_code=404, detail={"code": "no_such_site"})
    site = rows[0]

    token = _admin_token()

    # Hand-built, not body.model_dump() — same §2.5 rule 4 discipline
    # vrm_sync.py:post_sync() documents for the customer path (there is no
    # token field on VrmFleetSyncRequest to accidentally include here
    # either, but the admin token is read into a local variable just above,
    # and must never end up in this dict).
    job = jobs.create_job(
        "vrm_sync", customer_id=site["customer_id"], site_id=body.site_id,
        params={"site_id": body.site_id, "start": body.start, "end": body.end},
    )
    background_tasks.add_task(
        jobs.run_job, job["id"],
        lambda: _do_sync(site["customer_id"], site, body.start, body.end,
                         triggered_by="admin", token=token),
    )
    return JobCreated(job_id=job["id"])


@router.post("/refresh-snapshots", response_model=FleetSnapshotsRefreshOut)
def post_refresh_snapshots() -> FleetSnapshotsRefreshOut:
    """Fleet Dashboard Phase 2's live-snapshot sweep (2026-08-30) — meant
    to run every ~15 minutes via a GitHub Actions `cron:`, same shape as
    `billing-reconcile.yml`'s daily sweep. Synchronous, not a `vrm.jobs`
    row: this is a short, bounded, per-site loop (like `vrm_sync.py:
    post_run_due()`), not a long single-site render worth its own job
    record.

    Token per site, not one token for everything: a customer-connected
    site should be read with THAT CUSTOMER's own VRM credential (the same
    one `vrm_sync.py:post_sync()`'s "Sync now" already reads) — correct
    scoping, and it works even for an installation `VRM_ADMIN_TOKEN` was
    never granted to see. `VRM_ADMIN_TOKEN` is the fallback, for a site
    that only exists because it was linked through THIS router's own admin
    fleet flow, which never collects a customer token at all (`post_sync()`
    above always passes `token=VRM_ADMIN_TOKEN` explicitly, for the same
    reason). A site with neither is skipped, not failed — there is
    genuinely nothing to fetch it with.

    One site's failure never stops the sweep — same per-site isolation
    `vrm_sync.py:post_run_due()` already uses for exactly this reason.

    Live alarm/critical-alert state added 2026-09-01 (see
    `victron/vrm_live.py`'s module docstring for why): `fetch_live_snapshot()`
    below now folds each category's current state directly into this same
    snapshot row (`raw.alarms`/`raw.critical_alerts`) — a plain "is this
    present right now" read, not an episode/history record. The historical
    sync still owns `vrm.alarm_events`/`vrm.critical_alerts` for report/
    health-score purposes, untouched by this.

    Unexpected-silence anomaly detection added 2026-09-03 (Fleet Dashboard
    Phase 3b, PLAN_PHASE19_FLEET_P3.md §3 — see `victron/anomaly_silence.py`'s
    own module docstring for the full check). Same "reuse data this sweep
    already fetched, zero extra VRM API cost" reasoning as the live-alarm
    work above; this one is DB-only (no VRM call of its own), it just needs
    each site's PREVIOUS `site_snapshots` reading (for the 2-consecutive-
    check debounce) fetched BEFORE this loop's own upserts overwrite it, and
    each site's recent `vrm.energy_daily` rows (for the "should be
    producing" gate) — both batched in ONE query each for the whole sweep,
    not per-site, same "one query for the whole page, not N+1" discipline
    `_monitoring_suggestions_by_installation()` already uses above.
    """
    sites = (_t("sites").select("site_id, customer_id, vrm_installation_id, timezone")
            .eq("source", "vrm_api").eq("active", True).execute().data or [])
    admin_token = os.environ.get("VRM_ADMIN_TOKEN")
    site_ids = [s["site_id"] for s in sites]

    # Snapshot BEFORE this sweep's own upserts overwrite it — the "previous
    # check" half of anomaly_silence.py's debounce. `site_snapshots` is
    # latest-only (migration 031), so this is the only place that prior
    # reading is ever visible; read once for every site up front rather than
    # per-site inside the loop below (which would race against that same
    # site's own upsert a few lines down).
    previous_snapshots_by_site: dict[str, dict] = {}
    if site_ids:
        prev_rows = (_t("site_snapshots").select("site_id, captured_at, pv_power_w")
                    .in_("site_id", site_ids).execute().data or [])
        previous_snapshots_by_site = {r["site_id"]: r for r in prev_rows}

    # This sweep's own view of each site's "should be producing" history —
    # see anomaly_silence.py's module docstring for exactly what this gates.
    # `_ANOMALY_ENERGY_LOOKBACK_DAYS` mirrors that module's own
    # `_LOOKBACK_DAYS` constant (restated here rather than imported so this
    # query's window can't silently drift out of sync with what that module
    # actually reads — same "OK to duplicate a small literal across a module
    # boundary, not OK to duplicate real logic" call this codebase already
    # makes elsewhere).
    energy_daily_by_site: dict[str, list[dict]] = {}
    if site_ids:
        lookback_date = (datetime.now(timezone.utc) - timedelta(days=_ANOMALY_ENERGY_LOOKBACK_DAYS)).date().isoformat()
        energy_rows = (_t("energy_daily").select("site_id, pv_kwh, complete_day")
                      .in_("site_id", site_ids).gte("date", lookback_date).execute().data or [])
        for row in energy_rows:
            energy_daily_by_site.setdefault(row["site_id"], []).append(row)

    refreshed, skipped, failed = 0, 0, 0
    for site in sites:
        id_site = site.get("vrm_installation_id")
        if id_site is None:
            skipped += 1
            continue

        token: str | None = None
        try:
            token = secrets.read_customer_vrm_token(site["customer_id"])
        except Exception:  # noqa: BLE001 — a broken vault read for one
            # customer must not stop the rest of the sweep; fall through to
            # the admin token below same as "never connected" would.
            logger.warning("vrm-fleet refresh-snapshots: could not read customer token for customer_id=%s",
                          site["customer_id"])
        token = token or admin_token
        if not token:
            skipped += 1
            continue

        try:
            client = VrmRemoteClient(token)
            diagnostics = client.get_diagnostics(id_site)
            snapshot = fetch_live_snapshot(client, id_site, site["site_id"],
                                          tz=site.get("timezone") or DEFAULT_TZ_NAME,
                                          diagnostics=diagnostics)
        except Exception:  # noqa: BLE001 — see this function's own docstring
            logger.exception("vrm-fleet refresh-snapshots: unexpected error for site %s", site["site_id"])
            failed += 1
            continue

        if snapshot is None:
            skipped += 1
            continue

        # `updated_at DEFAULT now()` only fires on INSERT, not on the UPDATE
        # half of an upsert — found from `tools/run_migration_031.py`'s own
        # verification output, where a second upsert with different values
        # left `updated_at` frozen at its first-ever value. Set explicitly
        # on every write instead of relying on the column default.
        _t("site_snapshots").upsert({
            "site_id": site["site_id"], **snapshot,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
        refreshed += 1

        # Unexpected-silence check (Fleet Dashboard Phase 3b) — reads the
        # PRE-upsert previous reading captured above, and this site's own
        # recent energy_daily history; writes at most one vrm.site_anomalies
        # row. A failure here must not un-count a snapshot refresh that
        # already succeeded (nor stop the rest of the sweep) — logged and
        # skipped, same per-site isolation this whole loop already uses for
        # every other step.
        try:
            previous = previous_snapshots_by_site.get(site["site_id"])
            check_unexpected_silence(
                _t("site_anomalies"),
                site_id=site["site_id"],
                tz_name=site.get("timezone"),
                new_pv_power_w=snapshot.get("pv_power_w"),
                new_captured_at=snapshot.get("captured_at"),
                previous_pv_power_w=previous.get("pv_power_w") if previous else None,
                previous_captured_at=previous.get("captured_at") if previous else None,
                energy_daily_rows=energy_daily_by_site.get(site["site_id"], []),
            )
        except Exception:  # noqa: BLE001 — see this block's own comment above
            logger.exception("vrm-fleet refresh-snapshots: unexpected_silence check failed for site %s",
                             site["site_id"])

    return FleetSnapshotsRefreshOut(checked=len(sites), refreshed=refreshed, skipped=skipped, failed=failed)


@router.post("/detect-anomalies-daily", response_model=FleetAnomalyDetectDailyOut)
def post_detect_anomalies_daily() -> FleetAnomalyDetectDailyOut:
    """Fleet Dashboard Phase 3a ("quiet drift") + Phase 3c ("underperformance
    vs. design") anomaly detection, added 2026-09-03
    (PLAN_PHASE19_FLEET_P3.md §4/§5 — see `victron/anomaly_drift.py`'s own
    module docstring for the full checks). Sibling of
    `post_refresh_snapshots()` above (same per-site isolation, same "one
    query for the whole sweep, not N+1" batching of `vrm.energy_daily`), but
    NOT hooked into that ~15-minute live sweep — 3a/3c read `vrm.
    energy_daily`, which is daily-grain and only actually advances once per
    site per day (via `vrm_sync.py:post_run_due()`'s own due-ness gate), so
    running this on the same 15-minute cadence would just recompute an
    identical result ~96 times a day for nothing.

    Meant to be called once daily, piggybacking on the existing daily sync
    cadence per PLAN_PHASE19_FLEET_P3.md §4 point 4 / §5 ("same cadence as
    3a") — wired into `.github/workflows/scheduled-reports.yml`, right after
    that workflow's own "Sync due VRM-API sites" step, the same job that
    already keeps `vrm.energy_daily` current. That workflow's own cron is
    hourly, not daily (§0 of that file's own comment explains why: coarser
    per-site local-hour scheduling doesn't mean anything at daily
    granularity) — calling this endpoint on every one of those hourly ticks
    is harmless, not wasteful in any way that matters: `vrm.energy_daily`
    itself only changes once a day per site (same due-ness gate above), so
    every call before that day's sync lands just recomputes the same
    result idempotently, and each check's own Supabase read/write cost is
    trivial next to a VRM API call. This is a real, deliberate choice, not
    an oversight — building a literal once-daily-only trigger would need
    this workflow to track its own last-run date somewhere, additional
    state for no behavioral gain over "safe to call more often than it
    needs to matter."

    One site's failure never stops the sweep — same per-site isolation
    `post_refresh_snapshots()` above and `vrm_sync.py:post_run_due()` both
    already use for exactly this reason.
    """
    sites = (_t("sites").select("site_id, latitude, longitude, pv_kwp")
            .eq("source", "vrm_api").eq("active", True).execute().data or [])
    site_ids = [s["site_id"] for s in sites]

    # One query for the whole sweep, not per-site — same discipline
    # post_refresh_snapshots() already uses for its own energy_daily_by_site.
    energy_daily_by_site: dict[str, list[dict]] = {}
    if site_ids:
        lookback_date = (datetime.now(timezone.utc) - timedelta(days=_DRIFT_ENERGY_LOOKBACK_DAYS)).date().isoformat()
        energy_rows = (_t("energy_daily").select("site_id, date, pv_kwh, complete_day")
                      .in_("site_id", site_ids).gte("date", lookback_date).execute().data or [])
        for row in energy_rows:
            energy_daily_by_site.setdefault(row["site_id"], []).append(row)

    checked, skipped, failed = 0, 0, 0
    for site in sites:
        checked += 1
        lat, lon = site.get("latitude"), site.get("longitude")
        rows = energy_daily_by_site.get(site["site_id"], [])

        if lat is None or lon is None:
            # Neither check can derive a PVGIS shape at all without
            # coordinates -- both 3a (which otherwise needs no pv_kwp) and
            # 3c are equally blocked. Counted once here rather than twice
            # (once per check) so "skipped" means "this site, this sweep,"
            # not "this site-check pair."
            skipped += 1
            continue

        try:
            check_quiet_drift(
                _t("site_anomalies"), site_id=site["site_id"],
                lat=float(lat), lon=float(lon), energy_daily_rows=rows,
            )
        except Exception:  # noqa: BLE001 — one site's failure must not stop the rest of the sweep
            logger.exception("vrm-fleet detect-anomalies-daily: quiet_drift check failed for site %s",
                             site["site_id"])
            failed += 1

        pv_kwp = site.get("pv_kwp")
        try:
            check_underperformance(
                _t("site_anomalies"), site_id=site["site_id"],
                lat=float(lat), lon=float(lon),
                pv_kwp=float(pv_kwp) if pv_kwp is not None else None,
                energy_daily_rows=rows,
            )
        except Exception:  # noqa: BLE001 — see this block's own comment above
            logger.exception("vrm-fleet detect-anomalies-daily: underperformance check failed for site %s",
                             site["site_id"])
            failed += 1

    return FleetAnomalyDetectDailyOut(checked=checked, skipped=skipped, failed=failed)


@router.get("/site-shape", response_model=SiteShapeOut)
def get_site_shape(
    site_id: str = Query(...),
    range: Literal["today", "week", "month"] = Query(...),
) -> SiteShapeOut:
    """Fleet Dashboard Phase 2.5 (2026-08-30) — one site's hour-of-day
    PV/load/battery/grid shape, computed fresh from VRM on every call
    (`victron/vrm_shape.py`; see that module's own docstring for the
    "confirmed 180+ days of real 15-min history" finding this is built on).
    Never stored — this is the on-demand alternative to a new accumulating
    snapshot-history table, cheaper for a fleet this size.

    Same site lookup / token resolution as `post_refresh_snapshots()`
    above: a customer-connected site reads with that customer's own VRM
    credential, `VRM_ADMIN_TOKEN` is the fallback for an admin-fleet-linked
    site. 404 for a site this API doesn't know as `source='vrm_api'` — a
    CSV-only site or an unknown `site_id` has nothing this endpoint could
    ever answer.
    """
    row = (_t("sites").select("site_id, customer_id, vrm_installation_id, timezone, source")
          .eq("site_id", site_id).limit(1).execute().data)
    if not row or row[0].get("source") != "vrm_api" or row[0].get("vrm_installation_id") is None:
        raise HTTPException(status_code=404, detail={"code": "site_not_found"})
    site = row[0]

    token: str | None = None
    try:
        token = secrets.read_customer_vrm_token(site["customer_id"])
    except Exception:  # noqa: BLE001 — see post_refresh_snapshots()'s own try/except
        logger.warning("vrm-fleet site-shape: could not read customer token for customer_id=%s",
                      site["customer_id"])
    token = token or os.environ.get("VRM_ADMIN_TOKEN")
    if not token:
        raise HTTPException(status_code=409, detail={"code": "no_vrm_token_available"})

    client = VrmRemoteClient(token)
    shape = fetch_site_shape(client, site["vrm_installation_id"], range_key=range,
                            tz=site.get("timezone") or DEFAULT_TZ_NAME)
    return SiteShapeOut(**shape)


@router.get("/site-savings", response_model=SiteSavingsOut)
def get_site_savings(
    site_id: str = Query(...),
    range: Literal["today", "week", "month"] = Query(...),
) -> SiteSavingsOut:
    """Fleet Dashboard Phase 2.5 (2026-08-31) — estimated savings for one
    site over today/the last 7 days/the last 30 days. A thin wrapper around
    `victron/vrm_savings.py:fetch_site_savings()`, which itself only calls
    `victron/savings.py:compute_weekly_savings()` — the exact function the
    PDF report already uses (real ARESEP-blended CR tariff, or a site's own
    configured flat `savings_rate`/`savings_currency` elsewhere). No new
    tariff math lives here or in that wrapper.

    404 for the same reason `get_site_shape()` above does — a CSV-only site
    or an unknown `site_id` isn't something this endpoint can ever answer
    for, regardless of what savings math it might otherwise support.
    """
    row = _t("sites").select("site_id, source").eq("site_id", site_id).limit(1).execute().data
    if not row or row[0].get("source") != "vrm_api":
        raise HTTPException(status_code=404, detail={"code": "site_not_found"})

    result = fetch_site_savings(site_id, range_key=range)
    if result is None:
        return SiteSavingsOut(amount=None, currency=None, basis_count=None, days_with_data=0)
    return SiteSavingsOut(**result)
