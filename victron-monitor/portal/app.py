"""VRM Monitor customer portal — entry point.

Second, separate Streamlit application living alongside the internal
Pauly&Co tool (repo-root `app.py` + `pages/`), which this file — and
everything it imports — must never modify. See PLAN_PHASE13.md for the
full design; no `pages/` directory exists next to this file on purpose
(Streamlit auto-discovers one and would pull the entire internal app into
this portal's sidebar — navigation here is declared explicitly below).

Run from the REPO ROOT (not from victron-monitor/portal/) so
`.streamlit/config.toml` (the 200 MB upload cap) and `load_dotenv()` both
resolve against the right directory:

    streamlit run victron-monitor/portal/app.py
"""
from __future__ import annotations

import pathlib
import sys

# Streamlit puts the *entry script's own folder* on sys.path[0] — not the
# CWD, not the repo root. That folder is victron-monitor/portal/ here, so
# `from victron import ...` / `from vrm_portal import ...` fail without
# this. Must run before any repo-root import below. (§1.6, load-bearing.)
_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from vrm_portal import auth  # noqa: E402
from vrm_portal.strings import t  # noqa: E402
from vrm_portal.views import login  # noqa: E402

st.set_page_config(
    page_title="VRM Monitor",
    page_icon="\U0001f4e1",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _handle_activation_link() -> bool:
    """Handles the `?token_hash=...&type=invite|recovery` deep link from an
    invite/recovery email (§1.9): verify_otp -> "set your password" ->
    stamp activated_at -> clear the query params -> drop into the normal
    logged-in flow.

    Stubbed for Step 1 — always returns False, so the ordinary login screen
    always runs. Built out in Step 5 alongside the invite flow it exists to
    serve; left as an explicit stub (not omitted) so app.py's call order
    below — activation check BEFORE the session branch — is already correct
    and doesn't need reshuffling once Step 5 lands.
    """
    return False


def _placeholder_home(session: auth.Session) -> None:
    """Temporary landing page for Step 1 validation only: proves sign-in +
    role resolution work end to end before any real dashboard exists.
    Replaced in Steps 3-5 by the real role-gated navigation from §1.7
    ({"Admin": [...]} for session.role == "admin", {"VRM Monitor": [...]}
    otherwise) — this function and its st.Page wiring below both go away
    then, not just get more content added to them.
    """
    st.markdown(f"### {t(session.ui_language, 'signed_in_as').format(email=session.email)}")
    st.write(f"Role: `{session.role}`")
    st.write(f"Customer ID: `{session.customer_id or '—'}`")
    if st.button(t(session.ui_language, "log_out")):
        auth.sign_out()
        st.rerun()


def main() -> None:
    if _handle_activation_link():
        return

    session = auth.current_session()

    if session is None:
        pages = [st.Page(login.render, title="Log in", default=True)]
    else:
        # Step 1 has no real customer/admin views yet — both roles land on
        # the same placeholder page below.
        pages = [
            st.Page(lambda: _placeholder_home(session), title="Home", default=True)
        ]

    st.navigation(pages).run()


main()
