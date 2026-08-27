from __future__ import annotations
"""
Report module selection (PLAN_PHASE18.md §2) — the content-personalization
sibling of branding.py's tiered white-labeling (PLAN_PHASE17.md §4). Same
tier/account-type population, same "resolved once, server-side" shape:
`resolve_report_modules()` is the ONLY place selection is decided, and
`victron/weekly_report.py` receives its OUTPUT (a plain set of module ids
to render), never a customer's raw `report_modules` column directly — the
same "no id is ever accepted from a request body, every id is looked up"
discipline branding.py's own module docstring states.

Deliberately reuses the exact same entitlement question branding.py asks
(`account_type='installer'`, the `white_label` plan_limits flag, not
suspended) rather than introducing a second, independently-seeded
plan_limits column — both features are scoped to the same real population
(an installer curating what THEIR clients see), per PLAN_PHASE18.md's own
Decisions section, and `white_label` is already `true` for exactly
growth/fleet today (migration 026's seed data). A second column with
identical values forever would be redundant tracking, not clarity — if
these two entitlement rules are ever meant to diverge, that's a one-line
change here, not a schema migration.

`_is_entitled()` restates branding.py's own private helper rather than
importing it — same reasoning `lib/server/db/admin.ts`'s own
`ADMIN_SITE_WHITELIST` restatement gives for not sharing a tenancy-adjacent
check across module boundaries via an underscore-prefixed internal.

`ALL_MODULES` itself is NOT defined here — it's imported from
`victron.weekly_report`, which actually implements each block. `victron/`
never imports from `vrm_api/` anywhere in this codebase (the dependency
runs the other way: `vrm_api` is the FastAPI layer built on top of the
`victron` pipeline), so the module-id list has to live on the `victron`
side for this file to depend on it without introducing the only reverse
import in the project.
"""
import logging

from victron.weekly_report import ALL_MODULES
from vrm_api.report_limits import resolve_limits

logger = logging.getLogger("vrm_api.report_modules")

_ALL_MODULES_SET = frozenset(ALL_MODULES)

# Same denylist branding.py and PLAN_PHASE17.md §3.6's scheduler gate use —
# a denylist ON PURPOSE, so a legacy hand-created customer with
# billing_status='none' isn't accidentally excluded by a naive allowlist.
_NOT_ENTITLED_STATUSES = {"incomplete", "unpaid", "canceled"}


def _is_entitled(customer_row: dict) -> bool:
    if not customer_row.get("active"):
        return False
    if customer_row.get("provisioning_state") != "active":
        return False
    if customer_row.get("billing_status") in _NOT_ENTITLED_STATUSES:
        return False
    return True


def resolve_report_modules(customer_row: dict, site_row: dict) -> set[str]:
    """The one gate (PLAN_PHASE18.md §2). Always returns a non-empty set of
    module ids to render — never raises, never returns an id outside
    `ALL_MODULES` regardless of what's actually stored in either row.

    Rule 0 (account-type), rule 1 (tier), rule 2 (entitlement) all return
    the FULL default set and ignore `report_modules`/`default_report_modules`
    entirely — same "ignore the customer's own stored value entirely,
    don't merge with it" shape `resolve_branding()` uses for its own three
    gates. Only a white-labeled, entitled INSTALLER customer's stored
    selection is ever read at all.
    """
    if customer_row.get("account_type") != "installer":
        return set(ALL_MODULES)
    if not resolve_limits(customer_row.get("plan")).get("white_label"):
        return set(ALL_MODULES)
    if not _is_entitled(customer_row):
        return set(ALL_MODULES)

    selected = site_row.get("report_modules") or customer_row.get("default_report_modules")
    if not selected:
        return set(ALL_MODULES)

    # Defensive re-validation, independent of migration 028's own CHECK
    # constraint — same "hide an editor is UX, never the control"
    # discipline PLAN_PHASE17.md §3.1 point 2 already established for
    # schedules. A stored id outside today's known set (a future rename, a
    # row written before a module was renamed/removed) is dropped rather
    # than trusted blindly; an empty result after filtering falls back to
    # the full set rather than rendering a report with nothing in it.
    valid = {m for m in selected if m in _ALL_MODULES_SET}
    return valid if valid else set(ALL_MODULES)
