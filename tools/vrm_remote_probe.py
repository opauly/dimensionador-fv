from __future__ import annotations
"""
Throwaway discovery spike against Victron's real VRM API (PLAN_PHASE15.md
§8 Step 0). NOT shipped code — deleted or left clearly marked at Step 7.

Reads the token from VRM_TEST_TOKEN (env var only — never a CLI argument,
so it never lands in shell history). Prints findings for one real
installation, answering every [V] row in PLAN_PHASE15.md §0.2:

  1. GET /v2/users/me, GET /v2/users/{idUser}/installations — confirm the
     X-Authorization: Token <token> header works; list real installations.
  2. GET /v2/installations/{idSite}/diagnostics — the answer key for the
     whole mapping. Full dump saved to the scratchpad, not printed (can be
     hundreds of lines); a filtered subset (voltage/alarm/SOC-relevant
     codes) prints inline.
  3. stats?type=custom&attributeCodes[]=Pb,Pc,Pg,Gb,Gc,Bc,Bg&interval=days
     over 7 days — the energy-flow totals §4.4 maps onto energy_daily.
  4. stats?type=custom&interval=15mins for SOC, battery voltage/temp, and
     AC input voltage per phase (codes found in step 2) — the single most
     important unknown: does this repo's outage detector have anything to
     detect on the API path at all (vrm_csv.py's AC-voltage method)?
  5. Deliberately exceed the rate limit once, on a cheap endpoint (repeated
     GET /v2/users/me) — record the actual 429 shape and whether
     Retry-After is present.
  6. GET /v2/installations/{idSite}/alarms — record whether it returns
     anything real (community reports say usually not).

The token itself is never printed, logged, or included in any exception
message raised here — same rule this whole phase holds vrm_remote.py to.
"""
import json
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://vrmapi.victronenergy.com/v2"
SCRATCHPAD = Path(
    "/private/tmp/claude-501/-Users-oscarpauly-Desktop-Pauly---Co-AI---Data-Projects-Dimensionador-Claude/"
    "11bd4dc5-77f0-4b9d-865b-0f7f510de40e/scratchpad"
)
SCRATCHPAD.mkdir(parents=True, exist_ok=True)

TOKEN = os.environ.get("VRM_TEST_TOKEN")
if not TOKEN:
    print("VRM_TEST_TOKEN not set in the environment. Aborting.", file=sys.stderr)
    sys.exit(1)

HEADERS = {"X-Authorization": f"Token {TOKEN}"}


def _get(path: str, params: dict | None = None) -> requests.Response:
    return requests.get(f"{BASE_URL}{path}", headers=HEADERS, params=params, timeout=30)


def _section(title: str) -> None:
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


