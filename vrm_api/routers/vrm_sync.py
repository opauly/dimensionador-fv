from __future__ import annotations
"""
`vrm_api`'s router for pulling directly from Victron's VRM cloud
(PLAN_PHASE15.md §0.4 — `vrm_link.py`'s deliberate sibling: that router
stores the credential and the site mapping, this one uses them).

`POST /v1/vrm-sync` creates a `vrm_sync` job (migration 024 added the kind)
and runs it through the exact same in-process `BackgroundTasks` model
`routers/ingest.py` already uses (`jobs.create_job` / `jobs.run_job`) — no
new job machinery. Unlike ingest, there is no preview/commit split
(PLAN_PHASE15.md §6.1): a sync is idempotent and cheap to repeat, with no
uploaded artifact to parse exactly once, so a preview step would be pure
ceremony — the connect flow's validate-then-connect is this phase's
equivalent "never write on the first click" guarantee, for the part that
actually matters (the token).

── Tenancy — the third control (PLAN_PHASE15.md §3.2) ──────────────────────
`tenancy.assert_owns_site(customer_id, site_id)` is not a formality here —
it IS the enforcement point for "customer A's token can never pull customer
B's data even if a site_id gets confused somewhere". The site row it returns
is the ONLY source of `vrm_installation_id` this module ever calls Victron
with. `schemas.VrmSyncRequest` has no field that could carry an installation
id from a request body — grep it; there is nothing to grep. As a second,
independent backstop (in case our own site<->installation mapping is simply
wrong, not tampered with), `_do_sync()` compares the installation id Victron
actually returned data for against the one the site row said to call, and
aborts — writing nothing — on any mismatch (§3.2 control 3).

── Token handling (PLAN_PHASE15.md §2.5 rule 4) ────────────────────────────
`vrm.jobs.params` is exactly `{customer_id, site_id, start, end}` — built by
hand in `post_sync()` below, never `body.model_dump()` (unlike every other
job in this API, which does exactly that — this is the one place that
pattern must NOT be copied, because `VrmSyncRequest` has no token field to
accidentally include, but a future body that grew one would silently leak
through a `model_dump()`). The token itself is read fresh, per run, inside
`_do_sync()` via `vrm_api.secrets.read_customer_vrm_token()` — never cached,
never passed into `jobs.create_job()`, never returned in a job's `result`.

── Failure handling (PLAN_PHASE15.md §9 — the authoritative table this
   module implements row by row) ────────────────────────────────────────────
  * 401/403 (`VrmRemoteAuthError`) — stamps `vrm.customers.
    vrm_token_revoked_at`/`vrm_token_last_checked_at`/`vrm_token_last_error`.
    "Disable further syncs for that customer" is achieved WITHOUT a separate
    flag check: `vrm_api.secrets.read_customer_vrm_token()`'s own wrapper
    function already returns `NULL` once `vrm_token_revoked_at` is set
    (migration 024), so the very next sync attempt for this customer sees
    "no live token" and fails cleanly before ever calling Victron again —
    the revocation stamp IS the disable mechanism, not an additional one.
  * 429 (`VrmRemoteRateLimited`) — job fails with a retry message; NO
    `vrm.customers` token-state column is touched (§9: "token state
    untouched" — read literally here as "none of vrm_token_revoked_at/
    _last_checked_at/_last_ok_at/_last_error change").
  * Victron down / network (`VrmRemoteUnavailable`,
    `VrmRemoteBudgetExceeded`) — job fails; `vrm.sites.vrm_last_sync_error`
    is stamped; token state untouched, same reasoning as 429.
  * Installation missing / no longer shared (`VrmRemoteNotFound`) —
    `vrm.sites.vrm_last_sync_error='installation_not_found'` AND
    `vrm_sync_enabled=false`. §9's table is explicit about both — this is
    the literal table text, not the shorter "token untouched" paraphrase in
    PLAN_PHASE15.md §8 Step 4's build bullet, which doesn't mention
    `vrm_sync_enabled` either way; the table (§9) is the authoritative
    spec and is followed here. `vrm_installation_id` itself is left alone
    (unlinking-and-remapping is a customer/admin action, not this job's).
  * Installation id mismatch (§3.2 control 3) — job fails, nothing written,
    and it is logged at `CRITICAL` (not `WARNING`) specifically BECAUSE §9
    says this one means something is wrong with OUR OWN mapping, not
    Victron's data — the one failure mode in this table Oscar should
    actually go looking for.

── Step 4b addition: an optional admin-sourced token (PLAN_PHASE15.md §3.3) ─
`_do_sync()` gained an optional `token` keyword argument after this module
was first built and independently verified. `routers/vrm_fleet.py` (Oscar's
own VRM fleet, `VRM_ADMIN_TOKEN`) is the only caller that ever passes a real
value; every call site in THIS file (`post_sync()`, `post_run_due()`) still
passes nothing and gets the exact original Vault-read behaviour described
above, unchanged. See `_do_sync()`'s own docstring for why every place this
function touches `vrm.customers`' token-STATE columns is gated on
`token is None` (`is_customer_token`) — those columns describe a customer's
own connection, and must never be stamped from an admin-token call.
"""
import logging
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends

