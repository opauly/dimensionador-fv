"""VRM Monitor portal — authentication, session, and role resolution.

THE TWO-CLIENT RULE (PLAN_PHASE13.md §1.2) — this module is the only place
in the codebase allowed to call anything under `.auth`:

    get_client()   (database/supabase_client.py) -> service_role singleton,
                   used for ALL data access across both this app and the
                   internal one. NEVER call `.auth.*` on it.
    auth_client()  (below) -> a FRESH anon-key client, created per call.
                   Auth only. NEVER call `.table()`/`.schema()` on it.
    admin_client() (below) -> a FRESH service_role-keyed client, created per
                   call, for `auth.admin.*` calls (invite/generate_link/
                   update_user_by_id). A SEPARATE instance from get_client()
                   even though both hold the same key.

Why this matters, concretely: supabase-py resets a client's PostgREST auth
header to the signed-in user's access token on SIGNED_IN/TOKEN_REFRESHED/
SIGNED_OUT (verified: `supabase/_sync/client.py:_listen_to_auth_events`,
`.venv/.../supabase/_sync/client.py:334-341`). `get_client()` is a
process-wide singleton shared by every caller — including Oscar's own admin
data reads. Signing a user in on it would silently re-scope every other
caller's next query to that user's token. A fresh client per auth
operation sidesteps this entirely: nothing else in the app holds a
reference to it, so there is nothing to accidentally re-scope.

This module also does the one data read role-resolution needs (looking up a
customer by `auth_user_id`) via `get_client()` — that's a plain
`.schema("vrm").table("customers").select(...)` call, not an `.auth` call,
so it does not violate the rule above.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, replace

import streamlit as st
from supabase import Client, create_client

from database.supabase_client import get_client
from vrm_portal.strings import t

_SESSION_KEY = "vrm_portal_session"

# Refresh the underlying Supabase session once it's within this many seconds
# of expiring (§1.10) — cheap insurance against a dashboard left open long
# enough that its next auth-touching action would otherwise fail.
_REFRESH_MARGIN_SECONDS = 60


class NotLinked(Exception):
    """Raised when an authenticated Supabase user has no active link to a
    `vrm.customers` row and isn't flagged as admin via `app_metadata`
    (§1.5, step 3). `sign_in()` always signs the user back out before
    raising this — never a partially-authenticated state."""


@dataclass(frozen=True)
class Session:
    """The portal's notion of "who is signed in", held in
    `st.session_state` — nothing here is persisted across a hard browser
    refresh (§1.10, accepted for V1)."""

    role: str  # "admin" | "customer"
    customer_id: str | None
    user_id: str
    email: str
    # "es" for admin sessions (admin views are always Spanish); the
    # customer's own vrm.customers.ui_language otherwise (§0.3 Q2).
    ui_language: str
    access_token: str
    refresh_token: str
    expires_at: int | None


def auth_client() -> Client:
    """A brand-new anon-key client. See the module docstring for why this
    must never be `get_client()` and must never be reused across calls."""
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_ANON_KEY"]
    return create_client(url, key)


def admin_client() -> Client:
    """A service_role-keyed client for `auth.admin.*` calls only (invite/
    generate_link/update_user_by_id — Step 5). Deliberately a separate
    instance from `get_client()`, even though both hold the service_role
    key, so a bug in this module's auth handling can never bleed into the
    data-access singleton's auth state."""
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return create_client(url, key)


def resolve_role(user) -> tuple[str, str | None]:
    """Implements §1.5's role-resolution order exactly:

      1. `app_metadata.vrm_role == "admin"` -> ("admin", None).
      2. Else look up `vrm.customers` by `auth_user_id`; must also be
         `active` -> ("customer", customer_id).
      3. Else raise NotLinked -- an inactive customer gets the same clean
         rejection as an unlinked one (§1.5: "same clean rejection").

    `user` is the `supabase_auth.types.User` returned directly by
    `sign_in_with_password()` — `app_metadata` comes back on that response,
    so this never needs a second round-trip for the admin case.
    """
    if (user.app_metadata or {}).get("vrm_role") == "admin":
        return "admin", None

    rows = (
        get_client().schema("vrm").table("customers")
        .select("id, active")
        .eq("auth_user_id", user.id)
        .limit(1)
        .execute()
        .data
    )
    if rows and rows[0]["active"]:
        return "customer", rows[0]["id"]
    raise NotLinked(t("en", "not_linked_error"))


