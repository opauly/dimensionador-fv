from __future__ import annotations
"""
Report cost limits (PLAN_PHASE17.md §2, §5.1, §8 Step 3) — two independent
caps, for two independent threats:

  Cap A — manual regeneration. A customer (or a stuck retry loop, or a
  bored browser) clicking "Generate" repeatedly. Enforced in TWO layers,
  mirroring the tenancy discipline `vrm_api/tenancy.py`'s own docstring
  argues for ("two independent implementations of the same rule, in the
  two processes that hold privilege, is the one place defence in depth
  genuinely earns its keep"): `app/api/pipeline/reports/route.ts` checks a
  LOWER ceiling first via `lib/server/ratelimit.ts:checkRateLimit()`, and
  `check_manual_cap()` below checks a HIGHER ceiling again, independently,
  for any `actor='customer'` call that reaches this API — not redundancy
  theatre, because Next.js is only *today's* caller, and `vrm_api` holds
  its own trust boundary regardless of who calls it. Deliberately uses
  DIFFERENT `vrm.rate_limits` bucket names than the TS layer
  (`report_manual_*_vrm_api`, not `report_manual_*`) — sharing a bucket
  would double-count a single logical request (once per layer) and make
  this ceiling bite twice as fast as intended; a distinct bucket instead
  measures "requests that reached vrm_api directly," which is the thing
  this layer is actually meant to guard.

  Cap B — scheduled runs. A customer picking a high-frequency schedule
  across a large fleet, which is a *legitimate* setting that produces an
  *illegitimate* bill. `resolve_billing_period()` and `check_scheduled_cap()`
  are written now but have NO CALLER as of Step 3 — they are wired into
  `vrm_api/routers/reports.py:post_run_due()` at Step 6, once the scheduler
  itself exists. Full live verification (including the fail-CLOSED-ish
  behaviour §2.1's asymmetry table calls for) happens there.

Both caps resolve their numbers from `vrm.plan_limits`
(`resolve_limits()`), keyed by `vrm.customers.plan`, falling back to the
`'default'` row for any unrecognized value — never to "no limit." See
migration 026's own `COMMENT ON TABLE vrm.plan_limits` for why `'default'`
is stricter than every PAID tier but is deliberately NOT compared against
`trial`/`single_report`, which are independently stricter still on
scheduling for structural reasons.
"""
import logging
from datetime import date, datetime, timedelta, timezone

from database.supabase_client import get_client

logger = logging.getLogger("vrm_api.report_limits")

SCHEMA = "vrm"
DEFAULT_PLAN_KEY = "default"

# vrm.customers has no timezone column of its own (unlike vrm.sites,
# migration 012) — only `country`, DEFAULT 'CR'. This is the same
# CR-centric fallback direction migration 012/024 already take; a future
# non-CR customer just needs a real entry added here, same as
# vrm.sites.timezone already handles per-site.
_COUNTRY_TIMEZONE = {"CR": "America/Costa_Rica"}
_DEFAULT_TIMEZONE = "UTC"


class ReportRateLimited(Exception):
    """Cap A exceeded (PLAN_PHASE17.md §2.2). Customer-safe by construction
    — the message never carries anything but a retry hint. Registered with
    a FastAPI exception handler in `vrm_api/main.py` returning 429, the
    same pattern `NotAuthorized`/`VrmAccountAlreadyLinked` already use for
    403/409."""

    def __init__(self, retry_after_seconds: int):
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"Manual report rate limit exceeded — retry after {retry_after_seconds}s.")


def _plan_limits_table():
    return get_client().schema(SCHEMA).table("plan_limits")