from database.supabase_client import get_client

from victron import ingest as victron_ingest
from victron import vrm_series
from victron.vrm_remote import (
    VrmRemoteAuthError,
    VrmRemoteBudgetExceeded,
    VrmRemoteClient,
    VrmRemoteNotFound,
    VrmRemoteRateLimited,
    VrmRemoteUnavailable,
)
from victron.vrm_series import VrmSeriesError

from vrm_api import jobs, secrets, tenancy
from vrm_api.deps import require_pipeline_key
from vrm_api.schemas import JobCreated, VrmSyncRequest, VrmSyncRunDueOut, VrmSyncSiteResult

logger = logging.getLogger("vrm_api.vrm_sync")

router = APIRouter(prefix="/v1/vrm-sync", tags=["vrm-sync"],
                   dependencies=[Depends(require_pipeline_key)])

SCHEMA = "vrm"

# PLAN_PHASE15.md §0.5 Q4: 31 days, matching rdb.MAX_CUSTOM_RANGE_DAYS.
# `/run-due` (no caller yet — Step 7 is deferred) uses this as its own
# backfill ceiling on a site's first-ever scheduled sync; a real Step 7
# would likely promote this to an env var (`VRM_SYNC_MAX_BACKFILL_DAYS`,
# named in the plan's Step 7 docs) — not built here, since there is no
# caller yet to configure.
_DEFAULT_BACKFILL_DAYS = 31


def _t(name: str):
    return get_client().schema(SCHEMA).table(name)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class VrmSyncError(Exception):
    """Customer-safe failure text for a `vrm_sync` job (PLAN_PHASE15.md §9).
    Added to `jobs.py:_safe_error_message()`'s allowlist alongside
    `VrmCsvError`/`NotAuthorized`. Every message this module constructs is
    written by hand, in this file, specifically to be safe to return — never
    a token, never a raw Postgres/Victron error string (those go to the
    server log via `logging.exception`/`logging.critical` calls in this
    module, and again via `jobs.run_job`'s own `logging.exception`)."""


