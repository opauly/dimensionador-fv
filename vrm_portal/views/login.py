"""VRM Monitor portal — login screen.

Rendered by `st.navigation` (victron-monitor/portal/app.py) whenever there
is no session in `st.session_state`. Always in English — the portal's
default UI language (PLAN_PHASE13.md §0.3 Q2) — because a customer's own
`ui_language` preference isn't known until after they've signed in and
their `vrm.customers` row has been resolved (`vrm_portal.auth.sign_in`).
"""
from __future__ import annotations

import streamlit as st
from supabase_auth.errors import AuthError

from vrm_portal import auth
from vrm_portal.strings import t

_LANG = "en"


def render() -> None:
    st.markdown(f"## {t(_LANG, 'login_title')}")
    st.caption(t(_LANG, "login_subtitle"))

    with st.form("vrm_portal_login"):
        email = st.text_input(t(_LANG, "login_email"))
        password = st.text_input(t(_LANG, "login_password"), type="password")
        submitted = st.form_submit_button(t(_LANG, "login_submit"), type="primary")

    if submitted:
        if not email.strip() or not password:
            st.error(t(_LANG, "login_missing_fields"))
        else:
            try:
                auth.sign_in(email.strip(), password)
            except auth.NotLinked:
                # §1.5 step 3: sign_in() has already signed the underlying
                # auth user back out before raising this — never a
                # partially-authenticated state.
                st.error(t(_LANG, "not_linked_error"))
            except AuthError:  # noqa: BLE001 — deliberately generic: never
                # distinguish "no such user" from "wrong password" here,
                # that difference is exactly what an account-enumeration
                # attack goes looking for. Only Supabase's own auth errors
                # (bad credentials, rate-limited, etc.) get this generic
                # copy — anything else (e.g. SUPABASE_ANON_KEY missing from
                # the environment) is a real bug/misconfiguration and should
                # look like one, not like a wrong password, or a broken
                # local setup becomes very hard to tell apart from a typo.
                st.error(t(_LANG, "login_error"))
            else:
                st.rerun()

    # Inert until Step 5 wires up generate_link(type="recovery") (§1.8).
    # Present now so the login screen's layout doesn't shift once it works.
    if st.button(t(_LANG, "login_forgot_password"), type="tertiary"):
        st.info(t(_LANG, "login_forgot_password_inert"))