def _customer_ui_language(customer_id: str) -> str:
    rows = (
        get_client().schema("vrm").table("customers")
        .select("ui_language")
        .eq("id", customer_id)
        .limit(1)
        .execute()
        .data
    )
    return (rows[0]["ui_language"] if rows else None) or "en"


def sign_in(email: str, password: str) -> Session:
    """Signs in against a fresh anon client, resolves the role, and — only
    if that resolution succeeds — stores the result in `st.session_state`.
    Raises `NotLinked` (account has nowhere to land) or whatever
    `supabase_auth` raises for bad credentials (caught by the login view
    and shown as one generic message — never "no such user" vs. "wrong
    password", which is exactly what an account-enumeration attack goes
    looking for)."""
    client = auth_client()
    response = client.auth.sign_in_with_password(
        {"email": email, "password": password}
    )
    user, supa_session = response.user, response.session
    if user is None or supa_session is None:
        raise RuntimeError("Sign-in did not return a session.")

    try:
        role, customer_id = resolve_role(user)
    except NotLinked:
        # The Supabase auth call above already succeeded — undo it before
        # surfacing the rejection, so a user who can't use the portal is
        # never left holding a live (if useless) auth session (§1.5).
        try:
            client.auth.sign_out()
        except Exception:  # noqa: BLE001 — best effort only; we're already
            pass            # raising NotLinked regardless of this outcome.
        raise

    ui_language = "es" if role == "admin" else _customer_ui_language(customer_id)

    portal_session = Session(
        role=role,
        customer_id=customer_id,
        user_id=user.id,
        email=user.email or email,
        ui_language=ui_language,
        access_token=supa_session.access_token,
        refresh_token=supa_session.refresh_token,
        expires_at=supa_session.expires_at,
    )
    st.session_state[_SESSION_KEY] = portal_session
    return portal_session


def sign_out() -> None:
    """Drops the local session immediately (this is what actually logs the
    user out of the portal) and best-effort invalidates it remotely on a
    fresh client carrying this session's tokens — never on the singleton."""
    session: Session | None = st.session_state.pop(_SESSION_KEY, None)
    if session is None:
        return
    try:
        client = auth_client()
        client.auth.set_session(session.access_token, session.refresh_token)
        client.auth.sign_out()
    except Exception:  # noqa: BLE001
        pass


def current_session() -> Session | None:
    """Returns the signed-in session, or None if nobody is signed in.

    Proactively refreshes the underlying Supabase session when it's within
    `_REFRESH_MARGIN_SECONDS` of expiring (§1.10). If the refresh itself
    fails (e.g. the refresh token was revoked), the stale session is
    dropped and this returns None — the caller falls back to the login
    screen rather than proceeding on a session Supabase will reject anyway.
    """
    session: Session | None = st.session_state.get(_SESSION_KEY)
    if session is None:
        return None

    if (
        session.expires_at is not None
        and time.time() > session.expires_at - _REFRESH_MARGIN_SECONDS
    ):
        try:
            client = auth_client()
            response = client.auth.refresh_session(session.refresh_token)
            new_supa_session = response.session
            if new_supa_session is None:
                raise RuntimeError("refresh_session returned no session")
            session = replace(
                session,
                access_token=new_supa_session.access_token,
                refresh_token=new_supa_session.refresh_token,
                expires_at=new_supa_session.expires_at,
            )
            st.session_state[_SESSION_KEY] = session
        except Exception:  # noqa: BLE001
            st.session_state.pop(_SESSION_KEY, None)
            return None

    return session


def require_admin() -> Session:
    """First statement of every `views/admin_*.py` render function. UI-level
    navigation gating (§1.7) is convenience, not the control — this is."""
    session = current_session()
    if session is None:
        st.error(t("es", "please_log_in"))
        st.stop()
    if session.role != "admin":
        st.error(t("es", "not_authorized"))
        st.stop()
    return session


def require_customer() -> Session:
    """First statement of every `views/customer_*.py` render function."""
    session = current_session()
    if session is None:
        st.error(t("en", "please_log_in"))
        st.stop()
    if session.role != "customer":
        st.error(t(session.ui_language, "not_authorized"))
        st.stop()
    return session