def _do_sync(customer_id: str, site: dict, start: str, end: str,
            *, triggered_by: str, token: str | None = None) -> dict:
    """The `vrm_sync` job's work function (PLAN_PHASE15.md §8 Step 4).

    `site` is the ALREADY ownership-checked row `tenancy.assert_owns_site()`
    returned to the route handler — this function never re-derives
    `vrm_installation_id` from anything a caller supplied (§3.2 control 3).

    `token` (PLAN_PHASE15.md §3.3 / Step 4b, added after this function was
    first built and independently verified — see that section's own
    "correction #2" note): every EXISTING call site (`post_sync()`,
    `post_run_due()`) leaves this `None` and gets the ORIGINAL, unmodified
    behaviour below — a fresh per-run Vault read via `secrets.
    read_customer_vrm_token()`. `routers/vrm_fleet.py`'s admin sync is the
    only caller that ever passes a real value here, and it passes
    `os.environ["VRM_ADMIN_TOKEN"]` — Oscar's own platform-wide credential,
    not a customer's. `is_customer_token` (below) gates every place this
    function would otherwise read/write `vrm.customers`' TOKEN-STATE columns
    (`vrm_token_revoked_at`/`vrm_token_last_checked_at`/`vrm_token_last_ok_at`/
    `vrm_token_last_error`): those columns describe the health of a
    CUSTOMER'S OWN connected token, and must never be stamped from the
    outcome of a call made with the admin token instead — a bad/expired
    `VRM_ADMIN_TOKEN` is Oscar's problem, not a reason to tell some customer
    their own VRM connection just broke.
    """
    is_customer_token = token is None

    site_id = site["site_id"]
    vrm_installation_id = site.get("vrm_installation_id")
    if vrm_installation_id is None:
        raise VrmSyncError(
            "This site has no linked VRM installation — connect it from the "
            "Victron VRM account panel before syncing."
        )

    if is_customer_token:
        # Read fresh, per run — never cached, never in vrm.jobs.params (§2.5
        # rule 4). A `None` here means "disconnected between the request and
        # the job running" OR "an earlier failed sync already stamped
        # vrm_token_revoked_at" (see this module's docstring on how 401/403
        # disables further syncs) — either way, a clean no-op, not a crash.
        token = secrets.read_customer_vrm_token(customer_id)
        if token is None:
            raise VrmSyncError(
                "No live VRM connection for this customer — reconnect to resume syncing."
            )

    client = VrmRemoteClient(token)

    try:
        parsed = vrm_series.fetch_and_map(
            client, vrm_installation_id, site_id, start, end,
            pv_kwp=site.get("pv_kwp"), battery_usable_kwh=site.get("battery_usable_kwh"),
            # PLAN_PHASE15.md §4.6/Step 3's flagged gap, closed here: the
            # site's OWN timezone, not vrm_series.py's America/Costa_Rica
            # default — see that module's docstring, "Day-bucketing
            # timezone" section.
            tz=site.get("timezone") or vrm_series.DEFAULT_TZ_NAME,
        )
    except VrmRemoteAuthError:
        if is_customer_token:
            _t("customers").update({
                "vrm_token_revoked_at": _now(),
                "vrm_token_last_checked_at": _now(),
                "vrm_token_last_error": "Victron rejected the stored VRM token.",
            }).eq("id", customer_id).execute()
            logger.warning("vrm_sync: auth error for site %s (customer %s) — token revoked",
                           site_id, customer_id)
            raise VrmSyncError(
                "Your VRM connection stopped working — reconnect to resume automatic "
                "updates. Your existing data is unaffected."
            ) from None
        # Admin-token path (PLAN_PHASE15.md §3.3): Victron rejected
        # VRM_ADMIN_TOKEN itself — this customer's OWN connection state is
        # untouched (see this function's docstring on `is_customer_token`).
        # Loud in the server log because, unlike a customer's own expired
        # token, this affects every site the admin fleet flow can reach.
        logger.error(
            "vrm_sync: VRM_ADMIN_TOKEN was rejected by Victron while syncing "
            "site %s (customer %s) via the admin fleet flow.", site_id, customer_id,
        )
        raise VrmSyncError(
            "Couldn't sync — the admin VRM token was rejected by Victron."
        ) from None
    except VrmRemoteRateLimited as exc:
        # §9: token state untouched.
        raise VrmSyncError(
            "VRM is rate-limiting us — try again in a few minutes."
        ) from exc
    except VrmRemoteNotFound:
        # §9's table (not the shorter Step 4 build-bullet paraphrase, see
        # this module's docstring): both fields, data kept.
        _t("sites").update({
            "vrm_last_sync_error": "installation_not_found",
            "vrm_sync_enabled": False,
        }).eq("site_id", site_id).execute()
        raise VrmSyncError(
            "This VRM installation is no longer visible on the connected VRM "
            "account — re-map it or upload a CSV."
        ) from None
    except (VrmRemoteUnavailable, VrmRemoteBudgetExceeded) as exc:
        _t("sites").update({"vrm_last_sync_error": str(exc)[:500]}).eq("site_id", site_id).execute()
        raise VrmSyncError("Couldn't reach VRM — try again.") from exc
    except VrmSeriesError as exc:
        _t("sites").update({"vrm_last_sync_error": str(exc)[:500]}).eq("site_id", site_id).execute()
        raise VrmSyncError(str(exc)) from exc

    # §3.2 control 3, the mismatch check: the installation Victron actually
    # answered for must equal the one this (ownership-checked) site row
    # said to call. A mismatch here is OUR mapping being wrong, not
    # Victron's data — loud, at CRITICAL, and nothing is written.
    returned_installation_id = parsed.get("installation_id")
    if str(returned_installation_id) != str(vrm_installation_id):
        logger.critical(
            "vrm_sync: INSTALLATION ID MISMATCH for site %s (customer %s) — "
            "stored vrm.sites.vrm_installation_id=%s, Victron returned "
            "data for installation_id=%s. This means something is wrong "
            "with our own site<->installation mapping, not with Victron's "
            "data (PLAN_PHASE15.md §3.2 control 3). Nothing was written.",
            site_id, customer_id, vrm_installation_id, returned_installation_id,
        )
        raise VrmSyncError("Sync failed — please try again or contact support.")

    if is_customer_token:
        # A real, successful call to Victron with this customer's OWN token
        # — this IS "when we last knew it was alive" (migration 024's own
        # framing for why these columns exist). Never stamped on the
        # admin-token path (see this function's docstring): a successful
        # admin-fleet sync says nothing about whether this customer has ever
        # connected their own token at all.
        _t("customers").update({
            "vrm_token_last_checked_at": _now(),
            "vrm_token_last_ok_at": _now(),
            "vrm_token_last_error": None,
        }).eq("id", customer_id).execute()

    summary = victron_ingest.ingest_parsed(
        parsed, site_id, source="vrm_api", triggered_by=triggered_by,
    )
    _t("sites").update({
        "vrm_last_synced_at": _now(),
        "vrm_last_sync_error": None,
    }).eq("site_id", site_id).execute()

    return {"site_id": site_id, **summary}


