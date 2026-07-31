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
                  replace_alarms: bool = True) -> dict:
    """Persist `vrm_csv.parse_export()` output. Returns a summary.

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

    # 1. Alarm events first — the energy_daily trigger reads them.
    if replace_alarms and rows:
        (_t("alarm_events").delete()
         .eq("site_id", site_id)
         .gte("timestamp", parsed["period_start"])
         .lte("timestamp", parsed["period_end"])
         .execute())
    for chunk in _chunks(events):
        _t("alarm_events").insert(chunk).execute()

    # 2. Daily rows — trigger fires per row and scores each day.
    written = 0
    for chunk in _chunks(rows):
        res = _t("energy_daily").upsert(chunk, on_conflict="site_id,date").execute()
        written += len(res.data or chunk)

    # 3. Audit trail.
    log = {
        "site_id": site_id,
        "source": "csv_upload",
        "filename": filename or None,
        "installation_id": (str(parsed["installation_id"])
                            if parsed.get("installation_id") else None),
        "period_start": parsed["period_start"],
        "period_end": parsed["period_end"],
        "sample_count": parsed["sample_count"],
        "rows_written": written,
        "alarm_events_written": len(events),
        "warnings": {"messages": parsed.get("warnings", []),
                     "missing_signals": parsed.get("missing_signals", []),
                     "unscored_alarms": parsed.get("unscored_alarms", {})},
    }
    _t("ingestion_log").insert(log).execute()

    return {"rows_written": written, "alarm_events_written": len(events),
            "period_start": parsed["period_start"], "period_end": parsed["period_end"]}


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
