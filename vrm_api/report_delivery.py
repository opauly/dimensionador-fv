from __future__ import annotations
"""
Scheduled-report email delivery (PLAN_PHASE17.md §8 Step 8).

Only ever called from `vrm_api/routers/reports.py:post_run_due()`'s `done`
branch. A report a customer generates on demand ("Generate" in the portal)
already shows a download button immediately — there is no separate email
pass for that path, and none should be added: PLAN_PHASE17.md §3.8 states
this exactly ("email happens inside the report run, not as a separate
pass, so a rendered-but-unsent report is not a state that can exist") for
the scheduled path specifically, and a manual on-demand report has no
`vrm.report_runs` row to record `email_status` against in the first place
(only `run-due`'s own `report_runs.claim_period()` ever creates one).

**Never raises.** "A delivery failure must never lose the report" (the
plan's own words, §8 Step 8's validate list) — the PDF is already in
Storage and `vrm.report_runs.status` is already `'done'` by the time this
module runs; only `email_status`/`recipients` on that row reflect what
happened here. Every `MailerError` is caught and logged, never propagated.
"""
import base64
import hashlib
import hmac
import logging
import os
import re

from jinja2 import Environment, FileSystemLoader, select_autoescape

from victron.mailer import MailerError
from victron.mailer import send as mailer_send

logger = logging.getLogger("vrm_api.report_delivery")

# PLAN_PHASE17.md §0.6 Q5 — Oscar's decision, 2026-08-25: third-party
# recipients allowed, capped at 5 per site. Enforced here defensively (the
# database value is never trusted alone) AND independently on the write
# path (`victron-monitor/web/lib/server/db/sites.ts`'s own cap) — the same
# "hide an editor is UX, never the control" shape every other Phase 17 gate
# uses, restated for a numeric limit instead of a boolean one.
MAX_RECIPIENTS = 5

# Loose, display-string-shaped validation — this is a Resend API argument,
# not an RFC-5322 parser; a value already in the database that doesn't even
# look like an email must not become a Resend rejection that aborts email
# for every OTHER recipient of the same run.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "victron", "templates")
_env = Environment(loader=FileSystemLoader(_TEMPLATE_DIR), autoescape=select_autoescape(["html"]))


def resolve_recipients(site: dict, customer: dict) -> list[str]:
    """`vrm.sites.report_recipients` (explicit third-party addresses, capped
    at write time — re-capped and re-validated here regardless) -> else the
    customer's own `contact_email` -> else `auth_email` -> else nothing.
    Never returns more than `MAX_RECIPIENTS`, never returns a value that
    doesn't look like an email."""
    explicit = [e for e in (site.get("report_recipients") or []) if isinstance(e, str) and _EMAIL_RE.match(e)]
    if explicit:
        return explicit[:MAX_RECIPIENTS]
    if customer.get("contact_email") and _EMAIL_RE.match(customer["contact_email"]):
        return [customer["contact_email"]]
    if customer.get("auth_email") and _EMAIL_RE.match(customer["auth_email"]):
        return [customer["auth_email"]]
    return []


def _unsubscribe_secret() -> bytes | None:
    secret = os.environ.get("REPORT_UNSUBSCRIBE_SECRET")
    return secret.encode() if secret else None


def make_unsubscribe_token(site_id: str, email: str) -> str | None:
    """A signed, stateless token proving "whoever holds this link was sent
    this exact email at this exact site" — verified independently by
    `victron-monitor/web`'s own `/unsubscribe` route (a DIFFERENT process,
    DIFFERENT language; the signature is the only thing they share, via the
    SAME `REPORT_UNSUBSCRIBE_SECRET` value in both runtimes' env, the same
    cross-runtime-shared-secret shape `PIPELINE_API_KEY` already uses).
    Returns `None` if the secret isn't configured — the caller's job to
    treat that as "no unsubscribe link this send," not to guess a value.
    Never embeds anything an attacker could use for something other than
    unsubscribing this one (site_id, email) pair — no customer id, no
    admin capability, nothing else in `vrm.sites` reachable from it."""
    secret = _unsubscribe_secret()
    if secret is None:
        return None
    payload = f"{site_id}:{email}"
    sig = hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}:{sig}".encode()).decode().rstrip("=")


# PLAN_PHASE17.md §4.3/Q8 — fixed, semantic thresholds, ported unchanged
# from victron-monitor/apps-script/Victron_Events_App_Script_v1p7.js's own
# buildEmailHtml(). Deliberately NEVER branded, same reasoning
# report_svg.py's GREEN/AMBER/RED already states: a health tier is data,
# not decoration, and a customer whose brand colour is red must not ship a
# report where every healthy metric reads as an alarm.
def _health_score_colors(avg_health) -> tuple[str, str, str]:
    if avg_health is None:
        return "#5A6B7C", "#F0F3F5", "#5A6B7C"
    if avg_health >= 90:
        return "#1FAE6E", "#D9F2E6", "#0F7D4A"
    if avg_health >= 80:
        return "#4A9FD4", "#DCEEF8", "#1A5F88"
    if avg_health >= 70:
        return "#D4860F", "#FDEFC5", "#9A6200"
    return "#C94040", "#FAD9D9", "#8A1F1F"