@router.post("", response_model=JobCreated)
def post_sync(body: VrmSyncRequest, background_tasks: BackgroundTasks) -> JobCreated:
    # This IS §3.2 control 3's enforcement point — the site row returned
    # here supplies vrm_installation_id inside _do_sync(); nothing from
    # `body` ever does (there is no such field on VrmSyncRequest — see the
    # module docstring).
    site = tenancy.assert_owns_site(body.customer_id, body.site_id)

    job = jobs.create_job(
        "vrm_sync", customer_id=body.customer_id, site_id=body.site_id,
        # §2.5 rule 4: hand-built, not body.model_dump() — see the module
        # docstring for why that distinction matters here specifically.
        params={"customer_id": body.customer_id, "site_id": body.site_id,
               "start": body.start, "end": body.end},
    )
    background_tasks.add_task(
        jobs.run_job, job["id"],
        lambda: _do_sync(body.customer_id, site, body.start, body.end, triggered_by="customer"),
    )
    return JobCreated(job_id=job["id"])


@router.post("/run-due", response_model=VrmSyncRunDueOut)
def post_run_due() -> VrmSyncRunDueOut:
    """PLAN_PHASE15.md §6.1/§6.3: built now for Step 7 (a GitHub Actions
    `cron:` job), which has no caller yet — Step 7 itself is confirmed
    deferred (PLAN_PHASE15.md §0.6 Q3). A minimal, correct implementation:
    synchronous and sequential (mirrors `runAllWeeklyReports()`'s own
    per-site failure isolation, PLAN_PHASE14.md/Phase 12's pattern) rather
    than another `vrm.jobs` row, since there is no caller yet to poll one.
    Reachable only behind the pipeline key, same as every route in this
    router (this router's own `dependencies=[Depends(require_pipeline_key)]`
    — nothing here is unauthenticated).
    """
    due_sites = (_t("sites").select("*")
                .eq("source", "vrm_api").eq("active", True).eq("vrm_sync_enabled", True)
                .execute().data or [])

    results: list[VrmSyncSiteResult] = []
    yesterday = date.today() - timedelta(days=1)
    for site in due_sites:
        site_id = site["site_id"]
        last_synced = site.get("vrm_last_synced_at")
        start = (date.fromisoformat(last_synced[:10]) if last_synced
                else yesterday - timedelta(days=_DEFAULT_BACKFILL_DAYS))
        if start > yesterday:
            results.append(VrmSyncSiteResult(site_id=site_id, status="skipped_up_to_date"))
            continue
        try:
            _do_sync(site["customer_id"], site, start.isoformat(), yesterday.isoformat(),
                    triggered_by="schedule")
            results.append(VrmSyncSiteResult(site_id=site_id, status="done"))
        except Exception as exc:  # noqa: BLE001 — per-site isolation (§6.3): one
            # site's failure must not block the rest of the run.
            logger.exception("vrm_sync/run-due: site %s failed", site_id)
            results.append(VrmSyncSiteResult(site_id=site_id, status="failed", error=str(exc)))

    return VrmSyncRunDueOut(sites_checked=len(due_sites), results=results)
