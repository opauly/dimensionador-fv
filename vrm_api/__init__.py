from __future__ import annotations
"""
`vrm_api` — the internal FastAPI service wrapping the VRM report pipeline
(`victron/*.py`, `database/vrm_report_db.py`) for `victron-monitor/web`'s
server (PLAN_PHASE14.md §1.3, §2 Step 5).

Nothing in this package rewrites the pipeline — every route is a thin,
authenticated, tenant-checked wrapper around functions that already exist
and are already exercised by `pages/06_vrm_monitor.py`. See `main.py` for
the trust-boundary rules (no CORS, bearer-required, independent tenancy
re-check) and `vrm_api/README.md` for how to run this locally.
"""
