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

── `require_public_tariff_key` — a second, narrower key ───────────────────
`routers/public_tariffs.py` is this service's one deliberate exception to
"exactly one caller" (see `main.py`'s module docstring): an external tool
(Claude Design, building maintenance-report savings tables) needs to read
public ARESEP tariff rates live instead of a human retyping them by hand
each time. `PUBLIC_TARIFF_API_KEY` is a *separate* secret from
`PIPELINE_API_KEY` specifically so that key can leak to that external tool
without granting it anything else this API can do — ingestion, billing,
customer data. Same timing-safe comparison, same undifferentiated-401
reasoning as `require_pipeline_key` above; kept as a distinct function
rather than a parameterised one so a future edit to the pipeline key's
checks doesn't silently also change what the public route accepts.
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


def require_public_tariff_key(authorization: str | None = Header(default=None)) -> None:
    """FastAPI dependency — raises 401 unless the bearer token matches
    `PUBLIC_TARIFF_API_KEY`. Wired only onto `routers/public_tariffs.py`; see
    that env var's own key material and this module's docstring above for
    why it is deliberately not `PIPELINE_API_KEY`."""
    expected = os.environ.get("PUBLIC_TARIFF_API_KEY", "")
    provided = ""
    if authorization and authorization.startswith(_BEARER_PREFIX):
        provided = authorization[len(_BEARER_PREFIX):]

    ok = bool(expected) and hmac.compare_digest(provided, expected)
    if not ok:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="")