def resolve_limits(plan: str | None) -> dict:
    """`vrm.customers.plan` -> a `vrm.plan_limits` row, falling back to
    `'default'` for `None` or any string that isn't a seeded `plan_key`
    (PLAN_PHASE17.md §5.1 resolution). Never returns "no limit" — the
    `'default'` row is mandatory (migration 026) and this function raises
    loudly if it's somehow missing, rather than silently treating a broken
    seed as unlimited."""
    key = plan or DEFAULT_PLAN_KEY
    rows = _plan_limits_table().select("*").eq("plan_key", key).limit(1).execute().data
    if rows:
        return rows[0]

    if key != DEFAULT_PLAN_KEY:
        logger.warning(
            "report_limits.resolve_limits: unrecognized plan_key=%r — "
            "falling back to '%s'.", key, DEFAULT_PLAN_KEY,
        )
    default_rows = _plan_limits_table().select("*").eq("plan_key", DEFAULT_PLAN_KEY).limit(1).execute().data
    if not default_rows:
        # Migration 026 seeds this row with ON CONFLICT DO NOTHING — it can
        # only be missing if someone deleted it by hand. Fail loud, not
        # silently unlimited.
        raise RuntimeError(
            "vrm.plan_limits has no 'default' row — migration 026 must be "
            "applied and its seed data must not have been deleted."
        )
    return default_rows[0]


# ═══════════════════════════════════════════════════════════════════════
# Cap A — manual regeneration (PLAN_PHASE17.md §2.2 point 1)
# ═══════════════════════════════════════════════════════════════════════

def _truncate_to_window(now: datetime, window_seconds: int) -> str:
    """Identical truncation to `lib/server/ratelimit.ts:truncateToWindow()`
    — UTC epoch seconds, floored to the window size — so this Python layer
    and the TS layer would compute the same `window_start` for the same
    instant, IF they ever shared a bucket (they deliberately don't, see
    module docstring, but the arithmetic itself should still match in case
    that ever changes)."""
    epoch = int(now.timestamp())
    window_start_epoch = epoch - (epoch % window_seconds)
    return datetime.fromtimestamp(window_start_epoch, tz=timezone.utc).isoformat()


def _increment_rate_limit(bucket: str, key: str, window_start: str) -> int | None:
    """The Python-side twin of `lib/server/ratelimit.ts:checkRateLimit()`'s
    atomic upsert-and-return — same `vrm.increment_rate_limit()` RPC
    (migration 025), same fail-OPEN reasoning (this is an abuse control,
    not an authentication boundary; a transient Postgres hiccup should not
    itself become an outage for a legitimate manual regeneration). Returns
    `None` on a database error so the caller can tell "checked, under
    limit" apart from "couldn't check, allow anyway" instead of collapsing
    both into a bare boolean."""
    try:
        result = get_client().schema(SCHEMA).rpc("increment_rate_limit", {
            "p_bucket": bucket, "p_key": key, "p_window_start": window_start,
        }).execute()
        return int(result.data)
    except Exception as exc:  # noqa: BLE001 — fail open, log loudly
        logger.error(
            "report_limits.check_manual_cap: increment_rate_limit failed "
            "for bucket=%s — failing OPEN (this is an abuse control, not an "
            "auth boundary): %s", bucket, exc,
        )
        return None


def check_manual_cap(customer_id: str, plan: str | None) -> None:
    """Cap A's higher, `vrm_api`-side ceiling (PLAN_PHASE17.md §2.2 point 2)
    — called from `vrm_api/routers/reports.py:post_report()` for
    `actor='customer'` calls only (`actor='admin'` — `/admin/reports` — is
    exempt by design: rate-limiting Oscar's own support tooling is a bug,
    not a control). Raises `ReportRateLimited` if either the hourly or the
    daily window is over the resolved limit; both windows are always
    incremented regardless of outcome, so the counters reflect real request
    volume even when only one window trips."""
    limits = resolve_limits(plan)
    now = datetime.now(timezone.utc)

    hour_window = _truncate_to_window(now, 3600)
    hour_count = _increment_rate_limit("report_manual_hour_vrm_api", customer_id, hour_window)
    day_window = _truncate_to_window(now, 86400)
    day_count = _increment_rate_limit("report_manual_day_vrm_api", customer_id, day_window)

    if hour_count is not None and hour_count > limits["manual_reports_per_hour"]:
        raise ReportRateLimited(retry_after_seconds=3600)
    if day_count is not None and day_count > limits["manual_reports_per_day"]:
        raise ReportRateLimited(retry_after_seconds=86400)


