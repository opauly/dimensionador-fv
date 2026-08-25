# Phase 17 — VRM Monitor: scheduled reports, report cost limits, tiered white-label branding, and a visible trial

**Status:** Scoped 2026-08-21. **Not started.** Oscar answered Q1, Q2, Q4 and Q6 the same day (§0.6),
plus one decision not originally asked (§0.7): **CSV-sourced sites are never eligible for scheduling,
full stop** — only `source='vrm_api'` sites can be scheduled. This replaces §3.5's original two-path
freshness design with a single, simpler rule and is reflected throughout §2.3, §3.1, §3.5, §3.7, and
§5.3 below. Remaining open questions (Q3, Q5, Q7–Q11) still have stated defaults the build proceeds on.
**Author:** architect agent, 2026-08-21. **Decisions recorded by Claude, 2026-08-21**, same day, per
Oscar's direct answers in chat — not re-run through the architect agent, since the decisions are
unambiguous and the plan's own structure (confirmed-context / decisions / steps) makes them a
find-and-replace against specific sections, not a redesign.
**Builds on:** [`PLAN_PHASE14.md`](PLAN_PHASE14.md) (the Next.js app, `vrm_api`, the trust boundary,
the tenancy choke points, the `vrm.jobs` execution model), [`PLAN_PHASE15.md`](PLAN_PHASE15.md)
(§6.1/§6.3's `run-due` fan-out shape — **already built and still uncalled**, see §0.1; the
`vrm_sync_enabled` protective-default trick), [`PLAN_PHASE16.md`](PLAN_PHASE16.md) (`vrm.plans`,
`vrm.rate_limits` + `vrm.increment_rate_limit()`, `apply_entitlements()`, `billing_status`,
`provisioning_state`, `site_limit_source`, and the "one writer, named, and no fourth" discipline this
phase copies for branding and for schedules), and PHASES.md **Phase 12** (which locked GitHub Actions
`cron:` as this project's scheduling mechanism, and whose per-site failure-isolation requirement is
restated here as a hard gate, §3.6).
**Plan doc convention:** same shape as PLAN_PHASE15/16 — confirmed context first, then resolved
decisions with their reasoning, then vertical build steps each ending in something runnable behind its
own validation gate. Nothing proceeds past a failed gate.

---

## Goal

Four things that are currently either sold-but-not-built, half-built, or unbounded become real:

1. **A customer can put a site on a daily / weekly / monthly report schedule and the report shows up
   on its own** — rendered, archived, emailed, and logged, with one site's failure never touching
   another's. Today there is **no automated report generation for `vrm` (SaaS) customers at all**; the
   Pricing page's "Automatic weekly & Overview reports" and "Automatic email delivery" lines are
   aspirational copy.
2. **Report generation stops being an unbounded cost.** Two independent caps — a per-customer rate
   limit on manual regeneration, and a per-billing-period cap on scheduled runs — both driven by
   per-tier numbers that live in a table Oscar can `UPDATE`, not in a constant someone has to redeploy.
3. **A Growth/Fleet customer's report actually carries their branding, and a Starter customer's does
   not** — enforced server-side in one function, with a settings page that shows a Starter customer an
   upsell instead of an editor. `vrm.customers.branding` has existed since migration 012 and is
   completely dead: nothing reads it and no UI writes it.
4. **The 7-day trial is visible where people decide** — a distinct badge on the Pricing tier cards
   (which say nothing about it today) and on the signup form (where it is one line of body text).

**"Done" means:** a real site, on a real schedule, in a real timezone, produced a real PDF that
arrived in a real inbox with the right logo on it, without anyone touching a keyboard — and the run is
visible afterwards in a ledger that says what happened to every site, including the ones that were
skipped and why.

**Four constraints, stated up front because they shape every decision below:**

1. **An unattended job that fails silently is worse than one that never ran.** Every scheduled run
   writes a row — `done`, `skipped_*`, or `failed`, with a reason — before, not after, anyone asks.
   This is the exact bug class PHASES.md Phase 12 called out from the Apps Script era, and it is why
   §5.2's ledger table is not optional.
2. **A report must never be generated from data that isn't there.** `build_report_data()` raises on an
   empty window. A scheduler that catches that exception and moves on is hiding a product problem; a
   scheduler that checks first and records `skipped_no_data` is reporting one (§3.5).
3. **A tier gate that only exists in the UI is not a tier gate.** Branding is resolved in exactly one
   server-side function, and the renderer never sees `vrm.customers.branding` unresolved (§4.2). Same
   rule PLAN_PHASE16.md §6.4 established for ONVO ids.
4. **`victron/` is touched in this phase — for the first time since Phase 15 — and only additively,
   behind a byte-identical-output gate.** Branding cannot be wired without changing
   `victron/weekly_report.py`; report email cannot be sent without an `attachments` parameter on
   `victron/mailer.py`. Both are additive with defaults that preserve today's behaviour exactly, and
   both carry the same gate Phase 15 used when it extracted `vrm_daily.py` (§0.4).

---

## 0. Confirmed context (do not re-derive)

Everything in §0.1–§0.2 was read out of this codebase on 2026-08-21. The coder should not re-verify it;
they should verify the things §0.6 says are unverified.

### 0.1 What already exists and is reused

