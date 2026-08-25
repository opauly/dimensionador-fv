from __future__ import annotations
"""
The ledger against `vrm.report_runs` (PLAN_PHASE17.md §3.2, §3.4, §5.2, §8
Step 6) — claim, update. Three jobs, stated in migration 026's own `COMMENT
ON TABLE`: the scheduled-runs cap's counter (Cap B —
`report_limits.py:check_scheduled_cap()` already reads this table
directly), the scheduler's idempotency claim (this module), and the audit
trail `routers/reports.py:post_run_due()` writes plain-English status into.

Claiming a period is deliberately NOT a new `INSERT ... ON CONFLICT DO
NOTHING` RPC — migration 026's own header states it adds no new SECURITY
DEFINER function (§5.5), and Step 6 doesn't call for a new migration
either. Instead this follows the exact precedent
`vrm_api/billing.py:_conditional_upsert()` already set: attempt a write,
treat the table's own UNIQUE constraint rejecting it as an expected lost
race (not a real failure), and re-read whatever won. The partial unique
index on `(site_id, period_end) WHERE trigger='scheduled'` (migration 026)
is the actual mutex; this module never takes a lock of its own.

Retry semantics (§3.4's status table, and §3.2's own wording — "no
vrm.report_runs row already exists ... in a terminal-success or
in-progress state"): only `done` (terminal success) and `running`
(genuinely in flight, including a concurrent caller's claim that just won)
block a period from being reconsidered. `abandoned` is also terminal, but
for the opposite reason — permanently given up, not permanently succeeded.
Every skip status (`skipped_no_data`/`skipped_capped`/`skipped_not_entitled`)
and `failed` are retried on the next tick: the condition that produced them
may not hold an hour from now, and none of them cost an Anthropic call, so
retrying costs nothing. `failed` is the only one bounded by
`attempt_count`; past `MAX_ATTEMPTS` it becomes `abandoned` instead (see
`record_failed()`).
"""
import logging

from database.supabase_client import get_client

logger = logging.getLogger("vrm_api.report_runs")

SCHEMA = "vrm"
MAX_ATTEMPTS = 3

_BLOCKING_STATUSES = {"done", "running", "abandoned"}


def _t():
    return get_client().schema(SCHEMA).table("report_runs")


def claim_period(customer_id: str, site_id: str, schedule: str,
                 period_start: str, period_end: str) -> dict | None:
    """Claims `(site_id, period_end)` for a fresh scheduled work attempt —
    returns the row to do the work against (freshly inserted with
    `status='running'`, or an existing failed/skipped_* row bumped back to
    `running` in place), or `None` if this period must be left alone this
    tick (already `done`, permanently `abandoned`, or genuinely `running`
    right now).

    The caller MUST eventually call exactly one of `record_done()`,
    `record_skipped()`, or `record_failed()` on the returned row's `id` —
    this function only ever leaves a row in the transient `running` state,
    never a terminal one.
    """
    try:
        inserted = _t().insert({
            "customer_id": customer_id, "site_id": site_id, "trigger": "scheduled",
            "schedule": schedule, "period_start": period_start, "period_end": period_end,
            "status": "running", "attempt_count": 1,
        }).execute().data
        if inserted:
            return inserted[0]
    except Exception:  # noqa: BLE001 — a lost claim race against the partial
        # unique index, not a real failure (see module docstring). Fall
        # through to the re-read below, same as billing.py:_conditional_upsert().
        pass

    existing = (_t().select("*").eq("site_id", site_id).eq("period_end", period_end)
                .eq("trigger", "scheduled").limit(1).execute().data)
    if not existing:
        # The insert conflicted against a row that vanished before this
        # read — vanishingly unlikely (report_runs rows are never deleted,
        # PLAN_PHASE17.md §5.5) and not worth a retry loop here; the next
        # hourly tick will simply try the claim again from scratch.
        logger.error(
            "report_runs.claim_period: insert conflicted but no existing row "
            "found for site_id=%s period_end=%s — leaving this period for "
            "the next tick.", site_id, period_end,
        )
        return None

    row = existing[0]
    if row["status"] in _BLOCKING_STATUSES:
        return None

    # Retry-eligible (failed/skipped_*) — bump the SAME row back to
    # 'running' rather than a second insert (the unique index permits
    # exactly one trigger='scheduled' row per (site_id, period_end), ever).
    # attempt_count only climbs for a genuine failure, matching
    # record_failed()'s own bookkeeping — a retried skip keeps its prior
    # count, since a skip never actually attempted the work.
    next_attempt_count = row["attempt_count"] + 1 if row["status"] == "failed" else row["attempt_count"]
    # Compare-and-swap on status (same shape as _conditional_upsert()'s own
    # WHERE-guarded update): only lands if the row is still in the state we
    # just read it in, so two concurrent retries of the same stale row
    # can't both win.
    updated = (_t().update({"status": "running", "attempt_count": next_attempt_count})
              .eq("id", row["id"]).eq("status", row["status"]).execute().data)
    if not updated:
        # Lost the retry race to a concurrent claim on this same row —
        # the other caller's claim wins, this tick backs off.
        return None
    return updated[0]


