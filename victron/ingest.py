from __future__ import annotations
"""
Write path for the `vrm` schema: VRM CSV export → customer/site/rows.

Parsing and all mapping rules live in `victron/vrm_csv.py`; this module only
persists what that produces. Read path is `database/vrm_report_db.py`.

Ordering matters here. `vrm.energy_daily` has an AFTER INSERT/UPDATE trigger
calling `compute_daily_health()`, which reads `vrm.alarm_events` for the same
day. Alarm events are therefore written FIRST — otherwise every health score is
computed against zero alarms and comes out systematically optimistic, with
nothing to indicate it happened.

Migration 012 also provides `SET LOCAL vrm.skip_health_trigger = 'on'` plus
`vrm.recompute_health()` for bulk backfills. That is deliberately not used
here: PostgREST runs each request in its own transaction, so a `SET LOCAL` from
this side would not survive to the insert. It exists for direct-SQL backfills.
A single upload firing the trigger once per day-row is fine.
"""
import re
import unicodedata

from database.supabase_client import get_client

SCHEMA = "vrm"
_CHUNK = 500


def _t(name: str):
    return get_client().schema(SCHEMA).table(name)


def slugify(value: str) -> str:
    """Lowercase ASCII slug, matching vrm.customers.slug's CHECK constraint.

    Accents are transliterated (í → i), not stripped. This is load-bearing for
    re-uploads, not cosmetic: the slug *is* the site identity, so if "Rebeca
    Ruíz" and "Rebeca Ruiz" produced different slugs, re-uploading the same
    site's export with the accent typed differently would silently create a
    second site and a duplicate copy of its history instead of updating the
    first. Dropping the accent character outright gave "rebeca-ru-z" and
    "jos-pe-a" — mangled, and different from the unaccented spelling.
    """
    decomposed = unicodedata.normalize("NFKD", str(value).strip().lower())
    ascii_only = "".join(c for c in decomposed if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9]+", "-", ascii_only).strip("-")
    if not s or not s[0].isalnum():
        raise ValueError(f"Cannot build a slug from {value!r}")
    return s


def make_site_id(customer_slug: str, site_slug: str) -> str:
    """Namespaced site_id.

    `vrm.sites.site_id` is globally unique — it is the key every child table
    references, kept identical in shape to `monitoring.sites.site_id` so one
    reader serves both schemas. Namespacing by customer is what makes a global
    unique constraint safe: two customers can each have a "casa-principal".
    """
    return f"{slugify(customer_slug)}-{slugify(site_slug)}"


# ──────────────────────────────────────────────────────────────────
# Customers and sites
# ──────────────────────────────────────────────────────────────────
def upsert_customer(name: str, slug: str | None = None, **fields) -> dict:
    """Create or update a customer by slug."""
    slug = slugify(slug or name)
    existing = _t("customers").select("*").eq("slug", slug).limit(1).execute().data
    payload = {"name": name, "slug": slug, **fields}
    if existing:
        row = _t("customers").update(payload).eq("slug", slug).execute().data
        return (row or existing)[0]
    return _t("customers").insert(payload).execute().data[0]


def upsert_site(customer_id: str, site_id: str, display_name: str, **fields) -> dict:
    """Create or update a site by site_id."""
    existing = _t("sites").select("*").eq("site_id", site_id).limit(1).execute().data
    payload = {"customer_id": customer_id, "site_id": site_id,
               "display_name": display_name, **fields}
    if existing:
        row = _t("sites").update(payload).eq("site_id", site_id).execute().data
        return (row or existing)[0]
    return _t("sites").insert(payload).execute().data[0]