| Fact | Where |
|---|---|
| **`POST /v1/vrm-sync/run-due` is already built and has never been called by anything.** Synchronous, sequential, per-site `try/except` isolation, returns `{sites_checked, results:[{site_id, status, error}]}`. Its docstring says outright it was built for a Step 7 that was deferred. **This is the template for §3.4's report scheduler and it is also the fix for §3.5's data-freshness problem — the same workflow just has to call it.** | `vrm_api/routers/vrm_sync.py` L307–342 |
| `.github/workflows/billing-reconcile.yml` — this repo's only workflow. `cron:` + `workflow_dispatch`, repo secrets `PIPELINE_API_URL`/`PIPELINE_API_KEY`, `curl -sS -f` so a non-2xx fails the job visibly. **Copy this shape exactly.** | that file |
| `vrm.rate_limits` + `vrm.increment_rate_limit(bucket, key, window_start)` — an atomic upsert-and-return, fixed window, durable across serverless invocations. `lib/server/ratelimit.ts:checkRateLimit()` is the TS wrapper and **fails open on a DB error, deliberately** (it is an abuse control, not an auth boundary). Two callers today: signup, and the ONVO webhook. | migration 025 §7, `lib/server/ratelimit.ts` |
| `vrm.jobs` (`kind IN ('ingest_preview','ingest_commit','report','vrm_sync')`, `customer_id` FK, `status`, `params`, `result`, `error`) + `jobs.run_job()`'s FastAPI `BackgroundTasks` model, and `_safe_error_message()`'s allow-list of customer-safe exception types. **Rows are never pruned.** | migration 023, `vrm_api/jobs.py` |
| `vrm.sites` already carries every per-site report knob: `timezone` (IANA, `NOT NULL DEFAULT 'America/Costa_Rica'`, and migration 012's comment says it is **load-bearing, not cosmetic**), `report_language`, `system_type`, `health_thresholds`, `active`, `source`, `vrm_sync_enabled`, `vrm_last_synced_at`. | migration 012, 024 |
| `vrm.customers.branding jsonb NOT NULL DEFAULT '{}'` — exists since migration 012 with the comment "(logo_url, primary_color, contact block)". **Grep-confirmed dead:** `victron/weekly_report.py` and `victron/report_svg.py` never read it; no route, action, or component under `victron-monitor/web/app/` ever writes it. | migration 012 L69–71 |
| `vrm.plans` — the tier catalogue keyed by `(plan_key, billing_interval, currency, mode)`, with `site_limit` (`NULL` = unlimited), `account_types`, `self_serve`, `active`. Four seeded rows today (starter/growth × month/year, test mode). | migration 025 §1 |
| `vrm.customers.billing_status` — the derived entitlement cache written **only** by `apply_entitlements()`. Vocabulary: `none` \| `trialing` \| `active` \| `past_due` \| `incomplete` \| `unpaid` \| `canceled`. Entitled = `{active, trialing, past_due}`. **`'none'` means "no subscription was found at all" — a legacy hand-managed customer, not a lapsed one.** | `vrm_api/billing.py` L106–136, L509–518 |
| `site_limit_source` defaults to `'manual'` so a reconcile can never stomp a hand-negotiated limit. The same protective-default direction is used again in §5 for every new column. | migration 025 §8 |
| `SITE_WHITELIST` in `lib/server/db/sites.ts` (14 fields, type-level `Pick` + runtime `pickWhitelisted`), `PROFILE_WHITELIST` in `db/customers.ts`, `ADMIN_CUSTOMER_WHITELIST` in `db/admin.ts`. Every customer-writable field goes through one of these, twice. | those files |
| `victron/mailer.py` — a generic Resend client (`send(to, subject, html, from_, reply_to)` → message id, `MailerError`). Its own docstring says it exists **specifically** for scheduled report email and has no caller today. **It has no attachment support.** | that file |
| `vrm_api/storage.py:upload_report_pdf(site_id, start, end, pdf_bytes)` → `reports/{site_id}/{start}_{end}.pdf` in the `vrm-monitor` bucket, `upsert=true`. Signed upload URLs for customer uploads are minted by `app/api/uploads/sign/route.ts`. | those files |
| `victron/weekly_report.py:render_html()` passes `logo_b64=get_logo_b64()` (the shared Pauly & Co asset from `proposals/assets/assets.py`). The template hardcodes "Pauly &amp; Co." in three places, `proyectos@paulyco.com` in the footer, and `#1FAE6E` as the `.brand` colour. | `victron/weekly_report.py` L833–859, `victron/templates/weekly_report.html` L22, 41, 64, 78, 80 |
| `victron/report_svg.py`'s palette (`GREEN #1FAE6E`, `BLUE`, `AMBER`, `RED`, `MINT`, backgrounds) is **semantic** — health tiers, battery stress, grid quality all map onto those colours. §4.3 rules them out of white-labelling for exactly this reason. | `victron/report_svg.py` L25–33 |
| `Pricing.tsx` is **hardcoded English**, not `t()`-driven — no `i18n` import anywhere in `components/marketing/`. `/signup`, `/login`, `/activate` use `t('en', ...)` with paired `en`/`es` dicts and `FORCE_LANG='en'`. §1.2 says exactly which of the two conventions each new string follows. | `components/marketing/Pricing/Pricing.tsx`, `lib/i18n/strings.ts` |
| `Panel` already has a `featuredTag` pill, used for Growth's "Most installers". There is **no `Badge` component** in `components/ui/`. `--radius-pill: 20px` exists in `styles/tokens.css`. | `components/ui/Panel/Panel.tsx` L47, `styles/tokens.css` |
| The 7-day trial is a **literal `7` in two independent places**: `trial_period_days=7` at `vrm_api/routers/billing.py` L604, and the number spelled out in `signup_subtitle` / `billing_subscribe_note` copy. Nothing ties them together. | those files |
| `app/api/pipeline/reports/route.ts` — the on-demand report entry point. `requireCustomerForRoute()` first, Zod-parsed body, `assertOwnsSite()`, a range check against `getLimits()`, then `createReport()` with `schema:'vrm'`/`actor:'customer'` **hardcoded** (never from the body). Admin reports go through a separate route, `app/api/admin/pipeline/reports/route.ts`. | those files |
| `POST /v1/reports` costs, per call: one Anthropic `claude-sonnet-4-6` narrative generation, one Open-Meteo fetch, a WeasyPrint render, and a Storage write. **This is the unit of cost §2 is bounding.** | `vrm_api/routers/reports.py`, `victron/weekly_report.py` L46, L167 |
| Latest applied migration is **025**. Next free number: **026**. | `database/migrations/` |
| `scripts/test-scoping.ts` is the live-HTTP cross-tenant regression test. | that file |

### 0.2 What does NOT exist today — the honest starting line for each feature

| Feature | Actual current state |
|---|---|
| **Scheduled reports (§3)** | **Nothing.** No schedule column, no scheduler, no cron, no fan-out endpoint, no report email, no report ledger for `vrm`. Reports exist only as an on-demand `POST /v1/reports` triggered by a dashboard click. Phase 12 (PHASES.md) scoped a similar thing for the **`monitoring` schema and Oscar's own bureau clients** — a different tenancy model, different email routing (`get_report_email` RPC), different table (`monitoring.report_log`) — **and was never built either**. Read Phase 12 for the mechanism decision (GitHub Actions `cron:` over Supabase Edge Functions/pg_cron, because "this app has no deployed server today"), not for its design. |
| **Report limits (§2)** | **Nothing.** No cap of any kind on `POST /v1/reports`. The only rate limiting anywhere in the product is signup + webhook, via `vrm.rate_limits`. |
| **Branding (§4)** | **Half-built and inert.** The `branding jsonb` column exists and is always `{}`. "Full white-label branding" is already sold on the Growth tier card. No reader, no writer, no gate. |
| **Trial badge (§1)** | **Body text only.** `signup_subtitle` mentions it; the Pricing cards do not mention it at all. |
| **Data freshness for scheduled reports** | **This is the finding that reshapes §3.** A CSV-upload site's data only arrives when a human uploads. A `source='vrm_api'` site's data only arrives when someone clicks "Sync now" — Phase 15's Step 7 scheduled sync was deferred, so `vrm_sync_enabled` is set on linked sites and **nothing consumes it**. A report scheduler built without addressing this generates reports on stale data and looks like a bug in the report. §3.5 is the answer. |

### 0.3 The naming rule (PLAN_PHASE15.md §0.4 / PLAN_PHASE16.md §0.3, extended)

- **`vrm_api/report_schedule.py`** — pure period arithmetic: given `(schedule, weekday, day_of_month,
  hour, timezone, now_utc, last_period_end)` return the target `(start, end)` or `None`. **No database
  access, no I/O.** It is the one piece of this phase that is genuinely tricky and it must be testable
  without a DB, a network, or a clock.
- **`vrm_api/report_runs.py`** — the ledger: claim, update, count, query. Knows `vrm.report_runs` and
  nothing else.
- **`vrm_api/report_limits.py`** — limit resolution (`vrm.plan_limits` → effective numbers for one
  customer) and the two cap checks. The judgement layer.
- **`vrm_api/report_delivery.py`** — render the email, attach the PDF, call `victron/mailer.py`, record
  the outcome. SaaS-only; the *template* lives in `victron/templates/` so Phase 12 can reuse it.
- **`vrm_api/branding.py`** — `resolve_branding(customer_row) -> dict`. The **only** thing that turns
  `vrm.customers.branding` into what the renderer sees. The tier gate lives here and nowhere else.
- **`vrm_api/routers/reports.py`** — extended, not replaced. Gains `POST /v1/reports/run-due`.
- **`victron-monitor/web/lib/server/db/branding.ts`** — narrow data layer for the branding editor
  (read + one whitelisted write). Sits beside `db/customers.ts`; **must never import `db/admin.ts`**.
- **`victron-monitor/web/lib/server/db/reportRuns.ts`** — tenant-scoped reads of `vrm.report_runs` for
  the portal history list.
- **Prose rule:** "**schedule**" always means the per-site cadence setting; "**run**" always means one
  execution recorded in `vrm.report_runs`; "**cron**" always means the GitHub Actions trigger. Three
  words, three meanings, never swapped.

### 0.4 What this phase deliberately does NOT change

`pages/`, `app.py`, the `monitoring` schema, Node-RED, Apps Script, the ONVO integration, the signup
flow's logic, `resolveRole()`, `apply_entitlements()`'s entitlement math, and the CSV ingest path.
`git diff --stat -- pages/ app.py` must be **empty** at the end of this phase.

**`victron/` is the exception, and it is bounded to exactly three files and three kinds of change:**

| File | Change | Gate |
|---|---|---|
| `victron/weekly_report.py` | `build_report_data(..., branding: dict \| None = None)` and `render_html()` threading it into the template context. Default `None` → today's Pauly & Co behaviour, byte for byte. | §8 Step 4's byte-identical PDF gate |
| `victron/templates/weekly_report.html` | The three hardcoded "Pauly & Co." strings, the footer email, and the `.brand` colour become template variables **whose defaults are the current literals**. | same gate |
| `victron/mailer.py` | `send(..., attachments: list[dict] \| None = None)`, additive, default `None`. | §8 Step 8 |

`victron/report_svg.py` is **not touched at all** (§4.3). If branding work starts wanting to change a
colour constant in that file, the design is wrong — come back here.

### 0.5 The two decisions that shape everything else

**Decision 1 — The scheduler is a stateless due-check over durable state, not a queue.**

> There is no job queue, no persisted scheduler state, no "next fire time" that has to be kept in sync.
> The cron asks, on every run: *"for each site with a schedule, what complete period should it have a
> report for by now, and does the ledger already have one?"* If yes, skip. If no, generate. Running the
> cron twice, or three hours late, or twice concurrently, produces the same result as running it once
> on time.

This collapses four problems into one design:
1. **A missed cron run** (GitHub disables schedules on repos idle 60 days; scheduled runs are
   best-effort and are routinely delayed 5–15 minutes under load) self-heals on the next run, because
   "due" is computed from the calendar and the ledger, not from a timer.
2. **Overlapping runs** cannot double-generate, because the claim is a unique index in Postgres
   (§5.2), not a lock in a process.
3. **A restart mid-run** loses at most the site being processed; the next run picks it up.
4. **Retry-after-failure** is the same code path as first-attempt, bounded by `attempt_count` on the
   claimed row so a permanently-broken site does not retry forever.

The cost, recorded honestly: a site whose report failed for a transient reason waits until the next
cron tick (≤1h) rather than retrying immediately. That is a correct trade for a weekly report.

**Decision 2 — Every per-tier number in this phase is a database row, not a constant.**

Report limits and the white-label gate both resolve out of a new `vrm.plan_limits` table keyed by
`plan_key` (§5.1). Reasons, in order of weight:
- Migration 021's own comment already set this precedent for `site_limit`: *"a hand-negotiated deal
  just needs this value changed, not a migration."* A Fleet customer who needs 3× the scheduled-report
  cap should cost Oscar one `UPDATE`, not a deploy.
- The numbers in §2.3 are **first guesses calibrated against nothing**. They will be wrong. Making them
  wrong-and-editable is the difference between tuning and rework.
- It keeps the limits **out of the money path**. `vrm.plans` is the ONVO catalogue and
  `apply_entitlements()` is its only consumer; adding cost-control columns there would entangle two
  things that change on different schedules for different reasons.

`vrm.plan_limits` is keyed by `plan_key` (one row per tier), **not** by `(plan_key, interval,
currency, mode)` like `vrm.plans` — a customer's limits should not depend on whether they pay monthly
or annually. Resolution is `vrm.customers.plan` → `vrm.plan_limits.plan_key`, with a mandatory
`'default'` row as the fallback for any unrecognized plan string (`vrm.customers.plan` is free text and
always has been). **The fallback is stricter than every paid tier, not more permissive** — the opposite
of `lib/plans.ts:planSiteLimit()`, which fails *open*, and the plan says so explicitly at the call site
so nobody "makes it consistent" in the wrong direction. (Corrected 2026-08-21: the original phrasing
here claimed `'default'` is the strictest row in the *whole* table, which Step 2's own validation gate
caught as an overclaim once Oscar's revised numbers were in — `trial`/`single_report` are independently
even stricter on scheduling, for structural reasons, not typo-safety ones. See §5.1's note.)

### 0.6 Open questions for Oscar

**Q1, Q2, Q4 and Q6 block build steps and are now answered** (recorded below, each with Oscar's actual
decision and the date). Everything else has a stated default the coder should proceed on if no further
answer arrives.

1. **RESOLVED 2026-08-21 — per-site.** Matches the architect's recommendation below; recorded for the
   reasoning. *Reasons: `vrm.sites` already owns every other report knob (`report_language`,
   `system_type`, `timezone`, `health_thresholds`); a 50-site installer genuinely wants weekly on most
   sites and daily on the two that are misbehaving; and a per-customer field cannot express that at all,
   whereas a per-site field with a bulk "apply to all sites" action can express both.* Cost: configuring
   50 sites — mitigated by the bulk action and the customer-level default. **Unblocks Step 2.**
2. **RESOLVED 2026-08-21 — Oscar's revised numbers, superseding §2.3's first-guess table.** The updated
   table is in §2.3 and §5.1; the reasoning below is retained as background only, not as the numbers to
   build from. Also still worth Oscar's eye whenever it's convenient: **what is the actual Anthropic
   cost per report?** Step 3's gate still requires measuring it, and if it lands meaningfully different
   from what §2.3's math assumed, that's a third pass at the table, not a blocker to building it now.
   **Unblocks Step 3.**
3. **Should `daily` be tier-gated in addition to the numeric cap?** i.e. "daily reports are a Growth+
   feature," which is a marketing lever rather than a meter. *Recommendation: **no** for v1 — the
   numeric cap in §2.3 already makes daily-across-a-whole-fleet impossible on Starter, and a hard tier
   gate on a cadence is a second concept to explain on the Pricing page for no extra protection.*
   Trivially addable later as a `vrm.plan_limits.allowed_schedules text[]` column.
4. **RESOLVED 2026-08-21 — in.** Step 8 stays in scope, built as its own step with its own gate (still
   structurally droppable if it ever needs to be cut, but that is no longer the plan). **Unblocks Step
   8.**
5. **May a customer add third-party report recipients** (their own client's email, not their own)?
   That is the installer's whole use case and it is genuinely valuable. It is also outbound mail to
   people who never agreed to hear from us, sent from Oscar's Resend reputation. *Recommendation:
   **yes, capped at 5 per site**, entitled customers only, every send logged in `vrm.report_runs`, and
   an unsubscribe/"stop sending me this" footer link in the email. If that footer is more work than the
   step deserves, the fallback is "customer's own addresses only in v1."*
6. **RESOLVED 2026-08-21 — real storage**, matching the recommendation, for the security reason stated
   below (SSRF, not preference). Oscar also confirmed the scope of what's customer-editable: **color and
   "some header text"** — i.e. `primary_color` and `company_name` from §4.1's shape (both were already
   in the proposed jsonb keys; this confirms neither needs to expand, and that `contact_*`/`website` stay
   as-is too). This also resolves Q8 below in the same breath: nothing about "header text" implies the
   chart palette, so §4.3's chart-colors-are-off-limits rule stands unchanged. **Unblocks Step 5.**
   Original reasoning, retained: *a `logo_url` the renderer fetches at render time is (a) a server-side
   request-forgery vector — `vrm_api` fetching an arbitrary customer-supplied URL from inside Render's
   network — and (b) a reliability dependency where someone else's 404 breaks our PDF. Uploading to the
   existing `vrm-monitor` bucket under `branding/{customer_id}/logo.<ext>` reuses the signed-upload
   pattern `app/api/uploads/sign/route.ts` already implements, and the renderer only ever reads from our
   own bucket.*
7. **What happens when a customer hits the scheduled-run cap mid-period?** *Recommendation: **hard
   stop, loudly**: skip the run with `status='skipped_capped'`, show a persistent banner in the portal,
   and send **one** notification email per period (not one per skipped run). Never silently degrade
   daily→weekly — a customer who thinks they are getting daily reports and is getting weekly ones has
   been lied to by software, which is worse than being told they hit a limit.*
8. **RESOLVED (by implication) 2026-08-21 — no.** Q6's answer scoped customer branding to "color and
   some header text" specifically, with no mention of the chart palette — §4.3's rule stands: those
   colours are semantic (green = healthy, amber = watch, red = alarm), and a customer whose brand colour
   is red would ship a report where every healthy metric looks like an alarm. Branding recolors the
   header brand text, the page-2 header, and the footer rule — nothing in `report_svg.py`. Worth
   re-confirming explicitly if a future "but they said white-label" request tries to expand this.
9. **Reinforced by §0.7 — yes, and now load-bearing, not just recommended.** Once CSV-sourced sites are
   entirely excluded from scheduling (§0.7), `source='vrm_api'` sites are the *only* sites that can ever
   produce a scheduled report — so the deferred Phase 15 sync step isn't an optional freshness
   improvement anymore, it's the only mechanism by which a scheduled report is ever generated from
   current data at all. The cost is still **one extra step in one workflow file** calling an endpoint
   that already exists and already works (§0.1). Treat it as closing Phase 15 Step 7.
10. **Trial length is a literal `7` in two unconnected places** (§0.1). Should this phase introduce one
    source of truth while it is editing the copy anyway? *Recommendation: **yes, cheaply** — export a
    `TRIAL_DAYS = 7` constant from `lib/plans.ts`, interpolate it into the new badge copy and the two
    existing strings, and leave a comment at `vrm_api/routers/billing.py` L604 pointing at it. Not worth
    a shared config mechanism across the Python/TS boundary; worth not having two numbers drift.*
11. **What should a scheduled report do for a `past_due` customer?** They are entitled per
    `_STATUS_ENTITLEMENT` (Q8's 7-day grace window from Phase 16). *Recommendation: **keep generating** —
    the grace period exists precisely so nothing degrades except a banner. Stated here because
    "scheduled jobs stop first" is a natural instinct and would quietly turn a banner-only grace period
    into a service interruption.*

### 0.7 New decision, 2026-08-21 — CSV-sourced sites are never eligible for scheduling

Not one of the original eleven questions — Oscar raised it directly when answering Q1, and it changes
the shape of §3 meaningfully enough to record as its own decision rather than folding it silently into
Q9's answer.

> A CSV-upload site's data is exactly as stale as the last time a human uploaded a file. Scheduling
> automatic reports against that is scheduling reports against data that, by construction, isn't there
> yet on most ticks of the schedule. **Only `source='vrm_api'` sites — the ones this product can refresh
> on its own — are eligible for `report_schedule` at all.**

This **replaces** §3.5's original design, which handled CSV staleness with a per-run `skipped_no_data`
pre-check. That check is no longer needed for the reason it existed: a CSV site can no longer be *set*
to a non-`'off'` schedule in the first place, so there is nothing for the fan-out to skip around. It
simplifies four places, all updated below:

- **§2.3 / §5.1** — `single_report` (always CSV, per its own row's existing "(the same uploaded csv)"
  note) is `scheduled=0` for this reason too now, not only because it has no subscription.
- **§3.1** — the schema-level rule: `report_schedule` may only be non-`'off'` when `vrm.sites.source =
  'vrm_api'`.
- **§3.5** — rewritten: one path, not two. No more CSV pre-check; the sync-then-report ordering (§3.4's
  workflow) is now the *entire* freshness story, and it is exact rather than probabilistic (the sync
  step either ran and the data is current, or it failed and the site is `skipped_*`/`failed` for a
  legible reason — never "maybe stale").
- **§3.7** — the schedule editor on a CSV-sourced site's `SiteForm.tsx` doesn't render the cadence
  fields at all; it shows one sentence explaining why ("Connect this site to the VRM API to enable
  automatic reports") with a link to the connection flow, not a disabled control.

**What this does not change:** a CSV site can still be reported on *manually* at any time (Cap A still
applies) — this only removes it from the *scheduled* path. A customer who wants scheduling for a site
that's currently CSV-only has an obvious, correct next action (connect it to VRM), which is a better
product story than "your reports are sometimes stale and we don't tell you which ones."

---

## 1. Feature 1 — the trial badge (smallest, first)

### 1.1 What changes, precisely

| Surface | Today | After |
|---|---|---|
| `Pricing.tsx`, Starter card | no mention of the trial | a distinct badge pill on the card |
| `Pricing.tsx`, Growth card | no mention; already has `featuredTag="Most installers"` | badge **plus** the existing featured tag — see §1.3 |
| `Pricing.tsx`, Fleet card | no mention | **no badge** — Fleet is `mailto:`-negotiated, not self-serve, and has no trial |
| `Pricing.tsx`, Single Report | no mention | **no badge** — one-off purchase, no subscription, no trial |
| `/signup` (`SignupForm.tsx`) | `signup_subtitle`, a plain `<p>` | a visually distinct callout above the form; `signup_subtitle` stays as the supporting line inside it |
| `/app/billing` `PlanPicker.tsx` | `billing_subscribe_note`, plain text | same callout treatment, for consistency at the point of purchase |

### 1.2 The i18n split — read this before writing a single string

`components/marketing/**` is **hardcoded English** and has no `t()` import. `app/(auth)/**` and
`app/(portal)/**` use `t(lang, key)` against paired `en`/`es` dicts.

- Pricing's badge text is a **hardcoded English string in the component**, matching that file's own
  convention. **Do not convert `Pricing.tsx` to i18n as a side effect** — that is a real piece of work
  with its own reasons, and smuggling it into a badge change makes the diff unreviewable.
- The signup and billing callout strings are **new keys in both `en` and `es`**, per
  PLAN_PHASE16.md §11, even though `FORCE_LANG='en'` means only English renders today.

Proposed new keys (both dicts): `trial_badge_label` ("7-day free trial"), `trial_callout_title`,
`trial_callout_body`. Reuse `signup_subtitle` / `billing_subscribe_note` as the body rather than
duplicating their text.

### 1.3 A new `Badge` UI component, not a one-off span

There is no badge primitive in `components/ui/`. Add `components/ui/Badge/` (`.tsx` + `.module.css`,
exported from `components/ui/index.ts`) built on `--radius-pill`, `--good` / `--victron`, and the
existing type scale — because this phase needs the same treatment in three different places (Pricing,
signup, billing) and three hand-rolled spans will drift.

**The Growth card collision:** `Panel`'s `featuredTag` renders absolutely-positioned at the card's top
edge. Putting a second pill there will overlap. Put the trial badge **inline, immediately under the
price**, not at the card edge — it reads as an attribute of the price, which is what it is, and it
sidesteps the collision entirely. Verify visually on the Growth card first, since that is the one that
can break.

---

## 2. Feature 2 — two independent caps on report cost

### 2.1 Why two caps and not one

They defend against different things and have different correct shapes:

| | Cap A — manual regeneration | Cap B — scheduled runs |
|---|---|---|
| Threat | a customer (or a stuck retry loop, or a bored browser) clicking Generate repeatedly | a customer picking `daily` across a large fleet, which is a *legitimate* setting that produces an *illegitimate* bill |
| Shape | short fixed window (hour + day), per customer | one number per billing period, per customer |
| Mechanism | existing `vrm.rate_limits` + `checkRateLimit()` — no new machinery | a `count(*)` over `vrm.report_runs` for the current period |
| When it fires | at click time, with an immediate error the customer sees | at *schedule-set* time as a projection, and at *run* time as a backstop |
| Failure mode | fails **open** on a DB error (it is an abuse control) | fails **closed**-ish: an uncountable ledger means don't run, and log loudly |

The asymmetry in the last row is deliberate and should be commented in code. A manual click that slips
through a Postgres hiccup costs one report. A scheduled fan-out that slips through could cost hundreds.

### 2.2 Where each is enforced

**Cap A — two layers, mirroring the repo's existing "two independent checks" discipline:**
1. `app/api/pipeline/reports/route.ts`, after `assertOwnsSite()` and before `createReport()`:
   `checkRateLimit('report_manual_hour', customerId, 3600, hourLimit)` and
   `checkRateLimit('report_manual_day', customerId, 86400, dayLimit)`. Returns
   `{ error: 'report_rate_limited', retryAfterSeconds }` with **429**, and `ReportManager.tsx` renders a
   real sentence, not a code.
2. `vrm_api/routers/reports.py:post_report()`, **only when `actor == 'customer'`**, applies a second,
   higher ceiling from the same table. This is not redundancy theatre: the Next.js layer is the only
   caller *today*, and `vrm_api` holds the pipeline key's trust boundary, not the customer's.
   `actor == 'admin'` is exempt — `/admin/reports` is Oscar, and rate-limiting Oscar's support tooling
   is a bug, not a control.

**Cap B — two moments:**
1. **Projection, at schedule-set time** (§3.7's UI): when a customer sets or changes a schedule, compute
   the projected runs/period across all their active scheduled sites and refuse the change with a clear
   message if it exceeds the cap. This is where a customer should learn about the limit — *before* they
   are relying on it, not on day 6 of the month.
2. **Backstop, at run time** (`vrm_api/report_limits.py`, called from `run-due` per site): count
   `vrm.report_runs` rows with `trigger='scheduled'` and `status='done'` inside the current billing
   period; if at or over the cap, record `status='skipped_capped'` and move to the next site. Never
   raise, never abort the whole run.

**Billing period boundaries:** read `current_period_start`/`current_period_end` from the customer's
mirror `vrm.subscriptions` row. **Fallback when there is no subscription row** (a legacy hand-managed
customer, `billing_status='none'`): the calendar month in the customer's `country` timezone. Comment
this fallback — it is the case that covers Oscar's own existing customers, and getting it wrong means
they stop receiving reports.

### 2.3 Numbers — RESOLVED 2026-08-21, Oscar's table, superseding the architect's first guess

Seeded into `vrm.plan_limits` (§5.1). `site_limit` per tier is from PLAN_PHASE16.md §0.6 Q1: Starter
≤10, Growth ≤50, Fleet 50+/unlimited. Scheduled caps are now further naturally bounded by §0.7: only
`source='vrm_api'` sites can ever count against the scheduled column, so a tier's real usage is bounded
by how many of a customer's sites are API-connected, not by the tier's full `site_limit`.

| `plan_key` | manual /hour | manual /day | scheduled / billing period | `white_label` | Reasoning |
|---|---|---|---|---|---|
| `default` (fallback for any unrecognized `plan` string) | 3 | 10 | 4 | `false` | Most restrictive. Reached only by a typo or a retired plan name — it should be survivable, not generous. |
| `trial` | 2 | 10 | **0** | `false` | Under Phase 16, `plan='trial'` means *no subscription at all* (legacy row) or *signup not yet paid*. Scheduling is a paid capability. A real trialing customer has `plan='starter'` and `billing_status='trialing'` — they get Starter's numbers, correctly. |
| `single_report` | 3 | 5 | 0 | `false` | One-off purchase against the same uploaded CSV — 0 scheduled for two independent reasons now: no subscription, **and** (§0.7) CSV sites can't schedule at all. |
| `starter` (≤10 sites) | 10 | 30 | **100** | `false` | Weekly-on-10 ≈ 44/mo, comfortably inside 100. Daily-on-all-10 = 300 → **capped**. Tighter than the architect's first draft (150) — reasonable, since §0.7 means a Starter customer's real API-connected site count is usually well under 10. |
| `growth` (≤50 sites) | 20 | 50 | **300** | **`true`** | Weekly-on-50 ≈ 217, inside 300 with headroom. Daily-on-all-50 = 1,500 → **capped**. |
| `fleet` (50+, hand-negotiated) | 40 | 200 | **2000** | **`true`** | Generous by design; Fleet is a conversation, and a `UPDATE vrm.plan_limits` covers any real exception. |

**Two things to flag about these numbers:**
- They are calibrated against **zero measured data**. Step 3's gate still requires measuring the real
  Anthropic + wall-clock cost of one report and recording it in this file — if that number lands far
  from what this table assumes, that's a third pass at the table via `UPDATE`, not a reason to hold up
  the build.
- The scheduled cap bites on the abuse case (daily-across-most-of-the-fleet) and clears the reasonable
  case (weekly-everywhere, plus daily on a handful) by construction — that's the ratio to preserve if
  the numbers are re-derived later, not the absolute values.

---

## 3. Feature 3 — report periodicity

### 3.1 Where the schedule lives

**Per-site** (Q1, RESOLVED — §5.3 has the columns). One `report_schedule` per `vrm.sites` row,
defaulting to `'off'` so **every site that exists today keeps behaving exactly as it does today** — the
same protective-default direction migration 024 used for `vrm_sync_enabled` and migration 025 used for
`provisioning_state`.

**RESOLVED 2026-08-21 (§0.7) — `report_schedule` may only be non-`'off'` when `vrm.sites.source =
'vrm_api'`.** A CSV-upload site's data is only ever as fresh as the last manual upload, so scheduling
automatic reports against it schedules reports against data that usually isn't there yet. This is
enforced in three independent places, same "hide an editor is UX, never a control" discipline as §4.2's
branding gate:
1. **Database** — a CHECK constraint on `vrm.sites` (§5.3) makes the invalid state unrepresentable.
2. **Write path** — `updateSite()`/`SITE_WHITELIST` refuses a schedule write for a non-`vrm_api` site
   server-side, independent of what the UI shows.
3. **UI** — `SiteForm.tsx` doesn't render the cadence fields for a CSV-sourced site at all (§3.7).

A per-customer `default_report_schedule` on `vrm.customers` is applied by `createSite()` to **new**
sites only, and **only when the new site's `source = 'vrm_api'`** — a new CSV site is always created
with `report_schedule = 'off'` regardless of the customer's default, per the same rule. Never applied
retroactively to existing sites either way. Retroactive application is what the bulk action in §3.7 is
for, and it must be an explicit click, not a side effect of editing a default.

### 3.2 What period each cadence means

Computed by `vrm_api/report_schedule.py`, in the **site's own IANA timezone**, always over **complete**
periods — never a partial today. Let `L` = now in the site's timezone, `today = L.date()`.

| Cadence | Anchor | Report period (inclusive) | Due when |
|---|---|---|---|
| `daily` | `today` | `[today-1, today-1]` | `L.hour >= report_schedule_hour` |
| `weekly` | the most recent date `≤ today` whose ISO weekday == `report_schedule_weekday` | `[anchor-7, anchor-1]` — the 7 complete days ending the day before the anchor | `today >= anchor` and `L.hour >= hour` |
| `monthly` | the most recent date `≤ today` whose day == `report_schedule_day_of_month` | the complete calendar month immediately preceding `anchor`'s month | `today >= anchor` and `L.hour >= hour` |

With `weekday = 1` (Monday, the default) this reproduces the Monday-morning / previous-Mon–Sun cadence
`monitoring`'s Apps Script trigger has always used, and matches `database/vrm_report_db.py:week_bounds()`'s
inclusive-both-ends convention. `day_of_month` is **capped at 28** by a CHECK, so February never
silently skips a month.

A monthly period (28–31 days) may render in the report's **Overview** mode. That is intended, not a
bug — the Pricing page sells "weekly **& Overview** reports" and this is what makes that sentence true.

**Idempotency:** a site is due only if no `vrm.report_runs` row already exists for
`(site_id, period_end, trigger='scheduled')` in a terminal-success or in-progress state. The unique
index does the real enforcing (§5.2); the check is an optimisation, not the guarantee.

### 3.3 Time zones — the gotchas, named

- **`zoneinfo` needs the `tzdata` package on a slim Docker image.** `vrm_api` runs on Render in a
  container; if the base image has no system tzdata, `ZoneInfo('America/Costa_Rica')` raises
  `ZoneInfoNotFoundError` at runtime, not at build time. **Verify inside the container**, and add
  `tzdata` to `requirements.txt` if it is missing. This is a Step 6 gate item, not a footnote.
- **A bad `timezone` value must not break the run.** `vrm.sites.timezone` is free text with a
  `NOT NULL DEFAULT`; nothing validates it as a real IANA name. On `ZoneInfoNotFoundError`, fall back
  to UTC, record `status='failed'` with a clear reason, and continue to the next site. Do not let one
  typo take down the fan-out.
- **DST does not exist in Costa Rica but does elsewhere**, and `vrm.sites.country` already defaults to
  `'CR'` rather than being fixed to it. Using `ZoneInfo` (not a fixed offset) is what makes this correct
  for a future non-CR customer. Do not "simplify" it to `utc_offset_hours`.

### 3.4 The fan-out: `POST /v1/reports/run-due`

Added to the existing `vrm_api/routers/reports.py` (which already carries
`dependencies=[Depends(require_pipeline_key)]` — **no new unauthenticated route is created by this
phase**; `vrm_api` still ends with exactly one, `GET /health`).

Modeled directly on `vrm_api/routers/vrm_sync.py:post_run_due()` — read that function before writing
this one. Differences, and why:

**It is batched, because reports are slow.** A report is an Anthropic call + a weather fetch + a
WeasyPrint render; `jobs.py`'s own comment budgets "well under a minute" for the slowest one. Fifty
sites processed sequentially and synchronously is a request nobody's HTTP timeout will tolerate. So:

- Request body: `{ "max_sites": int = 10 }`.
- Response: `{ sites_checked, processed, remaining, results: [{site_id, status, error}] }`.
- A **wall-clock budget** (~240 s): once exceeded, stop *starting* new sites, return with
  `remaining > 0`. A time budget alongside a count budget matters because ten fast sites and ten slow
  ones are very different requests.
- The workflow (§3.8) calls it in a bounded `bash` loop until `remaining == 0` or an iteration cap
  (~20) is reached, so a runaway can never loop forever.

**Per-site isolation is the point, not an aside.** Each site is wrapped in its own `try/except` that
logs, records `status='failed'` + a customer-safe message in the ledger, and continues. The gate in §8
Step 6 requires deliberately breaking one site mid-run and proving the rest still complete — the same
gate Phase 12's plan demanded, for the same reason.

**Per-site status vocabulary** (recorded in `vrm.report_runs.status`):

| Status | Meaning |
|---|---|
| `done` | PDF rendered, archived, (and from Step 8, emailed) |
| `skipped_not_due` | schedule is set but the period isn't complete yet, or the ledger already has this period |
| `skipped_no_data` | the site is `source='vrm_api'` and its sync ran, but `vrm.energy_daily` still has no rows in the target window — e.g. a newly connected site with no history yet (§3.5) |
| `skipped_capped` | the customer is at their scheduled-runs cap for this billing period (§2.2) |
| `skipped_not_entitled` | see §3.6 |
| `failed` | an exception; `attempt_count` incremented, retried next tick until `MAX_ATTEMPTS` |
| `abandoned` | `attempt_count >= MAX_ATTEMPTS` (propose 3); stop retrying this period, surface it |

### 3.5 Data freshness — RESOLVED 2026-08-21 (§0.7): one path, not two

The original version of this section handled two sources with two different answers. Oscar's §0.7
decision — CSV-sourced sites are never eligible for `report_schedule` at all — removes one of them
entirely. There is now exactly one path to a scheduled report, and it is exact rather than
probabilistic:

**Every schedulable site is `source = 'vrm_api'`, by construction (§3.1's CHECK constraint).**
`POST /v1/vrm-sync/run-due` **already exists, already works, and has never been called** (§0.1). The
workflow (§3.8) calls it as a step **before** the report step, for every due site, unconditionally. This
is Phase 15's Step 7, finally wired — one YAML step, no new code — and per §0.6 Q9 it is no longer
optional, it is the entire freshness story: a site's data is either current (the sync step ran and
succeeded) or the site is legibly `skipped_*`/`failed` for a stated reason (the sync step ran and
failed, and `continue-on-error` means the *report* step still runs and finds stale-or-missing data,
which is exactly what `skipped_no_data` below is for) — never silently stale.

**`skipped_no_data` still exists, but for a narrower and rarer reason.** It no longer means "this is a
CSV site with no upload yet" (that state can't reach the scheduler at all now). It means: this
`vrm_api`-sourced site's sync ran, but `vrm.energy_daily` still has no rows in the target window —
realistically, a site connected minutes ago with no ingest history yet, or a sync that failed silently
upstream of what `continue-on-error` catches. `build_report_data()` raises `ValueError("No energy_daily
rows for ...")` on an empty window; the scheduler still pre-checks rather than catching that exception,
for the same reason as before — a caught exception is a failure log entry nobody reads, a pre-checked
skip is a legible status. Visible to the customer in the portal history (§3.7), phrased plainly ("no
data yet for this period"), not as an error.

Partial coverage is a real, separate case: some days present in the window, some missing (a sync that
partially succeeded). Do **not** skip — generate the report. `build_report_data()` already tracks
`missingDays` and the rendered report already says so.

### 3.6 The entitlement gate — and the trap in it

A scheduled report runs only if **all** of:
- `vrm.customers.active` is true, and
- `vrm.customers.provisioning_state = 'active'`, and
- `vrm.sites.active` is true, and
- `vrm.customers.billing_status` is **not** in the known not-entitled set `{incomplete, unpaid, canceled}`.

**Read that last condition carefully — it is stated as a denylist on purpose.** The naive version
("`billing_status` must be in `{active, trialing, past_due}`") silently excludes
`billing_status = 'none'` and `NULL`, which is **every legacy, hand-created, Oscar-invited customer in
the database today** — including the ones who are the actual current business. `'none'` means "no ONVO
subscription was found," which for these customers means "not billing-managed," not "not paying."
Getting this backwards would turn the phase that adds automatic reports into the phase that stopped
Oscar's existing customers from getting them.

`past_due` keeps generating (Q11) — Phase 16's 7-day grace window is banner-only by design.

**The scheduler never calls ONVO and never calls `reconcile_customer()`.** It reads the derived cache
that `apply_entitlements()` already maintains. Adding a billing round-trip to a fan-out loop would put
ONVO's availability in the path of a report being generated, which PLAN_PHASE16.md §10 explicitly
designed against.

### 3.7 Customer-facing surface

**Schedule editor — in `app/(portal)/app/sites/SiteForm.tsx`**, not a new page. That form already
edits `report_language`, `timezone`, and `system_type`; a cadence belongs beside them, and adding a
whole route for four fields would fragment "site settings" across two places. Fields: cadence
(off/daily/weekly/monthly), weekday (weekly only), day-of-month (monthly only), local hour, and
recipients (Step 8). Add the new columns to `SITE_WHITELIST` in `lib/server/db/sites.ts` — that
whitelist is the only way a customer write reaches these columns.

**RESOLVED 2026-08-21 (§0.7) — the cadence fields only render for a `source='vrm_api'` site.** For a
`source='csv_upload'` site, `SiteForm.tsx` shows one line in their place — "Connect this site to the
VRM API to enable automatic reports" — linking to the existing VRM connection flow, not a disabled
cadence control. A disabled control invites "why is this greyed out" support email; a sentence that
names the actual next action doesn't. The server-side write path enforces the same rule independently
(§3.1) — the UI omission is convenience, not the control.

**Bulk action** on `SitesManager.tsx`: "apply this schedule to all my sites," with the projected
runs/period and the cap shown *before* confirming (§2.2 moment 1).

**Report history** — the customer-facing view of `vrm.report_runs`, tenant-scoped through
`lib/server/db/reportRuns.ts`: date, site, period, status (with a human sentence for every `skipped_*`
value), and a download link for `done` runs. Render it in the existing Reports area on `/app` rather
than inventing a nav item; the dashboard is already the reports page.

**Admin:** a recent-runs panel on `/admin/activity`, mirroring `BillingEventsTable.tsx` /
`RecentSignupsPanel.tsx`, plus a manual "run due now" button hitting `run-due`. This is the detection
surface for "the cron silently stopped" — which, per §0.5, is a real GitHub Actions failure mode.

### 3.8 The workflow

`.github/workflows/scheduled-reports.yml`, shaped exactly like `billing-reconcile.yml` (repo secrets,
`curl -sS -f`, `workflow_dispatch: {}` for manual spot checks). Three steps:

1. **Sync due VRM-API sites** — `POST /v1/vrm-sync/run-due` (§3.5). `continue-on-error: true` still —
   even though every schedulable site now depends on this step (§0.7: CSV sites can't be scheduled at
   all, so there's no separate class of report that survives a sync failure), one site's sync failure
   must not abort the workflow before the report step runs for every *other* site. The report step's own
   per-site isolation (§3.4) is what actually protects the rest; this flag just keeps the workflow alive
   long enough to reach it.
2. **Run due reports** — the bounded loop over `POST /v1/reports/run-due` (§3.4).
3. **(Step 8) Nothing extra** — email happens inside the report run, not as a separate pass, so a
   rendered-but-unsent report is not a state that can exist.

**Cadence: hourly (`0 * * * *`).** Per-site local-hour scheduling across timezones is meaningless at
daily granularity. Cost check, since it is a real constraint on a private repo: ~24 runs/day × the
1-minute GitHub Actions billing minimum ≈ **720 minutes/month**, against a 2,000-minute free tier and
the existing billing workflow's ~30. Comfortable, but worth stating in the workflow's own header
comment so the next person doesn't add a fourth hourly workflow without noticing. If it ever becomes a
problem, `0 */3 * * *` plus constraining `report_schedule_hour` to multiples of 3 is the fallback —
say so in the comment.

**Two GitHub Actions realities to write into the header comment:** scheduled runs are best-effort and
routinely delayed 5–15+ minutes under load (harmless here — §0.5 Decision 1 is exactly what makes it
harmless), and **GitHub disables scheduled workflows on repositories with 60 days of no commit
activity** (not harmless — and the admin panel in §3.7 is how it gets noticed).

---

## 4. Feature 4 — tiered branding

### 4.1 The shape of `vrm.customers.branding`

Still `jsonb`, still no schema-level constraint (migration 012's reasoning holds: it varies and
shouldn't need a migration per field). But it stops being undefined: the shape is documented in a
`COMMENT ON COLUMN` update, a Zod schema in `lib/server/db/branding.ts`, and a Pydantic model in
`vrm_api/schemas.py` — three places, one shape, all validating the same keys:

```
company_name    text     -- replaces "Pauly & Co." in the header/footer
logo_storage_path text   -- 'branding/{customer_id}/logo.png' in the vrm-monitor bucket
primary_color   text     -- '#RRGGBB', strictly validated (§4.4)
contact_name    text
contact_email   text     -- replaces proyectos@paulyco.com in the footer
contact_phone   text
website         text
```

Every key optional; a missing key falls back to the Pauly & Co default individually, not
all-or-nothing. A Growth customer who sets only a logo gets their logo and our contact block, which is
the sane behaviour and requires no special casing.

### 4.2 The gate: `vrm_api/branding.py:resolve_branding()` — one function, no exceptions

```
resolve_branding(customer_row) -> dict   # always returns a complete, safe branding dict
```

Rules, in order:
0. **Added 2026-08-21, from live testing — not in the original design.** If
   `customer_row['account_type'] != 'installer'`, same as rules 1/2 below: pure defaults, `branding`
   jsonb ignored entirely, regardless of tier or entitlement. Reasoning: an `account_type='owner'`
   customer is monitoring their own single system — there is no third party for their report to be
   "branded" AT, so the feature doesn't apply no matter what plan they're on. `account_type='installer'`
   is the actual use case (sending reports to their own clients). Mirrored on the Next.js side in
   `lib/server/db/branding.ts:getBrandingAccess()`, and the settings page (`/app/branding`) shows a
   distinct "not available for owner accounts" message with no upgrade CTA for this case — telling an
   owner to upgrade would be a real dead end, since upgrading doesn't change rule 0's outcome.
1. If `vrm.plan_limits` for the customer's `plan` has `white_label = false` (or the plan is
   unrecognized → the `'default'` row → `false`), **return the Pauly & Co defaults and ignore the
   `branding` jsonb entirely.** Not "merge with defaults" — ignore.
2. If the customer is not entitled (§3.6's same denylist), same: defaults.
3. Otherwise, merge the validated `branding` jsonb over the defaults, key by key, re-validating each
   value at read time (a colour that was valid when written is re-checked; the database is not trusted
   as a validator).

**`victron/weekly_report.py` receives the output of this function or `None`. It never receives
`customer_row['branding']`.** That is the enforcement, and it should be stated in a comment at both
ends. The parallel is exact: PLAN_PHASE16.md §6.4 control 3 ("no ONVO id is ever accepted from a
request body — every id is looked up") is the same shape of rule, and this phase's version should name
it.

**The reason the gate is server-side and not a UI condition** is the one this repo has stated since
Phase 14: hiding an editor is UX, never a control. A Starter customer who POSTs a branding payload
directly gets a 403 from the route *and* would still get an unbranded PDF even if the write somehow
landed, because the renderer never sees unresolved branding. Two independent failures required.

### 4.3 What branding does and does not recolor

**Does:** the `.brand` header text and its colour, the page-2 header, the footer contact line, the
footer logo image, and the company name in all three template locations.

**Does not:** anything in `victron/report_svg.py`. `GREEN`/`AMBER`/`RED`/`MINT` encode health tiers,
battery stress, and grid quality — a customer whose brand colour is red would ship a report in which
every healthy metric renders as an alarm. This file is **not modified by this phase at all** (§0.4),
which is the cheapest possible enforcement of that rule. (Q8.)

Also worth stating because it will be asked: **the report's layout does not change.** White-labelling
here means "your name, logo, colour, and contact details," not a template system.

### 4.4 Validating what a customer supplies

- **Colour:** `^#[0-9a-fA-F]{6}$`, server-side, on write **and** on read (§4.2 rule 3). This string is
  interpolated into SVG/CSS; an unvalidated one is an injection, not a styling bug. Additionally reject
  colours whose relative luminance is too high to read as text on white (propose: reject if luminance
  > 0.75) — otherwise a customer picks `#FFFFFF` and produces a report with an invisible header, then
  emails Oscar about it.
- **Logo:** uploaded to `branding/{customer_id}/logo.<ext>` in the existing `vrm-monitor` bucket via
  the signed-upload pattern `app/api/uploads/sign/route.ts` already implements (Q6). Server-side:
  **verify the bytes with Pillow** (already a dependency) rather than trusting the declared
  content-type; accept PNG and JPEG only; **reject SVG** (it is a script-bearing format and this one
  ends up embedded in a rendered document); cap at ~1 MB and ~1000 px on the long edge. The renderer
  base64-encodes it exactly the way `get_logo_b64()` already does for the Pauly & Co asset, so
  WeasyPrint never fetches anything over the network.
- **Text fields:** length caps, HTML-escaped by Jinja2's `autoescape` (already on for `.html` in
  `render_html()` — confirm it stays on; `_safe()`/`Markup` is used only for pre-built SVG and must not
  be extended to branding values).

### 4.5 The settings page

New route `app/(portal)/app/branding/` (page + form + actions + CSS module) and a nav item in
`app/(portal)/app/layout.tsx` — its own page rather than a section of `/app/profile`, because a logo
uploader plus a colour picker plus a live preview is not a compact form and `/app/profile`'s existing
pattern is "compact status card + link" (which is what `/app/profile` should get here: a one-line
branding status card linking to the new page, matching how it already handles VRM connection and
billing).

- **Entitled Growth/Fleet:** the editor, plus a **live preview of the report header** rendered in the
  browser from the same values — so a customer can judge their colour without generating a PDF. This is
  worth building; the alternative is a generate-check-adjust loop that costs a report every iteration,
  which fights §2 directly.
- **Starter/trial:** an upsell `Panel` naming the tier that unlocks it and linking to `/app/billing`.
  Not a disabled form — a disabled form invites tampering and teaches nothing.
- **Admin:** add `branding` to `ADMIN_CUSTOMER_WHITELIST` so Oscar can set it for a Fleet customer
  during onboarding. Do **not** add it to `PROFILE_WHITELIST` — the branding write goes through
  `lib/server/db/branding.ts`'s own narrow, tier-gated path, not the generic profile update.

---

## 5. Schema — migration 026

One migration, serving all three schema-bearing features. Same header style and idempotency discipline
as migrations 024/025 (`CREATE TABLE IF NOT EXISTS` / `ADD COLUMN IF NOT EXISTS` throughout), plus
`tools/run_migration_026.py` mirroring `tools/run_migration_025.py`. **Every new column's default
preserves current behaviour** — that is the single most important property of this migration.

### 5.1 `vrm.plan_limits` — per-tier cost and capability limits

```
plan_key                     text PRIMARY KEY   -- 'default' | 'trial' | 'single_report' | 'starter' | 'growth' | 'fleet'
manual_reports_per_hour      int  NOT NULL
manual_reports_per_day       int  NOT NULL
scheduled_reports_per_period int  NOT NULL
white_label                  boolean NOT NULL DEFAULT false
notes                        text
updated_at                   timestamptz NOT NULL DEFAULT now()
```

Seeded from §2.3's table. **The `'default'` row is mandatory and is stricter than every paid tier**
(starter/growth/fleet) — a `COMMENT ON TABLE` should say so, and so should the resolver, because
`lib/plans.ts:planSiteLimit()` fails *open* and the contrast will look like an inconsistency to whoever
reads both next. **Note, added 2026-08-21 after Step 2's own validation gate caught this exact phrasing
as an overclaim on the first live run:** `'default'` is deliberately *not* asserted to be the strictest
row in the whole table — `trial` and `single_report` are independently even stricter on
`scheduled_reports_per_period` (0, vs `default`'s 4), because those states structurally cannot schedule
at all (no paid subscription, or CSV-only, §0.7), which is a different kind of restriction than
typo-safety. `tools/run_migration_026.py`'s check 4 only compares `'default'` against
starter/growth/fleet, not against every row.

No FK to `vrm.plans` (different grain — one row per tier, not per price) and no CHECK on `plan_key`
(`vrm.customers.plan` is free text and always has been).

### 5.2 `vrm.report_runs` — the ledger

One row per report generation attempt, manual or scheduled. Serves three jobs at once: Cap B's counter,
the scheduler's idempotency claim, and the "what happened last night" record that PHASES.md Phase 12
identified as non-negotiable for an unattended job.

```
id              uuid PRIMARY KEY DEFAULT gen_random_uuid()
customer_id     uuid NOT NULL REFERENCES vrm.customers(id) ON DELETE CASCADE
site_id         text NOT NULL          -- text, no FK, matching vrm.jobs' precedent
trigger         text NOT NULL CHECK (trigger IN ('scheduled','manual','admin'))
schedule        text                   -- the cadence that produced it; NULL for manual
period_start    date NOT NULL
period_end      date NOT NULL
status          text NOT NULL          -- §3.4's vocabulary; no CHECK (same reasoning as vrm.subscriptions.status)
attempt_count   int  NOT NULL DEFAULT 0
storage_path    text
job_id          uuid                   -- the vrm.jobs row, when one was used
recipients      text[]                 -- who it was emailed to (Step 8)
email_status    text                   -- 'sent' | 'failed' | 'skipped' | NULL
error           text                   -- customer-safe only, via jobs.py:_safe_error_message()'s discipline
created_at      timestamptz NOT NULL DEFAULT now()
updated_at      timestamptz NOT NULL DEFAULT now()
```

**The idempotency claim is a partial unique index, not a lock:**

```
CREATE UNIQUE INDEX idx_vrm_report_runs_scheduled_period
  ON vrm.report_runs (site_id, period_end) WHERE trigger = 'scheduled';
```

The scheduler claims a period with `INSERT ... ON CONFLICT DO NOTHING RETURNING id`. If nothing comes
back, the period is already claimed: re-read the row and proceed **only** if its status is `failed` and
`attempt_count < MAX_ATTEMPTS` (propose 3), updating that same row in place. This gives idempotency,
bounded retry, and safety under two concurrent cron runs, with no application-level locking — the same
"let Postgres be the mutex" move PLAN_PHASE16.md §5.4 landed on for duplicate subscriptions.

Manual runs are deliberately **not** covered by the index: a customer regenerating the same range is a
legitimate thing to do (which is what Cap A bounds).

Indexes: `(customer_id, created_at DESC)` for the portal history, and
`(customer_id, trigger, status, period_end)` for Cap B's count.

**Retention:** unlike `vrm.signup_requests`, these rows are **not pruned** — they are the audit trail
for a paid deliverable. Volume is bounded by Cap B by construction. Say this in a `COMMENT ON TABLE`
so nobody adds it to Phase 16's prune sweep by analogy.

### 5.3 `vrm.sites` — new columns

```
report_schedule            text NOT NULL DEFAULT 'off'
                             CHECK (report_schedule IN ('off','daily','weekly','monthly'))
report_schedule_weekday    smallint NOT NULL DEFAULT 1  CHECK (BETWEEN 1 AND 7)   -- ISO, Monday=1
report_schedule_day_of_month smallint NOT NULL DEFAULT 1 CHECK (BETWEEN 1 AND 28) -- 28 cap: §3.2
report_schedule_hour       smallint NOT NULL DEFAULT 6  CHECK (BETWEEN 0 AND 23)  -- site-local
report_recipients          text[]                        -- NULL/empty -> customer contact_email (Step 8)
report_last_period_end     date                          -- last successfully-generated scheduled period
report_last_run_at         timestamptz
```

**Plus one table-level CHECK, added by this same migration (§0.7):**

```sql
ALTER TABLE vrm.sites ADD CONSTRAINT sites_scheduled_reports_require_vrm_api
  CHECK (report_schedule = 'off' OR source = 'vrm_api');
```

This is the enforcement layer named first in §3.1's numbered list — it makes "a CSV-sourced site with a
live schedule" an unrepresentable state, independent of whatever the write path or the UI does or fails
to do. Every existing row passes trivially (`report_schedule` defaults to `'off'` for all of them), so
this constraint cannot fail against current data — the Step 2 gate should still insert-and-rollback a
row that violates it, to prove the constraint is real and not just present in the SQL.

`'off'` by default is the whole safety story: **no site that exists today starts generating or emailing
anything as a result of this migration.** The Step 2 gate asserts this with a count, not by eye.

### 5.4 `vrm.customers` — new columns

```
default_report_schedule text NOT NULL DEFAULT 'off'
                          CHECK (default_report_schedule IN ('off','daily','weekly','monthly'))
```

Applied by `createSite()` to new sites only (§3.1). Plus an updated `COMMENT ON COLUMN
vrm.customers.branding` documenting §4.1's shape and naming `vrm_api/branding.py:resolve_branding()`
as the only reader.

### 5.5 What migration 026 must NOT do

- **No new `SECURITY DEFINER` function.** (Migration 025 §3.9's rule, restated.)
- **No CHECK on `vrm.report_runs.status`** — same reasoning as `vrm.subscriptions.status`: a status
  vocabulary that grows should not be able to fail an insert in a background job.
- **No backfill of `vrm.report_runs` from `vrm.jobs`.** Tempting (there are historical `kind='report'`
  rows) and wrong: those rows have no period/trigger/schedule semantics and would corrupt Cap B's
  counts on day one.
- **No change to `vrm.plans`.** The tier catalogue is the money path; limits are not.
- **No RLS policies.** Unchanged from Phases 14–16: `anon`/`authenticated` hold zero grants on `vrm`,
  and every access path is service-role from `server-only` code.

---

## 6. Security

Most of this phase's surface is behind an existing session or the pipeline key. Four things are
genuinely new:

1. **A customer-supplied image ends up embedded in a document we render** (§4.4). Bytes verified with
   Pillow, PNG/JPEG only, SVG rejected, size and dimension capped, read only from our own bucket,
   base64-embedded rather than fetched. **Never fetch a customer-supplied URL from `vrm_api`** — that
   is the SSRF vector Q6 exists to close, and it should be a review criterion, not just a design note.
2. **A customer-supplied colour ends up in an SVG/CSS context** (§4.4). Strict regex, validated on both
   write and read.
3. **An automated system sends email to addresses a customer typed** (§3.7, Step 8, Q5). Capped per
   site, entitled customers only, every send logged, and the report-run caps double as the email-volume
   cap. The abuse budget here is measured in **Resend reputation**, exactly as PLAN_PHASE16.md §6.6
   framed signup — and unlike signup, this one can be triggered repeatedly by an account that already
   exists.
4. **A new authenticated `vrm_api` route that iterates across every tenant** (`run-due`). It is behind
   the pipeline key like every other route, takes **no customer or site identifier from its body**
   (it derives its own worklist from the database — the §4.2/PLAN_PHASE16 §6.4 rule again), and returns
   only site ids and statuses, never customer data.

Unchanged and re-asserted: `vrm_api` still has exactly **one** unauthenticated route (`GET /health`);
no CORS middleware anywhere; no secret in a log line; no raw Postgres/Python error string reaching a
browser (`_safe_error_message()`'s allow-list gains no new exception types unless a new
customer-safe exception class is added deliberately, in which case it is added the way `VrmSyncError`
was).

`scripts/test-scoping.ts` gains cases: customer A cannot read customer B's `vrm.report_runs`; customer
A cannot set a schedule on customer B's site; a Starter customer's branding write is refused
server-side; and a Starter customer's rendered report carries Pauly & Co branding even when their
`branding` jsonb is populated (the belt-and-braces case from §4.2).

---

## 7. Failure modes — what happens and what each party sees

| What happens | System behaviour | Customer sees | Oscar sees |
|---|---|---|---|
| One site's report raises mid-fan-out | `status='failed'`, `attempt_count+1`, loop continues | that period marked failed in history; retried within the hour | the run in `/admin/activity`; the traceback in Render logs |
| A site fails 3 times | `status='abandoned'`, no further retries for that period | "we couldn't generate this report — contact support" | an abandoned row, which is the thing to alert on |
| No data in the window (only possible for a `vrm_api` site — §0.7 means a scheduled run never reaches a CSV site) | `skipped_no_data`, no attempt, no cost | "no data synced yet for this period" | same row |
| Customer hits the scheduled cap | `skipped_capped`; one notification email per period (Q7) | a persistent portal banner + one email | the count in `/admin` |
| Customer's subscription lapses | `skipped_not_entitled`; **no data deleted, no schedule cleared** | billing banner (Phase 16's, unchanged) | `billing_status` on `/admin/customers` |
| The cron doesn't fire (GitHub 60-day idle disable, outage) | nothing runs; nothing corrupts; the next run catches up every missed complete period | reports arrive late | **the gap in `/admin/activity`'s recent-runs panel — this is the only detection surface, which is why §3.7 builds it** |
| Two cron runs overlap | the unique index rejects the second claim | nothing | nothing |
| VRM sync step fails | `continue-on-error` — the report step still runs; the affected site is likely `skipped_no_data` or reports a stale-but-honest window rather than blocking every other site's run | possibly an older period, or a `skipped_no_data` entry | the sync step's failure in the Actions tab |
| Resend rejects a report email | PDF is still rendered and archived; `email_status='failed'`, run stays `done` | the report is downloadable in the portal | `email_status` in the ledger |
| Logo file is missing/corrupt at render time | fall back to the Pauly & Co logo, log a warning, **still produce the report** | a report with our logo instead of theirs | the warning |
| `tzdata` missing in the container | every site fails at the timezone step | no reports at all | caught by Step 6's gate, before it ever ships |

---

## 8. Build steps

Each step ends in something runnable behind its own gate. Nothing proceeds past a failed gate.

### Step 0 — Make Phase 17 legible in `PHASES.md` (~15 min)

The architect agent has no `Edit` tool and `PHASES.md` is >1,200 lines, so §12 hands the mechanical
edits over verbatim, same as Phases 14/15/16 did. **Do this before any code.**

**Gate:** `PHASES.md` has a Phase 17 row and section; the timeline table and critical-path notes
mention it.

---

### Step 1 — The trial badge (~0.5 day; blocks nothing, unblocked by nothing)

Deliberately first: it is the smallest slice, it ships customer-visible value immediately, it touches
no schema, and it warms up the i18n/CSS-module conventions before the harder steps.

**Build:** `components/ui/Badge/` (+ export from `components/ui/index.ts`); badge on Starter and Growth
cards in `Pricing.tsx` (hardcoded English, §1.2 — **do not** i18n that file); the trial callout on
`SignupForm.tsx` and `PlanPicker.tsx` using new `en`/`es` key pairs; the `TRIAL_DAYS` constant in
`lib/plans.ts` interpolated into the new copy and the two existing strings, with a pointer comment at
`vrm_api/routers/billing.py` L604 (Q10).

**Validate:**
- The Growth card renders the badge **and** the "Most installers" featured tag with no overlap, at
  desktop and mobile widths. This is the one that can break (§1.3) — look at it, don't assume it.
- Fleet and Single Report show **no** badge.
- New keys exist in **both** `en` and `es` dicts (grep the file; count the pairs).
- `Pricing.tsx` still has zero `i18n` imports — confirm the diff didn't drift.
- `npm run build` clean; no new console warnings.

---

### Step 2 — Migration 026 (~1 day; **Q1 RESOLVED, unblocked**) — ✅ DONE 2026-08-21

Applied by Oscar via the Supabase SQL Editor; `python -m tools.run_migration_026` passes every check
(defaults on every existing row, the CSV-exclusion CHECK actually rejecting/accepting the right sites,
the partial unique index actually enforcing scheduled-run idempotency while allowing repeat manual runs,
the day-of-month/weekday CHECKs, and — after one fix, see below — the `plan_limits` invariant). Frontend
`npm run typecheck` re-confirmed clean (no `.ts`/`.tsx` touched this step, as expected).

**One real bug caught and fixed by the gate itself, worth recording:** the first version of check 4
asserted `'default'` must be the strictest row in the *entire* `vrm.plan_limits` table, and failed
against Oscar's real numbers — `trial` and `single_report` are deliberately even stricter than
`'default'` on `scheduled_reports_per_period` (0, vs `'default'`'s 4), because those states structurally
cannot schedule reports at all, not because of typo-safety. That's correct data; the test's assumption
was wrong. Fixed by narrowing the check to "`'default'` is stricter than every **paid** tier
(starter/growth/fleet)" — the actual security-relevant property — in `tools/run_migration_026.py`, the
`COMMENT ON TABLE vrm.plan_limits` in the migration file, and the three places in this plan (§0.5
Decision 2, §5.1) that repeated the original overclaim.

**Build:** `database/migrations/026_report_schedule_limits_branding.sql` (§5, all four sub-sections,
including §5.3's `sites_scheduled_reports_require_vrm_api` CHECK) + `tools/run_migration_026.py`. Seed
`vrm.plan_limits` from §2.3's final table (Q2, RESOLVED — Oscar's numbers, already the ones in §2.3, no
placeholder pass needed).

**Validate:**
- Every table/column/index exists with the intended constraints and comments.
- **`SELECT count(*) FROM vrm.sites WHERE report_schedule <> 'off'` returns 0.** Assert it; don't
  eyeball it. This is the single assertion that proves the migration changed nobody's behaviour.
- Same for `vrm.customers.default_report_schedule`.
- **The `sites_scheduled_reports_require_vrm_api` CHECK actually rejects the invalid state:** attempt
  `UPDATE vrm.sites SET report_schedule = 'weekly' WHERE source = 'csv_upload' LIMIT 1` inside a
  transaction that gets rolled back — it must fail. Then confirm the same update against a
  `source='vrm_api'` row succeeds.
- The partial unique index on `vrm.report_runs` actually refuses a second scheduled row for the same
  `(site_id, period_end)` — insert one and watch it fail — while **allowing** two `trigger='manual'`
  rows for the same period.
- The `'default'` row exists in `vrm.plan_limits`, is stricter than every paid tier
  (starter/growth/fleet — **not** compared against `trial`/`single_report`, which are independently
  stricter still on `scheduled_reports_per_period` by design, §5.1's note), and its values match §2.3
  exactly (diff the seeded row against the table in this file, not from memory).
- `day_of_month = 29` is rejected by the CHECK; `weekday = 0` and `weekday = 8` are rejected.
- The existing app still builds and `/app/sites`, `/app/profile`, `/admin/customers` all still render
  (nothing customer-facing changed yet).

---

### Step 3 — Report limits, enforced (~1 day; **Q2 RESOLVED, unblocked**) — ✅ DONE 2026-08-21

**Built:** `vrm_api/report_limits.py` — `resolve_limits()` (the `'default'`-fallback resolution),
`check_manual_cap()` (Cap A's `vrm_api`-side ceiling, its own `report_manual_*_vrm_api` rate-limit
buckets — deliberately distinct from the Next.js layer's buckets, see the module's own docstring for
why sharing one would double-count a single request), and `resolve_billing_period()` /
`check_scheduled_cap()` (Cap B — written now, no caller until Step 6). `ReportRateLimited` registered as
a FastAPI exception handler in `vrm_api/main.py` (429, nested `detail.retry_after_seconds`, matching
`routers/billing.py`'s own `over_site_limit` shape so `lib/server/pipeline.ts:pipelineJson()` parses it
for free). Wired into `vrm_api/routers/reports.py:post_report()` for `actor=='customer'` only.

Next.js side: `lib/server/db/reportLimits.ts:getManualReportLimits()` (reads `vrm.plan_limits` directly,
the same resolution rule as the Python side); Cap A's lower ceiling in
`app/api/pipeline/reports/route.ts`, checked via the existing `lib/server/ratelimit.ts:checkRateLimit()`
before `createReport()` is ever called — a rate-limited customer costs `vrm_api` nothing. `429
report_rate_limited` handled in `ReportManager.tsx` with a real sentence
(`reports_error_rate_limited_hour`/`_day`, en/es).

**Validated:**
- Python and TS both compile clean (`ast.parse` + a live `vrm_api.main` import — 31 routes register with
  no circular-import issue from the new `ReportRateLimited` import; `npm run typecheck` / `npm run lint`
  both clean).
- `resolve_limits()` correctly resolves a real seeded tier and falls back to `'default'` for `None`/an
  unrecognized string — exercised against the live `vrm.plan_limits` table from Step 2.
- **Cap A end-to-end, against the real database, not just read from the code:** for a throwaway
  `customer_id` on the `'default'` plan (`manual_reports_per_hour=3`), three real `check_manual_cap()`
  calls succeeded and the fourth correctly raised `ReportRateLimited(retry_after_seconds=3600)`. Real
  `vrm.rate_limits` rows were written and cleaned up afterward.
- **The nonsense-plan test the gate specifically calls out, run for real:** `resolve_limits('this-is-not-
  a-real-plan-xyz')` resolves to the exact same row as `resolve_limits('default')` — confirmed by value
  equality, not just by plan_key — proving the failure direction is "restrictive," not "unlimited."
- `resolve_billing_period()`'s calendar-month fallback, exercised for a customer_id with no subscription
  row at all (the legacy-customer case §3.6 names): correctly returned the current calendar month
  (2026-08-01..2026-08-31, run on 2026-08-21). `check_scheduled_cap()` correctly reports "under cap" for
  a customer with zero prior `vrm.report_runs` rows.
- **Real measurement, `tools/measure_report_narrative_cost.py`** (a genuine, priced Anthropic call using
  the exact model/`max_tokens`/prompt framing `victron/weekly_report.py:generate_narrative()` itself
  uses, not a mock):

  | | wall-clock | input tokens | output tokens | cost @ Sonnet 4.6 ($3/$15 per 1M) |
  |---|---|---|---|---|
  | Weekly report narrative | 7.34s | 454 | 236 | **≈$0.0049** |
  | Monthly (Overview) narrative | 6.76s | 649 | 230 | **≈$0.0054** |

  **Finding: §2.3's numbers do not need a downward revision on cost grounds.** Even Fleet's cap (2,000
  scheduled reports/period) costs roughly **$10/month** in Anthropic spend at these rates — the narrative
  call itself is not the expensive part of a report. What the caps in §2.3 actually protect against is
  report-generation *churn* (WeasyPrint render time, weather-API calls, Storage writes, and the
  wall-clock budget in §3.4's fan-out — a report takes ~7s just for the narrative, before rendering),
  and abuse/spam prevention, not Anthropic token cost specifically. This is worth remembering if the
  numbers are ever revisited: tightening them further for "cost" reasons would be solving the wrong
  problem.
- Cap A's fail-open behavior (both layers) is a direct reading of `checkRateLimit()`'s and
  `_increment_rate_limit()`'s own committed code (both return `true`/`None` and log on a DB error, never
  raise) — not re-tested by killing a live database this pass; Cap B's `check_scheduled_cap()`
  deliberately has no equivalent try/except, so a DB error there propagates rather than returning a
  count, which is the fail-closed-ish shape §2.1's asymmetry table calls for. Full live verification of
  both under real concurrent load happens at Step 6, once Cap B has an actual caller.

---

### Step 4 — Branding, server-side only (~1.25 days; no UI) — ✅ DONE 2026-08-21

**Built:** `vrm_api/branding.py:resolve_branding()` — the tier gate (rule 1, `vrm.plan_limits.
white_label`), the entitlement gate (rule 2, the same denylist §3.6 uses), and per-field validation on
read (rule 3: hex-colour regex + luminance check, text length caps, and a real Pillow-verified logo
fetch+base64-encode with a warn-and-fall-back-per-field on any failure). `victron/weekly_report.py`
gained an additive `branding: dict | None = None` parameter on `build_report_data()` — deliberately
threaded through the same returned `d` dict every other computed value already flows through (a small,
deliberate deviation from the plan's literal "parameter on `render_html()` too" — `render_html(d)`'s own
signature is untouched; it reads `d.get("branding")` internally, which is a smaller diff and one fewer
thing for `render_pdf()`/`generate()` to know about, and preserves the exact same "one `d` dict carries
everything" shape this file already uses everywhere else). `victron/templates/weekly_report.html`'s three
"Pauly & Co." locations, the `.brand`/`.p2hdr-l` text colour, and the footer contact email are now
Jinja variables defaulting to the literals they replaced. `vrm_api/routers/reports.py:_do_report()`
resolves branding once, at the top, for `schema_=='vrm'` only — `monitoring` reports (no
`vrm.customers` owner at all) always get `None`, unconditionally. `vrm_api/schemas.py:BrandingFields`
documents the shape as the third of the plan's "three places, one shape" (alongside migration 026's
`COMMENT ON COLUMN` and the Zod schema Step 5 will add).

**Validated — real, live checks against the real database, not just read from the code:**
- **The byte-identical gate, proven empirically, not asserted.** Used `git stash push -- victron/
  weekly_report.py victron/templates/weekly_report.html` to get the true pre-Step-4 baseline, rendered a
  real `monitoring` site (`vista-atenas-lp-m1`, a real 7-day window with real data) and a real `vrm` site
  (`vista-atenas-2-floor-pool`, real data, `branding=None`) with the OLD code, `git stash pop` to restore
  Step 4's code, rendered both again, and `cmp`'d the raw PDF bytes: **both byte-identical.**
- **The five `resolve_branding()` gate scenarios, each run for real:** (1) a Starter (non-white-labeled)
  customer with `branding` fully populated → resolves to the exact `DEFAULTS` dict, branding jsonb
  ignored entirely, not merged; (2) a Growth (white-labeled) customer who is `billing_status='canceled'`
  → same, defaults, proving entitlement is checked independently of the tier gate; (3) a real entitled
  Growth customer with real branding → `company_name`/`primary_color`/`contact_email` all applied
  correctly; (4) `primary_color = '#fff" onload="alert(1)'` (a real injection attempt, written as if
  bypassing every UI) → rejected by the regex, falls back to `#1FAE6E`; (5) `primary_color = '#FFFFFF'`
  → rejected by the luminance check (too light to read), also falls back to `#1FAE6E`.
- **The nonexistent-logo case, for real:** `logo_storage_path` pointed at an object that doesn't exist in
  the bucket → a real 404 from Supabase Storage, caught, logged as a warning
  (`branding: could not download logo at ... — falling back to default logo: ... 404 ... not_found`),
  `logo_b64` resolves to `None` (so the renderer falls back to the Pauly & Co asset) — **and
  `company_name` from the SAME branding dict still applied**, proving the per-field (not all-or-nothing)
  fallback really works, not just for logo.
- **The "every chart colour is unchanged" requirement, proven by diffing real rendered HTML, not by
  eyeballing a PDF:** rendered the same real `monitoring` site's data once with `branding=None` and once
  with a full custom branding dict (`company_name`, `primary_color=#2277CC`, no logo), diffed the two
  HTML strings line by line. **Exactly 12 lines differed, all six of them the branding touchpoints
  (2 CSS colour rules, header text, page-2 header text, footer contact line, footer logo `alt` text) —
  every KPI/bar/SOC/trend/savings SVG block was byte-for-byte identical**, empirically confirming
  `report_svg.py`'s palette is untouched, not just inferred from the file being unmodified.
- `git diff --stat -- victron/` confirmed **exactly two files** (`weekly_report.py`,
  `templates/weekly_report.html`); `report_svg.py` does not appear in the diff at all.
- Python `ast.parse` on all five touched/new files, plus a live `vrm_api.main` import (31 routes,
  no circular-import issue introduced by `branding.py` importing `report_limits.py` lazily inside
  `_white_label_allowed()`).

---

### Step 5 — The branding settings page (~1.5 days; **Q6 RESOLVED — real storage, unblocked**) — ✅ DONE 2026-08-21

**Built:** `lib/server/db/branding.ts` + `reportLimits.ts:getWhiteLabelAllowed()` (the TS-side mirror of
`vrm_api/branding.py`'s gate); `app/api/branding/logo-sign/route.ts` (signed-upload, gated the same way);
`app/(portal)/app/branding/` (page, controlled-input form with a live header preview, server action with
real colour/luminance/email validation); nav item; `/app/profile` status card; `branding` added to
`ADMIN_CUSTOMER_WHITELIST` (not `PROFILE_WHITELIST`).

**Validated live against the real database:** Starter → `getBrandingAccess()` false, direct
`updateBranding()` call throws with nothing written; real entitled Growth → write round-trips correctly;
canceled Growth (white-label tier, not entitled) → correctly denied. TS luminance port hand-verified
against the same hex values Python's Step 4 gate was tested with. **Not verified live in this pass:** the
actual Pillow-rejection-through-a-real-upload cases (`.svg` renamed to `.png`, a 20MB image) — those
exercise `vrm_api/branding.py`'s Pillow check (already proven in Step 4) via a real browser file upload,
which needs an authenticated session this environment doesn't have; and no `scripts/test-scoping.ts` case
was added — see this section's own note below on why one doesn't apply here.

**Two rounds of real user feedback landed on top of this step and are folded in, not tracked as separate
steps:**
- **A new gate, §4.2 rule 0 (2026-08-21):** branding is `account_type='installer'`-only — an `owner`
  account has no third party for a report to be branded at, so it's excluded regardless of tier, with its
  own "not available for owner accounts" copy (no upgrade CTA, since upgrading wouldn't change the
  outcome). Added to both `resolve_branding()` and `getBrandingAccess()`, verified live on both sides.
- **The Billing page's plan-change flow**, unrelated to branding but fixed in the same session from live
  testing: the "Save X%" badge ported from Signup into `PlanPicker.tsx` and the marketing Pricing section;
  the Cancel-subscription dialog moved to render under the Subscription panel instead of the page bottom;
  a real backend bug fixed (`vrm.subscriptions.billing_interval` was never populated — ONVO's response
  has no such field, confirmed against a real payload; now sourced from `vrm.plans` instead); and the
  "Select a plan with no card on file" flow reworked end-to-end (auto-opens the card form, a real
  `no_payment_method` message, a confirmation step after the card saves, "Add card" vs "Replace card"
  wording).

---

### Step 6 — The scheduler: due-check + `run-due` + the ledger (~2 days; no email, no cron) — ✅ DONE 2026-08-24

The step where the hard thinking is. Keep it runnable by hand: set a test site's schedule with SQL, then
`curl` the endpoint.

**Build:** `vrm_api/report_schedule.py` (pure period arithmetic, §3.2); `vrm_api/report_runs.py` (claim,
update, count); `POST /v1/reports/run-due` in `vrm_api/routers/reports.py` (§3.4 — batching, wall-clock
budget, per-site isolation, the full status vocabulary); the entitlement denylist (§3.6) and the
`skipped_no_data` pre-check (§3.5); Cap B's runtime backstop wired in.

**Validate:**
- **Period arithmetic, table-driven and without a database:** for each of daily/weekly/monthly, across
  at least `America/Costa_Rica` and one DST-observing zone, assert the computed `(start, end)` and the
  due/not-due decision at hours either side of `report_schedule_hour`, on month boundaries, on a leap
  day, and with `day_of_month = 28` in February. This is the part that will be subtly wrong; test it
  like it.
- **`zoneinfo` resolves real IANA names inside the Render container**, not just on macOS. If it doesn't,
  add `tzdata` and re-verify. Do this before anything else in this step is believed.
- A site with a bad timezone string fails that one site and no others.
- **Idempotency:** call `run-due` twice back-to-back → the second produces zero new reports.
- **Concurrency:** call `run-due` twice *simultaneously* → still one report per site, no duplicate
  ledger rows, no interleaved half-write.
- **Per-site isolation (the Phase 12 gate):** deliberately break one site's data mid-run → every other
  site still completes, and the broken one has a `failed` row with a customer-safe message.
- A site with no data in the window → `skipped_no_data`, **no Anthropic call**.
- **§0.7's guarantee, proven at the query level, not just the schema level:** the due-site query
  `run-due` runs against never returns a `source='csv_upload'` row, even after attempting (and having
  the migration 026 CHECK reject) a direct `UPDATE` that tries to schedule one.
- A `billing_status='none'` legacy customer's site **does** generate (§3.6's trap — assert it
  explicitly).
- A `canceled` customer's site → `skipped_not_entitled`, and **no site was deactivated and no schedule
  was cleared**.
- A customer at their Cap B limit → `skipped_capped`, loop continues.
- `max_sites` and the wall-clock budget both actually bound the request; `remaining` is accurate.
- A site that fails 3 times → `abandoned`, and the 4th run does not retry it.

**Verification, 2026-08-24 — real, not hypothetical:**
- **Period arithmetic:** 20 table-driven assertions run against `report_schedule.py` with plain `python3`
  (zero dependencies, so this needed none of the checks below) — daily/weekly/monthly, `America/Costa_Rica`
  (fixed offset) vs `America/New_York` (DST, both EST and EDT instants), month and year boundaries, and
  the 2028 leap day. All passed. Full assertions in the session transcript; script was scratch, not
  committed.
- **Live, against the real Supabase database**, using a fully disposable test customer + site created and
  torn down by the test itself (verified zero leftover rows afterward, and the two real `vrm_api`
  customers — Karen Montealegre, Roberto Villalobos — confirmed untouched, `report_schedule` still `'off'`
  on both): 28 assertions, all passed —
  - `billing_status=None` (the §3.6 trap) generates normally, not `skipped_not_entitled`.
  - `skipped_no_data` fires with no Anthropic call; retried in place on a second call (one ledger row, not
    two).
  - A `done` row blocks a third call outright and is reported as `done`, not a generic skip.
  - A plan with `scheduled_reports_per_period=0` → `skipped_capped`.
  - `billing_status='canceled'` → `skipped_not_entitled`, with the site's `active`/`report_schedule` left
    untouched.
  - 3 manual `record_failed()` calls → `abandoned`; a 4th claim attempt is refused and `existing_status()`
    reports `abandoned` accurately.
  - **Concurrency:** 5 simultaneous threads claiming the same fresh period → exactly 1 winner, exactly 1
    ledger row.
  - **§0.7 at the query level:** flipping the test site to `source='csv_upload'` while
    `report_schedule='daily'` is REJECTED by migration 026's own CHECK constraint (`23514`,
    `sites_scheduled_reports_require_vrm_api`) — the row is provably unrepresentable, not just
    conventionally avoided.
  - **Per-site isolation:** one site with `timezone='Not/ARealZone'` and one healthy site processed in the
    same call — the bad one fails alone (logged, not raised), the healthy one still completes.
  - **Budgeting:** `max_sites=1` against 2 simultaneously-due sites processes exactly 1 and reports
    `remaining=1`.
- **Not verified this session:** `zoneinfo`/`tzdata` inside the actual Render container (only checked on
  macOS, which has its own system tz database) — flagged as a Step 9 (or pre-Step-9) gate item, not
  forgotten.

---

### Step 7 — The schedule UI + report history (~1.5 days) — ✅ DONE 2026-08-24

Placed before email deliberately: without this, every site is `'off'` and the scheduler has nothing to
do except in SQL.

**Build:** schedule fields in `SiteForm.tsx` + the new columns in `SITE_WHITELIST`; the bulk "apply to
all sites" action on `SitesManager.tsx` with the Cap B projection shown before confirming (§2.2 moment
1); `lib/server/db/reportRuns.ts` + the history list in the `/app` Reports area with a human sentence
for every `skipped_*` status and a download link for `done`; `createSite()` applying
`default_report_schedule`; the `/admin/activity` recent-runs panel + "run due now" button; `en`/`es`
strings for everything.

**Validate:**
- A customer sets weekly on one site, `run-due` generates it, the history row appears with a working
  download link.
- A schedule change that would exceed Cap B is **refused with the projected number named**, before
  anything is saved.
- Customer A cannot set a schedule on customer B's site, including via a tampered request body
  (`scripts/test-scoping.ts`).
- The new columns are actually in `SITE_WHITELIST` and a non-whitelisted field in the same payload is
  still dropped.
- Every `skipped_*` status renders as a sentence a non-technical customer can act on — read all six out
  loud.

**Verification, 2026-08-24 — real, not hypothetical:**
- `npm run typecheck`, `npm run lint`, `npm run build` — all clean (the build actually registers both new
  routes: `POST /api/admin/pipeline/reports/run-due`, `GET /api/pipeline/reports/runs/[runId]/download`).
- `npm run test:scoping` — still 11/11, unaffected by the `sites.ts`/`SITE_WHITELIST` changes.
- The three leak checks (`NEXT_PUBLIC_SUPABASE`, secrets in `.next/static`) — both clean.
- **Live, against the real database**, disposable fixtures created and torn down by the test itself: 11
  assertions on the new `sites.ts` functions — `createSite()` and `updateSite()` both correctly throw
  `ScheduleRequiresVrmApi` for a `csv_upload` site (§3.1 point 2, enforced independently of the CHECK
  constraint and of `SiteForm.tsx` not rendering the fields at all); `updateSite()` succeeds for a real
  `vrm_api` site; `applyScheduleToAllSites()`/`countSchedulableSites()` only ever touch active `vrm_api`
  sites, confirmed a `csv_upload` sibling site was left untouched; `getScheduledCapLimit()` resolves the
  real seeded `100` for `'starter'`.
- **A full, genuine end-to-end run** (not simulated): a disposable customer + `vrm_api` site + one real
  `energy_daily` row, then a real HTTP call to `vrm_api`'s own `POST /v1/reports/run-due` (the real
  Anthropic call, the real WeasyPrint render, the real Storage upload) — `status="done"`, a real
  `vrm.report_runs` row with a `storage_path`, `vrm.sites.report_last_period_end`/`report_last_run_at`
  correctly stamped, and a real Supabase Storage signed URL successfully created for the exact object the
  new `/api/pipeline/reports/runs/[runId]/download` route would serve. All fixture rows AND the generated
  Storage object were deleted afterward — confirmed zero leftovers.
- **Not verified this session** (no test customer session/cookie available in this environment, same
  limitation as Steps 1-6's own disclosures): a live browser click-through of `SiteForm.tsx`'s
  conditionally-rendered fields, the `BulkScheduleForm.tsx` projection UI, `ReportHistory.tsx`'s rendering
  of all 6 status sentences, and `/admin/activity`'s "Run due now" button — all exercised via the same real
  data paths above and confirmed to typecheck/build/lint clean, but not clicked through in a real browser.

---

### Step 8 — Report email delivery (~1.5 days; **Q4 RESOLVED — in scope, unblocked**; **Q5 RESOLVED 2026-08-25 — third-party recipients allowed, capped at 5 per site**, per the architect's own recommendation) — ✅ DONE 2026-08-25

**Build:** `attachments` parameter on `victron/mailer.py:send()` (additive, default `None`);
`victron/templates/report_email.html` — a Jinja2 port of the Apps Script `buildEmailHtml()` shape
(table layout, inline styles, **no `data:` URIs** — Gmail strips them), left in `victron/` so Phase 12
inherits it; `vrm_api/report_delivery.py` (render, attach the PDF, resolve recipients, send, record
`recipients`/`email_status`); recipient resolution (`vrm.sites.report_recipients` → else
`vrm.customers.contact_email` → else `auth_email`) with the per-site cap; the recipients field in
`SiteForm.tsx`; Cap B's per-period notification email (Q7).

**Validate:**
- A scheduled run for a real site lands in a real inbox with the PDF attached, correct subject, and the
  **customer's** branding in both the email body and the PDF (for a Growth customer).
- Resend rejects a send (bad address) → the run stays `done`, `email_status='failed'`, the PDF is still
  downloadable in the portal. **A delivery failure must never lose the report.**
- No `RESEND_API_KEY` → `MailerError`, one site affected, run continues.
- The per-site recipient cap is enforced server-side, not just in the form.
- Grep the sent HTML for `data:` URIs → none.
- `git diff --stat -- victron/` now shows exactly three files, all additive.

**A real design change made during the build, not in the original plan text — the unsubscribe mechanism.**
Q5's "yes, capped at 5" carries its own requirement: "an unsubscribe/'stop sending me this' footer link."
Built as `lib/server/reportUnsubscribe.ts` (TS) + `vrm_api/report_delivery.py:make_unsubscribe_token()`
(Python) — a stateless, HMAC-signed `(site_id, email)` token, cross-runtime-shared via a new
`REPORT_UNSUBSCRIBE_SECRET` env var (same shape as `PIPELINE_API_KEY`), landing on a new public
`/unsubscribe` route (no session, the signature is the sole authorization — mirrors `/activate`'s
"bound Server Action, token never a client prop" shape). Never sent for the customer's own
fallback-resolved address — only for a genuine third-party entry in `report_recipients`.

**A real bug found and fixed before it shipped, not in the original plan text — Cap B's notification
gate.** The first design reused `vrm.rate_limits`/`vrm.increment_rate_limit()` (the same primitive Cap A
uses). Wrong: `POST /v1/billing/prune-signups`'s own 2-day retention sweep would have silently deleted a
cap-notification row on day 3 of a ~30-day billing period, resetting the gate and sending a second
(third, ...) email for the same period — exactly the "flood them" outcome Q7 explicitly rules out. Fixed
with **migration 027** — one durable `vrm.customers.report_cap_notified_period_end` column instead, with
a compare-and-swap update so two concurrent `run-due` calls can't both send.

**Verification, 2026-08-25 — real, not hypothetical:**
- `npm run typecheck`, `npm run lint`, `npm run build` — all clean (a real bug caught here: importing
  `MAX_REPORT_RECIPIENTS` as a VALUE, not a type, from `@/lib/server/db` into the Client Component
  `SiteForm.tsx` pulled the whole `server-only` barrel into the client bundle graph and failed the build
  — fixed by keeping a local copy in the client component, the same "each file keeps its own whitelist
  copy" shape `sites.ts` already uses).
- `npm run test:scoping` — still 11/11. The three leak checks (now including `REPORT_UNSUBSCRIBE_SECRET`)
  — all clean.
- **Local, no network:** the rendered `report_email.html` output inspected directly — correct branding
  interpolation, the health-score badge staying FIXED/semantic (green/amber/red by score, never the
  customer's own brand colour, confirmed with a low-health case rendering red under green branding), a
  real unsubscribe link present only for a third-party recipient and absent for the customer's own
  address, zero `data:` substrings after two rounds of catching the check's own documentation comments
  accidentally containing the literal string being grepped for. Cross-runtime interoperability: a token
  signed in Python verified correctly in TypeScript with the shared secret; a tampered token, a malformed
  token, and a missing secret all correctly rejected/failed closed.
- **Live, against the real database and the real Resend/Anthropic/Storage stack**, disposable fixtures
  created and torn down by the tests themselves:
  - `sites.ts` recipient cap+format enforcement: 8 candidate emails (one malformed) →
    exactly 5 valid ones kept, in order.
  - `removeReportRecipient()`: case-insensitive removal, idempotent on a re-run or an absent email, silent
    no-op on a non-existent site (never throws).
  - `createSite()` with `report_recipients` but no schedule does NOT throw `ScheduleRequiresVrmApi` — an
    inert value on a `csv_upload` site is harmless, not an error.
  - "No `RESEND_API_KEY`" → `send_report_email()` returns `("failed", recipients)`, never raises.
  - The core "never lose the report" guarantee, at the DB layer directly: `status='done'` +
    `storage_path` intact + `email_status='failed'` coexist correctly on one row.
  - **A full, genuine end-to-end send**: a disposable Growth-plan, installer-type, custom-branded
    ("Step 8 Test Co.", amber) customer + a real `vrm_api` site with real `energy_daily` data → a real
    `POST /v1/reports/run-due` call → `email_status='sent'` recorded → **a real email landed in
    `proyectos@paulyco.com`'s inbox** with the correct branded header, health score, key stats, and the
    PDF attached — confirmed directly by Oscar (screenshot + the actual received PDF), both carrying
    identical "STEP 8 TEST CO." amber branding while the health-score/chart colours stayed the fixed
    semantic green, exactly as designed.
  - **The Cap B notification gate, the real reason for migration 027**: a disposable `trial`-plan customer
    (structurally capped at 0 scheduled reports/period) with TWO sites both hitting `skipped_capped` in
    the SAME `run-due` tick → `vrm.customers.report_cap_notified_period_end` set exactly once; a SECOND
    `run-due` call in the same period leaves the column unchanged, confirming no second email fires —
    exactly Q7's "once per period, not once per skipped run." Confirmed by Oscar: exactly one "Scheduled
    report limit reached" email received.
  - Every fixture (customers, sites, report_runs rows, and the two Storage PDF objects the live sends
    created) deleted afterward — confirmed zero leftovers.

---

### Step 9 — The workflow, the VRM sync wiring, and docs (~0.75 day; Q9) — ✅ DONE 2026-08-25

**Build:** `.github/workflows/scheduled-reports.yml` (§3.8 — hourly, `workflow_dispatch`, the VRM sync
step with `continue-on-error`, the bounded `run-due` loop, the minute-budget and 60-day-idle notes in
the header comment); updates to `vrm_api/README.md`, `victron-monitor/web/README.md`, `.env.example` (if
any new var), `ARCHITECTURE.md`, `CONTEXT.md`; PHASES.md marked complete.

**Validate:**
- `actionlint` clean.
- Grep the YAML: every secret referenced only as `${{ secrets.NAME }}`, never a literal.
- Trigger via `workflow_dispatch` and watch a real end-to-end run produce a real report and a real
  email.
- **The headline test:** set three sites to three different cadences in three different timezones, let
  the hourly cron run unattended for 48 hours, then read the ledger. Every expected period generated
  exactly once; nothing generated twice; every skip explained.
- Confirm the VRM sync step runs **before** the report step and that a forced sync failure for one site
  does not prevent every *other* due site's report from running (§0.7 means there is no separate
  CSV-upload class to fall back on here — the isolation this proves is site-to-site, via §3.4's per-site
  `try/except`, not sync-dependent vs. sync-independent).

**Also discovered during this step, retroactively closed:** `PLAN_PHASE17.md` §8 Step 0 ("make Phase 17
legible in `PHASES.md` — do this before any code") was never actually done earlier in the build — grepping
`PHASES.md` for any Phase 17 mention turned up nothing. Folded into this step's own doc pass rather than
left as a gap: `PHASES.md` now has the status-table row, the full phase section, the timeline row, and the
critical-path paragraph, all written as "complete" rather than "not started" since every step is now done.

**Verification, 2026-08-25 — real, not hypothetical:**
- `actionlint .github/workflows/*.yml` — clean, both workflows.
- Every secret in `scheduled-reports.yml` referenced only via `${{ secrets.NAME }}` — grepped directly,
  confirmed.
- **The exact bash+`jq` loop from the workflow's own "Run due reports" step, run locally against the real
  running `vrm_api`** (not simulated — the literal script, copy-pasted) against a disposable test site
  with real `energy_daily` data: one iteration, `remaining: 0`, loop correctly exits. `email_status` came
  back `'skipped'` (the test customer had no `contact_email`/`auth_email` configured) — confirmed no
  accidental email fired, then cleaned up (report_runs row, Storage PDF, site, customer).
- **Not verified this session** (both require the workflow file pushed and live on GitHub, which this
  session did not do without being asked — a `git push` is outside what was requested):
  - A real GitHub-hosted `workflow_dispatch` trigger.
  - The 48-hour, three-sites/three-cadences/three-timezones unattended headline test. The individual
    pieces it would exercise — per-cadence period arithmetic (Step 6, 20 assertions across timezones
    including DST), idempotency and concurrency (Step 6/7, live against the real database), and the
    workflow's own due-reports loop (this step, live against the real API) — are each independently
    verified; only their unattended combination over real wall-clock time is not.
  - Per-site isolation between a forced VRM-sync failure and an unrelated site's report: `continue-on-error:
    true` on the sync step is a structural property of the YAML itself (inspected directly, not run), and
    the report step's own per-site `try/except` isolation was already proven live in Step 6 with a
    genuinely broken site (a bad timezone) alongside a healthy one in the same `run-due` call — the same
    mechanism, not a new one, per §3.8's own framing ("the isolation this proves is site-to-site ... not
    sync-dependent vs. sync-independent").

**Docs updated:** `vrm_api/README.md` (the `POST /v1/reports/run-due` endpoint, and the `branding` key
added to `POST /v1/reports`'s own `result` shape — neither had been documented since Steps 6-8 built
them), `ARCHITECTURE.md` (new §6, the scheduled-reports wiring diagram — the hourly cron, the per-site
isolation, and the third "starts outside this system" arrow: an anonymous unsubscribe click), `CONTEXT.md`
(a full Phase 17 entry, matching Phase 16's own), `PHASES.md` (all four edits from §12, adapted to
"complete" past tense). `.env.example` already carried `SITE_URL`/`REPORT_UNSUBSCRIBE_SECRET` from Step 8.

---

## 9. Explicit non-goals

- **Any change to `pages/`, `app.py`, the `monitoring` schema, Node-RED, or Apps Script.** Phase 12
  remains unbuilt and this phase does not build it — it only leaves `victron/templates/report_email.html`
  and `victron/mailer.py`'s attachment support behind for it, the same way Phase 14 left `mailer.py`
  itself behind.
- **A real job queue** (Celery/Redis/pg_boss). §0.5 Decision 1 exists specifically so one isn't needed.
  Unchanged from Phases 14–16.
- **Sub-hourly or arbitrary-cron schedules.** Four values: off/daily/weekly/monthly. A cron-expression
  field is a support burden and an abuse surface for a report nobody reads twelve times a day.
- **Custom report date ranges on a schedule.** The cadence determines the period (§3.2). Custom ranges
  stay on-demand, which is what they already are.
- **A report template system.** Branding is name/logo/colour/contact (§4.3). Not layout, not section
  selection, not custom KPIs.
- **Recoloring the chart palette** (§4.3, Q8).
- **Fetching a customer-supplied URL at render time** (§4.4, Q6) — ruled out on security grounds, not
  convenience.
- **Per-user notification preferences / multi-user accounts.** One `vrm.customers` row still has one
  login. Recipients are a list of addresses, not a list of users.
- **Unsubscribe management beyond a single footer link** (Q5). A full preference centre is its own
  thing.
- **Invoice PDFs, dunning sequences, or any billing change.** Phase 16 is done; this phase reads
  `billing_status` and writes nothing billing-related.
- **Backfilling `vrm.report_runs` from historical `vrm.jobs` rows** (§5.5).
- **Metered/usage-based billing.** The caps are cost controls, not a meter. If a customer should be able
  to *buy* more scheduled reports, that is a Phase 16 amendment, not a limit-table edit.
- **RLS policies, per-user JWTs, a test framework.** Unchanged from Phases 14–16. (Step 6's period
  arithmetic wants unit tests badly, and the right home for them under this constraint is a
  `tools/validate_report_schedule.py` script in the style of `tools/validate_billing_step2.py` — a
  committed, runnable validation script, not a new test framework.)
- **Alerting on cron failure** beyond the `/admin/activity` panel. A real alerting integration is worth
  doing and is not this phase.

---

## 10. Risks and tradeoffs

| Risk | Blast radius | How this plan addresses it |
|---|---|---|
| **Scheduled reports built on stale data** | Every scheduled report is quietly wrong, and it looks like a bug in the report rather than in ingestion | §0.7/§3.5: CSV-sourced sites are structurally excluded from scheduling (a CHECK constraint, not a runtime check), and the workflow calls the already-built `vrm-sync/run-due` before every report step, so the one remaining freshness gap (a brand-new `vrm_api` site with no history yet) is explicitly `skipped_no_data` rather than silently reported on |
| **The entitlement gate written as an allowlist** | **Every existing hand-managed customer silently stops receiving reports** — the phase that adds automation becomes the phase that broke the business | §3.6 states it as a denylist, explains why, and Step 6's gate asserts a `billing_status='none'` customer still generates |
| **One site's failure kills the whole run** | The exact Apps Script-era bug PHASES.md Phase 12 names | Per-site `try/except` copied from `vrm_sync.py:post_run_due()`; Step 6's gate deliberately breaks a site mid-run |
| **A silent scheduler** — cron disabled, or failing every night | Nobody notices for weeks; customers notice first | §5.2's ledger, §3.7's admin panel, and the 60-day-idle note in the workflow header. Detection is designed in, not assumed |
| **Timezone arithmetic that is subtly wrong** | Reports arrive on the wrong day, or a month is skipped every February | §3.2's table is explicit; §0.3 puts the logic in a pure, I/O-free module; Step 6's gate is table-driven across DST, leap days, and month boundaries |
| **`tzdata` missing in the container** | Every scheduled report fails, in production only | Named in §3.3 and made a Step 6 gate item rather than a footnote |
| **Two cron runs double-generating** | Double cost, duplicate emails to a customer | §5.2's partial unique index — Postgres is the mutex, no application locking. Proven concurrently in Step 6's gate |
| **A branding change breaking every existing report** | Every customer's and Oscar's own reports, in one commit | §0.4 bounds `victron/` to two additive files; Step 4's gate is a **byte-identical PDF** before any branding feature is even looked at |
| **A Starter customer white-labelling anyway** | The Growth tier's headline feature becomes free | §4.2's single resolver, enforced at the renderer rather than the UI, with Step 4's gate testing a populated jsonb on a Starter customer |
| **An SVG or oversized image embedded in a rendered PDF** | Renderer exploitation, or a 40 MB email | §4.4: Pillow verification of bytes, PNG/JPEG only, size/dimension caps, our bucket only |
| **Limit numbers that are wrong** | Either a customer blocked from something they paid for, or a bill nobody expected | §0.5 Decision 2 puts them in a table Oscar can `UPDATE`; Step 3's gate requires *measuring* the real per-report cost so the second pass is arithmetic |
| **The `'default'` limits row failing open** | A typo'd plan string granting unlimited reports | §5.1 makes `'default'` stricter than every paid tier and calls out the deliberate contrast with `planSiteLimit()`'s fail-open behaviour, which is right next door and points the other way |
| **Report email burning Resend reputation** | Deliverability damage affecting invites, resets, and every report — slow to repair | Caps double as email-volume caps; entitled customers only; per-site recipient cap; every send logged. §6 point 3 |
| **Scope creep from "white-label" into a template system** | An open-ended feature with no definition of done | §4.3 and §9 state the boundary in the same words twice, deliberately |
| **A customer thinks they're getting daily reports and is getting weekly** | Trust, and it is invisible | Q7's recommendation: hard stop with a banner, never silent degradation |

---

## 11. Conventions the coder must follow

All of `PLAN_PHASE14.md` §3, `PLAN_PHASE15.md` §12, and `PLAN_PHASE16.md` §11 apply unchanged.
Additions:

- **Read `node_modules/next/dist/docs/` before writing Next.js code** — `victron-monitor/web/AGENTS.md`
  warns this version differs from training data. Still true.
- **`victron/` changes are additive-with-a-preserving-default, or they don't happen.** Three files,
  named in §0.4. `report_svg.py` is not one of them. If a fourth file needs changing, stop and come back
  here.
- **`resolve_branding()` is the only reader of `vrm.customers.branding`.** Comment both ends, naming
  §4.2. If a second reader seems necessary, the design is wrong.
- **`vrm.sites.report_schedule*` are written from exactly two places:** `SITE_WHITELIST`'s update path
  and `createSite()`'s default application. The scheduler writes `report_last_period_end` /
  `report_last_run_at` and **nothing else** on that table.
- **The scheduler never calls ONVO and never calls `reconcile_customer()`** (§3.6). It reads
  `billing_status`. Comment it, because adding a "let's make sure billing is fresh" call there will look
  like an improvement.
- **Every per-tier number is read from `vrm.plan_limits` at use time.** No constant, no cached module-level
  dict, no `.env` var. One `UPDATE` must change behaviour on the next request.
- **Every new customer-facing string goes in both `en` and `es`** — except `components/marketing/**`,
  which is hardcoded English by that directory's own existing convention (§1.2). Know which file you're
  in.
- **Never let a report failure lose a report.** Storage write before email; email failure never
  downgrades a `done` run.
- **A `skipped_*` status must always carry a sentence a customer can act on.** A status code with no
  human sentence behind it is a support ticket with extra steps.
- **Money and counts stay integers.** No floats for a limit, a count, or a period boundary.
- Existing git rules: stage in batches of 5–10, `timeout 90 git commit`.

---

## 12. Step 0 for the coder: make Phase 17 legible in `PHASES.md`

Hand-over edits, verbatim, same as Phases 14/15/16. **Do these before any code.**

**Edit 1 — status table.** After the Phase 16 row (currently line ~27), add:

```
| 17 — VRM Monitor: scheduled reports, report cost limits, tiered white-label branding, visible trial | ⬜ Not started (see PLAN_PHASE17.md; Q1/Q2/Q4/Q6 answered 2026-08-21 — per-site schedules, Oscar's limit numbers, email in-scope, real logo storage; CSV-sourced sites are structurally excluded from scheduling, §0.7) |
```

**Edit 2 — a new section**, immediately after the Phase 16 section and before `## Timeline summary`:

```markdown
## Phase 17 — VRM Monitor: scheduled reports, report cost limits, tiered branding, visible trial (9–13 days, scoped 2026-08-21)

**Goal:** the four things VRM Monitor currently sells but does not have. A customer puts a site on a
daily/weekly/monthly schedule and the report arrives on its own — rendered, archived, emailed, logged,
with one site's failure never touching another's. Report generation stops being an unbounded cost, via
two independent per-tier caps that live in a table Oscar can `UPDATE`. A Growth/Fleet customer's report
finally carries their own branding and a Starter customer's provably does not. And the 7-day trial
becomes visible on the Pricing cards and the signup form.

Full build plan, the confirmed-context tables, and per-step validation gates:
[`PLAN_PHASE17.md`](PLAN_PHASE17.md). Not duplicated in full here.

### Why this phase exists

Three of these four are already on the Pricing page. "Automatic weekly & Overview reports" and
"Automatic email delivery" are sold on every tier and there is **no automated report generation for
`vrm` customers at all** — reports exist only as an on-demand click. "Full white-label branding" is sold
on Growth and `vrm.customers.branding` has been an empty jsonb column since migration 012 that nothing
reads and no UI writes. Meanwhile every report costs a real Anthropic call with nothing bounding how
many a customer can trigger. Phase 16 gave the product a revenue mechanism; this phase makes the thing
being paid for actually run by itself.

### Where this sits relative to other phases

- Depends on Phases 14/15/16 (the web app, `vrm_api`, the tenancy model, `vrm.plans`,
  `vrm.rate_limits`, `apply_entitlements()`'s `billing_status`).
- **Closes Phase 15's deferred Step 7 as a side effect**: `POST /v1/vrm-sync/run-due` was built and has
  never been called: this phase's workflow calls it, because scheduled reports on un-synced sites report
  stale data.
- **Is not Phase 12.** Phase 12 is the `monitoring` schema and Oscar's own bureau clients — different
  tenancy, different email routing, different table, still unbuilt. This phase reuses Phase 12's
  *mechanism* decision (GitHub Actions `cron:`) and its per-site failure-isolation requirement, and
  leaves `victron/templates/report_email.html` + `victron/mailer.py`'s attachment support behind for it.
- **The first phase since Phase 15 to touch `victron/`** — three files, additively, behind a
  byte-identical-PDF gate.

### Decisions locked (see PLAN_PHASE17.md §0.5, §2, §3, §4, §5)

- **The scheduler is a stateless due-check over durable state, not a queue.** "Due" is computed from the
  calendar and a ledger, never from a timer, so a missed run, a late run, or two overlapping runs all
  produce the same result as one on-time run. Idempotency is a partial unique index in Postgres, not a
  lock in a process.
- **Every per-tier number is a database row** (`vrm.plan_limits`), not a constant — report caps and the
  white-label gate both. Migration 021's own precedent: a hand-negotiated deal should cost an `UPDATE`,
  not a deploy. The fallback row is the most restrictive, deliberately the opposite of
  `lib/plans.ts:planSiteLimit()`'s fail-open behaviour.
- **Two independent report caps, not one**: a short-window rate limit on manual regeneration (fails
  open — it's an abuse control) and a per-billing-period cap on scheduled runs (checked as a projection
  at schedule-set time, and as a backstop at run time).
- **Branding is resolved in exactly one server-side function** and the renderer never sees the raw
  jsonb. The chart palette is semantic and is never recolored.
- **The entitlement gate is a denylist, not an allowlist** — `billing_status='none'` means "not
  billing-managed," which is every existing hand-created customer, and they must keep receiving reports.
- **Schedules are per-site**, with a per-customer default applied to new sites only. Every new column
  defaults to the current behaviour: no site that exists today starts sending anything.

### Explicit non-goals

A real job queue, sub-hourly or cron-expression schedules, custom date ranges on a schedule, **scheduled
reports for CSV-sourced sites at all** (§0.7 — only `source='vrm_api'` sites are schedulable; a CSV site
gets manual reports only, and a "connect to VRM" prompt in place of a cadence picker), a report
*template* system (branding is name/logo/colour/contact only), recoloring the chart palette, fetching a
customer-supplied URL at render time, multi-user accounts or per-user notification preferences, a full
unsubscribe preference centre, any billing change, metered billing, backfilling the report ledger from
`vrm.jobs`, RLS policies, a test framework, alerting beyond the admin panel, and any change to `pages/`,
`app.py`, the `monitoring` schema, Node-RED, or Apps Script.

### Validation

Per-step gates in PLAN_PHASE17.md §8. The headline ones: a byte-identical PDF for `monitoring` and for
an unbranded `vrm` site before any branding feature is accepted; a Starter customer with a fully
populated `branding` jsonb still gets a Pauly & Co report; a `billing_status='none'` legacy customer's
site still generates; a CSV-sourced site cannot be scheduled at the database, write-path, or UI layer
(three independent checks); deliberately breaking one site mid-fan-out leaves every other site
completing; two simultaneous `run-due` calls produce exactly one report per site; and three
`vrm_api`-sourced sites on three cadences in three timezones, left to the hourly cron unattended for 48
hours, each generate exactly once with every skip explained.

### Decisions Oscar made 2026-08-21 (see PLAN_PHASE17.md §0.6–§0.7)

Per-site schedules (Q1); Oscar's own limit-numbers table, tighter than the architect's first draft on
Starter and Growth (Q2); report email is in this phase, not a fast-follow (Q4); logo goes to real
storage in the existing bucket, and the customer-editable fields are confirmed as color + header text
only — the chart palette stays off-limits (Q6, and by implication Q8); and, raised independently of the
original eleven questions: **CSV-sourced sites are never eligible for scheduling at all** — only
`source='vrm_api'` sites can be, enforced at the database, the write path, and the UI (§0.7). This also
settles Q9 (the deferred Phase 15 VRM sync) as load-bearing rather than optional: it is now the only
mechanism by which a scheduled report is ever generated from current data. Remaining open questions (Q3,
Q5, Q7, Q10, Q11) still have stated defaults the build proceeds on.
```

**Edit 3 — timeline table.** After the Phase 16 row:

```
| 17 | VRM Monitor: scheduled reports, report cost limits, tiered branding, visible trial | 9–13 | Whenever needed — triggered by the first customer who should not have to click Generate every Monday |
```

**Edit 4 — critical path.** After the Phase 16 paragraph:

```
**Phase 17 is off this critical path too, and depends on 14/15/16.** It is the phase where the
product's marketing copy and the product's behaviour are made to agree: three of its four features are
already on the Pricing page and none of the three exists. It is also the first phase whose primary
deliverable runs when nobody is watching, which is why its plan spends more of its length on failure
visibility, idempotency, and timezone arithmetic than on features. Trigger it by the first customer who
should not have to click Generate every Monday morning — or by the first Anthropic bill that surprises
someone.
```
