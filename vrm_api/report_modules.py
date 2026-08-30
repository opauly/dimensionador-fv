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

`_is_entitled()` used to restate branding.py's own private helper rather
than importing it (module-privacy convention). That held until adding the
`'trial_expired'` billing_status (migration 030) meant editing three
separate copies of the same denylist and the first pass only found two —
now both this file and branding.py import the single shared
`vrm_api.billing.NOT_ENTITLED_BILLING_STATUSES` instead (that constant's
own docstring has the full reasoning), and only the surrounding
active/provisioning_state checks stay duplicated (they're each a single
line, not a vocabulary that can drift).

`ALL_MODULES`/`DEFAULT_MODULES` are NOT defined here — they're imported from
`victron.weekly_report`, which actually implements each block. `victron/`
never imports from `vrm_api/` anywhere in this codebase (the dependency
runs the other way: `vrm_api` is the FastAPI layer built on top of the
`victron` pipeline), so the module-id lists have to live on the `victron`
side for this file to depend on them without introducing the only reverse
import in the project.
"""
import logging

from victron.weekly_report import ALL_MODULES, DEFAULT_MODULES
from vrm_api.billing import NOT_ENTITLED_BILLING_STATUSES
from vrm_api.report_limits import resolve_limits

logger = logging.getLogger("vrm_api.report_modules")

_ALL_MODULES_SET = frozenset(ALL_MODULES)


def _is_entitled(customer_row: dict) -> bool:
    if not customer_row.get("active"):
        return False
    if customer_row.get("provisioning_state") != "active":
        return False
    # The shared entitlement denylist (`vrm_api.billing.
    # NOT_ENTITLED_BILLING_STATUSES` — that constant's own docstring has the
    # full reasoning). Previously a private restatement here, along with two
    # others in branding.py and routers/reports.py — consolidated 2026-08-29.
    if customer_row.get("billing_status") in NOT_ENTITLED_BILLING_STATUSES:
        return False
    return True


def resolve_report_modules(customer_row: dict, site_row: dict) -> set[str]:
    """The one gate (PLAN_PHASE18.md §2). Always returns a non-empty set of
    module ids to render — never raises, never returns an id outside
    `ALL_MODULES` regardless of what's actually stored in either row.

    Rule 0 (account-type), rule 1 (tier), rule 2 (entitlement) all return
    `DEFAULT_MODULES` — NOT the full `ALL_MODULES` — and ignore
    `report_modules`/`default_report_modules` entirely — same "ignore the
    customer's own stored value entirely, don't merge with it" shape
    `resolve_branding()` uses for its own three gates. `DEFAULT_MODULES`
    (PLAN_PHASE18.md §7, Oscar's decision 2026-08-29) is the original 9
    modules plus `critical_alerts` — every non-customizing customer
    (that's everyone below Growth/Fleet, and any not-yet-customized
    installer) gets that, never the 3 hardware-conditional Phase 2 modules
    (grid_meter_detail/generator_runtime/tank_level), which are opt-in
    only. Only a white-labeled, entitled INSTALLER customer's stored
    selection is ever read at all.
    """
    if customer_row.get("account_type") != "installer":
        return set(DEFAULT_MODULES)
    if not resolve_limits(customer_row.get("plan")).get("white_label"):
        return set(DEFAULT_MODULES)
    if not _is_entitled(customer_row):
        return set(DEFAULT_MODULES)

    selected = site_row.get("report_modules") or customer_row.get("default_report_modules")
    if not selected:
        return set(DEFAULT_MODULES)

    # Defensive re-validation, independent of migration 029's own CHECK
    # constraint — same "hide an editor is UX, never the control"
    # discipline PLAN_PHASE17.md §3.1 point 2 already established for
    # schedules. A stored id outside today's known set (a future rename, a
    # row written before a module was renamed/removed) is dropped rather
    # than trusted blindly; an empty result after filtering falls back to
    # DEFAULT_MODULES rather than rendering a report with nothing in it.
    valid = {m for m in selected if m in _ALL_MODULES_SET}
    return valid if valid else set(DEFAULT_MODULES)