# ──────────────────────────────────────────────────────────────────
# Ingest
# ──────────────────────────────────────────────────────────────────
def _chunks(seq: list, size: int = _CHUNK):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def ingest_parsed(parsed: dict, site_id: str, filename: str = "",
                  replace_alarms: bool = True, *,
                  source: str = "csv_upload",
                  triggered_by: str | None = None) -> dict:
    """Persist `vrm_csv.parse_export()` output — or, identically,
    `vrm_series.fetch_and_map()`'s (PLAN_PHASE15.md §4.2: both mappers return
    the same shape on purpose, so this function never branches on which
    produced `parsed`). Returns a summary.

    `source`/`triggered_by` are keyword-only and additive (PLAN_PHASE15.md
    §5.1/§3.3). `source` becomes `vrm.ingestion_log.source` — defaults to
    `"csv_upload"`, today's only value, so every caller that doesn't pass it
    (`ingest_csv()`, `vrm_api/routers/ingest.py:_do_commit()`) writes exactly
    the row it writes today, unchanged. `triggered_by` becomes
    `vrm.ingestion_log.triggered_by` (`'customer' | 'admin' | 'schedule'`,
    migration 024) — `None` by default (the column is nullable with no
    CHECK-breaking default), set explicitly by callers that know who/what
    triggered the write; a customer's own CSV upload or "Sync now" is
    `'customer'`, Oscar's Streamlit/`/admin` tools are `'admin'`, Step 7's
    scheduled sync (if built) is `'schedule'`.

    Re-ingesting an overlapping window is safe: `energy_daily` upserts on
    (site_id, date), and alarm events for the covered period are replaced
    rather than appended — without that, re-uploading the same CSV would double
    every alarm episode count and quietly degrade health scores.
    """
    rows = [dict(r) for r in parsed["rows"]]
    for r in rows:
        r["site_id"] = site_id
    events = [dict(e) for e in parsed["alarm_events"]]
    for e in events:
        e["site_id"] = site_id
    # PLAN_PHASE18.md §7 item 9 — same episode shape as `events` above, but
    # `source` becomes `category` and these go to vrm.critical_alerts, a
    # table vrm.count_alarm_episodes() never reads (see that table's own
    # migration comment for why they must never share alarm_events).
    # `.get(..., [])` keeps this call site working for any older `parsed`
    # dict that predates this key (there are none in this codebase today,
    # but `ingest_parsed()` is a public function and this costs nothing).
    critical_events = [dict(e) for e in parsed.get("critical_alerts", [])]
    for e in critical_events:
        e["site_id"] = site_id
        e["category"] = e.pop("source")

    # 1. Alarm events first — the energy_daily trigger reads them.
    if replace_alarms and rows:
        (_t("alarm_events").delete()
         .eq("site_id", site_id)
         .gte("timestamp", parsed["period_start"])
         .lte("timestamp", parsed["period_end"])
         .execute())
    for chunk in _chunks(events):
        _t("alarm_events").insert(chunk).execute()

    if replace_alarms and rows:
        (_t("critical_alerts").delete()
         .eq("site_id", site_id)
         .gte("timestamp", parsed["period_start"])
         .lte("timestamp", parsed["period_end"])
         .execute())
    for chunk in _chunks(critical_events):
        _t("critical_alerts").insert(chunk).execute()

    # PLAN_PHASE15.md §5.3/§5.4: look up what dump_type (if any) already
    # occupies each touched (site_id, date) BEFORE the upsert below
    # overwrites it. This is both the `days_replacing_csv` audit figure
    # (§5.4) and, further down, what the daily_health cleanup needs to know
    # which OTHER dump_type's row to remove. Every row a single parse
    # produces shares one dump_type (vrm_csv.py and vrm_series.py each call
    # vrm_daily.to_energy_daily_rows() once per parse, for the whole batch),
    # so `rows[0]["dump_type"]` speaks for all of them.
    touched_dates = sorted({r["date"] for r in rows})
    new_dump_type = rows[0]["dump_type"] if rows else None
    prior_dump_type_by_date: dict[str, str] = {}
    if touched_dates:
        prior_dump_type_by_date = {
            r["date"]: r["dump_type"]
            for r in (_t("energy_daily").select("date,dump_type")
                     .eq("site_id", site_id).in_("date", touched_dates)
                     .execute().data or [])
        }

    # 2. Daily rows — trigger fires per row and scores each day.
    written = 0
    for chunk in _chunks(rows):
        res = _t("energy_daily").upsert(chunk, on_conflict="site_id,date").execute()
        written += len(res.data or chunk)

    # PLAN_PHASE15.md §5.3: vrm.daily_health is keyed (site_id, date,
    # dump_type) — a DIFFERENT key from energy_daily's (site_id, date) — so
    # the health trigger the upsert above just fired ADDS a second
    # daily_health row per date rather than replacing one, whenever a date
    # already had a health row under a different dump_type (e.g. a
    # csv_upload day now re-ingested via the API, or vice versa).
    # database/vrm_report_db.py:bucket_health_days() dedups a mixed-source
    # site by keeping the HIGHEST-scoring row per date, which would silently
    # flatter a customer's health score — the worst possible way to be wrong
    # about a health metric. Delete the other dump_type's row for each
    # touched date so exactly one survives. Done here (shared by both
    # mappers, not per-path) so a CSV re-ingest of an API-sourced day is
    # cleaned up symmetrically, too. A no-op for a CSV-only site: it has only
    # ever had one dump_type per date, so there is never another dump_type's
    # row to find or delete.
    days_replacing_csv = 0
    if new_dump_type and touched_dates:
        for d in touched_dates:
            prior = prior_dump_type_by_date.get(d)
            if prior == "csv_upload" and prior != new_dump_type:
                days_replacing_csv += 1
        (_t("daily_health").delete()
         .eq("site_id", site_id)
         .in_("date", touched_dates)
         .neq("dump_type", new_dump_type)
         .execute())

    # 3. Audit trail.
    log = {
        "site_id": site_id,
        "source": source,
        "triggered_by": triggered_by,
        "filename": filename or None,
        "installation_id": (str(parsed["installation_id"])
                            if parsed.get("installation_id") else None),
        "period_start": parsed["period_start"],
        "period_end": parsed["period_end"],
        "sample_count": parsed["sample_count"],
        "rows_written": written,
        "alarm_events_written": len(events),
        "critical_alerts_written": len(critical_events),
        "warnings": {"messages": parsed.get("warnings", []),
                     "missing_signals": parsed.get("missing_signals", []),
                     "unscored_alarms": parsed.get("unscored_alarms", {}),
                     # New (§5.4): when this sync overwrote days that came
                     # from a CSV, that fact is recorded here rather than
                     # only being visible as a silent diff in energy_daily —
                     # the difference between "the report changed" and "we
                     # can explain why the report changed."
                     "days_replacing_csv": days_replacing_csv},
    }
    _t("ingestion_log").insert(log).execute()

    return {"rows_written": written, "alarm_events_written": len(events),
            "critical_alerts_written": len(critical_events),
            "period_start": parsed["period_start"], "period_end": parsed["period_end"],
            "days_replacing_csv": days_replacing_csv}


def ingest_csv(source, customer_name: str, site_name: str,
               filename: str = "", customer_slug: str | None = None,
               site_fields: dict | None = None,
               customer_fields: dict | None = None) -> dict:
    """End-to-end: file → customer → site → rows. Returns a summary."""
    from victron import vrm_csv

    customer = upsert_customer(customer_name, customer_slug, **(customer_fields or {}))
    site_id = make_site_id(customer["slug"], site_name)

    parsed = vrm_csv.parse_export(
        source, site_id=site_id, filename=filename,
        pv_kwp=(site_fields or {}).get("pv_kwp"),
        battery_usable_kwh=(site_fields or {}).get("battery_usable_kwh"),
    )

    fields = dict(site_fields or {})
    if parsed.get("installation_id"):
        fields.setdefault("vrm_installation_id", int(parsed["installation_id"]))
    site = upsert_site(customer["id"], site_id, site_name, **fields)

    summary = ingest_parsed(parsed, site_id, filename=filename)
    summary.update({"customer": customer, "site": site, "site_id": site_id,
                    "warnings": parsed.get("warnings", [])})
    return summary