# ═══════════════════════════════════════════════════════════════════════
# Cap B — scheduled runs (PLAN_PHASE17.md §2.2 point 2, §2.3). No caller
# until Step 6 (`vrm_api/routers/reports.py:post_run_due()`).
# ═══════════════════════════════════════════════════════════════════════

def resolve_billing_period(customer_id: str, country: str | None) -> tuple[str, str]:
    """The `[period_start, period_end)` window Cap B counts against
    (PLAN_PHASE17.md §2.2). Reads `current_period_start`/
    `current_period_end` off the customer's live (non-canceled)
    `vrm.subscriptions` mirror row when one exists. **Fallback, when there
    is no subscription row at all** (`billing_status='none'` — a legacy,
    hand-managed, Oscar-invited customer, exactly the trap
    PLAN_PHASE17.md §3.6 names for the entitlement gate): the calendar
    month in the customer's own country's timezone. Getting this fallback
    wrong means Oscar's own existing customers silently lose scheduled
    reports — it is deliberately NOT "no billing period, no cap.\""""
    rows = (
        get_client().schema(SCHEMA).table("subscriptions")
        .select("current_period_start, current_period_end, canceled_at")
        .eq("customer_id", customer_id)
        .order("created_at", desc=True)
        .execute().data
    )
    live = [r for r in rows if r.get("canceled_at") is None]
    sub = live[0] if live else None

    if sub and sub.get("current_period_start") and sub.get("current_period_end"):
        return sub["current_period_start"], sub["current_period_end"]

    # No live subscription mirror row — the calendar-month fallback.
    tz_name = _COUNTRY_TIMEZONE.get((country or "CR").upper(), _DEFAULT_TIMEZONE)
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(tz_name)
    except Exception:  # noqa: BLE001 — a bad/missing tzdata entry must not break Cap B
        logger.error(
            "report_limits.resolve_billing_period: could not load timezone "
            "%r for customer_id=%s — falling back to UTC.", tz_name, customer_id,
        )
        tz = timezone.utc

    today = datetime.now(tz).date()
    period_start = today.replace(day=1)
    if today.month == 12:
        next_month_start = date(today.year + 1, 1, 1)
    else:
        next_month_start = date(today.year, today.month + 1, 1)
    period_end = next_month_start - timedelta(days=1)
    return period_start.isoformat(), period_end.isoformat()


def check_scheduled_cap(customer_id: str, plan: str | None, period_start: str, period_end: str) -> bool:
    """Cap B's runtime backstop. Returns `True` if the customer is at or
    under their scheduled-runs cap for `[period_start, period_end]`
    (inclusive), `False` if at/over. Counts `vrm.report_runs` rows with
    `trigger='scheduled'` AND `status='done'` whose `period_end` falls
    inside the window — `done` only, deliberately: a `failed`/`skipped_*`
    run did not cost an Anthropic call and must not count against the
    customer's budget.

    Deliberately does NOT fail open on a database error, unlike Cap A
    (§2.1's stated asymmetry: "a manual click that slips through a
    Postgres hiccup costs one report; a scheduled fan-out that slips
    through could cost hundreds"). A caller that cannot get a count back
    from this function should treat that as "skip this run," not "allow
    it" — enforced by letting the exception propagate rather than
    swallowing it here."""
    limits = resolve_limits(plan)
    cap = limits["scheduled_reports_per_period"]

    count = (
        get_client().schema(SCHEMA).table("report_runs")
        .select("id", count="exact")
        .eq("customer_id", customer_id)
        .eq("trigger", "scheduled")
        .eq("status", "done")
        .gte("period_end", period_start)
        .lte("period_end", period_end)
        .limit(1)
        .execute().count
    )
    return count < cap
