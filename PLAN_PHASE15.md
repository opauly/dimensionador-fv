# Phase 15 — VRM Monitor: direct ingestion from a customer's own Victron VRM account (personal access token)

**Status:** ready for the coder agent **after Step 0**, with 8 open questions for Oscar flagged in §0.5
**Author:** architect agent, 2026-08-18
**Builds on:** [`PLAN_PHASE14.md`](PLAN_PHASE14.md) (the Next.js web app + `vrm_api` this hangs off),
[`PLAN_PHASE13.md`](PLAN_PHASE13.md) §1 (tenant model), `database/migrations/012_vrm_schema.sql`
(which anticipated this phase three years of phases ago — §1.1 below re-verifies its guesses
rather than inheriting them), `victron/vrm_csv.py` (the CSV mapper whose hard-won rules must
not be re-learned or re-broken).
**Spec sources:** Victron's live VRM API docs and community record (§0.2 — every claim there is
cited and marked *confirmed* or *to verify at Step 0*), `victron-monitor/docs/vrm-report-saas-architecture.md`
§4–§5 (**stale**, see §0.3 for what in it is wrong), `PLAN_PHASE14.md` §1.2/§1.3/§1.12 (the
security rules this phase inherits unchanged).
**Plan doc convention:** same shape as `PLAN_PHASE6.md` / `PLAN_PHASE14.md` — confirmed context,
resolved decisions with their reasoning, then vertical build steps each ending in something
runnable behind its own validation gate.

---

## Goal

A VRM Monitor customer connects their own Victron VRM account **once**, by pasting a personal
access token they generated in their own VRM portal, picks which of their real VRM installations
maps to which of their sites, and from then on their data arrives by a pull from Victron instead
of a manual CSV upload.

"Done" means: from `/app/sites`, a customer pastes a token, sees a list of *their* actual VRM
installations (fetched live, before anything is stored), maps one to a site, clicks **Sync now**,
and the resulting `vrm.energy_daily` rows are numerically comparable — within a measured,
written-down tolerance — to what the same period's CSV export produces. Their token is never
stored in plaintext, never returned to a browser, never logged, and never usable to read another
customer's data.

**Two hard constraints, from Oscar's own framing ("plan how to do that safely without breaking
what we currently have"):**

1. **CSV upload keeps working exactly as it does today.** This is a *second, parallel* ingestion
   path, not a replacement. A customer who never connects a token must not be able to tell this
   phase happened. `victron/vrm_csv.py`'s output for a given file must be **byte-identical**
   before and after this phase (Step 2's gate). `pages/06_vrm_monitor.py` stays untouched except
   for one additive capability, §3.3's Step 4b.

**Added after Step 0 (§3.3): a third path.** Alongside customer self-serve, Oscar's own VRM
personal access token sees his whole fleet, and he wants to link/sync any of it onto any
customer's site himself — the API-era equivalent of uploading a CSV on their behalf. Both models
ship; neither replaces the other.
2. **"Safely" means the same rigor the rest of this product got.** We are storing a third party's
   credential on a customer's behalf, and that credential can read *every installation on their
   VRM account* (§0.2, confirmed). §2 (storage), §3 (tenancy), and §8 (risk table) are the answer.

---

## 0. Confirmed context (do not re-derive)

### 0.1 What already exists in this repo

| Fact | Where |
|---|---|
| `vrm.customers` already carries `vrm_user_id text UNIQUE`, `vrm_account_email`, `vrm_token_secret_id uuid`, `vrm_token_added_at`, `vrm_token_revoked_at` — with a header comment stating that a plaintext token column was **deliberately** never created | migration 012 L50–65 |
| `vrm.sites` already carries `source text CHECK (source IN ('csv_upload','vrm_api'))` and `vrm_installation_id bigint UNIQUE` | migration 012 L96, L114–116 |
| `vrm_installation_id` is **already populated today** on the CSV path, parsed out of the export filename by `vrm_csv.installation_id()` and set in `vrm_api/routers/ingest.py:_do_commit()` | those files |
| `vrm.energy_daily` has `UNIQUE (site_id, date)` **deliberately not keyed on `dump_type`** — migration 012's own comment says "re-ingesting a date via the API replaces the CSV row instead of adding to it" | migration 012 L193–201 |
| `vrm.daily_health` has `UNIQUE (site_id, date, dump_type)` — **a different key**, and `database/vrm_report_db.py:bucket_health_days()` handles duplicate dates per site by *keeping the highest-scoring row*. See §5.3: this is a live trap for a mixed-source site. | migration 012 L257, `vrm_report_db.py` L221–231 |
| The report reader already accepts both sources: `REAL_DUMP_TYPES[VRM] = ("csv_upload", "vrm_api")` | `database/vrm_report_db.py` L35 |
| `victron/ingest.py:ingest_parsed()` hardcodes `"source": "csv_upload"` in its `ingestion_log` write | `victron/ingest.py` L131 |
| `vrm.jobs.kind` has `CHECK (kind IN ('ingest_preview','ingest_commit','report'))` — a new job kind needs an `ALTER` | migration 023 L76–77 |
| Latest applied migration number is **023**. 022 is unrelated Phase 6 work. Next free number: **024** | `database/migrations/` |
| `vrm_api/` is the FastAPI pipeline service; `victron-monitor/web/` is the Next.js app; the trust boundary rules (bearer-only, no CORS, independent tenancy re-check, no raw errors to the browser) are `PLAN_PHASE14.md` §1.2/§1.3/§1.12 and are **already implemented** in `vrm_api/main.py`, `vrm_api/deps.py`, `vrm_api/tenancy.py`, `victron-monitor/web/lib/server/db/` | those files |
| There is **no scheduler anywhere in this repo** — no `.github/workflows/`, no cron, no queue. `vrm_api` runs jobs in-process on Starlette's bounded thread pool | `Glob`, `vrm_api/jobs.py` |
| Phase 12 already **locked GitHub Actions `cron:`** as this project's scheduling mechanism (over Supabase Edge Functions + `pg_cron`), for the weekly-report job | `PHASES.md` Phase 12, "Decisions locked with the user (2026-08-16)" |

### 0.2 Victron's real VRM API — verified against current sources, 2026-08-18; empirically confirmed against Oscar's own account 2026-08-18 (Step 0)

Everything in this table is now **[C] confirmed**, either by a live/current external source or —
for the rows that were **[V]** — by Step 0's real probe (`tools/vrm_remote_probe.py` +
`vrm_probe_followup.py`) against Oscar's own VRM account, token, and a real production
installation (`idSite=523804`, "El Encino (Apartamento)": MultiPlus-II 48/3000/35-50 120V +
Pylontech battery + Cerbo GX). Raw dumps live in the session scratchpad
(`vrm_diagnostics_full.json`, `vrm_diagnostics_filtered.json`); this table is the durable record.

