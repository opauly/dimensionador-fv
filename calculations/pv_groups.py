"""Strings that share an MPPT input: how many runs, how many strings per run.

Oscar's rule (2026-11-14): when the design has more strings than MPPT inputs (or controllers), the extra strings are paralleled in the
roof with MC4 "Y" connectors. After the Y there is ONE run of cable and ONE DC breaker per MPPT input, sized for the combined current
(Isc x strings in that run). The wiring, the materials list and the unifilar all read the numbers from here so they agree.

Strings are spread evenly: 3 strings on 2 inputs -> runs of 2 and 1; the cable and breaker are sized for the largest run.
"""
from __future__ import annotations


def sizes(strings: int, inputs: int) -> list[int]:
    """Strings in each run (one run per MPPT input that gets strings), largest first."""
    strings, inputs = max(0, int(strings or 0)), max(1, int(inputs or 1))
    runs = min(strings, inputs)
    if not runs:
        return []
    base, extra = divmod(strings, runs)
    return [base + 1 if i < extra else base for i in range(runs)]


def summary(strings: int, inputs: int) -> dict:
    """{strings, inputs, runs, sizes, per_run, y_pieces}: `y_pieces` counts the MC4 Y connector pieces (one per polarity at every join)."""
    s = sizes(strings, inputs)
    return {"strings": int(strings or 0), "inputs": max(1, int(inputs or 1)), "runs": len(s), "sizes": s,
            "per_run": max(s) if s else 0, "y_pieces": 2 * (int(strings or 0) - len(s)) if s else 0}


def backfeed_a(isc: float, per_run: int) -> float:
    """Reverse current a module can see from the other strings joined to it by the Y: (n - 1) x Isc."""
    return max(0, per_run - 1) * float(isc or 0)
