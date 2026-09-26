from __future__ import annotations
"""Suggests a starting overall margin % for a new Cotización, from historical
project performance. Phase 23 (PLAN_PHASE23_PROFIT_DISTRIBUTION.md §1.3).

Pure module — no `database`/`streamlit` imports, same convention
`calculations/project_finance.py`'s own docstring establishes — so it's
directly exercisable with a handful of already-fetched rows, no DB fixture
needed. `database/projects_db.py:list_margin_benchmark_rows()` is this
module's only caller-side data source.

The suggestion is a starting point, never an authority — the spec's own
benchmarking section is explicit about this ("señal direccional... nunca...
valor definitivo", especially with a thin sample), so every result reports
its own sample size and whether it had to fall back to a mixed-system-type
sample, and the UI (both wizards' costs step) must show that context rather
than silently pre-filling a number that looks more certain than it is.
"""


def suggest_margin_pct(rows: list[dict], system_type: str) -> dict | None:
    """`rows`: one dict per completed project, each `{system_type,
    ingresos_base, gastos_base}` — the same two figures
    `calculations/project_finance.py:summarize()` already computes per
    project, read back across every project by
    `database/projects_db.py:list_margin_benchmark_rows()`.

    Returns `{"margin_pct": float, "n": int, "same_type": bool}` — the
    average `(ingresos_base - gastos_base) / gastos_base` ratio, i.e. profit
    over real cost, matching exactly how `margin_pct` is applied in
    `gz_s7_costs.py`/`og_s7_costs.py`'s own `_shown_price()`
    (`costo_real * (1 + margin_pct)`). Prioritizes rows matching
    `system_type` (spec: "el tipo de sistema importa más que el tamaño para
    este ratio específico") and only falls back to every row, regardless of
    type, when there isn't a single usable same-type row — `same_type` tells
    the caller which happened. Returns `None` when there is no usable
    history at all (a project with `gastos_base <= 0` can't produce a
    margin ratio and is skipped, not counted as zero)."""

    def _ratios(candidate_rows: list[dict]) -> list[float]:
        out = []
        for r in candidate_rows:
            gastos = float(r.get("gastos_base") or 0)
            if gastos <= 0:
                continue
            ingresos = float(r.get("ingresos_base") or 0)
            out.append((ingresos - gastos) / gastos)
        return out

    same_type_rows = [r for r in rows if r.get("system_type") == system_type]
    ratios = _ratios(same_type_rows)
    same_type = True
    if not ratios:
        ratios = _ratios(rows)
        same_type = False
    if not ratios:
        return None

    return {
        "margin_pct": round(sum(ratios) / len(ratios), 4),
        "n": len(ratios),
        "same_type": same_type,
    }