def existing_status(site_id: str, period_end: str) -> str | None:
    """The current `status` of the `(site_id, period_end, trigger='scheduled')`
    row, if one exists, or `None` if there isn't one yet. Not used by
    `claim_period()` itself — it re-reads the full row internally — this is
    for a caller that already got `None` back from `claim_period()` and
    wants to report an ACCURATE status (`done`/`abandoned` are real,
    meaningfully different outcomes worth surfacing; a genuinely in-flight
    `running` row is the one case worth collapsing to `skipped_not_due`,
    since §3.4's response vocabulary has no slot for "someone else is
    handling this right now")."""
    rows = (_t().select("status").eq("site_id", site_id).eq("period_end", period_end)
            .eq("trigger", "scheduled").limit(1).execute().data)
    return rows[0]["status"] if rows else None


def record_done(run_id: str, storage_path: str, *,
                recipients: list[str] | None = None, email_status: str | None = None) -> None:
    """`recipients`/`email_status` (PLAN_PHASE17.md §8 Step 8) are additive
    and optional — a caller that doesn't pass them (there are none yet, but
    a future direct caller might exist) leaves both `NULL`, exactly
    pre-Step-8 behaviour. `report_delivery.py:send_report_email()` never
    raises, so by the time `post_run_due()` calls this, both values are
    always already known — `email_status` is never left to default here on
    a real send attempt."""
    payload: dict = {"status": "done", "storage_path": storage_path}
    if recipients is not None:
        payload["recipients"] = recipients
    if email_status is not None:
        payload["email_status"] = email_status
    _t().update(payload).eq("id", run_id).execute()


def record_skipped(run_id: str, status: str) -> None:
    """`status` is one of `skipped_no_data`/`skipped_capped`/
    `skipped_not_entitled` — all retried on the next tick (see module
    docstring), so nothing else about the row changes."""
    _t().update({"status": status}).eq("id", run_id).execute()


def record_failed(run_id: str, attempt_count: int, error: str) -> None:
    """`attempt_count` is the CURRENT attempt's count, as already stamped by
    `claim_period()` before the work was attempted. At or past
    `MAX_ATTEMPTS` this moves the row to the permanently-terminal
    `abandoned` state instead of `failed` — the next tick must not retry it
    (§3.4's own status table). `error` must already be customer-safe (same
    discipline as `jobs.py:_safe_error_message()` — never a raw Postgres/
    Python error string)."""
    status = "abandoned" if attempt_count >= MAX_ATTEMPTS else "failed"
    _t().update({"status": status, "error": error}).eq("id", run_id).execute()
