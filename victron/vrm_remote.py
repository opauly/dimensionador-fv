from __future__ import annotations
"""
Standalone HTTP client for Victron's cloud VRM API — not this repo's own
`vrm_api/` FastAPI service (PLAN_PHASE15.md §0.4 names and keeps that
collision deliberately). Nothing in this codebase calls this module yet: it
is built in Step 2 so Step 3 (`victron/vrm_series.py`, a later step) has a
client to map Victron cloud data against. Facts cited below are the
empirically-confirmed findings of PLAN_PHASE15.md §0.2 (Step 0's real probe
against a live account), not guesses.

Auth: `X-Authorization: Token <token>` — exactly one space, never `Bearer`
(`Bearer` is for a password-login JWT this client never obtains; a personal
access token always uses `Token`).

Base URL: `VRM_REMOTE_BASE_URL` env var, default
`https://vrmapi.victronenergy.com/v2`.

Safety margins below are all self-imposed, because Victron's own rate-limit
shape is not fully confirmed (§0.2: "~200 requests, ~3 req/s refill" is a
planning assumption from community reports — Step 0's own probe sent 60
rapid requests and never observed a 429). Treat this client's own throttle as
the real safety margin regardless of what Victron's server actually does:
  - a pacer holding calls to <= `min_interval_s` apart (default 0.5 s, i.e.
    <=2 req/s) regardless of server behaviour;
  - exponential backoff with jitter on 429/5xx, honouring a `Retry-After`
    header when Victron sends one (§0.2: often absent — the backoff does not
    depend on it being there);
  - a hard per-instance request budget (`max_requests`) so a bug in a caller
    (e.g. an unbounded retry loop upstream, or a backfill job with a mis-set
    date range) cannot hammer Victron's API without limit;
  - a hard request timeout (`timeout_s`) on every call.

One `VrmRemoteClient` instance = one bounded budget for one run. Construct a
fresh one per sync (a later step's job runner will do this per customer sync
job), never as a long-lived singleton shared across runs — the budget is
meant to cap a single run's worst case, not a process's lifetime total.

── Token handling ──────────────────────────────────────────────────────────
This module follows the same non-negotiable rule `vrm_api/secrets.py` holds
for a token at rest, for a token in transit: never logged, in whole or in
part, and never present in any exception message this module raises. Every
request is made with a headers dict built immediately before the call and
discarded after; no code path below serializes `response.request.headers`,
the `Authorization`/`X-Authorization` header, or the `token` argument into a
message or a `logger.*` call — every raised exception's text names only the
HTTP method, path, and status code, never a header or a credential.

── Response-shape quirks confirmed live against a real account (§0.2) ──────
Both of the following are surfaced as-is by `get_stats()`, not "fixed" here —
normalising them in this transport-only client would hide real information
that only the mapper (Step 3) can correctly interpret:
  1. A requested attribute code with no data for that installation/window
     returns the literal JSON value `false`, not an empty list or `0`.
     `get_stats()`'s return value can therefore contain a series that is the
     Python value `False` instead of a list — callers MUST check
     `isinstance(series, list)` before indexing into a `records` entry, never
     assume every returned series is list-shaped.
  2. At least one code (`bs`, system-service battery SOC) returns 4-element
     points `[epoch_ms, v, v, v]` instead of the usual 2-element
     `[epoch_ms, v]` — likely a min/max/avg aggregation Victron applies to
     some "system" instance codes but not "custom" ones. This client does
     not special-case any code; whichever shape Victron returns for a given
     code is what `get_stats()` returns.
"""
import logging
import os
import random
import time

import requests

logger = logging.getLogger("victron.vrm_remote")

DEFAULT_BASE_URL = "https://vrmapi.victronenergy.com/v2"
DEFAULT_TIMEOUT_S = 30.0
DEFAULT_MAX_REQUESTS_PER_RUN = 500
DEFAULT_MIN_INTERVAL_S = 0.5  # <=2 req/s self-imposed pacer
DEFAULT_MAX_RETRIES = 5
DEFAULT_BACKOFF_BASE_S = 1.0
DEFAULT_BACKOFF_MAX_S = 30.0


class VrmRemoteError(Exception):
    """Base class for this module's errors. Every subclass below is
    constructed with only an HTTP method/path/status code — never with
    request headers or a token value. See the module docstring."""


class VrmRemoteAuthError(VrmRemoteError):
    """Victron rejected the token (401/403 on any call)."""


class VrmRemoteRateLimited(VrmRemoteError):
    """Victron returned 429 and either the retry budget (`max_retries`) or
    the per-instance request budget (`max_requests`) was exhausted before a
    successful response came back."""


