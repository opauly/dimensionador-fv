"""VRM Monitor customer portal — Python package.

Second, separate Streamlit application (entry point:
`victron-monitor/portal/app.py`) sitting alongside the internal Pauly&Co tool
(`app.py` + `pages/`), which nothing under this package may import from or
modify. Reuses the existing pipeline as-is: `victron/`, `database/`,
`calculations/`. Full design and build plan: PLAN_PHASE13.md.

Deliberately no `pages/` directory anywhere under `victron-monitor/portal/` —
Streamlit auto-discovers one next to the entry script and would pull the
entire internal app into this portal's sidebar. Navigation here is declared
explicitly with `st.navigation` (see `victron-monitor/portal/app.py`).
"""
