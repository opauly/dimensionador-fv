"""
Measures the real wall-clock time and Anthropic token usage of the ONE
Anthropic call `victron/weekly_report.py:generate_narrative()` makes per
report (PLAN_PHASE17.md §8 Step 3's own gate: "Measure and record in this
file the real wall-clock time and Anthropic token cost of one weekly
report and one monthly (Overview) report — §2.3's numbers get a second
pass from these.").

Uses the EXACT model, `max_tokens`, and prompt-framing text
`generate_narrative()` itself uses (copied verbatim from
`victron/weekly_report.py`, not re-derived), with representative stats
substituted in — this is a real, priced API call against the real
Anthropic account, not a mock, so the token counts and latency below are
real measurements, not estimates. Deliberately does NOT call
`generate_narrative()` itself: that function expects a full site/report
context (a real `stats` dict assembled from real `vrm.energy_daily` rows)
that doesn't exist for a clean, data-free measurement — reproducing its
exact prompt text with synthetic-but-realistic numbers gets the same
token count without needing a real site's data.

Usage:
    python -m tools.measure_report_narrative_cost
"""
from __future__ import annotations

import os
import time

from dotenv import load_dotenv

load_dotenv()

import anthropic

_NARRATIVE_MODEL = "claude-sonnet-4-6"  # must match victron/weekly_report.py's own constant
_MAX_TOKENS = 400  # must match victron/weekly_report.py's own client.messages.create() call

# ── Weekly framing — copied verbatim from victron/weekly_report.py's
#    generate_narrative(), else-branch (period_label='week') ────────────
_WEEKLY_FRAMING = (
    "You are writing the insights paragraph for a residential "
    "solar+battery monitoring report covering a week. "
    "Write the narrative in English."
    "\n\nWrite exactly 2 short paragraphs (60-90 words total). Plain prose "
    "only - no headers, no bullets, no markdown."
    " Warm, professional tone. Be specific with numbers. Lead with the most "
    "meaningful story of the week."
    " If the battery kept the home running during outages, say so."
    " A forward-looking closing sentence is welcome, but only restate a "
    "fact given below (e.g. the season named, if one is given) or a trend "
    "visible in these numbers — never invent a date, a transition month, "
    "or any other detail not explicitly given, even one that sounds "
    "plausible. If a season is given, do not guess when it changes."
    "\n\nThis week's data:"
)

_WEEKLY_STATS_LINES = (
    "\n- Site: Casa Modelo"
    "\n- Report period: 2026-08-03 to 2026-08-09"
    "\n- Solar generated: 61.3 kWh"
    "\n- Total consumption: 58.1 kWh"
    "\n- Grid consumption: 4.2 kWh"
    "\n- Grid independence: 92.8%"
    "\n- Health score: 87/100 (Good)"
    "\n- Lowest battery SOC: 34%"
    "\n- Battery cycles this week: 3.1"
    "\n- Days battery reached full charge: 6 of 7"
    "\n- Grid outages: 1 (18 minutes total)"
    "\n- Longest single outage: 18 minutes"
    "\n- Battery covered loads during outages: yes"
    "\n- Alarm episodes: 0"
    "\n- Best production day: 10.4 kWh"
    "\n- Worst production day: 6.7 kWh"
    "\n- Season: dry season"
    "\n- Weather: avg 6.8 sunshine hrs/day, days with significant rain (>5mm): 0, avg cloud cover: 22%."
    " If weather affected generation, mention it."
    "\n- Solar performance ratio: 94% of expected"
    "\n- Grid quality: 96/100 (Excellent)"
)

# ── Monthly/Overview framing — copied verbatim from
#    generate_narrative()'s if-branch (multi-segment / bucketTrendLines) ─
_OVERVIEW_FRAMING = (
    "You are writing the insights paragraph for a residential "
    "solar+battery monitoring report covering a month. "
    "Write the narrative in English."
    "\n\nWrite exactly 2 short paragraphs (60-90 words total). Plain prose "
    "only - no headers, no bullets, no markdown."
    " Warm, professional tone. Be specific with numbers. Lead with the most "
    "meaningful story of the month, focusing on whether the trend across "
    "segments is improving, worsening, or holding steady — rather than "
    "only restating the period's totals; that trend is the most meaningful "
    "story of a multi-segment report, more than any single number."
    " If the battery kept the home running during outages, say so."
    " A forward-looking closing sentence is welcome, but only restate "
    "a fact given below (e.g. the season named, if one is given) or a "
    "trend visible in these numbers — never invent a date, a "
    "transition month, or any other detail not explicitly given, even "
    "one that sounds plausible. If a season is given, do not guess "
    "when it changes."
    "\n\nPer-segment breakdown:\n"
    "Week of Jul 6: PV 58.2 kWh, load 55.9 kWh, grid independence 91.2%\n"
    "Week of Jul 13: PV 63.7 kWh, load 57.4 kWh, grid independence 93.8%\n"
    "Week of Jul 20: PV 49.1 kWh, load 54.2 kWh, grid independence 84.6%\n"
    "Week of Jul 27: PV 61.3 kWh, load 58.1 kWh, grid independence 92.8%"
    "\n\nFull month totals:"
)


def _measure(label: str, framing: str, stats_lines: str) -> None:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise SystemExit("ANTHROPIC_API_KEY not set — see victron-monitor/web/README.md / .env.example.")

    prompt = framing + stats_lines
    client = anthropic.Anthropic(api_key=api_key)

    start = time.monotonic()
    msg = client.messages.create(
        model=_NARRATIVE_MODEL, max_tokens=_MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )
    elapsed = time.monotonic() - start

    print(f"── {label} ──")
    print(f"  model:          {_NARRATIVE_MODEL}")
    print(f"  wall-clock:     {elapsed:.2f}s")
    print(f"  input tokens:   {msg.usage.input_tokens}")
    print(f"  output tokens:  {msg.usage.output_tokens}")
    print(f"  narrative:      {msg.content[0].text.strip()[:200]}...")
    print()


if __name__ == "__main__":
    _measure("Weekly report", _WEEKLY_FRAMING, _WEEKLY_STATS_LINES)
    _measure("Monthly (Overview) report", _OVERVIEW_FRAMING, _WEEKLY_STATS_LINES)
    print("Record these numbers in PLAN_PHASE17.md §2.3/§8 Step 3 — they only "
          "measure the Anthropic call itself, not the full report's wall-clock "
          "(WeasyPrint render + weather fetch + storage write are separate, "
          "typically much smaller costs).")
