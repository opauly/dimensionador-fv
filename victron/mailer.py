from __future__ import annotations
"""
Generic Resend wrapper — PLAN_PHASE14.md §1.9 / §2 Step 7.

Deliberately has NO invite-specific logic: no template rendering, no
`vrm.customers` writes, no knowledge of `type=invite` vs `type=recovery`.
Just `send(to, subject, html, ...)` against Resend's HTTP API. That is what
lets Phase 12 (scheduled report emails, Python-side, not yet built) import
this module unchanged later — whichever phase landed first was always going
to write this exact function (PLAN_PHASE14.md §1.9's own framing).

── Why this module is not what actually sends a Phase 14 invite email ──────
`victron-monitor/web` (Next.js) and this process are separate runtimes with
no shared Python interpreter — `lib/server/invites.ts` cannot `import` this
file. Phase 14 Step 7 resolved that by giving `invites.ts` its own
lightweight Resend HTTP client in TypeScript (see that file's header comment
for the full reasoning): sending a transactional email is one HTTP POST, and
round-tripping it through `vrm_api` would have made that service responsible
for something PLAN_PHASE14.md §1.3 deliberately keeps out of its scope
(ingest/report/meta only). This module exists anyway, now, because the plan
asks for it by name as a Step 7 deliverable and because Phase 12's scheduled
report emails DO run Python-side and will need exactly this.

── Why `requests`, not `urllib.request` (unlike victron/weekly_report.py's weather call) ──
`weekly_report.py` uses `urllib.request` for a single unauthenticated GET.
This module needs a JSON POST with a bearer header and structured error
handling — `requests` (already pinned in requirements.txt, already the
convention `calculations/pvgis.py` uses for exactly this shape of call) is
the better fit; reaching for `urllib.request` here would just be
re-implementing header/JSON handling `requests` already does correctly.
"""
import logging
import os

import requests

logger = logging.getLogger("victron.mailer")

RESEND_API_URL = "https://api.resend.com/emails"
_TIMEOUT_S = 15


class MailerError(Exception):
    """Raised on any failure to hand the email to Resend — a non-2xx
    response, a network error, or a missing API key. Callers get one typed
    exception to catch, never a raw `requests` exception or Resend's own
    error body shape (which is not this module's contract to expose)."""


def send(to: str, subject: str, html: str, from_: str | None = None,
         reply_to: str | None = None,
         attachments: list[dict[str, str]] | None = None) -> str:
    """Sends one email via Resend. Returns Resend's message id on success.

    `from_` defaults to `PORTAL_FROM_EMAIL` (env) — the shared "reports@" /
    "info@" sender this repo's transactional email already comes from
    (`.env.example`'s own comment: "Resend (email provider for invites/
    re-sends/password resets — and, once Phase 12 lands, weekly report
    delivery too)"). Passing `from_` explicitly is for a future caller that
    needs a different sender identity, not something invites need today.

    `attachments` (PLAN_PHASE17.md §8 Step 8, additive — every existing
    caller passes nothing and gets exactly today's behaviour): a list of
    `{"filename": ..., "content": <base64-encoded bytes>}` dicts, Resend's
    own documented shape. `vrm_api/report_delivery.py` is the only caller
    that ever passes one (the rendered report PDF) — base64-encoding is
    that caller's job, not this function's, so this module stays a thin,
    content-agnostic wrapper.
    """
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        raise MailerError("RESEND_API_KEY is not set.")
    sender = from_ or os.environ.get("PORTAL_FROM_EMAIL")
    if not sender:
        raise MailerError("No sender address: pass from_ or set PORTAL_FROM_EMAIL.")

    payload: dict[str, object] = {
        "from": sender,
        "to": [to],
        "subject": subject,
        "html": html,
    }
    if reply_to:
        payload["reply_to"] = reply_to
    if attachments:
        payload["attachments"] = attachments

    try:
        resp = requests.post(
            RESEND_API_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=_TIMEOUT_S,
        )
    except requests.RequestException as exc:
        # Never let the underlying exception (which can carry the request
        # URL/headers in its repr) propagate — see the module docstring's
        # "never log a token_hash, a password, or a full email-send payload"
        # convention, restated here for the network-failure path too.
        logger.exception("Resend request failed for %s", to)
        raise MailerError("Could not reach Resend.") from exc

    if resp.status_code >= 400:
        # Resend's error body can legitimately include the caller's own
        # payload details (e.g. a malformed "to" address) — safe to log at
        # this layer (server-side only, never returned to a browser), but
        # never included in the exception message a caller might surface
        # further up without thinking about where it ends up.
        logger.warning("Resend rejected an email to %s: %s %s", to, resp.status_code, resp.text)
        raise MailerError(f"Resend rejected the email ({resp.status_code}).")

    data = resp.json()
    message_id = data.get("id", "")
    logger.info("Sent email to %s via Resend (id=%s)", to, message_id)
    return message_id