def main() -> None:
    # ---- 1. Auth + installations -------------------------------------
    _section("1. GET /users/me")
    r = _get("/users/me")
    print(f"status: {r.status_code}")
    if r.status_code != 200:
        print(f"body: {r.text[:500]}")
        print("\nAuth header form failed — stopping here. Do NOT proceed to mapping.")
        return
    me = r.json()
    print(f"response keys: {list(me.keys())}")
    print(json.dumps(me, indent=2)[:1000])
    # Real shape (confirmed live, differs from the plan's guess): the user
    # object nests under "user" and the id field is "id", not "idUser".
    user_obj = me.get("user", {})
    id_user = user_obj.get("id") or me.get("idUser") or user_obj.get("idUser")

    _section("1b. GET /users/{idUser}/installations")
    r = _get(f"/users/{id_user}/installations", params={"extended": 1})
    print(f"status: {r.status_code}")
    installations_raw = r.json()
    print(f"top-level response keys: {list(installations_raw.keys())}")
    records = installations_raw.get("records", installations_raw)
    if isinstance(records, dict):
        records = records.get("installations", records)
    print(f"installation count: {len(records) if isinstance(records, list) else 'n/a'}")
    print(json.dumps(records, indent=2)[:3000])

    if not isinstance(records, list) or not records:
        print("\nNo installations returned — cannot proceed to per-installation probes.")
        return

    # Pick the first real installation for the rest of the probe.
    site = records[0]
    id_site = site.get("idSite")
    print(f"\nUsing installation for remaining probes: idSite={id_site}, name={site.get('name')}")

    time.sleep(0.5)

    # ---- 2. Diagnostics: the answer key --------------------------------
    _section("2. GET /installations/{idSite}/diagnostics")
    r = _get(f"/installations/{id_site}/diagnostics")
    print(f"status: {r.status_code}")
    diag = r.json()
    diag_records = diag.get("records", diag)
    print(f"attribute count: {len(diag_records) if isinstance(diag_records, list) else 'n/a'}")

    diag_path = SCRATCHPAD / "vrm_diagnostics_full.json"
    diag_path.write_text(json.dumps(diag, indent=2))
    print(f"full dump written to: {diag_path}")

    # Filter for the signals we actually care about.
    interesting_keywords = [
        "voltage", "input voltage", "ac input", "ac-in", "vac",
        "state of charge", "soc", "battery",
        "temperature", "temp",
        "alarm", "low battery", "overload",
        "frequency",
    ]
    filtered = []
    if isinstance(diag_records, list):
        for rec in diag_records:
            desc = str(rec.get("description", "")).lower()
            code = str(rec.get("code", "")).lower()
            name = str(rec.get("Device", "")).lower() + " " + str(rec.get("dbusServiceType", "")).lower()
            if any(kw in desc or kw in code or kw in name for kw in interesting_keywords):
                filtered.append({
                    "code": rec.get("code"),
                    "idDataAttribute": rec.get("idDataAttribute"),
                    "description": rec.get("description"),
                    "formatWithUnit": rec.get("formatWithUnit"),
                    "dbusServiceType": rec.get("dbusServiceType"),
                    "instance": rec.get("instance"),
                })
    print(f"\nFiltered (voltage/soc/battery/temp/alarm/frequency) — {len(filtered)} matches:")
    print(json.dumps(filtered, indent=2))
    filtered_path = SCRATCHPAD / "vrm_diagnostics_filtered.json"
    filtered_path.write_text(json.dumps(filtered, indent=2))
    print(f"filtered dump written to: {filtered_path}")

    time.sleep(0.5)

    # ---- 3. Daily energy-flow totals -----------------------------------
    _section("3. GET /installations/{idSite}/stats — energy-flow totals, 7 days")
    now = int(time.time())
    seven_days_ago = now - 7 * 86400
    energy_codes = ["Pb", "Pc", "Pg", "Gb", "Gc", "Bc", "Bg"]
    r = _get(
        f"/installations/{id_site}/stats",
        params={
            "type": "custom",
            "attributeCodes[]": energy_codes,
            "interval": "days",
            "start": seven_days_ago,
            "end": now,
        },
    )
    print(f"status: {r.status_code}")
    print(f"requested codes: {energy_codes}")
    body = r.json()
    print(json.dumps(body, indent=2)[:2500])

    time.sleep(0.5)

    # ---- 4. Fine-grained series: SOC, battery V/temp, AC input voltage --
    _section("4. GET /installations/{idSite}/stats — 15min series (SOC/battery/AC voltage)")
    # Pull whatever codes step 2 flagged as voltage/soc/battery/temp related,
    # capped to a reasonable count to stay well under the rate limit.
    candidate_codes = [f["code"] for f in filtered if f.get("code")][:15]
    print(f"probing candidate codes (from diagnostics filter): {candidate_codes}")
    one_day_ago = now - 1 * 86400
    if candidate_codes:
        r = _get(
            f"/installations/{id_site}/stats",
            params={
                "type": "custom",
                "attributeCodes[]": candidate_codes,
                "interval": "15mins",
                "start": one_day_ago,
                "end": now,
            },
        )
        print(f"status: {r.status_code}")
        body = r.json()
        records_body = body.get("records", body)
        if isinstance(records_body, dict):
            for code, series in records_body.items():
                count = len(series) if isinstance(series, list) else "n/a"
                sample = series[:2] if isinstance(series, list) else series
                print(f"  code={code}: {count} points, sample={sample}")
        else:
            print(json.dumps(body, indent=2)[:2000])
    else:
        print("No candidate codes found from diagnostics filter — cannot probe.")

    time.sleep(0.5)

    # ---- 5. Deliberately exceed the rate limit --------------------------
    _section("5. Deliberately exceeding the rate limit (repeated GET /users/me)")
    statuses = []
    last_body = None
    last_headers = None
    for i in range(60):
        r = _get("/users/me")
        statuses.append(r.status_code)
        if r.status_code == 429:
            last_body = r.text[:500]
            last_headers = dict(r.headers)
            print(f"Hit 429 after {i + 1} requests.")
            break
    else:
        print(f"Did not hit 429 after {len(statuses)} requests.")
    print(f"status sequence (tail): {statuses[-10:]}")
    if last_body is not None:
        print(f"429 body: {last_body}")
        print(f"Retry-After header present: {'Retry-After' in (last_headers or {})}")
        if last_headers:
            rate_headers = {k: v for k, v in last_headers.items() if "rate" in k.lower() or "retry" in k.lower()}
            print(f"rate-limit-related headers: {rate_headers}")

    time.sleep(2)  # let the rate limit window recover before the last call

    # ---- 6. Alarms endpoint ----------------------------------------------
    _section("6. GET /installations/{idSite}/alarms")
    r = _get(f"/installations/{id_site}/alarms")
    print(f"status: {r.status_code}")
    print(json.dumps(r.json(), indent=2)[:2000])

    _section("Done")
    print(f"Full diagnostics dump: {diag_path}")
    print(f"Filtered diagnostics dump: {filtered_path}")
    print("Paste the relevant findings into PLAN_PHASE15.md §0.2, then revoke")
    print("VRM_TEST_TOKEN in the VRM portal and delete it from .env.")


if __name__ == "__main__":
    main()