def _render_email(*, customer: dict, site: dict, branding: dict, summary: dict,
                  period_start: str, period_end: str, to: str, is_third_party: bool) -> str:
    score_color, badge_bg, badge_text = _health_score_colors(summary.get("avgHealth"))
    unsubscribe_url = None
    if is_third_party:
        token = make_unsubscribe_token(site["site_id"], to)
        site_url = os.environ.get("SITE_URL")
        if token and site_url:
            unsubscribe_url = f"{site_url.rstrip('/')}/unsubscribe?token={token}"
    template = _env.get_template("report_email.html")
    return template.render(
        company_name=branding.get("company_name"),
        primary_color=branding.get("primary_color"),
        contact_email=branding.get("contact_email"),
        site_name=site.get("display_name") or site["site_id"],
        period_start=period_start,
        period_end=period_end,
        avg_health=summary.get("avgHealth"),
        health_status=summary.get("healthStatus"),
        score_color=score_color, badge_bg=badge_bg, badge_text=badge_text,
        pv_kwh=(summary.get("totals") or {}).get("pv"),
        load_kwh=(summary.get("totals") or {}).get("load"),
        grid_independence_pct=summary.get("gridIndependencePct"),
        unsubscribe_url=unsubscribe_url,
    )


def send_report_email(customer: dict, site: dict, branding: dict, summary: dict,
                      pdf_bytes: bytes, period_start: str, period_end: str) -> tuple[str, list[str]]:
    """Renders and sends the report email to every resolved recipient,
    attaching `pdf_bytes`. Returns `(email_status, recipients)` — the exact
    values `report_runs.record_done()` stores. `email_status` is
    `'sent'` | `'failed'` | `'skipped'`, migration 026's own vocabulary for
    this column: `'skipped'` when nobody could be resolved to send to at
    all (no explicit recipients and no customer contact/auth email — rare,
    but not impossible for a very old hand-created row), `'failed'` only
    when EVERY resolved recipient's send failed, `'sent'` if at least one
    succeeded (a partial failure among several recipients still counts as
    delivered — the report reached someone).

    Never raises — see this module's own header comment.
    """
    recipients = resolve_recipients(site, customer)
    if not recipients:
        return "skipped", []

    is_third_party = bool(site.get("report_recipients"))
    site_label = site.get("display_name") or site["site_id"]
    subject = f"Your {site_label} report — {period_start} to {period_end}"
    attachment = {
        "filename": f"Report - {site_label} - {period_end}.pdf",
        "content": base64.b64encode(pdf_bytes).decode(),
    }

    sent_count = 0
    for to in recipients:
        try:
            html = _render_email(
                customer=customer, site=site, branding=branding, summary=summary,
                period_start=period_start, period_end=period_end, to=to, is_third_party=is_third_party,
            )
            mailer_send(to, subject, html, attachments=[attachment])
            sent_count += 1
        except MailerError as exc:
            # One recipient's failure (a bad address, Resend down) must not
            # stop the others — same per-item isolation discipline
            # `routers/reports.py:post_run_due()`'s own per-site loop uses.
            logger.warning("report_delivery: failed to email %s for site %s: %s", to, site["site_id"], exc)
        except Exception:  # noqa: BLE001 — a template-rendering bug must not
            # lose the already-generated report either.
            logger.exception("report_delivery: unexpected error emailing %s for site %s", to, site["site_id"])

    return ("sent" if sent_count > 0 else "failed"), recipients


def notify_cap_reached_once(customer: dict, cap: int, cap_period_end: str) -> None:
    """PLAN_PHASE17.md §0.6 Q7 — ONE notification email per customer per
    billing period, the first time a scheduled run is skipped for
    `skipped_capped` that period — never one per skipped run (a fleet stuck
    at the cap could otherwise skip many sites a day, every day, for the
    rest of the period, and Q7's whole point is "tell them once, loudly,"
    not "flood them").

    The gate is `vrm.customers.report_cap_notified_period_end` (migration
    027) — a durable column, NOT `vrm.rate_limits`: that table's own 2-day
    prune sweep (`routers/billing.py:post_prune_signups()`) would silently
    reset a ~30-day billing-period gate on day 3, sending a second (third,
    ...) notice for the same period. See migration 027's own header for the
    full reasoning (that was the first design, found wrong before it
    shipped). A plain read-then-conditional-update: matching
    `cap_period_end` means "already notified this period, skip"; anything
    else sends and updates the column. The tiny race window between two
    concurrent `run-due` calls both reading a stale value is bounded by the
    CAS-style `.eq('report_cap_notified_period_end', ...)` on the update
    below — only the read whose update actually lands sends the email; a
    lost race sends nothing, never two.

    Never raises — a failure here must not affect the `run-due` loop it's
    called from.
    """
    try:
        already_notified = customer.get("report_cap_notified_period_end") == cap_period_end
        if already_notified:
            return

        to = customer.get("contact_email") or customer.get("auth_email")
        if not to or not _EMAIL_RE.match(to):
            return

        from database.supabase_client import get_client
        previous = customer.get("report_cap_notified_period_end")
        query = (get_client().schema("vrm").table("customers")
                .update({"report_cap_notified_period_end": cap_period_end})
                .eq("id", customer["id"]))
        query = query.is_("report_cap_notified_period_end", "null") if previous is None else query.eq("report_cap_notified_period_end", previous)
        updated = query.execute().data
        if not updated:
            # Lost the race to a concurrent run-due call that already
            # claimed this period's notification — it sends, this one
            # doesn't (never both).
            return

        html = _env.get_template("cap_reached_email.html").render(cap=cap, period_end=cap_period_end)
        mailer_send(to, "Scheduled report limit reached", html)
    except MailerError as exc:
        logger.warning("report_delivery: could not send the cap-reached notice for customer %s: %s", customer.get("id"), exc)
    except Exception:  # noqa: BLE001 — see module docstring
        logger.exception("report_delivery: unexpected error sending the cap-reached notice for customer %s", customer.get("id"))
