from __future__ import annotations
"""
`vrm_api`'s router for linking to Victron's VRM cloud (PLAN_PHASE15.md §0.4:
this file's name says exactly what it is — our API's router for linking to
Victron's — deliberately distinct from `vrm_api` itself, which is what this
whole service is called).

Three deliberate steps, none of which stores anything until the last
(PLAN_PHASE15.md §3.1):

  1. `POST /validate` — Victron `GET /users/me` + `GET /users/{id}/installations`
     with the pasted token. Writes NOTHING to Postgres or Vault. Lets the
     customer see *their own real installation names* before committing to
     anything.
  2. (client-side only) the customer maps each returned installation to
     "ignore" (simply omit it), "link to an existing site", or "create a new
     site" — mirrored here by `VrmLinkMapping.site_name_or_id`, the exact
     same ambiguous-by-design field `IngestPreviewRequest` already uses
     (`tenancy.find_customer_site()` decides which case it is — see
     `routers/ingest.py`). Reused deliberately rather than inventing a
     second way to express the same "existing site, or this string is a new
     site's name" ambiguity.
  3. `POST /connect` — re-validates the token (the customer may have taken
     minutes to map), then and only then writes: the Vault-backed token
     (`vrm_api/secrets.py`), the customer's `vrm_user_id`/
     `vrm_account_email`, and each mapping's `vrm_installation_id`/
     `source='vrm_api'`/`vrm_sync_enabled=true` on its target site (created
     via `victron.ingest.upsert_site()` if new, exactly like
     `routers/ingest.py`'s commit flow does for a new CSV-uploaded site).

`POST /disconnect` destroys the credential (via `vrm_api.secrets.
clear_customer_vrm_token()`, which stamps `vrm_token_revoked_at` and
actually deletes the Vault secret — Step 1's job, not reimplemented here)
and reverts every `source='vrm_api'` site of this customer's back to
`source='csv_upload'`/`vrm_sync_enabled=false`. It never deletes
`energy_daily`/`alarm_events`/`daily_health` history (PLAN_PHASE15.md §3.1:
"disconnecting a credential must not delete a year of a customer's
history").

`GET /status` returns connection STATE only — never a token, not even a
hint of one (PLAN_PHASE15.md §2.5 rule 2, the rule this endpoint exists
closest to violating by accident: its response model
(`schemas.VrmLinkStatusOut`) simply has no field a token could travel
through).

── Tenancy (PLAN_PHASE15.md §3.2) ──────────────────────────────────────────
Every handler below calls `tenancy.get_customer(body.customer_id)` first.
A mapping's target site is tenancy-checked by construction: an *existing*
site can only be found by `tenancy.find_customer_site()`, which is scoped to
`customer_id` from the start (the same guarantee `routers/ingest.py`'s
preview flow relies on for exactly the same reason) — there is no code path
here that can write to a site belonging to a different customer.

── Token handling ───────────────────────────────────────────────────────────
`body.token` lives in this module for exactly as long as one request/
job-scheduling call takes, is never logged, and is only ever passed to
`victron.vrm_remote.VrmRemoteClient` (which itself never logs it — see that
module's own docstring) or to `vrm_api.secrets.set_customer_vrm_token()`
(which stores it in Vault and never returns it). No response model in
`vrm_api/schemas.py` for this router has a field that could carry a token
back out.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from database.supabase_client import get_client

from victron import ingest as victron_ingest
from victron.vrm_remote import VrmRemoteAuthError, VrmRemoteClient

from vrm_api import secrets, tenancy
from vrm_api.deps import require_pipeline_key
from vrm_api.schemas import (
    VrmInstallationOut,
    VrmLinkConnectOut,
    VrmLinkConnectRequest,
    VrmLinkDisconnectOut,
    VrmLinkDisconnectRequest,
    VrmLinkSiteResult,
    VrmLinkSiteStatus,
    VrmLinkStatusOut,
    VrmLinkValidateOut,
    VrmLinkValidateRequest,
)
from vrm_api.tenancy import VrmAccountAlreadyLinked

logger = logging.getLogger("vrm_api.vrm_link")

router = APIRouter(prefix="/v1/vrm-link", tags=["vrm-link"],
                   dependencies=[Depends(require_pipeline_key)])

SCHEMA = "vrm"


def _t(name: str):
    return get_client().schema(SCHEMA).table(name)


def _whoami(token: str) -> tuple[str, str | None, dict]:
    """`GET /users/me` + `GET /users/{id}/installations` against the
    Victron VRM cloud — shared by `validate` and `connect` (§3.1 step 3:
    connect re-validates). Returns `(vrm_user_id, vrm_account_email,
    installations_body)`. Raises `HTTPException(400)` — a clean, customer-
    renderable error, not a 500 — if Victron rejects the token; any other
    `victron.vrm_remote` exception (rate-limited, unavailable, …) is left to
    propagate to `main.py`'s generic 500 handler, which already logs the
    real cause server-side without leaking it to the caller.
    """
    client = VrmRemoteClient(token)
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
        # A bad/expired/revoked token is a customer-facing 4xx, not a 500 —
        # PLAN_PHASE15.md §8 Step 4's own instruction. The exception's own
        # text is already token-free (vrm_remote.py's own rule), so it is
        # safe to surface verbatim server-side (logged, not returned).
        logger.info("vrm-link: Victron rejected a token for customer flow — %s", exc)
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_vrm_token",
                   "message": "Victron rejected this VRM personal access token."},
        ) from None
    return str(vrm_user_id), user.get("email"), installations


@router.post("/validate", response_model=VrmLinkValidateOut)
def post_validate(body: VrmLinkValidateRequest) -> VrmLinkValidateOut:
    tenancy.get_customer(body.customer_id)
    vrm_user_id, account_email, installations = _whoami(body.token)
    records = installations.get("records") or []
    return VrmLinkValidateOut(
        vrm_user_id=vrm_user_id,
        vrm_account_email=account_email,
        installations=[
            VrmInstallationOut(id_site=r["idSite"], name=r.get("name"),
                              identifier=r.get("identifier"))
            for r in records if isinstance(r, dict) and r.get("idSite") is not None
        ],
    )


@router.post("/connect", response_model=VrmLinkConnectOut)
def post_connect(body: VrmLinkConnectRequest) -> VrmLinkConnectOut:
    customer = tenancy.get_customer(body.customer_id)

    # §3.1 step 3: re-validate — the customer may have taken minutes to map,
    # and this is also where `valid_installation_ids` (below) comes from, so
    # a mapping can never name an installation this token doesn't actually
    # see.
    vrm_user_id, account_email, installations = _whoami(body.token)
    valid_installation_ids = {
        r["idSite"] for r in (installations.get("records") or [])
        if isinstance(r, dict) and r.get("idSite") is not None
    }

    # §1.5: a raw Postgres unique violation on vrm_user_id must never reach
    # the caller. A reconnect of the SAME customer's own already-connected
    # account is fine (and is in fact the normal "my token expired, here's a
    # new one" path) — only a DIFFERENT customer already holding this VRM
    # account is the typed conflict.
    other = tenancy.find_customer_by_vrm_user_id(vrm_user_id)
    if other and other["id"] != body.customer_id:
        raise VrmAccountAlreadyLinked(
            "This VRM account is already connected to another VRM Monitor account."
        )

    # Validate the WHOLE batch before writing anything — a later mapping
    # naming an installation this token can't see must not leave earlier
    # mappings half-applied.
    invalid = [m.vrm_installation_id for m in body.mappings
              if m.vrm_installation_id not in valid_installation_ids]
    if invalid:
        raise HTTPException(
            status_code=400,
            detail={"code": "installation_not_visible", "vrm_installation_id": invalid[0]},
        )

    # Nothing was written above this line (§3.1: "never write on the first
    # click" — connect's own re-check is the last gate before it does).
    secrets.set_customer_vrm_token(body.customer_id, body.token)
    (_t("customers").update({
        "vrm_user_id": vrm_user_id,
        "vrm_account_email": account_email,
    }).eq("id", body.customer_id).execute())

    results: list[VrmLinkSiteResult] = []
    for mapping in body.mappings:
        existing_site = tenancy.find_customer_site(body.customer_id, mapping.site_name_or_id)
        site_id = (existing_site["site_id"] if existing_site
                  else victron_ingest.make_site_id(customer["slug"], mapping.site_name_or_id))

        site_fields = mapping.site_fields.model_dump(exclude_none=True)
        display_name = site_fields.pop("display_name", None) or mapping.site_name_or_id
        # Not part of SiteFieldsIn's whitelist (schemas.py's own comment:
        # vrm_installation_id is "derived, not caller-set") — set here,
        # programmatically, the one place that's actually true.
        site_fields["vrm_installation_id"] = mapping.vrm_installation_id
        site_fields["source"] = "vrm_api"
        site_fields["vrm_sync_enabled"] = True

        victron_ingest.upsert_site(body.customer_id, site_id, display_name, **site_fields)
        results.append(VrmLinkSiteResult(
            vrm_installation_id=mapping.vrm_installation_id,
            site_id=site_id, site_is_existing=bool(existing_site),
        ))

    return VrmLinkConnectOut(vrm_user_id=vrm_user_id, vrm_account_email=account_email,
                             sites=results)


@router.post("/disconnect", response_model=VrmLinkDisconnectOut)
def post_disconnect(body: VrmLinkDisconnectRequest) -> VrmLinkDisconnectOut:
    tenancy.get_customer(body.customer_id)
    # Destroys the credential — deletes the Vault secret and stamps
    # vrm_token_revoked_at (vrm_api/secrets.py / migration 024's wrapper);
    # not reimplemented here.
    secrets.clear_customer_vrm_token(body.customer_id)
    # Telemetry is NEVER touched here — only the path this customer's FUTURE
    # data will arrive by. energy_daily/alarm_events/daily_health rows
    # already ingested stay exactly as they are (PLAN_PHASE15.md §3.1).
    reverted = (_t("sites").update({"source": "csv_upload", "vrm_sync_enabled": False})
               .eq("customer_id", body.customer_id).eq("source", "vrm_api")
               .execute().data or [])
    return VrmLinkDisconnectOut(sites_reverted=len(reverted))


@router.get("/status", response_model=VrmLinkStatusOut)
def get_status(customer_id: str = Query(...)) -> VrmLinkStatusOut:
    customer = tenancy.get_customer(customer_id)
    connected = bool(customer.get("vrm_token_secret_id")) and not customer.get("vrm_token_revoked_at")
    sites = (_t("sites")
            .select("site_id,display_name,vrm_last_synced_at,vrm_last_sync_error,vrm_sync_enabled")
            .eq("customer_id", customer_id).eq("source", "vrm_api")
            .execute().data or [])
    return VrmLinkStatusOut(
        connected=connected,
        vrm_account_email=customer.get("vrm_account_email") if connected else None,
        connected_since=customer.get("vrm_token_added_at") if connected else None,
        token_revoked_at=customer.get("vrm_token_revoked_at"),
        token_last_error=customer.get("vrm_token_last_error"),
        sites=[VrmLinkSiteStatus(**s) for s in sites],
    )
