from __future__ import annotations
"""
Bearer-token auth for `vrm_api` (PLAN_PHASE14.md §1.3).

Every route except `GET /health` requires `Authorization: Bearer
<PIPELINE_API_KEY>`, a long random secret that lives only in this service's
env and the Next.js server's env — never in a browser, never in a repo. It is
NOT a Supabase key: it authenticates "this request came from our own Next.js
server," a separate fact from "this Supabase credential is valid."

Comparison uses `hmac.compare_digest`, never `==`. A naive `==` on strings of
different lengths short-circuits at the first mismatched byte, which leaks —
one HTTP timing measurement at a time — how many leading characters of a
guessed token were right. `compare_digest` is written to take the same time
regardless of where (or whether) the strings differ.

Missing token and wrong token both raise the same 401 with no body detail
(`HTTPException(status_code=401)` — FastAPI's default handler serialises
that to `{"detail": null}`): a caller must not be able to tell "no
Authorization header" apart from "wrong key," which is one less bit of
information towards guessing the real one.
"""
import hmac
import os

from fastapi import Header, HTTPException, status

_BEARER_PREFIX = "Bearer "


def require_pipeline_key(authorization: str | None = Header(default=None)) -> None:
    """FastAPI dependency — raises 401 unless the bearer token matches
    `PIPELINE_API_KEY`. Wired onto every router except `meta`'s `/health`
    route (that one is registered directly on `app`, with no dependency)."""
    expected = os.environ.get("PIPELINE_API_KEY", "")
    provided = ""
    if authorization and authorization.startswith(_BEARER_PREFIX):
        provided = authorization[len(_BEARER_PREFIX):]

    # An empty/unset PIPELINE_API_KEY must never be treated as "anything
    # matches" — compare_digest("", "") is True, which would otherwise turn
    # a missing env var into an open door instead of a hard failure.
    ok = bool(expected) and hmac.compare_digest(provided, expected)
    if not ok:
        # detail="" rather than the default None: Starlette's HTTPException
        # fills in the status phrase ("Unauthorized") when detail is None,
        # which is harmless but is still one more string in the body than
        # "no detail" promises. Empty string keeps the body
        # `{"detail": ""}` — identical for a missing header and a wrong one.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="")