class VrmRemoteNotFound(VrmRemoteError):
    """Victron returned 404 — the installation/site id does not exist, or
    exists but is not visible to this token."""


class VrmRemoteUnavailable(VrmRemoteError):
    """Anything else that prevented a usable response: a 5xx after retries
    were exhausted, a network error, a request timeout, or a response body
    that didn't parse as JSON."""


class VrmRemoteBudgetExceeded(VrmRemoteError):
    """The per-instance request budget (`max_requests`) was already
    exhausted before this call could be attempted at all (as opposed to
    being exhausted while retrying a 429/5xx — that raises
    `VrmRemoteRateLimited`/`VrmRemoteUnavailable` instead, so a caller can
    tell "we never got a real answer" apart from "Victron kept failing")."""


class VrmRemoteClient:
    """Thin, paced, budgeted HTTP client for Victron's cloud VRM API.

    `token` is held only as an instance attribute for the lifetime of this
    client and used solely to build the `X-Authorization` header immediately
    before each request — see the module docstring's token-handling rules
    before extending this class.
    """

    def __init__(self, token: str, *, base_url: str | None = None,
                 timeout_s: float = DEFAULT_TIMEOUT_S,
                 max_requests: int = DEFAULT_MAX_REQUESTS_PER_RUN,
                 min_interval_s: float = DEFAULT_MIN_INTERVAL_S,
                 max_retries: int = DEFAULT_MAX_RETRIES,
                 backoff_base_s: float = DEFAULT_BACKOFF_BASE_S,
                 backoff_max_s: float = DEFAULT_BACKOFF_MAX_S,
                 session: requests.Session | None = None) -> None:
        if not token:
            raise ValueError("token is required")
        self._token = token
        self.base_url = (base_url or os.environ.get("VRM_REMOTE_BASE_URL")
                          or DEFAULT_BASE_URL).rstrip("/")
        self.timeout_s = timeout_s
        self.max_requests = max_requests
        self.min_interval_s = min_interval_s
        self.max_retries = max_retries
        self.backoff_base_s = backoff_base_s
        self.backoff_max_s = backoff_max_s
        self._session = session or requests.Session()
        self._requests_made = 0
        self._last_request_at: float | None = None

    @property
    def requests_made(self) -> int:
        """Total requests attempted so far this instance's lifetime,
        including ones that came back 429/5xx and were retried — for a
        caller (or a test) to confirm the budget is actually being
        enforced."""
        return self._requests_made

    # -- internals ------------------------------------------------------

    def _pace(self) -> None:
        """Self-imposed <= `min_interval_s`-per-request throttle, independent
        of anything Victron's server does or doesn't enforce."""
        if self._last_request_at is None:
            return
        elapsed = time.monotonic() - self._last_request_at
        remaining = self.min_interval_s - elapsed
        if remaining > 0:
            time.sleep(remaining)

    def _headers(self) -> dict:
        # Built fresh immediately before each call, never stored or logged.
        return {"X-Authorization": f"Token {self._token}"}

    def _sleep_backoff(self, attempt: int, retry_after: str | None) -> float:
        if retry_after:
            try:
                delay = float(retry_after)
            except ValueError:
                delay = self._exp_backoff(attempt)
        else:
            delay = self._exp_backoff(attempt)
        time.sleep(delay)
        return delay

    def _exp_backoff(self, attempt: int) -> float:
        base = min(self.backoff_base_s * (2 ** (attempt - 1)), self.backoff_max_s)
        return base * (0.5 + random.random())  # jitter: 0.5x-1.5x of base

    def _request(self, method: str, path: str, *, params: dict | None = None) -> dict:
        url = f"{self.base_url}{path}"
        attempt = 0
        while True:
            if self._requests_made >= self.max_requests:
                raise VrmRemoteBudgetExceeded(
                    f"Request budget of {self.max_requests} exhausted before "
                    f"{method} {path} could be attempted."
                )
            self._pace()
            self._requests_made += 1
            self._last_request_at = time.monotonic()
            try:
                response = self._session.request(
                    method, url, headers=self._headers(), params=params,
                    timeout=self.timeout_s,
                )
            except requests.exceptions.Timeout:
                raise VrmRemoteUnavailable(
                    f"Timed out calling Victron VRM API ({method} {path})."
                ) from None
            except requests.exceptions.RequestException:
                raise VrmRemoteUnavailable(
                    f"Network error calling Victron VRM API ({method} {path})."
                ) from None

            if response.status_code in (401, 403):
                raise VrmRemoteAuthError(
                    f"Victron VRM API rejected the token "
                    f"({response.status_code} on {method} {path})."
                )
            if response.status_code == 404:
                raise VrmRemoteNotFound(f"Not found: {method} {path}.")

            if response.status_code == 429 or response.status_code >= 500:
                attempt += 1
                budget_left = self._requests_made < self.max_requests
                if attempt > self.max_retries or not budget_left:
                    logger.warning(
                        "Victron VRM API %s for %s %s; retry budget exhausted "
                        "(attempt=%s, max_retries=%s, requests_made=%s, max_requests=%s).",
                        response.status_code, method, path, attempt,
                        self.max_retries, self._requests_made, self.max_requests,
                    )
                    if response.status_code == 429:
                        raise VrmRemoteRateLimited(
                            f"Victron VRM API rate-limited {method} {path} "
                            "and the retry budget was exhausted."
                        )
                    raise VrmRemoteUnavailable(
                        f"Victron VRM API returned {response.status_code} for "
                        f"{method} {path} and the retry budget was exhausted."
                    )
                delay = self._sleep_backoff(attempt, response.headers.get("Retry-After"))
                logger.warning(
                    "Victron VRM API %s for %s %s; retrying (attempt %s/%s) after %.1fs.",
                    response.status_code, method, path, attempt, self.max_retries, delay,
                )
                continue

            if not response.ok:
                raise VrmRemoteUnavailable(
                    f"Victron VRM API returned {response.status_code} for {method} {path}."
                )

            try:
                return response.json()
            except ValueError:
                raise VrmRemoteUnavailable(
                    f"Victron VRM API returned a non-JSON response for {method} {path}."
                ) from None

    # -- public surface ---------------------------------------------------

    def get_me(self) -> dict:
        """`GET /users/me` -> the authenticated account.

        Real response shape, confirmed live (§0.2 — corrects migration 012's
        original guess): `{success, user: {id, name, email, country,
        idAccessToken, accessLevel}}`. The user id is `user["id"]`, not a
        top-level `idUser`.
        """
        return self._request("GET", "/users/me")

    def list_installations(self, id_user, *, extended: bool = True) -> dict:
        """`GET /users/{id_user}/installations` -> every installation this
        token can see.

        §0.2: a personal access token grants access to every installation on
        the account, including ones merely *shared with* it, not only ones
        it owns — never assume the caller only gets back installations they
        expect. Response: `{success, records: [...]}`, each record carrying
        `idSite`, `name`, `identifier`, `timezone`.
        """
        params = {"extended": 1} if extended else None
        return self._request("GET", f"/users/{id_user}/installations", params=params)

    def get_diagnostics(self, id_site) -> dict:
        """`GET /installations/{id_site}/diagnostics` -> the live list of
        attributes this specific installation actually publishes (each with
        `code`, `idDataAttribute`, `description`, `formatWithUnit`,
        `dbusServiceType`, `instance`). This is Victron's documented
        discovery endpoint — the mapper (Step 3) runs this first to find
        which codes a given installation exposes before requesting `stats`
        for them.
        """
        return self._request("GET", f"/installations/{id_site}/diagnostics")

    def get_stats(self, id_site, *, type, interval, start, end,
                  attribute_codes: list[str] | None = None,
                  show_instance: bool = False) -> dict:
        """`GET /installations/{id_site}/stats`.

        `start`/`end` are epoch seconds. `type` is one of Victron's stats
        types (`venus`, `live_feed`, `consumption`, `kwh`, `solar_yield`,
        `forecast`, `custom`); with `type="custom"`, `attribute_codes`
        becomes repeated `attributeCodes[]` query params. `interval` accepts
        at least `15mins`, `hours`, `days` (§0.2: `15mins` confirmed to
        return real, gapless data for a 24h window; longer-horizon retention
        at 15-min resolution was not tested by Step 0).

        `show_instance` — documented parameter (confirmed live 2026-09-01
        against Victron's own OpenAPI spec at vrm-api-docs.victronenergy.com,
        Commands/Installation/docs/StatsCommand.yaml), NOT the same as
        passing `instance` as a plain query param (silently ignored — tested
        live, returns the same ambiguous merged series every time). When
        `True`, `records`/`totals` become a LIST of `{instance, stats}`/
        `{instance, totals}` objects instead of one flat dict — this is the
        only way to separate a code like `PVP` that exists on more than one
        physical device (see `victron/vrm_live.py`'s module docstring for
        why that ambiguity exists and what it's used for).

        Returns `{records: {...}, totals: {...}}` exactly as Victron sent
        it — see the module docstring for the two response-shape quirks
        every caller must handle itself (a no-data code returning the
        literal `False`, and at least one code returning 4-element points).
        """
        params = {"type": type, "interval": interval, "start": start, "end": end}
        if attribute_codes:
            params["attributeCodes[]"] = attribute_codes
        if show_instance:
            params["show_instance"] = "true"
        return self._request("GET", f"/installations/{id_site}/stats", params=params)