| | Finding | Source |
|---|---|---|
| [C] | Base URL is `https://vrmapi.victronenergy.com/v2`. There is **no OAuth**; the only customer-grantable credential is a Personal Access Token created at **VRM portal → Preferences → Integrations → Access tokens**. | official Python client, community |
| [C] | **The auth header is `X-Authorization`, not `Authorization`.** Two token *types* travel in it: `X-Authorization: Token <personal access token>` and `X-Authorization: Bearer <JWT from /auth/login>`. **We use `Token`.** Victron's own `vrm-api-python-client` sends `Bearer` because it logs in with a password; several community reports are of tokens "not working" purely because `Bearer` was used with a personal access token. Exactly one space after `Token`. Empirically confirmed live in Step 0 — `GET /users/me` returned 200 with `Token`. | victronenergy/vrm-api-python-client, community threads; Step 0 |
| [C] | **A personal access token grants access to every installation the account can see.** Victron has no per-installation token scoping; this is an open, acknowledged feature gap ("Access Tokens: Security risk, No option to limit scope"). The old arch doc's warning was right and if anything understated: it is not just "every site the customer owns" but every site *shared with* that account. Empirically confirmed: Oscar's own token's `/installations` call returned all **13** installations on the account, not just one. | Victron Community; Step 0 |
| [C] | Tokens can be given an **expiry** at creation, and can be revoked by the customer from the same VRM preferences page. So "the token stops working" is a normal, expected event, not an exception path. | victron-vrm client, community |
| [C] | Rate limit: community reports describe a **rolling window of ~200 requests, with one slot freeing every ~0.33 s** (≈3 req/s sustained), `429` returned, `Retry-After` frequently absent, different endpoint classes having different limits. **Step 0 did not reproduce a 429**: 60 rapid sequential `GET /users/me` calls all returned 200. This does not contradict the community figure — `/users/me` is a cheap, likely more-generously-limited endpoint, and 60 requests is well under the reported ~200 window — but the actual limit/`Retry-After` shape remains **unconfirmed by direct observation**. Treat the ~200/~3-req/s figure as a planning assumption, not a verified fact, and keep the client's own throttle (§6.3) as the real safety margin regardless of what Victron's server does. | Victron Community; Step 0 (inconclusive) |
| [C] | `GET /v2/users/me` → the authenticated account. **The id field is `user.id`, not a top-level `idUser`** (the response nests: `{success, user: {id, name, email, country, idAccessToken, accessLevel}}`) — migration 012's comment assumed the wrong shape; corrected here. `GET /v2/users/{idUser}/installations` (optional `extended`) → every installation, `{success, records: [...]}`, each with `idSite`, `name`, `identifier`, `timezone`. These are the two calls the connect flow needs, and they are cheap. | official client; Step 0 (shape correction) |
| [C] | `GET /v2/installations/{idSite}/stats` with `type`, `interval`, `start`, `end` (epoch seconds). `type` values include `venus`, `live_feed`, `consumption`, `kwh`, `solar_yield`, `forecast`, and **`custom`**. With `type=custom` you pass repeated `attributeCodes[]=<code>`. `interval` accepts at least `15mins`, `hours`, `days`. Response is `{records: {...}, totals: {...}}`, each series normally an array of `[epoch_ms, value]` pairs. **Two real shape quirks found in Step 0, both must be handled by `vrm_series.py`'s mapper:** (1) a requested code with **no data for that installation returns the literal value `false`**, not an empty list or a `0` — `vrm_series.py` must check `isinstance(series, list)` before indexing, never assume list. (2) at least one code (`bs`, system-service battery SOC) returned **4-element points `[epoch_ms, v, v, v]`** instead of the usual 2-element `[epoch_ms, v]` — likely a min/max/avg aggregation Victron applies to some "system" instance codes but not "custom" ones. Prefer the plain 2-element codes (`SOC`, not `bs`) where both exist; if a 4-element shape is ever consumed, take index 1, not the last element, unless confirmed which position is the representative value. | community, node-red node, official client; Step 0 (quirks) |
| [C] | The energy-flow attribute codes are VRM's own decomposition and map cleanly onto `energy_daily`: `Pb` PV→battery, `Pc` PV→consumers, `Pg` PV→grid, `Gb` grid→battery, `Gc` grid→consumers, `Bc` battery→consumers, `Bg` battery→grid. Empirically confirmed over a real 7-day window on the test installation: `Pb`, `Pc`, `Bc`, `Gc` returned real daily totals (~20-34 kWh range); `Pg`, `Gb`, `Bg` returned `false` (no data) for every day — consistent with this specific installation being off-grid/non-export, not a mapping error (see the `false`-shape note above). | Victron Community; Step 0 |
| [C] | `GET /v2/installations/{idSite}/diagnostics` returns the **live list of attributes this specific installation actually publishes**, each with its `code`, `idDataAttribute`, `description`, `formatWithUnit`, `dbusServiceType`, `instance`. This is the documented way to discover what a given site exposes — i.e. it is the discovery endpoint Step 0 runs first. Confirmed live: 273 attributes returned for the test installation. | Victron Community; Step 0 |
| [C] | `GET /v2/installations/{idSite}/alarms` exists. Multiple reports of it returning `"alarms": []` while the portal shows a populated alarm log — i.e. it is **not** a reliable alarm-history source. Empirically confirmed: returned `{"alarms": [], "rateLimited": false, ...}` for the real test installation. | Victron Community; Step 0 |
| [C] | **Victron's own terms state the VRM API "is not intended for commercial/professional purposes and is offered without support."** This is a business risk on a paid product, not a technical one. Oscar's decision (§0.5 Q2): accept the risk and handle it separately via Victron's Software Integrator Program. | Victron Community |
| [C] | **Per-phase AC-input voltage IS available as a real 15-minute time series — the single most important finding of Step 0.** Codes `IV1`/`IV2` ("Input voltage phase 1/2", `dbusServiceType=vebus`, `instance=276`) returned **96 real data points over 24h** (matches 15-min granularity exactly, no gaps observed), values in the ~120-121V range. This means `vrm_csv.py`'s existing, trusted outage-detection method (AC-input-voltage absence) **carries over to the API path for VE.Bus systems**, avoiding the NULL-with-warning fallback the plan originally assumed would be needed. Also confirmed available in the same probe: `IF1`/`IF2` (input frequency), `OV1`/`OV2` (output voltage), `OF` (output frequency). Not yet tested: a non-VE.Bus (pure Cerbo/GX-only, no MultiPlus) installation — the fallback path (§4.5) is still needed for those. | Step 0 — confirmed |
| [C] | **The two scored alarm signals ARE available as time series, the same way.** `eL`/`eL1`/`eL2` (Low battery / per-phase) and `eO`/`eO1`/`eO2` (Overload / per-phase) each returned 96 real points over 24h — all reading `0` throughout the window (no alarm condition was active), which confirms the series is live and query-able, not that it is empty/broken (contrast with the `alarms` endpoint above, which really is empty). `Agl` ("Grid alarm" — the known-unreliable signal `vrm_csv.py`'s docstring warns against) is also present as a series, for completeness/cross-checking only, never as the primary signal. | Step 0 — confirmed |
| [C] | **Finest interval actually served**: `interval=15mins` returned exactly 96 points for a 24h window for every sensor code tested (`IV1`, `IV2`, `SOC`, `BT`, `V`, `eL*`, `eO*`) — i.e. real, gapless 15-minute granularity for recent data. **Retention horizon beyond ~24h back was not tested** (Step 0 only queried the last day) — if a longer backfill window (the plan's 31-day default) behaves differently near the edge of what VRM retains at 15-min resolution, that would surface as a real gap during Step 3's fixture comparison, not before. | Step 0 (recent-window confirmed; long-horizon retention still open, defer to Step 3) |
| [C] | **Battery SOC, voltage, and temperature are all available as clean 2-element 15-minute series** via the plain codes `SOC` (state of charge, e.g. 98%), `V` (battery voltage, e.g. 52.19V — note: this is the *battery-service* `V`, distinct from `bs`, see the shape-quirk note above), and `BT` (battery temperature, e.g. 31.1°C), each 96 points over 24h, no gaps. `CT` (an alternate battery-temp code guess) returned `false` for this installation — `BT` is the code that works, at least for a Pylontech/VE.Bus system; do not assume `CT` is universal. | Step 0 — confirmed |
| [C] | **Do `type=kwh`/`type=custom` daily totals agree with integrating power ourselves?** Measured against a real 79-day fixture (§4.6, Step 3): `pv_kwh`/`load_kwh`/`grid_kwh`/`grid_export_kwh` agree within 1-8% — close enough to ship directly. `battery_charge_kwh`/`battery_discharge_kwh` do **not** agree (up to 97%/58% off on individual days) for a structural reason, not measurement noise — Victron's `Pb+Gb`/`Bc+Bg` flow-diagram total is a derived complement of `pv_kwh-load_kwh`, not an independent battery measurement, on a DC-coupled installation. Shipped as `NULL`+warning rather than a number nobody should trust. Also newly confirmed here: 15-minute retention holds at least ~3.3 months back (the only untested part of Step 0's own retention finding), and `interval=days` buckets are plain 24h windows anchored at the caller's `start`, not calendar-day-aligned in any timezone. | Step 3 — resolved |

### 0.3 What the old exploratory doc got wrong, and must not be carried forward

`victron-monitor/docs/vrm-report-saas-architecture.md` §4–§5 is the origin of this idea and is
**partly stale**. Corrections, so nobody re-inherits them:

- ~~"a scheduled worker pulls `/v2/installations/{idSite}/stats`"~~ — the path is right, but the
  doc gives **no auth header** and the obvious guess (`Authorization: Bearer`) is **wrong**
  (§0.2). Nothing about the endpoint shape in that doc was ever verified.
- ~~"separate Supabase project"~~ (its §2) — **not what was built.** Migration 012 put `vrm` in
  the same project. Any reasoning in that doc that depends on project separation is void.
- ~~"per-customer API key (`api_keys` table)"~~ (its §5) — **not what was built.** Customer
  identity is Supabase Auth → `vrm.customers.auth_user_id` (migration 021), and the only API key
  in the system is `PIPELINE_API_KEY`, which authenticates *our own server*, not a customer.
- **Still correct and load-bearing:** no OAuth exists; the token is generated by hand in the
  customer's own VRM preferences; **a token can read every installation on the account, so never
  assume it is scoped to one** — every call must be scoped to a specific `idSite` *we* recorded.

### 0.4 The naming collision, decided deliberately

This repo's own FastAPI service is the package `vrm_api/`. Victron's remote service is also
universally called "the VRM API." Left alone, a stack trace or a `git blame` six months from now
is genuinely ambiguous. Decision:

- **New code that talks to Victron's servers never uses the token "api" in its module name.**
  - `victron/vrm_remote.py` — the authenticated HTTP client for **Victron's** VRM service.
    "remote" because that is what it is from here: someone else's machine, over the internet,
    that can fail, throttle, and revoke.
  - `victron/vrm_series.py` — the mapper from Victron time-series responses → `energy_daily` rows.
    The deliberate sibling of `victron/vrm_csv.py`; the name says what the *input shape* is
    (time series by attribute code) exactly as `vrm_csv` says CSV.
  - `victron/vrm_daily.py` — the format-independent daily-row core extracted from `vrm_csv.py`
    so both mappers share it rather than re-implementing it (§4).
- **Prose rule, enforced in comments and docstrings:** Victron's service is always written
  "**the Victron VRM cloud**" or "**Victron's VRM API**"; ours is always written "**`vrm_api`**"
  in code font. New comments in `vrm_api/` that mention Victron's service must use the long form.
- `vrm_api/routers/vrm_link.py` (connect/validate/disconnect) and `vrm_api/routers/vrm_sync.py`
  (pull) are the two new routers. Reading `vrm_api/routers/vrm_link.py` should immediately say
  "our API's router for linking to Victron's."

### 0.5 Open questions for Oscar — these block specific steps, not the whole phase

1. **A VRM personal access token from Oscar's own account, for Step 0.** *This is a hard blocker
   on Step 0 and therefore on everything.* Nothing in §0.2's `[V]` rows can be answered without a
   real token against a real installation. Preferably a token created *for this purpose* with a
   short expiry, revoked after Step 0.
2. **Victron's "not intended for commercial/professional purposes, offered without support"
   terms** (§0.2). VRM Monitor is a paid subscription that would now depend on that API. Accept
   the risk, ask Victron for written clarification, or keep CSV as the contractual path and treat
   API sync as a convenience? Blocks nothing technically; it changes what the product may promise.
3. **Does v1 need scheduled polling, or is on-demand "Sync now" enough for the first customers?**
   *Working assumption:* on-demand ships in Steps 4–6; scheduling is Step 7 and is **deferrable
   without rework** (§6.4). Answering "on-demand is enough" removes Step 7 and ~1.5 days.
4. **Initial backfill window at connect time.** *Working assumption:* **31 days**, matching
   `rdb.MAX_CUSTOM_RANGE_DAYS` (the report's own detailed-mode ceiling). Longer backfills stay on
   the CSV path via `pages/06_vrm_monitor.py`, exactly as >50 MB uploads already do
   (`PLAN_PHASE14.md` §1.5).
5. **Sync cadence, once Step 7 exists, and whether the customer picks it.** *Working assumption:*
   one daily run at 06:00 America/Costa_Rica, not customer-configurable in v1.
6. **May Oscar paste a customer's token from `/admin`?** *Working assumption and recommendation:
   **no**, in v1.* Admin CSV-upload-on-behalf exists because a CSV is the customer's *data*; a
   token is the customer's *credential to their whole VRM account*. Making Oscar its custodian
   converts a support convenience into a liability. Oscar can still *trigger a sync* for a
   customer who connected their own token, and can *disconnect* one.
7. **`source` semantics when both paths are used on one site.** *Working assumption:* `source` is
   "the path this site's data currently arrives by," **not** an exclusive mode — a CSV upload to
   an API-connected site still works (§5.2). The alternative (hard mode switch, CSV upload
   refused for linked sites) is defensible but loses the "the API is down, just upload the CSV"
   escape hatch on the day it is most needed.
8. **Brand/UX detail:** where the connect entry point lives. *Working assumption:* a panel at the
   top of `/app/sites`, since `source` is a per-site column and site mapping is the real work —
   even though the token itself is account-level (§3.1).

**Steps 1–7 are all blocked on Step 0. Step 0 is blocked only on Q1.**

### 0.6 Oscar's answers — all eight questions, 2026-08-18

1. **Q1 (token for Step 0):** provided — a real personal access token, stored temporarily in root
   `.env` as `VRM_TEST_TOKEN` with explicit deletion instructions. Used to run Step 0 (§0.2 above).
   **Must be revoked in the VRM portal and deleted from `.env` now that Step 0's findings are
   recorded** — not yet done, see the pending-tasks note at the end of this file.
2. **Q2 (commercial-terms risk):** accepted. Oscar will address it separately and directly with
   Victron via **the Software Integrator Program**, not by having the coder change scope. No code
   or contract-language change follows from this in-repo.
3. **Q3 (scheduled polling for v1):** **on-demand "Sync now" is enough for v1.** Step 7 (scheduled
   sync via GitHub Actions `cron:`) is confirmed deferred, per §6.4 — Steps 1–6 ship without it.
4. **Q4 (backfill window, sync cadence, admin-pastes-token):** all three defaults confirmed as
   proposed — **31-day initial backfill**, **15-minute interval** for the fine-grained series (now
   doubly justified: §0.2 confirms 15-min data is real and gapless for the codes that matter), and
   **no, admin does not paste a customer's token** in v1 (Q6's working assumption stands).
5. **Q5, Q7, Q8:** not explicitly re-answered; their working assumptions (daily 06:00
   America/Costa_Rica cadence once Step 7 exists; `source` as non-exclusive path-of-record; connect
   entry point on `/app/sites`) stand as written above and are not blocking.

All eight questions are now resolved. Nothing in §0.5 blocks Step 1.

---

## 1. Re-verifying migration 012's three-phases-old anticipations

Migration 012 guessed at this phase's shape before Phase 13, 14, or `vrm_api` existed. Most of it
holds up remarkably well. Two things do not, and one is a **latent bug that exists today**.

### 1.1 `vrm.sites.vrm_installation_id UNIQUE` is wrong and must become `UNIQUE (customer_id, vrm_installation_id)`

Migration 012 called it "globally unique, and the authoritative key for API sync." That was true
in a world with one kind of customer. It is not true in the world Phase 13/14 built, which sells
**two account types** (`vrm.customers.account_type IN ('installer','owner')`, migration 021, and
the landing page's own installer/owner toggle):

- An **installer** customer's VRM account contains their clients' installations.
- One of those clients can independently be an **owner** customer of ours, with their own VRM
  account, that VRM account having the same installation shared into it.
- Both are legitimately our customers. Both legitimately have a `vrm.sites` row for that
  installation. A global `UNIQUE` makes the second one's ingest fail with a Postgres unique
  violation — and it fails **today, on the CSV path**, because `_do_commit()` already writes
  `vrm_installation_id` from the export filename.

**Decision:** migration 024 drops the global unique index and creates
`UNIQUE (customer_id, vrm_installation_id) WHERE vrm_installation_id IS NOT NULL`. This is
strictly more permissive than today, so it cannot break an existing row. Tenancy is unaffected —
`site_id` remains globally unique and remains the key every child table references.

### 1.2 `vrm_token_secret_id` on `vrm.customers` (not on `vrm.sites`) — confirmed correct

Migration 012's reasoning ("a token can read EVERY installation on that account, which is why the
token lives here (once) rather than per site") is **exactly right** and §0.2 confirms the premise
against current sources. One token per customer. Keep as designed.

The same comment's second half — "and why every API call must still be scoped to the specific
idSite the customer connected" — becomes §3.2's enforced rule rather than an aspiration.

### 1.3 `vrm_token_revoked_at` alone is not enough state — confirmed by what it can't express

The column was anticipated and never wired to anything. It can say "this token is dead" but not
*why*, or *when we last knew it was alive*, which is precisely what a customer-facing "your VRM
connection stopped working" banner and Oscar's admin view both need. Migration 024 adds
`vrm_token_last_checked_at`, `vrm_token_last_ok_at`, `vrm_token_last_error` on `vrm.customers`,
and `vrm_last_synced_at`, `vrm_last_sync_error`, `vrm_sync_enabled` on `vrm.sites` (§7).

### 1.4 `vrm.sites.source` — keep the column and the CHECK, correct the meaning in a `COMMENT`

`source` was written as though it were exclusive. §5.2 makes it "the path this site's data
currently arrives by." The column and its CHECK are unchanged; migration 024 adds a `COMMENT ON
COLUMN` stating the refined meaning, so the next reader doesn't infer exclusivity from the name.

### 1.5 `vrm_user_id UNIQUE` — keep, but the connect endpoint owns the error message

Two of our customer rows connecting the same VRM account is almost always a mistake (someone
pasted the wrong token), and the unique index is a good guard. But a raw Postgres unique violation
must never surface: the connect endpoint checks for an existing `vrm_user_id` first and returns a
typed `vrm_account_already_linked` code that the UI renders as "This VRM account is already
connected to another VRM Monitor account."

---

## 2. Token storage — Supabase Vault, reached only through `SECURITY DEFINER` wrappers in `vrm`

Migration 012 assumed Vault. Per this repo's own standard (Phase 14 verified every assumption
empirically rather than trusting old comments), here is what is actually true, and what Step 1
must prove before any UI exists.

### 2.1 What's confirmed about Supabase Vault today

- Vault is a first-party Supabase feature, **enabled by default on Supabase projects**, exposing
  `vault.create_secret(secret, name, description) → uuid`, `vault.update_secret(id, ...)`, and a
  decrypting view `vault.decrypted_secrets`. The underlying `vault.secrets` holds only ciphertext.
- The root encryption key lives **outside** the database, so a plain `pg_dump` of the database
  does not contain anything that can decrypt a secret. That is precisely the property migration
  012's comment wanted ("a plaintext token column would put a credential … into every database
  dump, backup, and accidental `SELECT *`").
- `pgsodium` is deprecated; **Vault is not** — its backend was reimplemented without pgsodium
  (merged March 2025) with the same public API. So this is not a bet on a dying extension.
- Access is `service_role`/`postgres`-shaped by design; `anon`/`authenticated` have nothing.

### 2.2 The practical obstacle, and the design that solves it

`vrm_api` talks to Postgres exclusively through PostgREST (`database/supabase_client.py` →
`supabase-py`). **PostgREST can only reach schemas explicitly exposed in the Data API settings,
and the `vault` schema is not exposed — and must never be.** Exposing `vault` to widen access for
one feature would put every secret in the project one PostgREST call away from anything holding a
key. So:

**Decision: three `SECURITY DEFINER` functions in the `vrm` schema (already exposed), which are
the only way any application code touches Vault.**

```
vrm.set_customer_vrm_token(p_customer_id uuid, p_token text)   -> void
vrm.read_customer_vrm_token(p_customer_id uuid)                -> text
vrm.clear_customer_vrm_token(p_customer_id uuid)               -> void
```

Properties that make this the right shape, each of which the coder must actually implement (not
just assume from this list):

- `EXECUTE` is `REVOKE`d from `PUBLIC`, `anon`, `authenticated`; `GRANT`ed only to `service_role`.
  A `SECURITY DEFINER` function with a default `PUBLIC` execute grant is the classic way to build
  a privilege-escalation hole; this one is closed explicitly, in the same migration.
- `SET search_path = ''` (fully-qualified identifiers inside), the standard `SECURITY DEFINER`
  hardening.
- **The vault secret id never leaves the database.** `set_...` calls `vault.create_secret`
  (or `vault.update_secret` when `vrm_token_secret_id` is already populated) *and* writes
  `vrm.customers.vrm_token_secret_id` / `vrm_token_added_at` / clears `vrm_token_revoked_at` in
  the same statement. `vrm_api` passes a `customer_id` and a token; it never handles a vault id.
  This is what makes the "pointer, never the secret" design from migration 012 actually hold.
- `read_...` returns `NULL` (not an error) when the customer has no live token, so a sync of a
  disconnected customer is a clean no-op rather than an exception path.
- The secret is named deterministically (`vrm_token:<customer_id>`) so an orphaned secret is
  identifiable, and `clear_...` deletes the vault row rather than just nulling the pointer — a
  disconnect must actually destroy the credential, not merely forget where it is.

### 2.3 The honest cost, recorded rather than discovered later

Vault secrets **do not survive a `pg_dump`/`pg_restore` into a new Supabase project** — the new
project gets a fresh root key and cannot decrypt copied ciphertext. This **conflicts with
migration 012's stated design goal** that the `vrm` schema stay "dumpable into its own Supabase
project." Recorded in migration 024's header, with the mitigation: a token is not derived data and
cannot be reconstructed anyway; on such a migration every customer simply reconnects, and the
`vrm_token_revoked_at`/reconnect flow this phase builds is already the mechanism for that. No
telemetry is lost — only the credential, which is the correct thing to lose in a project move.

### 2.4 The fallback, and the bar it must clear before being taken

**Only if Step 1's empirical gate fails** (Vault absent, `create_secret` unavailable, or the
wrapper cannot round-trip through PostgREST on this project): envelope encryption —
AES-256-GCM via `cryptography`, a 32-byte key held **only** in `vrm_api`'s environment
(`VRM_TOKEN_KEY`), ciphertext + nonce in a new `vrm.customer_vrm_tokens` table, `vrm.customers`
keeping only the row pointer. This is **strictly worse** than Vault (the key sits in an env var
the Next.js server must never receive, rotation is a manual re-encrypt, and a leaked env dump is
game over) and is therefore the fallback, not the default. **Do not implement both. Do not
implement this one without recording in this file that Vault was tried and why it failed.**

### 2.5 Rules that hold regardless of storage mechanism

1. **The token exists in exactly two places in transit**: the browser's POST body (TLS, one time)
   and `vrm_api`'s request handler. The Next.js route handler forwards it and **must not** log it,
   cache it, put it in a URL, a cookie, a redirect, a server-action return value, or a client
   component's props (`PLAN_PHASE14.md` §3, restated because this is the first credential in the
   product that belongs to someone else).
2. **No endpoint ever returns a stored token**, in whole or in part. The UI shows connection
   *state* (`connected as <vrm_account_email> since <date>`), never the secret. A "last 4
   characters" hint is deliberately **not** offered: it's a partial credential disclosure that
   buys nothing when the account email already identifies the connection.
3. **No token in any log line, ever** — including exception messages. `victron/vrm_remote.py`
   raises errors that carry the HTTP status and endpoint, never the request headers.
4. **`vrm.jobs.params` must not contain the token.** A sync job's params are
   `{customer_id, site_id, start, end}`; the token is read from Vault inside the job, per run.
   This is easy to get wrong because every other job in this API stores its whole request body.

---

## 3. Tenancy — how customer A's token can never pull customer B's data

The failure mode named in Oscar's brief ("customer A's token can never be used to pull customer
B's data even if a `site_id` gets confused somewhere") gets three independent controls, in the
three processes that could get it wrong.

### 3.1 Where the token is entered and validated (the UI/flow decision)

Entry point: **a "Victron VRM account" panel at the top of `/app/sites`.** The token is
account-level (§1.2) but every meaningful action is per-site mapping, and `source` is a per-site
column — so the panel and the site table belong on one page.

The flow, in three deliberate steps, none of which stores anything until the last:

1. **Paste + validate (nothing stored).** `POST /api/vrm/validate` → `vrm_api`
   `POST /v1/vrm-link/validate {customer_id, token}` → Victron `GET /v2/users/me`, then
   `GET /v2/users/{idUser}/installations`. Returns `{vrm_user_id, vrm_account_email,
   installations: [{id_site, name, identifier}]}` and **nothing is written to Postgres or Vault.**
   This is the "cheap who-am-I call before committing to store it" the brief asks for, and it
   doubles as the thing that makes the next step honest: the customer sees *their own real
   installation names* before mapping.
2. **Explicit mapping.** For each returned installation the customer chooses: *ignore*, *link to
   an existing site (dropdown of their own sites)*, or *create a new site (name prefilled from the
   VRM installation name)*. **Nothing is auto-mapped**, not even when there is exactly one
   installation and one site — §0.2 is explicit that a token sees every installation on the
   account, and "the token's only site" is an assumption this design refuses to make. Creating
   sites here is gated by `canAddSite()` / `site_limit`, same as everywhere else.
3. **Connect.** `POST /v1/vrm-link/connect {customer_id, token, mappings[]}` → re-validates the
   token (the customer may have taken minutes to map), stores it via `vrm.set_customer_vrm_token`,
   writes `vrm_user_id` / `vrm_account_email`, and for each mapping sets `vrm_installation_id`
   and `source='vrm_api'` on that site. Optionally kicks off the initial backfill (§0.5 Q4).

**Disconnect** is a first-class action on the same panel: `vrm.clear_customer_vrm_token` (deletes
the vault secret), stamp `vrm_token_revoked_at`, set each linked site back to
`source='csv_upload'` and `vrm_sync_enabled=false`. **Telemetry already ingested is not deleted** —
disconnecting a credential must not delete a year of a customer's history. The UI says so.

### 3.2 The three controls

1. **Next.js** (`victron-monitor/web/lib/server/db/`): every new function takes `customerId`
   first; `assertOwnsSite()` before any site-keyed operation; `requireCustomer()` as the first
   statement of every new route handler. Unchanged rules, new call sites.
2. **`vrm_api`** re-derives ownership itself (`vrm_api/tenancy.py`), as it already does — it does
   not trust that Next.js checked.
3. **New, specific to this phase — the installation binding is the third control.** A sync never
   accepts an `idSite` from a request. It reads `vrm.sites.vrm_installation_id` for a
   `(customer_id, site_id)` pair that already passed `assert_owns_site()`, and calls Victron with
   *that*. Concretely: `vrm_sync.py` has no code path in which an installation id from a request
   body reaches `victron/vrm_remote.py`. Additionally, at every sync the returned installation's
   `idSite` is compared to the stored one and a mismatch aborts the run — cheap, and it is the
   check that turns "a `site_id` got confused somewhere" from silent cross-contamination into a
   failed job.

`scripts/test-scoping.ts` (Phase 14's regression test for exactly this) gains cases for the new
functions and must keep passing at every step.

### 3.3 A second, parallel token model: Oscar's own fleet, admin-side — added 2026-08-18

Confirmed with Oscar after Step 0: he wants **two independent ways data gets linked and synced**,
not one:

1. **Customer self-serve** (§3.1 above, unchanged) — a customer pastes their own VRM personal
   access token, maps their own installations to their own sites, syncs and reports on their own
   data. Vault-backed, per-customer, exactly as designed.
2. **Admin fleet access (new)** — Oscar's own VRM personal access token already sees his whole
   install base (Step 0: 13 installations on one account). He wants to browse *that* fleet and
   link/sync **any** installation onto **any** customer's site — the same role CSV upload already
   plays for him today (`pages/06_vrm_monitor.py`'s "Cargar" tab, and the Next.js `/admin` panel),
   just pulling from the API instead of a file. Customers who never touch their own VRM account at
   all are still fully served, because Oscar can connect and sync on their behalf, the same way he
   already uploads a CSV on their behalf.

These are not alternatives to pick between — **both ship**, because they answer different
questions: "can a customer self-manage their own connection" (1) and "can Oscar keep his existing
install-everything-himself workflow, just faster than a CSV export" (2). A given site may end up
linked via either path; nothing about `vrm.sites.source='vrm_api'` (§1.4) distinguishes them, and
nothing needs to — the data written is identical either way.

**Why this does *not* reopen §0.5 Q6** ("no, admin does not paste a customer's token"): that
decision was about Oscar becoming custodian of a *customer's own* credential — a liability
transfer. This is different. It is Oscar's *own* token, which he already holds, used the same way
he already holds `RESEND_API_KEY` and `PIPELINE_API_KEY`. No customer's credential is ever touched
by admin code.

**Storage — a platform secret, not a Vault-per-customer one.** There is exactly one admin fleet
token, so it does not belong in `vrm.customers`/Vault at all — that machinery exists specifically
to isolate *many* tenant-owned secrets from each other, which does not apply to a single
platform-wide credential. **Corrected 2026-08-18** (the original wording here assumed `vrm_api` has
its own, separate env file — it does not; checked the actual code before Step 3): `vrm_api` has no
env file of its own and reads everything via `database/supabase_client.py`'s bare `load_dotenv()`,
which finds the root `.env` (both `vrm_api` and Streamlit are launched from the repo root). Step
4b's own design also has `pages/06_vrm_monitor.py` read this token **directly**, not through
`vrm_api` — so a physically separate file was never going to hold both readers anyway. It lives in
the shared root `.env`, next to `PIPELINE_API_KEY`/`RESEND_API_KEY` — every credential already there
is server-side-only by the same rule (never `NEXT_PUBLIC_*`, never `victron-monitor/web/.env.local`),
so this is consistent with existing practice, not a new exception:

```
VRM_ADMIN_TOKEN=<value>
```

The token that sat in root `.env` as `VRM_TEST_TOKEN` (generated for Step 0) is the same real
credential — Oscar confirmed keeping it permanently rather than the throwaway-then-revoke plan Step
0 originally described. It is now `VRM_ADMIN_TOKEN` in root `.env`, with a header comment recording
its real, permanent purpose and every reader that will use it.

**New endpoints, admin-authenticated, reusing the same pipeline (`vrm_remote.py` /
`vrm_series.py` / `vrm_daily.py`) as the customer path — only the token source and the
authorization check differ:**

- `GET /v1/vrm-fleet/installations` — calls Victron with `VRM_ADMIN_TOKEN`, returns every
  installation on Oscar's account plus, for each, whether it is already linked (and to which
  `customer_id`/`site_id`) by joining against `vrm.sites.vrm_installation_id`. Admin-role check
  only (Phase 14's existing admin auth), no `assertOwnsSite()` — that check does not apply because
  there is no single owning customer in this flow, by design.
- `POST /v1/vrm-fleet/link {vrm_installation_id, customer_id, site_id | new_site: {...}}` — mirrors
  the customer connect step's mapping UI (§3.1 step 2): pick an existing site or create one inline
  (reuses `ingest.upsert_customer`/`upsert_site`, exactly as the Streamlit CSV tab already does).
  Sets `vrm.sites.vrm_installation_id` and `source='vrm_api'` on the target site. The
  `UNIQUE (customer_id, vrm_installation_id)` constraint from §1.1 already tolerates the same
  installation being linked under a different `customer_id` than a customer's own self-serve link
  would use — no schema conflict between the two paths.
- `POST /v1/vrm-fleet/sync {site_id}` — same job machinery as `POST /v1/vrm-sync` (§6.1), just
  reads `VRM_ADMIN_TOKEN` instead of calling `vrm.read_customer_vrm_token`. One new parameter on
  the shared sync function, `token_source: "customer" | "admin"` — never a request body field the
  caller controls; the route handler fixes it.

**Auditability — one new column, not a new table.** `vrm.ingestion_log` (§5.4) gains
`triggered_by text CHECK (triggered_by IN ('customer','admin','schedule'))`. Every existing write
site sets it: CSV upload from the Streamlit tool or `/admin` → `'admin'`; a customer's own CSV
upload or "Sync now" → `'customer'`; Step 7's scheduled run, if built → `'schedule'`. This is what
keeps "why did this report look wrong" (§5.4's founding question) answerable once two actors can
both touch the same site's data.

**UI surfaces — both, as asked:**

- **Next.js `/admin` panel**: a new "VRM fleet" section next to the existing customer/site admin
  views (Phase 14 Step 7 already built the admin shell and auth) — lists Oscar's live installations
  via `GET /v1/vrm-fleet/installations`, lets him link/create + sync, same interaction shape as
  §3.1's customer flow, admin-scoped.
- **`pages/06_vrm_monitor.py`** (Streamlit, operator-only tool, already has full DB access via the
  service-role key): the "Cargar" tab gains a second mode alongside "Cargar CSV" —
  "Sincronizar desde VRM API" — same customer/site picker already in `tab_upload()`, but instead of
  a file uploader it lists Oscar's fleet (via a small `vrm_api` call, or `victron/vrm_remote.py`
  directly since this tool already runs server-side with full trust) and syncs on selection. Reuses
  `tab_sites()`'s existing site table unchanged — a synced site just shows `Instalación VRM`
  populated, same column CSV-linked sites already populate.

**Reports need no change.** `vrm_report_db.py` is already schema/source-agnostic (§5.4's own
framing) — a site fed by admin-fleet sync reports identically to one fed by CSV or customer
self-serve, because all three write the same `vrm.energy_daily`/`vrm.daily_health`/
`vrm.alarm_events` shape. "Customers can retrieve reports" and "Oscar can retrieve any report" were
already true the moment §4's mapping lands; nothing in this section adds report-generation work.

**Where this lands in the build steps (§8):** Step 1 (migration 024 + Vault) is **unchanged** — the
customer-token path still needs it. The `triggered_by` column is a one-line addition to Step 1's
migration. The fleet endpoints and both UIs land after Step 4 (`vrm_api` validate/connect/sync)
exists, as a **new Step 4b**, parallel to Step 5's customer UI rather than nested inside it — see
§8's updated step list.

---

## 4. Data mapping — what is genuinely reusable from `victron/vrm_csv.py`, and what is not

This is a **new mapping problem, not a transport swap.** The CSV path parses named columns from a
3-row-header wide CSV; the Victron VRM cloud returns arrays of `[epoch_ms, value]` per attribute
code. But the split between "CSV-shaped" and "format-independent" inside `vrm_csv.py` is cleaner
than it first looks, and it falls exactly where we need it.

### 4.1 The line: everything downstream of `tidy()` is already format-independent

| `vrm_csv.py` member | Shape | Fate |
|---|---|---|
| `load_vrm_csv`, `_pick_all`, `_pick`, `tidy`, `SIGNALS`, `YIELD_TODAY`, `CHARGE_STATE`, `installation_id` | **CSV-specific** (3-row header, `Device::Description` naming, duplicate columns) | Stay in `vrm_csv.py`, untouched |
| `integrate`, `_min_max_nonzero`, `_grid_outages` (+ `_GRID_PRESENT_V`, `_GRID_SITE_MIN_V`, `_GRID_SITE_MIN_SHARE`, `_MIN_OUTAGE_MIN`, `_PLAUSIBLE_BATT_TEMP_C`, `MAX_GAP_S`), `to_energy_daily_rows`, `validate_export`'s non-CSV checks | **Format-independent** — they operate on the *tidied* frame's canonical columns (`pv_w`, `load_w`, `grid_import_w`, `grid_v_l1`, `soc_pct`, `batt_v`, `batt_temp_c`, …), not on anything CSV | **Move to `victron/vrm_daily.py`**, shared by both mappers |
| `_category_active`, `alarm_events`, `unscored_alarm_summary` | CSV-column-shaped, but the **episode semantics** (WARNING→CLEARED, open-in-alarm counts as an episode) are not | Episode edge-detection moves to `vrm_daily.py` taking a boolean series; the column-finding stays in `vrm_csv.py` |

So: **`victron/vrm_series.py`'s job is to produce a frame with the same canonical tidied columns
from Victron cloud time series.** Once it does, the three traps — outage-from-AC-voltage, NaN
inherits previous state, and (in spirit) don't-halve-multi-device-sums — are inherited, not
re-implemented. That is the whole point of the split, and it is why this phase does **not** get to
write a second outage detector.

### 4.2 The extraction must be provably behaviour-preserving

`vrm_csv.py` keeps every public name and signature it has today (`parse_export`,
`to_energy_daily_rows(raw, tidied, site_id, ...)`, `alarm_events`, `validate_export`,
`installation_id`, `VrmCsvError`, `MAX_GAP_S`), re-exporting from `vrm_daily` where the body
moved. `PLAN_PHASE14.md` §3's "do not modify the signatures of `victron/*.py`" is respected.

**Step 2's gate is byte-identical output:** the same reference export
(`vista-atenas-lp-m3`, 2026-05-10..07-28, already this repo's fixture) through `parse_export()`
before and after the extraction must produce an identical dict — compared with a deep equality
check on the serialized result, not eyeballed. If it doesn't, the extraction is wrong and nothing
proceeds.

### 4.3 `MAX_GAP_S = 300` is a live landmine for the API path — call it out now

`integrate()` refuses to integrate across gaps longer than 300 s, so a logging hole isn't billed
as steady power. **At `interval=15mins`, every single sample gap is 900 s** — so integrating
Victron cloud data with the CSV path's constant would return approximately **zero kWh for every
day**, silently, with no error. It would look like every API-connected site generated nothing.

`integrate()` already accepts `max_gap_s`; `to_energy_daily_rows()` and `_grid_outages()` do not
thread it through. The `vrm_daily.py` extraction must make `max_gap_s` an explicit parameter of
every function that uses it, with `vrm_csv.py` passing `300` (preserving today's behaviour
exactly) and `vrm_series.py` passing `2 × interval_seconds`. **This is a named acceptance check in
Step 3, not a footnote:** a day of API-sourced data whose `pv_kwh` is 0 while `soc` clearly cycled
is the tell.

### 4.4 kWh: prefer Victron's own daily energy-flow totals; use fine-grained series for state

- **Energy columns** (`pv_kwh`, `load_kwh`, `grid_kwh`, `grid_export_kwh`,
  `battery_charge_kwh`, `battery_discharge_kwh`) come from
  `stats?type=custom&attributeCodes[]=Pb,Pc,Pg,Gb,Gc,Bc,Bg&interval=days`, combined as:
  `pv = Pb+Pc+Pg`, `load = Pc+Gc+Bc`, `grid import = Gb+Gc`, `grid export = Pg+Bg`,
  `battery charge = Pb+Gb`, `battery discharge = Bc+Bg`.
  Rationale: these are VRM's own accumulations of the same quantities the CSV path integrates by
  hand — using them avoids compounding 15-minute averaging error over a day, and it is the number
  the customer sees in their own VRM portal, which matters when they cross-check our report.
- **State columns** (`min/max/avg_soc`, `min/max_voltage`, `min/max/avg_temperature`,
  grid voltage/frequency extremes, and the **outage state machine**) come from
  `interval=15mins` series, run through the shared `vrm_daily.py` code.
- **`pv_yield_kwh_sc0/sc1/_mppt`, `battery_reached_float`** are per-solar-charger CSV artifacts.
  If Step 0 finds equivalent per-instance attributes, map them; otherwise write `NULL` and record
  a warning. **Do not fabricate `battery_reached_float`** — `compute_daily_health()` deducts 5
  points when it is false, so defaulting it either way silently biases every API-sourced site's
  health score relative to a CSV-sourced one. If it can't be determined, the honest options are
  (a) leave it `NULL` and accept the SQL's `COALESCE(..., false)` penalty consistently, or (b)
  set it from `max_soc >= 100` only, which is half of the CSV path's own rule. **Recommendation:
  (b)**, because it is a subset of the existing rule rather than a new one, and record it as a
  known scoring difference in the ingestion log's warnings.
- **`hours_covered` / `complete_day`**: computed from real returned sample coverage, same ≥23 h
  rule. A sync of "today" always produces a partial day; that is correct and already handled
  downstream.

### 4.5 Outages and alarms: no data is better than fabricated data

If Step 0 finds AC-input voltage is not retrievable as a series, then for API-sourced days
`outage_count` and `outage_minutes` are written **`NULL`, not `0`**, and every affected
`ingestion_log` row carries the warning `"outages cannot be detected on the API path for this
installation"`. `vrm_csv.py`'s own header explains why this matters: `Grid alarm` read flat "no
outages ever" across 9 real exports while AC input sat at 0.00 V for hours, and the whole voltage
rewrite exists to remove that silent zero. Reintroducing it through a different door would be the
same bug with a new cause. Same rule for alarms: no derivable alarm signal → **zero events plus a
warning**, never a substitute taxonomy.

### 4.6 Step 3 validation results — measured tolerances, 2026-08-18

**Build:** `victron/vrm_series.py` (`fetch_and_map()`), as specified above. Validation script lived
in the coder's session scratchpad (not committed — it is a thin driver around `vrm_csv.parse_export()`
and `vrm_series.fetch_and_map()`, reproducible from this section's numbers and the shipped code).
Real CSV fixture
(`vista-atenas-lp-m3`/`idSite=844478`, `~/Downloads/844478_0_VistaAtenasLPM32FloorPool_log_
20260510-0000_to_20260728-1538.csv`) vs. the same installation pulled live through
`VrmRemoteClient(VRM_ADMIN_TOKEN)` for the identical window (2026-05-10..2026-07-28), both parsed
offline, nothing written to Postgres.

**Retention-horizon question (§0.2's last open row) — answered: yes, fully.** A single
`interval=15mins` request spanning the whole 80-day window (oldest sample ~101 days before "today")
returned real, gapless data: `SOC`/`V`/`BT` = 7647/7647 expected points, `IV1`/`eL`/etc. =
7633/7647 (99.8%) — no retention cliff found anywhere in the tested range. Step 0's "only confirmed
for 24h" caveat is resolved: 15-minute data survives at least ~3.3 months back on this account.
`interval=days` bucket boundaries were also empirically confirmed to be plain 24-hour windows
anchored at the caller's `start` parameter, **not** calendar-day-aligned in any timezone — this is
why `vrm_series.py` converts `start`/`end` to local midnight (`America/Costa_Rica`, UTC-6, fixed —
see the module's own docstring for why that specific assumption) before calling `get_stats()`,
rather than passing the caller's date range straight through.

**Per-column agreement, 79 full common days** (2026-07-28 excluded — partial on the CSV side, since
that export stops mid-day; compared separately, no surprises: both paths agree the day was partial/
full for their own respective cutoffs):

| Column | Mean CSV | Mean API | Mean \|diff\| | Max \|diff\| | Max % | **Tolerance shipped as** |
|---|---:|---:|---:|---:|---:|---|
| `pv_kwh` | 60.36 | 62.65 | 2.32 | 4.24 | 6.1% | within **8%** |
| `load_kwh` | 49.86 | 50.29 | 0.54 | 1.73 | 4.2% | within **5%** |
| `grid_kwh` | 1.48 | 1.48 | 0.018 | 0.23 | 3.3% | within **15% or 0.25 kWh abs**, whichever is greater (values are often near-zero on this self-consumption site, where a pure-% tolerance is unstable) |
| `grid_export_kwh` | 0.00 | 0.00 | 0.00 | 0.00 | — | exact, **on this fixture only** — this installation never exports (`Pg`/`Bg` both absent from `get_diagnostics`, matching the CSV path's own `grid_export_kwh=0` every day); a genuinely-exporting installation's agreement is **not yet measured** — flagged, not assumed |
| `battery_charge_kwh` | 21.91 | *(shipped as NULL)* | 5.76 | 12.36 | **97%** | **NULL + warning** — see below |
| `battery_discharge_kwh` | 21.35 | *(shipped as NULL)* | 7.53 | 15.21 | **58%** | **NULL + warning** — see below |
| `min_soc` | 54.82 | 55.10 | 0.28 pts | 1.5 pts | — | within **2 percentage points** |
| `max_soc` | 97.30 | 97.29 | 0.02 pts | 0.6 pts | — | within **1 percentage point** |
| `avg_soc` | 78.09 | 78.58 | 0.63 pts | 3.8 pts | — | within **4 percentage points** |
| `min_voltage` | 48.83 | 48.98 | 0.16 V | 0.7 V | — | within **1 V** |
| `max_voltage` | 52.03 | 51.95 | 0.08 V | 0.38 V | — | within **1 V** |
| `min_temperature` | 21.08 | 21.06 | 0.25 °C | 0.6 °C | — | within **1.5 °C** |
| `max_temperature` | 25.94 | 25.87 | 0.29 °C | 1.1 °C | — | within **1.5 °C** |
| `outage_count`/`outage_minutes` | 9 events / 32.9 min-mean | 5 events / 32.5 min-mean | — | — | — | see below — resolution-limited, not shippable as a strict numeric tolerance |

**`battery_charge_kwh`/`battery_discharge_kwh`: shipped as `NULL`+warning, deviating from §4.4's
literal `Pb+Gb`/`Bc+Bg` formula.** This is the most important finding of Step 3. §4.4's formula
disagreed with the CSV path by a mean of 26%/35% and up to **97%/58%** on individual real days — far
outside every other energy column's 1-8% band. Root cause, confirmed rather than guessed: on this
fixture (a DC-coupled architecture — PV feeds the battery/DC bus directly through solar chargers,
there is no "PV - AC-coupled" signal), `(Pb+Gb) - (Bc+Bg)` is algebraically forced to equal
`pv_kwh - load_kwh` to two decimal places on every sampled day — it is Victron's flow-diagram's
*derived complement* of the PV/load balance, not an independent measurement of the battery. The
CSV path's `battery_charge_kwh`/`battery_discharge_kwh` come from an actual battery-monitor/shunt
(or GX-estimated) power reading, which captures real conversion losses and self-consumption the
simple flow-balance arithmetic never sees — confirmed by the fact that CSV's own
`battery_charge_kwh - battery_discharge_kwh` does **not** equal CSV's `pv_kwh - load_kwh` (e.g.
2026-05-10: net battery −0.82 kWh vs. pv−load +11.03 kWh — a real, physically expected gap the flow
diagram's numbers cannot have by construction). Both figures are real Victron output; they answer
different questions, and only the sensor-derived one is comparable to what the CSV path — and a
customer's own VRM portal battery widget — report. §4's own validation instructions pre-authorize
exactly this outcome ("a column that can't meet a reasonable tolerance ships as NULL-with-warning,
not as a number nobody should trust") — this is that outcome, not an improvised redesign.
`pv_kwh`/`load_kwh`/`grid_kwh` are unaffected: `pv_kwh = Pb+Pc+Pg` sums to Victron's own total PV
production regardless of how the Pb/Pc/Pg split is internally allocated, which is why it agrees
tightly even though its `Pb` component individually does not correspond to a net battery reading.

**Outages — resolution-limited agreement, documented as such rather than forced into a single
number.** For outages long enough to survive 15-minute sampling (all but two of the CSV's 9 real
events), the API path found the same days, start/end within one 15-minute bucket (e.g. CSV
08:58:33→10:00:35 vs. API 09:00:00→09:45:00), and `outage_minutes` agreed within **~12%** worst
case (51.0 vs. 45.0 min) and typically within 1-5%. **Two of the CSV's 9 outages (2.5 min and 4.0
min — both under one 15-minute sample interval) were invisible to the API path** — a structural,
expected consequence of 15-minute vs. ~1-minute sampling, not a mapping defect: an outage shorter
than the sampling interval can start and end between two consecutive samples and leave no trace.
**Shipped behaviour:** `outage_count`/`outage_minutes` are computed exactly as specified (voltage-
absence via the shared `vrm_daily._grid_outages()`, `NULL` when `IV1`/`IV2` are both unavailable);
no special-casing was added to "fix" the short-outage miss, because there is nothing to fix — it is
an honest reading of what 15-minute data can see. This is recorded here as an operating
characteristic API-connected customers and Oscar should know about, not as a defect blocking Step 4.

**Alarm episode counts — also resolution-limited, noted for awareness, not a Step 3 gate.** Low
Battery episodes: 482 (CSV) vs. 144 (API); Overload episodes: 147 (CSV) vs. 90 (API). Same cause as
the outage undercount — brief threshold-crossing chatter visible at ~1-minute CSV sampling is
smoothed away at 15-minute API sampling. `count_alarm_episodes()`'s SQL is shared and correct for
either input; the *inputs* are not resolution-equivalent. This means a site's health score is not
expected to be identical before/after switching that site from CSV to API sync for the same real
conditions — a real, useful fact for Oscar and a future Step 5 UI to be aware of, not something
Step 3 is scoped to close.

**`pv_kwh > 0` regression assertion (§4.3's `MAX_GAP_S` landmine): PASS.** All 80 days had
`pv_kwh > 0` (range 22.6-90.8 kWh); the first sunny day checked was 2026-05-10 at `pv_kwh=55.33`.

**`pv_yield_kwh_sc0`/`_sc1`/`_mppt` and `battery_reached_float`:** per-solar-charger yield is `NULL`
on the API path — `get_diagnostics()` shows this installation has two separate `Solar Charger`
device instances both publishing `code="YT"`, and `stats?attributeCodes[]=YT` returns one series
with no visible way to request a specific instance, so there is no reliable way to attribute yield
to `sc0` vs. `sc1` through this endpoint. `battery_reached_float` uses §4.4's recommendation (b)
only (`max_soc >= 100`) — confirmed correct in the sample (`true` on every day `max_soc` hit 100 in
both paths).

**Nothing in this step wrote to the database** — `fetch_and_map()` itself makes no Postgres calls,
and the validation script only calls `vrm_csv.parse_export()` and `victron.vrm_series.
fetch_and_map()`, both pure in-memory mappers.

**Step 3 status: done and independently verified, 2026-08-18.** Read `victron/vrm_series.py` in
full; re-ran two checks myself rather than only trusting the coder's report. (1) The load-bearing
algebraic claim behind the `battery_charge_kwh`/`battery_discharge_kwh` `NULL`-with-warning
decision — `(Pb+Gb)-(Bc+Bg) == pv_kwh-load_kwh` — re-derived live against a **different day the
coder never quoted** (2026-06-15, not 2026-05-10): `16.2716` both ways, exact to 4 decimals. This
is the single most consequential deviation in Step 3 and it holds up independently. (2) Smoke-tested
`fetch_and_map()` itself end-to-end against a fresh 3-day live window (2026-06-10..12, not part of
the coder's own validation run) — ran cleanly, sensible output, correct warnings emitted, `None` on
the two battery columns as designed. `python -m py_compile` clean on every touched file; `git diff
--stat` confirms only `victron/vrm_series.py` is new since Step 2 — `vrm_daily.py`/`vrm_csv.py`
untouched.

**One real, open gap this step did not close (correctly out of scope for Step 3, but a genuine
Step 4/5 action item):** `fetch_and_map()` has no timezone parameter and hardcodes
`LOCAL_TZ = "America/Costa_Rica"` for day-bucketing, because Victron's `stats`/`diagnostics`
endpoints return no per-installation timezone. This matched the Vista Atenas fixture's real portal
timezone (`America/Guatemala`, also UTC-6, no DST) by coincidence — but `vrm.sites.timezone`
already varies per real site in this product. Step 4 (the `vrm_api` sync job) must pass the site's
own `vrm.sites.timezone` value into a new parameter on `fetch_and_map()` rather than inherit this
constant, or every non-Costa-Rica site's calendar days will be silently mis-bucketed once real sync
jobs run. Flagging explicitly here so it isn't rediscovered as a bug later.

---

## 5. Coexistence with CSV — concretely

### 5.1 Both paths stay available for every site, forever

Nothing about the CSV upload UI, its route handlers, `vrm_api/routers/ingest.py`, or
`pages/06_vrm_monitor.py` changes behaviourally. The only edit anywhere in the CSV path is
`victron/ingest.py:ingest_parsed()` gaining a **keyword-only `source: str = "csv_upload"`**
argument that flows into the `ingestion_log` row (§5.4) — additive, default-identical.

### 5.2 A `csv_upload` site *can* be linked; that is the normal case

Existing customers already have sites with history. Linking sets
`vrm_installation_id` + `source='vrm_api'` + `vrm_sync_enabled=true` on that site; disconnecting
reverses it. API connection is **not** restricted to brand-new sites — restricting it would mean
every existing customer has to abandon their history to use the feature, which is not a product.

Because `vrm.energy_daily` is keyed `(site_id, date)` with no `dump_type` in the key (migration
012's deliberate choice), a re-ingest of a date **replaces** it whichever path wrote it first.
Last writer wins, per date. The UI must say this plainly on the connect screen: *"Days already
imported from a CSV will be replaced by the data pulled from VRM."*

### 5.3 The `daily_health` duplicate-row trap — must be fixed by this phase

`vrm.daily_health` is keyed `(site_id, date, dump_type)`. So the first API sync of a date that
already has a CSV-sourced health row produces **two** rows for one day. `vrm_report_db.py:
bucket_health_days()` deduplicates by *keeping the highest-scoring row per date* — meaning a
mixed-source site would silently report the more flattering of two health scores, which is the
worst possible way to be wrong about a health metric.

**Decision:** after writing energy rows, the ingest path deletes `vrm.daily_health` rows for the
touched `(site_id, date)` pairs whose `dump_type` differs from the one just written. One row per
site per day, always. This is done in `victron/ingest.py` (shared by both paths, so a *CSV*
re-ingest of an API-sourced day is cleaned up symmetrically), guarded by a comment naming
`bucket_health_days()` as the reason. Migration 024 records the same reasoning in a
`COMMENT ON TABLE vrm.daily_health`.

Deliberately **not** done: changing `daily_health`'s unique constraint to `(site_id, date)`. It
would diverge from `monitoring.daily_health`, and schema parity between the two is what lets one
reader serve both (migration 012's founding constraint).

### 5.4 `vrm.ingestion_log` gets a row per sync run — this is non-negotiable

The table's own header says it exists "to answer *why did this customer's report look wrong*."
That question must stay answerable regardless of source. Every sync writes one row:

| column | API-path value |
|---|---|
| `source` | `'vrm_api'` |
| `filename` | `NULL` |
| `installation_id` | the VRM `idSite` actually called |
| `period_start` / `period_end` | the requested window |
| `sample_count` | number of time-series samples received |
| `rows_written` | day rows upserted |
| `alarm_events_written` | 0 when alarms aren't derivable (with a warning saying so) |
| `warnings` | `{messages, missing_signals, unscored_alarms, days_replacing_csv: N, http_retries: N}` |

`days_replacing_csv` is new and specific to this phase: when a sync overwrites days that came from
a CSV, that fact is recorded and surfaced in the sync result and in `/admin/activity`. It is the
difference between "the report changed" and "we can explain why the report changed."

`/app/upload`'s existing Uploads-history table becomes an **Activity** table showing both sources,
distinguished by an icon/label. No new table.

---

## 6. Where the pull happens, and on what trigger

### 6.1 v1: on-demand, as a job, reusing everything that already exists

`POST /v1/vrm-sync` `{customer_id, site_id, start, end}` → creates a `vrm.jobs` row of a **new
kind `vrm_sync`** (migration 024 alters the `kind` CHECK) → runs in the same in-process
background-task model as ingest and report jobs (`PLAN_PHASE14.md` §1.6). The browser polls the
existing `/api/pipeline/jobs/[id]` proxy, which already refuses another customer's job. `JobProgress`
renders it with no changes.

**No preview/commit two-step.** That split exists because a 140 MB CSV must be parsed exactly once
(`vrm_api/routers/ingest.py`'s docstring). A sync is idempotent, cheap to repeat, and has no
uploaded artifact — a preview step would be ceremony. The **connect** flow's validate-then-connect
is the equivalent "never write on the first click" guarantee for the part that matters (the token).

### 6.2 Trigger: a "Sync now" button per linked site, plus a "Sync all" on the panel

Default range: from `MAX(date)` already present for that site (or `now − backfill_window` on first
sync) through yesterday, clamped to the §0.5 Q4 ceiling. Today is deliberately excluded by default
— a partial current day is correct data but confusing on a dashboard; an "include today" toggle is
a one-line addition if Oscar wants it.

### 6.3 Scheduled sync (Step 7): GitHub Actions `cron:` → one authenticated endpoint

`POST /v1/vrm-sync/run-due` (pipeline-key auth, same as everything else) selects every site with
`source='vrm_api' AND active AND vrm_sync_enabled` whose customer has a live token and whose
`vrm_last_synced_at` is older than the cadence, and syncs each **sequentially** with per-site
failure isolation (one site's failure is logged and skipped, exactly as
`runAllWeeklyReports()` already does and as Phase 12 specifies). A `.github/workflows/vrm-sync.yml`
with a `cron:` trigger `curl`s it.

**Why GitHub Actions and not the alternatives, in this repo's terms:**

- **Phase 12 already locked GitHub Actions cron** as this project's scheduling mechanism, for the
  same reason it applies here: there is no always-on machine of Oscar's, and a `launchd` job on a
  personal Mac is a reliability regression. Using a second, different scheduler for the second
  scheduled job in the product is how a solo operator ends up with two things to remember.
- **Not an in-process timer thread in `vrm_api`.** It looks free (the container is always on) but
  it silently couples "does the sync run" to "did the container restart," gives no run history,
  and double-runs the moment there are two instances. `vrm.jobs` gives per-run history either way;
  the trigger should be somewhere you can see it failed.
- **Not Render Cron Jobs.** Perfectly reasonable and would keep everything on one host — noted as
  the alternative if Oscar prefers not to give GitHub Actions a secret. It is a separate paid
  service and a second billing surface.
- **Not `pg_cron` + `pg_net`.** Already rejected once, in Phase 12, for this project.

Rate-limit shape: sequential per-site syncs with the client's own ≤2 req/s ceiling (§0.2's ~3 req/s
refill) keeps a whole nightly run far under the 200-request window even at dozens of sites. A
per-run request budget in `vrm_remote.py` makes that a guarantee rather than an expectation.

### 6.4 Step 7 is deferrable

If Oscar answers §0.5 Q3 with "on-demand is enough for now," Steps 0–6 ship a complete, useful
feature and Step 7 is dropped. Nothing in Steps 0–6 is designed around scheduling existing.

---

## 7. Migration 024 — the whole schema change, in one file

`database/migrations/024_vrm_api_ingestion.sql`, header written in the explanatory style of 012 /
021 / 023 (what changed, what was tried and rejected, what would make us revisit). Idempotent.

1. **`vrm.customers`**: `+ vrm_token_last_checked_at timestamptz`, `+ vrm_token_last_ok_at
   timestamptz`, `+ vrm_token_last_error text` (§1.3).
2. **`vrm.sites`**: `+ vrm_last_synced_at timestamptz`, `+ vrm_last_sync_error text`,
   `+ vrm_sync_enabled boolean NOT NULL DEFAULT false` (§1.3). `vrm_sync_enabled` defaults false so
   existing rows are unaffected and linking is always an explicit act.
3. **Drop** the global unique on `vrm.sites.vrm_installation_id`; **create**
   `UNIQUE (customer_id, vrm_installation_id) WHERE vrm_installation_id IS NOT NULL` (§1.1), with
   the installer/owner reasoning in the comment.
4. **`vrm.jobs.kind` CHECK** gains `'vrm_sync'` (drop + recreate the constraint).
5. **The three Vault wrapper functions** (§2.2), with `SET search_path = ''`, `REVOKE ... FROM
   PUBLIC, anon, authenticated`, `GRANT EXECUTE ... TO service_role`.
6. **`COMMENT ON`**: `vrm.sites.source` (§1.4, "current path, not exclusive"),
   `vrm.daily_health` (§5.3, the `bucket_health_days` dedup reason),
   `vrm.customers.vrm_token_secret_id` (§2.3, the pg_dump portability caveat).
7. **`vrm.ingestion_log`**: `+ triggered_by text CHECK (triggered_by IN ('customer','admin',
   'schedule'))` (§3.3) — who/what caused this write, independent of `source` (which path). Backfill
   existing rows to `'admin'` (every row so far came from the Streamlit operator tool).
7. **Revisit trigger in the header:** *if Victron ever ships per-installation token scoping, or an
   OAuth flow, the `set/read/clear` wrappers and the connect flow must be revisited together —
   a narrower credential changes §3.2's third control from "we bind the installation" to "the
   credential is already bound," and half-adopting it would leave both.*

**Not done, and stated so nobody adds it:** no RLS policies (`PLAN_PHASE14.md` §1.2 rule 3 —
`anon`/`authenticated` still hold zero grants on `vrm`, so there is nothing for a policy to
police); no `dump_type`/`source` CHECK constraints (`monitoring` parity, migration 012).

---

## 8. Build steps

Each step ends in something runnable plus a validation you can execute.
**Do not start step N+1 until step N's validation passes.**

---

### Step 0 — Discovery spike against Oscar's own VRM account (blocked on §0.5 Q1; ~0.5 day)

**Build:** `tools/vrm_remote_probe.py` — a throwaway, *not-shipped* script (it lives in `tools/`
like this repo's other one-off scripts, and it is deleted or left clearly marked at Step 7). Reads
a token from an env var (**never** an argument — shell history), and prints, for one installation:

1. `GET /v2/users/me` and `GET /v2/users/{idUser}/installations` — confirm the header form
   `X-Authorization: Token <token>` works and record the exact response shapes and field names.
2. `GET /v2/installations/{idSite}/diagnostics` — dump every `code` / `description` /
   `formatWithUnit`. **This is the answer key for the whole mapping.** Save the output to the
   scratchpad and paste the relevant subset into §0.2 of this file.
3. `stats?type=custom&attributeCodes[]=…&interval=days` for `Pb,Pc,Pg,Gb,Gc,Bc,Bg` over 7 days.
4. `stats?type=custom&interval=15mins` for the SOC, battery voltage, battery temperature, and —
   critically — **AC input voltage per phase** codes found in (2). Record whether each returns
   data, and how far back.
5. Deliberately exceed the rate limit once, on a cheap endpoint: record the status, the body, and
   whether `Retry-After` is present.
6. Probe `GET /v2/installations/{idSite}/alarms` and record whether it returns anything real.

**Validate:** every `[V]` row in §0.2 is answered and **this file is edited to record the answers**
before any other code is written. If AC-input voltage turns out to be unavailable, §4.5's
NULL-with-warning path is confirmed as the shipped behaviour and Oscar is told, because it means
API-sourced sites report no outages — a real product difference, not an implementation detail.

**Step 0 status: done, 2026-08-18.** All `[V]` rows in §0.2 converted to `[C]` with real findings
against Oscar's own account and a real production installation. Headline result: AC input voltage
**is** available as a clean 15-minute series (`IV1`/`IV2`), so §4.5's NULL-with-warning fallback is
**not** the default path for VE.Bus systems — it only applies to non-VE.Bus installations, still
untested. SOC/battery-voltage/battery-temperature and the two scored alarm signals are all
confirmed available the same way. One genuinely open item carried into Step 3 rather than blocking
Step 1: whether VRM's own daily totals agree with our own integration (§0.2's last `[V]` row).

**Revised after Step 0, 2026-08-18: the probe token is not revoked.** Oscar decided (§3.3) to keep
using this same real token permanently as the admin fleet credential, not discard it. It has moved
out of the throwaway-probe framing: root `.env`'s `VRM_TEST_TOKEN` line is now `VRM_ADMIN_TOKEN`,
kept permanently in the shared root `.env` (§3.3's corrected storage note — `vrm_api` has no
separate env file of its own). `tools/vrm_remote_probe.py` and the scratchpad follow-up script
remain reference-only and can be deleted at Step 7 as originally planned — they are not the
shipped fleet-browse code path (§3.3's new endpoints are).

---

### Step 1 — Migration 024 + Vault, proven end to end with no UI (~1 day)

**Build:** migration 024 (§7) in full. `vrm_api/secrets.py` — a tiny module whose only job is
calling the three wrapper RPCs via `get_client().schema("vrm").rpc(...)`, with a header comment
carrying §2's rules.

**Validate:**
- Round-trip a **fake** token string through `set_ → read_ → clear_` from a Python REPL.
- `SELECT * FROM vrm.customers` shows `vrm_token_secret_id` populated and **no plaintext
  anywhere** — grep the whole row's text representation for the fake token; zero hits.
- `SELECT * FROM vault.secrets` shows ciphertext; `vault.decrypted_secrets` (as `postgres`) shows
  the fake token. This is the actual proof Vault works on *this* project.
- With the **anon** key, calling each wrapper RPC via PostgREST → permission denied. With the anon
  key, `GET /rest/v1/rpc/read_customer_vrm_token` under `Accept-Profile: vault` → denied/404.
- `clear_` actually deletes the `vault.secrets` row (not just the pointer).
- Re-run the migration → no error (idempotent).
- Existing CSV ingest still works unchanged (`pages/06_vrm_monitor.py`, one small file).
- **If any of this fails, stop and take §2.4's fallback — recording here why.**

**Step 1 status: done and fully verified, 2026-08-18.** Migration 024 applied via the Supabase SQL
Editor. `tools/run_migration_024.py` confirmed every PostgREST-reachable check (all 7 new columns
present, fake-token round-trip through `set_/read_/clear_` clean, no plaintext on `vrm.customers`,
`read_` returns `NULL` post-disconnect, anon key denied on all three RPCs). The two Vault-only
checks were run by hand in the SQL Editor against a live throwaway secret: `vault.secrets.secret`
was real ciphertext, `vault.decrypted_secrets.decrypted_secret` matched the fake token exactly —
the actual proof Vault decrypts correctly on this project, not just that the wrappers ran without
raising. §2.4's fallback was not needed. Throwaway test customer and its Vault secret deleted
afterward. `git status` confirmed no changes to `victron/ingest.py` or `pages/06_vrm_monitor.py`.

---

### Step 2 — `victron/vrm_daily.py` extraction + `victron/vrm_remote.py` client (~1.5 days)

**Build:**
- `victron/vrm_daily.py` — the format-independent core moved out of `vrm_csv.py` (§4.1), with
  `max_gap_s` threaded through every function that needs it (§4.3). `vrm_csv.py` keeps every
  public name and behaviour, delegating.
- `victron/vrm_remote.py` — the Victron VRM cloud client. `X-Authorization: Token <token>`; base
  URL from `VRM_REMOTE_BASE_URL` (default `https://vrmapi.victronenergy.com/v2`); a self-imposed
  ≤2 req/s pacer; exponential backoff with jitter on 429/5xx honouring `Retry-After` when present;
  a per-run request budget; a hard timeout; typed exceptions (`VrmRemoteAuthError`,
  `VrmRemoteRateLimited`, `VrmRemoteUnavailable`, `VrmRemoteNotFound`) that **never** carry
  headers or the token. Functions: `get_me`, `list_installations`, `get_diagnostics`,
  `get_stats(id_site, *, type, interval, start, end, attribute_codes=None)`.

**Validate:**
- **The byte-identical gate (§4.2):** `parse_export()` on the reference export before and after
  the extraction produces an identical serialized dict. Automate the comparison; do not eyeball it.
- A deliberately wrong token → `VrmRemoteAuthError`, and the token string appears in **no** log
  line (grep the captured logs).
- Force a 429 (or simulate one) → backoff happens, the budget caps total attempts, the error type
  is `VrmRemoteRateLimited` and not a generic failure.
- `pages/06_vrm_monitor.py` and the Phase 14 upload flow both still ingest a real CSV correctly.

**Step 2 status: done and independently verified, 2026-08-18.** The real `vista-atenas-lp-m3`
fixture was located at `~/Downloads/844478_0_VistaAtenasLPM32FloorPool_log_20260510-0000_to_20260728-1538.csv`
(145,334,218 bytes, matches the plan's description exactly) — not checked into git, but present on
disk. Independently re-ran the byte-identical gate outside the coder's own report: checked out
`vrm_csv.py` from git HEAD (pre-extraction) into a separately-loaded module, ran `parse_export()`
on the real fixture through both versions, and confirmed **matching SHA256 hashes** on the full
serialized output (80 rows, 1258 alarm events, 9 outages, 2 warnings, identical in both). Also
independently re-ran the fake-token test against the real live Victron API: a garbage token raises
`VrmRemoteAuthError` with message `"Victron VRM API rejected the token (401 on GET /users/me)."` —
confirmed the token string does not appear anywhere in the exception. `git diff --stat` confirmed
the only files touched were `victron/vrm_csv.py` (diff-reviewed line by line — every removed block
reappears verbatim, or with only `max_gap_s` threading added, in the new module) plus the two new
files; `victron/ingest.py` and `pages/06_vrm_monitor.py` are untouched. `MAX_GAP_S = 300` was kept
in `vrm_csv.py` rather than duplicated into `vrm_daily.py` (a reasonable reading of §4.1: the
constant is this path's own concrete choice, while `vrm_daily.py`'s functions take `max_gap_s` as a
required argument with no default of their own).

---

### Step 3 — `victron/vrm_series.py`: the mapping, measured against the CSV fixture (~2 days)

**Build:** `victron/vrm_series.py` — `fetch_and_map(client, id_site, site_id, start, end, *,
pv_kwp, battery_usable_kwh, interval="15mins") -> dict` returning **the same shape
`vrm_csv.parse_export()` returns** (`rows`, `alarm_events`, `warnings`, `missing_signals`,
`period_start/end`, `sample_count`, `installation_id`), so `victron/ingest.py:ingest_parsed()`
consumes it with no branching. Internally: build the canonical tidied frame from the fine-grained
series, take energy columns from the daily energy-flow totals (§4.4), and run everything else
through `vrm_daily.py`.

Its module docstring is a **peer of `vrm_csv.py`'s** — it names the traps *it* inherits (and from
where), the ones that don't apply, and the ones that are new (the `MAX_GAP_S` interval mismatch;
VRM's own totals vs. our integration; unavailable signals becoming NULL rather than 0).

**Validate — this is the most important gate in the phase:**
- Pick a site that has **both** a real CSV export and API access (Oscar's own —
  `vista-atenas-lp-m3` is this repo's existing fixture). Pull the **exact same window** through
  both paths and produce a per-column, per-day **agreement table**, in the same spirit as the
  original CSV validation (`vrm-report-v1-implementation-plan.md` §7).
- Accept only with a **written tolerance per column** recorded in this file (e.g. energy columns
  within X%, SOC extremes exact, outage minutes exact if voltage is available). A column that
  can't meet its tolerance ships as NULL-with-warning, not as a number nobody trusts.
- **Explicitly assert `pv_kwh > 0` on a sunny day** — the `MAX_GAP_S` landmine (§4.3) presents as
  a clean-looking zero.
- If AC-input voltage is available: outage timestamps from the API path match the CSV path's for
  the same window. If not: `outage_count`/`outage_minutes` are `NULL` and the warning is present.
- Nothing writes to the database in this step; the mapper is exercised offline against real
  responses.

**Step 3 status: done, 2026-08-18 — see §4.6 for the full agreement table and reasoning.**
`victron/vrm_series.py` built and validated against the real `vista-atenas-lp-m3`/`idSite=844478`
CSV fixture and the live Victron VRM API for the identical 2026-05-10..07-28 window. Headline
results: `pv_kwh`/`load_kwh`/`grid_kwh`/`grid_export_kwh` and every state-extreme column (SOC,
voltage, temperature) agree within the tolerances recorded in §4.6; the `pv_kwh > 0` regression
assertion passed on all 80 days; outage timestamps match within one 15-minute bucket for outages
long enough to survive that sampling resolution (two sub-15-minute CSV outages were invisible to
the API path, a documented, structural limitation, not a bug). **One deviation from §4.4's literal
formula, pre-authorized by §4's own validation instructions:** `battery_charge_kwh`/
`battery_discharge_kwh` ship as `NULL`+warning rather than `Pb+Gb`/`Bc+Bg`, because that formula
turned out to be a derived complement of `pv_kwh-load_kwh` rather than an independent battery
measurement on this (DC-coupled) architecture, and disagreed with the CSV path's battery-monitor
figure by up to 97%/58% on real days — see §4.6 for the full reasoning and the confirmation that
this is structural, not noise. `python -m py_compile victron/vrm_series.py` clean. Nothing in this
step touched Postgres.

---

### Step 4 — `vrm_api`: validate / connect / disconnect / sync (~2 days)

**Build:**
- `vrm_api/routers/vrm_link.py` — `POST /v1/vrm-link/validate` (stores nothing),
  `POST /v1/vrm-link/connect`, `POST /v1/vrm-link/disconnect`, `GET /v1/vrm-link/status`.
  All take `customer_id` and run `tenancy.get_customer()` first; every mapping's `site_id` goes
  through `tenancy.assert_owns_site()`. `vrm_account_already_linked` handled as a typed code (§1.5).
- `vrm_api/routers/vrm_sync.py` — `POST /v1/vrm-sync` → a `vrm_sync` job; `POST /v1/vrm-sync/run-due`
  (used at Step 7, built here). The job reads the token from Vault per run (§2.5 rule 4), reads
  `vrm_installation_id` from the already-ownership-checked site row (§3.2 control 3), calls
  `vrm_series.fetch_and_map`, then `victron/ingest.py:ingest_parsed(..., source="vrm_api")`.
- `victron/ingest.py` — the keyword-only `source` argument (§5.1) and the `daily_health`
  cross-`dump_type` cleanup (§5.3). Both additive; the CSV path's behaviour is unchanged.
- Failure handling per §9: 401/403 → stamp `vrm_token_revoked_at` + `vrm_token_last_error`,
  disable further syncs for that customer; 429 → fail the job with a retry message, do **not**
  touch the token state; installation missing → per-site `vrm_last_sync_error`, token untouched.

**Validate:**
- `curl` the whole flow with a real token: validate → connect → sync → rows in `vrm.energy_daily`
  with `dump_type='vrm_api'` and an `ingestion_log` row with `source='vrm_api'`.
- Re-run the same sync → row counts do not grow; alarm episodes do not double; exactly **one**
  `daily_health` row per date (this is §5.3's regression check).
- Sync a date range that already has CSV-sourced rows → rows are replaced, `days_replacing_csv`
  is reported, and **one** `daily_health` row remains per date.
- **Tamper tests**, aimed straight at `vrm_api` with a valid pipeline key: another customer's
  `site_id` → 403, nothing written. A body carrying an `id_site` that differs from the stored one
  → rejected (there should be no field to carry it; assert that too).
- Revoke the token in the VRM portal mid-test → the next sync fails cleanly, stamps
  `vrm_token_revoked_at`, and does not retry in a loop.
- `vrm.jobs.params` for a sync job contains **no token** (§2.5 rule 4) — assert on the stored row.
- Existing ingest/report endpoints and the Phase 14 upload flow are unaffected.

**Step 4 status: done and independently verified, 2026-08-18.** `vrm_api/routers/vrm_link.py`
(`validate`/`connect`/`disconnect`/`status`) and `vrm_api/routers/vrm_sync.py`
(`vrm-sync`/`vrm-sync/run-due`) built; `victron/ingest.py` gained keyword-only `source`/
`triggered_by` plus the §5.3 `daily_health` cross-`dump_type` cleanup; `victron/vrm_series.py`
gained the `tz` parameter closing Step 3's flagged timezone gap. Re-ran independent checks beyond
the coder's own report, all against live data: (1) `tenancy.assert_owns_site()` denies a second
throwaway customer access to the first's site — the exact tamper scenario `vrm_sync.py`'s tenancy
control depends on; (2) a full connect → sync → disconnect round trip against the real admin token
and installation 844478, for a fresh 2-day window the coder's own run never touched — real rows
landed in `energy_daily` with `dump_type='vrm_api'`, `ingestion_log` recorded `source='vrm_api'`,
`triggered_by='customer'`, and the stored `vrm.jobs.params` JSON does **not** contain the token
string; (3) read `vrm_series.py`'s `tz` threading line by line — confirmed `zone` (not the old
hardcoded `LOCAL_TZ` constant) actually reaches both `_series_to_pandas()` call sites, not just the
window-boundary calculation, so the fix is real and not superficial. `python -m py_compile` clean
on every touched/new file. `git status` confirms scope: no changes to `victron-monitor/web/`,
`pages/06_vrm_monitor.py`, or any Step 4b file.

**One real cleanup action item, not yet done — flagged by the coder, confirmed structurally sound
by the reasoning but not independently re-inspected (Vault is unreachable via PostgREST, so this
needs the Supabase SQL Editor, as `postgres`):** three of the coder's own validation runs deleted a
throwaway customer directly instead of calling `disconnect` first, leaving 3 orphaned
`vault.secrets` rows (2 hold the real `VRM_ADMIN_TOKEN` value, 1 a fake test string) with no
`vrm.customers.vrm_token_secret_id` pointing at them anymore. Low severity — unreachable by any
live code path, and migration 024's own header already accepts orphaned-secret cleanup as a known,
occasional manual task — but should be run before Step 4 is considered fully closed:

```sql
DELETE FROM vault.secrets
WHERE name LIKE 'vrm_token:%'
  AND id NOT IN (SELECT vrm_token_secret_id FROM vrm.customers WHERE vrm_token_secret_id IS NOT NULL);
```

---

### Step 4b — Admin fleet access: fleet browse/link/sync + both UIs (§3.3; ~2 days)

**Build:**
- `vrm_api/routers/vrm_fleet.py` — `GET /v1/vrm-fleet/installations` (calls Victron with
  `VRM_ADMIN_TOKEN`, joins against `vrm.sites.vrm_installation_id` to show link state per
  installation), `POST /v1/vrm-fleet/link` (create-or-reuse customer + site via
  `ingest.upsert_customer`/`upsert_site`, then set `vrm_installation_id`/`source='vrm_api'`),
  `POST /v1/vrm-fleet/sync` (same job machinery as `POST /v1/vrm-sync`, `token_source="admin"`).
  Admin-role check only — no `assertOwnsSite()` (§3.3 explains why that check does not apply here).
- `vrm.jobs`/`vrm_sync.py` gain the `token_source: "customer" | "admin"` parameter fixed by the
  route handler, never client-supplied; `"admin"` reads `VRM_ADMIN_TOKEN` from env instead of
  calling `vrm.read_customer_vrm_token`.
- Every write site for `vrm.ingestion_log` (CSV upload, customer sync, admin sync) sets the new
  `triggered_by` column (§3.3, migration 024 §7 item 7).
- Next.js `/admin` panel: new "VRM fleet" section (`app/(portal)/admin/vrm-fleet/`), same
  interaction shape as §3.1's customer mapping step, admin-scoped.
- `pages/06_vrm_monitor.py`: the "Cargar" tab gains a "Sincronizar desde VRM API" mode alongside
  "Cargar CSV" (§3.3) — same customer/site picker already in `tab_upload()`, fleet list instead of
  a file uploader, direct call into `victron/vrm_remote.py` (this tool already runs server-side
  with full trust, no `vrm_api` hop required, matching every other page in this Streamlit app).
- Root `.env`'s `VRM_TEST_TOKEN` line is removed once `vrm_api`'s own `.env` carries
  `VRM_ADMIN_TOKEN` — the same real token, renamed, no longer throwaway.

**Validate:**
- `GET /v1/vrm-fleet/installations` returns Oscar's real fleet with correct link state for
  already-linked sites.
- Link an unlinked installation to a **new** customer+site inline, then to an **existing** one —
  both write `vrm_installation_id`/`source='vrm_api'` correctly; the `UNIQUE (customer_id,
  vrm_installation_id)` constraint does not block linking the same installation under a different
  `customer_id` than any existing self-serve link.
- Admin sync writes `ingestion_log` with `source='vrm_api'`, `triggered_by='admin'` — distinguish
  from a customer-triggered sync of the same site in the same table.
- Tamper test: a non-admin session hitting any `/v1/vrm-fleet/*` route → 403.
- The Streamlit "Sincronizar desde VRM API" mode round-trips against a real installation and the
  resulting site is indistinguishable in `tab_report()` from a CSV-sourced one.
- Leak checks repeat: `VRM_ADMIN_TOKEN` in no log line, no `vrm.jobs.params`, no Next.js bundle.

**Step 4b status: done and independently verified, 2026-08-18.** `vrm_api/routers/vrm_fleet.py`
(`installations`/`link`/`sync`), the Next.js `/admin/vrm-fleet` page + proxy routes, and
`pages/06_vrm_monitor.py`'s new "Sincronizar desde VRM API" mode all built on top of the
already-verified Steps 1–4, with three corrections to the plan's pre-Step-4 wording applied (no
separate `vrm_api/.env` — `VRM_ADMIN_TOKEN` lives in the shared root `.env`; `vrm_sync.py:_do_sync()`
gained an optional `token` parameter rather than a `token_source` enum; the admin gate is entirely
Next.js's `requireAdmin()`/`requireAdminForRoute()`, not a new in-`vrm_api` check). Re-ran the single
most safety-critical claim independently, with a sharper test than the coder's own: connected a
throwaway customer's **own** token via the customer self-serve path first, confirmed their
`vrm_token_last_ok_at`/`_last_checked_at` were `NULL`, then ran an **admin**-path sync on that exact
same customer's site — confirmed the customer's token-state row is **byte-identical before and
after** (the `is_customer_token` guard in `_do_sync()` genuinely holds, not just exists on paper).
Also independently confirmed: `ingestion_log` rows for the two paths are distinguishable
(`triggered_by='admin'` vs `'customer'`) on the same site; `VRM_ADMIN_TOKEN` appears nowhere in any
`app/`/`lib/`/`components/` source file under `victron-monitor/web/` (grepped directly — the two
remaining matches are server-only-file comments naming the env var, not its value, in files that
either have no `'use client'` directive or import `server-only`); `npm run typecheck` passes clean
independently (not just re-trusted from the coder's report); `python -m py_compile` clean on every
touched file. Read the full `pages/06_vrm_monitor.py` diff — confirmed CSV mode's `ingest_parsed()`
call site is untouched (zero new kwargs passed) and only the new API-mode branch passes
`source="vrm_api", triggered_by="admin"`.

**One legitimate, deliberately out-of-scope gap, not a defect:** `vrm_api/routers/ingest.py:_do_commit()`
— the CSV path shared by `/app/upload` (customer) and `/admin/upload` — still never sets
`ingestion_log.triggered_by`; it stays `NULL` for both. The coder correctly scoped this out (Step 4b's
task only asked for the new fleet-sync and Streamlit-API-mode paths to set it) rather than silently
expanding into `IngestPreviewRequest`/`IngestCommitRequest` and both upload UIs. Worth a small,
explicit follow-up task later — not blocking Step 5/6.

### Post-Step-4b bug-fix pass, 2026-08-18 — not a numbered step, real bugs found by real use

Oscar used the live "Flota VRM" page immediately after Step 4b shipped and found three real problems,
one of them live (a real customer's report rendered wrong). All three fixed and independently
verified same-day, before Step 5 started:

1. **The actual bug**: `/admin/vrm-fleet`'s link form collected zero site metadata (`SiteFieldsIn`
   never existed on that form, only on `/admin/upload`'s), so linking VRM installation `156868`
   ("Proyecto KM Ukiyo") to customer "Karen Montealegre" created a `vrm.sites` row with
   `system_type` defaulted to `'hybrid'` and every coordinate/battery field `NULL` — producing a
   wrong report (hybrid template, meaningless grid-quality section, no weather) for a real customer.
   Fixed two ways: (a) the fleet-link form now collects the same `SiteFieldsIn` fields
   `/admin/upload` already does; (b) a genuinely useful addition — `vrm_api/routers/vrm_fleet.py`
   now cross-references `monitoring.sites.monitoring_urls` (Oscar's older, separate Node-RED
   product, which often already has real settings for the same physical installation, embedded as
   a VRM dashboard URL) and surfaces matched settings as **suggested, never auto-applied** defaults.
   Confirmed live: 7 of Oscar's 13 fleet installations now get real suggestions, including exactly
   the values that fix Karen's site. Karen's actual `vrm.sites` row was hand-corrected the same day
   (system_type → `off_grid`, real coordinates/pv_kwp/battery specs) using this same
   `monitoring.sites` match, independent of the code fix.
2. **Streamlit's Cargar "Sincronizar desde VRM API" mode gained a token-source choice** — "Mi
   flota" (unchanged) vs. "Token propio del cliente" (uses that customer's own Vault-stored token,
   reached the same way `vrm_api/secrets.py` does, no `vrm_api` HTTP hop, matching this tool's
   existing full-trust direct-DB pattern). The customer-token branch correctly stamps
   `vrm_token_last_checked_at`/`_last_ok_at` on success — independently re-verified with a fresh
   throwaway customer (before: `NULL`; after a real customer-token call: a real timestamp) — the
   deliberate **opposite** of Step 4b's admin-fleet guard, since this genuinely is that customer's
   own credential being exercised, not the admin token standing in for it. `triggered_by` stays
   `'admin'` regardless of which token is used (Oscar is the one clicking either way).
3. **The admin Reports page's customer picker now actually filters `monitoring`-schema sites**, via
   `monitoring.sites.owner` (populated on all 25 current rows) — case-insensitive exact match
   against the selected customer's name. `vrm`-schema filtering (already correct, real
   `customer_id` FK) is unchanged. Independently confirmed live: exactly Karen Montealegre's 3 real
   sites match her name, out of 25 total.

`python -m py_compile` and `npm run typecheck` both independently re-run clean. Not part of this
plan's Step numbering because it fixes what Step 4b shipped rather than building something new —
recorded here so the history is legible.

---

### Step 5 — The customer UI: connect, map, sync, see state (~2 days)

**Build:**
- `victron-monitor/web/lib/server/db/vrmLink.ts` (`import 'server-only'`, `customerId` first) —
  connection state reads for the UI. No token ever passes through here on its way *out*.
- Route handlers `app/api/vrm/{validate,connect,disconnect,sync}/route.ts` — `requireCustomerForRoute()`
  first statement; Zod-parse the body; `customer_id` injected from the session, **never** the body;
  forward to `vrm_api` through `lib/server/pipeline.ts`'s existing client (extended with the new
  calls, same typed-error shape).
- `app/(portal)/app/sites/` — the **Victron VRM account** panel: disconnected state (explainer +
  a link to the exact VRM portal path *Preferences → Integrations → Access tokens* + a password-type
  input + Validate); mapping step (real installation list, per-installation *ignore / link to
  existing site / create new site*, `canAddSite()`-gated, with the "days already imported from CSV
  will be replaced" notice); connected state (account email, connected-since, per-site last-synced,
  **Sync now** per site and for all, **Disconnect** with a confirm that says telemetry is kept).
- `JobProgress` reused for `vrm_sync`. New `lib/i18n/strings.ts` keys, EN + ES, no literals.

**Validate:**
- End to end in a browser as a real customer: paste → see *their* installations → map one →
  connect → sync → the report page renders from the pulled data.
- **Leak checks, re-run:** no `NEXT_PUBLIC_*` addition; the token appears in **no** server log, no
  `vrm.jobs` row, no client bundle, no URL, no cookie. Grep a production build for the test token.
- Flip `ui_language` to `es` → the whole panel translates; no English left behind.
- Over `site_limit` → creating a site from the mapping step is blocked with upgrade copy.
- Disconnect → sites revert to `source='csv_upload'`, **history remains**, and CSV upload for that
  site still works immediately after.
- `scripts/test-scoping.ts` extended and passing.

**Step 5 status: done and independently verified, 2026-08-18.** The customer-facing "Victron VRM
account" panel on `/app/sites` (`VrmLinkPanel.tsx`), four new route handlers
(`app/api/vrm/{validate,connect,disconnect,sync}`), `lib/server/db/vrmLink.ts`, and the matching
`lib/server/pipeline.ts` client functions all built, reusing the ingest-preview route's tenancy
patterns and `JobProgress` unchanged for sync jobs. Re-ran independent checks beyond the coder's own
report: `npm run typecheck` clean; `npm run test:scoping` re-run fresh — **11/11 passed**, including
the live-HTTP tamper case (`vrmSync(A.id, B.site_id)` refused by the real running `vrm_api`); read
all four route handlers directly and confirmed `customer_id` is always `session.customerId`, never
the request body, with `assertOwnsSite()`/`canAddSite()` re-checked server-side per PLAN_PHASE14.md
§1.12 rule 3; confirmed `pipeline.ts`'s new TS types match `vrm_api/schemas.py`'s real `VrmLink*`
models field-for-field, not a guess; confirmed all 39 new `vrm_link_*` i18n keys appear exactly
twice (EN + ES paired) with a scripted check, not a visual skim; confirmed the coder's own flagged
deviation — sending `site_fields.display_name` on an "existing site" mapping — is actually present
in `VrmLinkPanel.tsx` (line ~183), preventing `vrm_link.py`'s connect handler from falling back to
the site's slug as its display name. No `E2E`/`Scoping Test`-named customer rows left in the dev DB;
the two `test-portal-qa*` rows found are pre-existing Phase 14 fixtures, unrelated to this step.

---

### Step 6 — Failure surfacing + admin (~1 day)

**Build:**
- Customer-facing banner on `/app` and `/app/sites` when `vrm_token_revoked_at` is set or
  `vrm_token_last_error` is present: *"Your VRM connection stopped working — reconnect to resume
  automatic updates. Your existing data is unaffected."* Plus per-site last-sync error text,
  human sentences only (`PLAN_PHASE14.md` §1.12 rule 6).
- `/admin/customers` gains a **VRM link** column (`Sin conectar` / `Conectado <email> desde <date>` /
  `Token revocado <date>`) and a per-customer disconnect action (Oscar can sever a link he can't
  create — §0.5 Q6). `/admin/sites` shows `source` + `vrm_last_synced_at`. `/admin/activity` shows
  `vrm_api` ingestion rows alongside CSV ones, with `days_replacing_csv` visible.

**Validate:** revoke a token in VRM → the banner appears on the next sync attempt and in
`/admin/customers`; reconnect clears it. Admin disconnect works and the customer's next visit
shows the disconnected state, with history intact.

**Step 6 status: done and independently verified, 2026-08-19.** `VrmConnectionBanner` (customer-
facing, on `/app` and `/app/sites`), the `/admin/customers` VRM column + reused-disconnect action,
`/admin/sites`' `Origen`/`Última sync VRM` columns, and `/admin/activity`'s `days_replacing_csv`
badge all built. **The coder found and fixed a real false-positive**: `vrm.set_customer_vrm_token()`
clears `vrm_token_revoked_at` on reconnect but never clears `vrm_token_last_error` (confirmed by
reading migration 024's actual SQL — only `vrm_token_revoked_at` is nulled), so §9's literal banner
condition would keep telling a customer their connection "stopped working" after they just
successfully reconnected. Fixed with a `!status.connected` guard. **Independently reproduced the
exact scenario myself**, not just re-read the fix: forced a real auth failure on a fresh throwaway
customer (confirmed the banner condition correctly fires), reconnected with a real valid token, and
confirmed live that `token_last_error` genuinely survives the reconnect while `connected` flips to
`true` — proving both that the false positive is real and that the guard suppresses it. Re-ran
`npm run typecheck`/`npm run lint` (both clean) and `npm run test:scoping` fresh (11/11 passed) after
this and the two report-display fixes below. Zero leftover test customer rows.

**Also fixed in this pass, discovered from real usage rather than the plan's own checklist:** the
"remove that grid score" / "still don't see your fixes" bug report (2026-08-19) turned out to be
two separate things. First, `vrm_api` had been running since before the earlier off-grid
report-generation fix (`victron/weekly_report.py`/`report_svg.py`/`report_i18n.py`) — a Python
process, like Streamlit, does not reload edited modules while running; restarted both. Second, and
not previously caught: the exact "no system_type gating" bug already fixed in the PDF and the
Streamlit preview was independently duplicated a third and fourth time, in
**`AdminReportsManager.tsx`** and its customer-facing twin **`ReportManager.tsx`** — both showed a
grid-quality chip/warning unconditionally and would have rendered `(null cyc)` for the new
"Sin datos" battery-cycle state (introduced by the earlier fix) since neither file's TS type allowed
`batteryCycles: number | null`. Fixed identically in both: grid-quality chip/warning and the outages
chip hidden for `system_type === 'off_grid'`, `batteryCycles` typed as `number | null` and rendered
conditionally. Verified via a real `POST /v1/reports` call against the restarted `vrm_api` for
Proyecto KM Ukiyo — `batteryCycles: null`, `battStressLabel: "Sin datos"` confirmed in the actual
job result. **Follow-up closed same day, 2026-08-19**: `vrm_api/routers/reports.py`'s
`_report_summary()` hand-picks a field list from `build_report_data()`'s output that predated
`battery_kwh_available` (§4.6) — added `"batteryKwhAvailable": tot["batteryKwhAvailable"]` to its
`totals` dict, additive, no other field changed. `ReportManager.tsx`'s `EnergyMixBar` now excludes
the battery segment from the bar's own proportions and shows "—" in the legend when
`batteryKwhAvailable` is `false`, mirroring `report_svg.py`'s own `_legend_value_text()` fix in the
PDF; `AdminReportsManager.tsx`'s `totals` type gained the same field for shape-accuracy (that view
has no energy-mix bar of its own to gate). Verified live against the restarted `vrm_api`: Proyecto
KM Ukiyo (off-grid, `vrm_api`-ingested) now returns `"batteryKwhAvailable": false`; a real
CSV-sourced hybrid site (`vista-atenas-2-floor-pool`, real `charge`/`discharge` values) returns
`"batteryKwhAvailable": true` — both branches confirmed on real data, not assumed. `npm run
typecheck` clean.

---

### Step 7 — Scheduled sync + docs (deferrable; ~1.5 days)

**Build:** `.github/workflows/vrm-sync.yml` (`cron:`, `PIPELINE_API_URL` + `PIPELINE_API_KEY` from
repo secrets, `curl` → `POST /v1/vrm-sync/run-due`, non-zero exit on a non-2xx so a failed run is
visible in the Actions tab). Docs: `vrm_api/README.md` (the two new routers, the trust-boundary
rules, the env vars), `victron-monitor/web/README.md`, `.env.example` (`VRM_REMOTE_BASE_URL`,
`VRM_SYNC_MAX_BACKFILL_DAYS`, and `VRM_TOKEN_KEY` **only** if §2.4's fallback was taken),
`ARCHITECTURE.md` (a new box: `vrm_api` → Victron VRM cloud, one-way, outbound only), `CONTEXT.md`
entry in the existing style, `PHASES.md` Phase 15 status, and a note in
`victron-monitor/docs/vrm-report-saas-architecture.md` §4 pointing at this file and marking its V2
sketch superseded.

**Validate:** a real scheduled run picks up every due site, isolates one deliberately broken site's
failure without blocking the rest, writes one `ingestion_log` row per site, and stays under the
rate limit (count requests). Re-run the leak checks. `git diff --stat` shows **no changes** to
`app.py` or anything under `pages/`; `streamlit run app.py` still works.

---

**Estimate:** 8–12 days at this repo's part-time pace (Steps 0–6: 7–10; Step 7: 1.5).

---

## 9. Revocation and failure modes — what happens, and what the customer sees

| Event | Detected as | State written | Customer sees | Oscar sees |
|---|---|---|---|---|
| Customer revokes the token in VRM | `401`/`403` from any call | `vrm_token_revoked_at=now`, `vrm_token_last_error='unauthorized'`; syncs stop for that customer | Banner: connection stopped working, reconnect; data unaffected | `Token revocado <date>` in `/admin/customers` |
| Token expires (customer set an expiry) | identical to above | identical | identical | identical |
| Rate limited | `429` | job `failed` with a retry message; **token state untouched** | "VRM is rate-limiting us — try again in a few minutes" | job row + `ingestion_log` warning |
| Victron down / network | timeout, `5xx` | job `failed`; `vrm_last_sync_error` on the site; token untouched | "Couldn't reach VRM — try again" | same |
| Installation removed from the account, or no longer shared | absent from `list_installations`, or `404` | `vrm_last_sync_error='installation_not_found'`, that site's `vrm_sync_enabled=false`; **data kept** | Per-site notice: this VRM installation is no longer visible; re-map or upload a CSV | `/admin/sites` |
| Installation id mismatch (§3.2 control 3) | stored id ≠ returned id | job `failed`, nothing written | Generic failure | Full detail in the API log — **this one Oscar should look at**, it means something is wrong with our own mapping |
| Signals missing on the API path (outages/alarms) | mapper | rows written with `NULL`s + `ingestion_log` warnings | The report's own existing "no grid measurements" style caption | `/admin/activity` warnings |
| Sync overwrote CSV-sourced days | mapper/ingest | `warnings.days_replacing_csv` | Shown in the sync result | `/admin/activity` |

**Not in v1:** email notification of a broken connection. `victron/mailer.py` exists (Phase 14) and
the hook is one call, but sending unprompted mail on a failure the customer may already know about
is a product decision, not a technical one. Noted here so it isn't quietly added.

---

## 10. Explicit non-goals

- **Replacing the CSV path.** It stays, for every site, including linked ones (§5.2), and
  `pages/06_vrm_monitor.py` remains the only path for large backfills.
- **OAuth / "Sign in with Victron."** Does not exist on Victron's side (§0.2). Do not build a
  facsimile.
- **Per-installation token scoping.** Victron does not offer it (§0.2). §3.2's third control is
  our substitute; do not pretend the token is narrower than it is.
- **Writing anything to Victron** — no control commands, no settings, no alarm acknowledgement.
  `victron/vrm_remote.py` exposes `GET` only, and that is a design constraint, not an oversight.
- **Real-time / streaming / sub-daily dashboards.** This phase produces `energy_daily` rows,
  exactly like the CSV path.
- **Multiple VRM accounts per customer.** One token per `vrm.customers` row (§1.2).
- **Admin pasting a customer's token** (§0.5 Q6, recommendation: no).
- **Widening `ALARM_CATEGORIES`.** A cross-path change requiring Node-RED to emit the same
  categories, or health scores stop meaning the same thing (`vrm_csv.py`'s own comment).
- **Any change to `monitoring`, Node-RED, or Apps Script.**
- **RLS policies / per-user JWTs / a browser Supabase client.** `PLAN_PHASE14.md` §1.2, unchanged.
- **A real job queue.** `PLAN_PHASE14.md` §1.6, unchanged.
- **A test framework.** The extraction gate and the agreement table are scripts, like
  `scripts/test-scoping.ts`. Introducing pytest/Vitest is a separate decision.
- **Backfilling beyond Victron's retention.** VRM keeps fine-grained data ~6 months; the API
  cannot resurrect what VRM discarded.

---

## 11. Risks and tradeoffs

| Risk | Blast radius | How this plan addresses it |
|---|---|---|
| **A customer's token leaks** (log, dump, error body, job params, client bundle) | Catastrophic and not ours to absorb: read access to *every installation on that customer's VRM account*, including installations they don't own but that are shared with them. | Vault + `SECURITY DEFINER` wrappers so plaintext never sits in a column, a dump, or a backup (§2); the vault id never leaves Postgres; §2.5's four transit rules; typed exceptions that never carry headers; `vrm.jobs.params` explicitly excludes the token; grep-for-the-token leak checks at Steps 2, 4 and 5. |
| **Pulling the wrong customer's data** | Cross-tenant data contamination — the failure this whole tenancy model exists to prevent. | Three independent controls (§3.2), the third specific to this phase: no request body can carry an installation id; the id comes from an already-ownership-checked `vrm.sites` row, and a mismatch aborts. `scripts/test-scoping.ts` extended. |
| **Silently corrupting `energy_daily` for a site that had clean CSV data** | A customer's history quietly gets worse, and the report can't explain why. | Last-writer-wins is migration 012's deliberate design, but made *visible*: `days_replacing_csv` in the ingestion log and in the UI; the connect screen says it before the customer agrees; `ingestion_log` gets a row per sync (§5.4); and the §4.2 byte-identical gate proves the CSV path itself didn't change. |
| **Two `daily_health` rows per date on a mixed-source site** | `bucket_health_days()` keeps the *highest*-scoring row — health scores silently flattered. | §5.3: cross-`dump_type` cleanup in `victron/ingest.py`, symmetric for both paths, with the reason in a comment and in migration 024's `COMMENT ON`. |
| **`MAX_GAP_S = 300` vs. a 900 s sampling interval** | Every API-sourced day reports ~0 kWh, silently, looking like a dead system. | §4.3: `max_gap_s` becomes an explicit parameter through the extracted core; Step 3 asserts non-zero generation on a sunny day. Named as a first-class acceptance check, not a footnote. |
| **Outages read as zero on the API path** | The exact silent failure `vrm_csv.py`'s voltage rewrite was built to remove, reintroduced through a different door. | §4.5: `NULL` + a loud warning, never `0`. Step 0 determines availability *before* any mapping code exists, and Oscar is told if the answer is no, because it is a product difference. |
| **VRM's own daily totals ≠ our integrated CSV numbers** | Two of our own numbers disagree for one site across two paths, with no story. | Step 3's agreement table with a written per-column tolerance; residual differences recorded in this file rather than discovered by a customer comparing reports. |
| **Victron's terms: "not intended for commercial/professional purposes, offered without support"** | The paid product's automatic ingestion could be throttled or withdrawn with no recourse. | Surfaced as §0.5 Q2 for Oscar, not decided by the coder. Structurally mitigated by CSV remaining a first-class, always-available path (§5.1) — if the API goes away, the product still works. |
| **Rate limiting** (200 rolling, ~3/s refill, `Retry-After` often absent) | A nightly run could throttle itself or, worse, get the *account* limited. | Client-side ≤2 req/s pacer, per-run request budget, exponential backoff with jitter, sequential per-site scheduling (§6.3). 429 never touches token state. |
| **Vault secrets don't survive a project move** | Conflicts with migration 012's "dumpable into its own project" principle. | Named in §2.3 and in migration 024's header, with the mitigation (customers reconnect; telemetry is unaffected) rather than being discovered during a migration. |
| **The `vrm_csv.py` extraction regresses the CSV path** | Breaks the one thing Oscar said must not break. | The byte-identical gate (§4.2) on a real 80-day fixture, automated. Nothing proceeds if it fails. |
| **A `SECURITY DEFINER` function with a default `PUBLIC` grant** | Classic privilege escalation: anyone who can reach PostgREST reads every token. | Explicit `REVOKE ... FROM PUBLIC, anon, authenticated` in the same migration, `SET search_path = ''`, and a Step 1 validation that actually attempts the call with the anon key. |
| **Scope creep into "real-time monitoring"** | The API makes live dashboards look easy; they are a different product. | §10, plus the deliberate choice to produce only `energy_daily` rows and reuse the existing report pipeline unchanged. |

---

## 12. Conventions the coder must follow

All of `PLAN_PHASE14.md` §3 applies unchanged. Additions specific to this phase:

- **The naming rule (§0.4) is enforced in prose, not just filenames.** Victron's service is "the
  Victron VRM cloud" / "Victron's VRM API"; ours is `` `vrm_api` ``.
- **`victron/vrm_series.py`'s docstring must be a peer of `vrm_csv.py`'s** — the traps it inherits
  and from where, the ones that don't apply, and the ones that are new. Someone reading only that
  file must not be able to re-introduce a trap the CSV path already paid for.
- **Never re-implement a rule that `vrm_daily.py` now owns.** If a rule needs to differ between
  paths, it becomes a parameter with a comment saying why — never a copy.
- **No token in a comment, a docstring example, a fixture, a commit message, or this file.**
- **Comment every place a `NULL` is written where a `0` would have been easier**, naming §4.5.
- Existing git rules from `PLAN_PHASE14.md` §3 (stage in batches of 5–10, `timeout 90 git commit`).

---

## 13. Step 0 for the coder: make Phase 15 legible in `PHASES.md`

The architect agent has no `Edit` tool and `PHASES.md` is >1000 lines, so these mechanical edits
are handed over verbatim — same as `PLAN_PHASE14.md` Step 0 did. **Do these before any code.**

**Edit 1 — status table.** After the Phase 14 row, add:

```
| 15 — VRM Monitor: direct VRM API ingestion (customer-connected Victron accounts) | ⬜ Not started (see PLAN_PHASE15.md; Step 0 blocked on a VRM token from Oscar) |
```

**Edit 2 — a new section**, immediately after the Phase 14 section and before `## Timeline summary`:

```markdown
## Phase 15 — VRM Monitor: direct ingestion from a customer's own Victron VRM account (8–12 days, scoped 2026-08-18)

**Goal:** a customer connects their own Victron VRM account once, with a personal access token
they generate in their own VRM portal, maps their real VRM installations to their VRM Monitor
sites, and their data is pulled from Victron instead of being exported and uploaded by hand.
The CSV path is **not** replaced — this is a second, parallel ingestion path, and a customer who
never connects a token must not be able to tell this phase happened.

Full build plan, resolved decisions, the verified Victron API findings, and per-step validation
gates: [`PLAN_PHASE15.md`](PLAN_PHASE15.md). Not duplicated in full here.

### Why this phase exists

`vrm.sites.source` has had a `'vrm_api'` value since migration 012 and nothing has ever written
it. Every customer's data still arrives because a human exported a CSV from the VRM portal and
uploaded it — which caps the product at "as fresh as the last time someone remembered." Migration
012 also pre-built the token columns (`vrm_token_secret_id` and friends) on the explicit
understanding that a plaintext token column was never acceptable. This phase finally uses them.

### Where this sits relative to other phases

- **Depends on Phase 14** (`victron-monitor/web/` + `vrm_api/` + the tenancy choke points). Its
  security model is inherited wholesale, not re-decided.
- Off the critical path like Phases 9–14. Triggered by a customer who should not have to export a
  CSV every week.
- **Blocked on one input from Oscar**: a VRM personal access token from his own account, for the
  Step 0 discovery spike. Nothing else in the phase can be verified without it.
- Touches `victron/vrm_csv.py` for the first time since it was written — but only to *extract* its
  format-independent core into `victron/vrm_daily.py`, behind a byte-identical-output gate.

### Decisions locked (see PLAN_PHASE15.md §1–§6 for the full reasoning)

- **Naming, deliberately:** Victron's remote service is reached through `victron/vrm_remote.py`
  and mapped by `victron/vrm_series.py`. Neither is called "api" — this repo's own FastAPI service
  is already `vrm_api/`, and the ambiguity would otherwise bite every future stack trace.
- **Token storage: Supabase Vault**, reached *only* through three `SECURITY DEFINER` wrappers in
  the `vrm` schema (`vault` is not exposed to the Data API and must never be). The vault secret id
  never leaves Postgres. Envelope encryption is the documented fallback, taken only if Step 1's
  empirical gate fails.
- **Verified against Victron's current docs, correcting the old exploratory doc:** the auth header
  is `X-Authorization: Token <token>` (not `Authorization: Bearer`); a personal access token can
  read **every installation the account can see**, with no per-installation scoping available;
  rate limit is a ~200-request rolling window; and Victron's own terms say the API is not intended
  for commercial use — a business risk flagged for Oscar.
- **The customer maps installations explicitly.** Never auto-mapped, not even when there is exactly
  one installation and one site.
- **Coexistence:** `source` means "the path this site's data currently arrives by," not an
  exclusive mode. Every sync writes a `vrm.ingestion_log` row (`source='vrm_api'`) so "why did this
  report look wrong" stays answerable, and a sync that overwrites CSV-sourced days says so.
- **Trigger:** on-demand "Sync now" in v1; a GitHub Actions `cron:` hitting one authenticated
  `run-due` endpoint as a deferrable final step — the same scheduling mechanism Phase 12 locked.

### Explicit non-goals

Replacing the CSV path, OAuth (Victron has none), writing anything back to Victron, real-time
dashboards, multiple VRM accounts per customer, Oscar pasting a customer's token from `/admin`,
widening the scored alarm taxonomy, RLS policies, a real job queue, a test framework, and
backfilling beyond VRM's own retention.

### Validation

- The reference CSV export produces a **byte-identical** `parse_export()` result before and after
  the `vrm_daily.py` extraction.
- The same window pulled through both paths for one real site produces an agreement table within
  written per-column tolerances; anything that can't meet its tolerance ships as `NULL` with a
  warning rather than as a number nobody trusts.
- A token never appears in a log line, a `vrm.jobs` row, a client bundle, a URL, or a cookie.
- Customer A's token cannot reach customer B's data, including via a tampered request aimed
  straight at `vrm_api`.
- Re-syncing does not grow row counts, double alarm episodes, or leave two `daily_health` rows for
  one date on a mixed-source site.
- `git diff --stat` shows no changes to `app.py` or anything under `pages/`.

### Open questions for Oscar (see PLAN_PHASE15.md §0.5)

A VRM token for the Step 0 spike (**hard blocker**), whether Victron's non-commercial API terms are
acceptable for a paid product, whether v1 needs scheduled polling or on-demand is enough, the
initial backfill window, sync cadence, whether Oscar may connect a token on a customer's behalf
(recommendation: no), and whether `source` stays non-exclusive.
```

**Edit 3 — timeline table**, after the Phase 14 row:

```
| 15 | VRM Monitor: direct VRM API ingestion (customer-connected accounts) | 8–12 | Whenever needed — triggered by a customer who shouldn't have to export a CSV weekly |
```

**Edit 4 — critical path notes**, after the Phase 14 paragraph:

```
**Phase 15 (direct VRM API ingestion) is off this critical path too**, and is the first phase that
*depends* on another off-path phase: it builds on Phase 14's web app, `vrm_api`, and tenancy model
rather than standing alone. It is also the first time this product stores a credential belonging to
a third party on a customer's behalf, which is why its plan spends more of its length on storage and
tenancy than on features. Trigger it by the first customer for whom weekly CSV exports are the thing
standing between them and renewing.
```

**Validate:** both files render on GitHub; `git diff` on `PHASES.md` shows only additions.
