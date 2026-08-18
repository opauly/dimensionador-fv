# Phase 13 — VRM Monitor Customer Portal: Auth, User Dashboard, Admin Dashboard

> ## ⚠️ SUPERSEDED (2026-08-16) — see [`PLAN_PHASE14.md`](PLAN_PHASE14.md)
>
> **Nothing below is deleted, because most of it is still the record of decisions that still
> hold.** What changed is the *shape*, not the goal: Oscar chose to rebuild VRM Monitor as
> **one unified Next.js site** (marketing page + customer portal + admin in one codebase,
> with the Python pipeline wrapped in an API) instead of the second Streamlit app this
> document plans. `PLAN_PHASE14.md` §7 is a decision-by-decision map of what carried forward
> and what was overridden. In short:
>
> - **Built and live from this plan — do not redo:** `database/migrations/021_vrm_portal_auth.sql`
>   (applied to the dev DB) and a working Streamlit login + role resolution, validated
>   end-to-end with a real test customer.
> - **Still correct and carried forward:** §1.3 (auth columns on `vrm.customers`, soft
>   pointer, no FK), §1.4 (`PLANS`), §1.5 (admin via `app_metadata.vrm_role` + the
>   role-resolution order), §1.8–§1.9 (invites via `generate_link()` + Resend — though one of
>   its three arguments, the URL-fragment one, is explicitly retired in `PLAN_PHASE14.md`
>   §1.9), §1.11, §4's non-goals, and every answer in §0.3.
> - **Reopened and re-decided:** §1.1 (access control). Its own revisit trigger — *"the moment
>   anything other than this Streamlit process talks to Supabase on a customer's behalf…
>   per-user JWTs + RLS policies become mandatory"* — **has now fired.** The answer is in
>   `PLAN_PHASE14.md` §1.2: all Supabase access stays server-side, no Supabase credential of
>   any kind reaches the browser, `anon`/`authenticated` keep zero grants on `vrm`, and
>   enforcement moves to a typed `server-only` choke point.
> - **Superseded as Streamlit-specific:** §1.2 (two-client rule), §1.6 (`vrm_portal/` layout
>   and the `sys.path` bootstrap), §1.7 (`st.navigation`), §1.10 (no session persistence —
>   now retired as a non-goal, since cookie sessions give it for free).
> - **`vrm_portal/` and `victron-monitor/portal/` are legacy.** Kept as porting reference
>   through Phase 14 Step 7, deleted at Step 8 (`PLAN_PHASE14.md` §6.1).

**Status:** SUPERSEDED — was: ready for the coder agent, with 5 open questions for Oscar flagged in §0.3
**Author:** architect agent, 2026-08-16
**Spec sources:** `victron-monitor/docs/vrm-report-saas-architecture.md` §5–§7,
`victron-monitor/docs/vrm-report-v1-implementation-plan.md` (V1 build log),
`database/migrations/012_vrm_schema.sql` (the schema this extends),
`victron-monitor/landing-page/landing_template.html` (what is already being sold publicly)
**Plan doc convention:** same shape as `PLAN_PHASE6.md` — confirmed context, resolved
decisions, then vertical build steps each with its own validation gate.

---

## Goal

VRM Monitor stops being a tool Oscar operates on customers' behalf and becomes a product
customers log into. A customer follows a **Log in** link from the landing page, signs in with
a password they set from an invitation email, and gets their own tenant-scoped dashboard —
**Reports**, **Upload CSV**, **My Sites**, **Profile** — showing only their own sites. Oscar
gets an admin dashboard in the same app: create customers, send the invite, see every
customer/site/upload across the product, and still do everything he does today on a
customer's behalf.

"Done" means: Oscar creates a customer from the admin dashboard, that customer receives an
email, sets a password, logs in, uploads their own VRM CSV, and downloads their own report —
without Oscar touching anything, and without customer A being able to see or modify anything
belonging to customer B.

**The existing Streamlit app (`app.py` + everything under `pages/`, including
`pages/06_vrm_monitor.py`) is not modified by this phase.** Not one line. This is a second,
separate Streamlit application in the same repo.

---

## 0. Confirmed context (do not re-derive)

### 0.1 Facts established by reading the code

| Fact | Where |
|---|---|
| `vrm.customers` is already the tenant root — `id`, `name`, `slug` (unique, CHECK'd), `contact_name`, `contact_email`, `country`, `plan` (default `'trial'`, **no CHECK**), `active`, `branding jsonb`, `notes` | `database/migrations/012_vrm_schema.sql` L39–74 |
| `vrm.sites.customer_id` → `vrm.customers(id) ON DELETE CASCADE`; `site_id` is globally unique and namespaced `<customer-slug>-<site-slug>` | migration 012 L88–141, `victron/ingest.py:make_site_id()` |
| RLS is **ENABLED with zero policies** on every `vrm.*` table; `anon` and `authenticated` have `REVOKE ALL ON SCHEMA vrm`; only `service_role` is granted anything | migration 012 L629–645 |
| Migration 012's own comment states the intended end-state: *"the policies go here and the app keeps using service_role — RLS is defence in depth behind application-layer scoping, not a substitute for it"* | migration 012 L594–598 |
| `database/supabase_client.py:get_client()` is a **module-level singleton holding the service_role key** | that file |
| `supabase-py` resets its PostgREST client to the *user's* access token on `SIGNED_IN` / `TOKEN_REFRESHED` / `SIGNED_OUT` | `.venv/.../supabase/_sync/client.py:334–341` |
| `supabase_auth` sync API has `admin.invite_user_by_email()`, `admin.generate_link()` (returns `hashed_token`), `admin.create_user()`, `admin.update_user_by_id()`, `admin.list_users()` | `.venv/.../supabase_auth/_sync/gotrue_admin_api.py` |
| …and on the client: `sign_in_with_password()`, `verify_otp({token_hash, type})`, `update_user()`, `set_session()`, `refresh_session()`, `sign_out()`, `reset_password_for_email()` | `.venv/.../supabase_auth/_sync/gotrue_client.py` |
| `generate_link()` **does not send an email** — it returns `{action_link, email_otp, hashed_token, redirect_to, verification_type}` for you to send yourself | `supabase_auth/types.py:778–806` (docstring: *"Generates email links and OTPs to be sent via a custom email provider"*) |
| Streamlit 1.50.0 is installed → `st.navigation` / `st.Page` (callable pages) available | `.venv/.../streamlit-1.50.0.dist-info` |
| `.streamlit/config.toml` at repo root sets `maxUploadSize = 200` and `primaryColor = "#4BAE6A"`; Streamlit reads it from **CWD**, not from the entry script's folder | that file |
| `.env.example` deliberately omits `SUPABASE_ANON_KEY` and says so in a comment block | `.env.example` L30–31 |
| The reusable pipeline: `victron/vrm_csv.py` (parse), `victron/ingest.py` (write), `victron/weekly_report.py` (`build_report_data` + `render_pdf`), `victron/report_svg.py`, `victron/report_i18n.py`, `victron/savings.py`, `database/vrm_report_db.py` (schema-agnostic read) | those files |
| Landing page today: nav has **no** Log in link; "Request early access" is a `mailto:proyectos@paulyco.com` composed by JS; pricing = installer subscription (Starter $14/site/mo ≤10 sites, Growth $9/site/mo ≤50, Fleet custom) and owner Single Report $29; account-type toggle is **installer / owner** | `victron-monitor/landing-page/landing_template.html` L414–429, L636–710, L720–780 |
| Phase 12 (not built yet) already locked **Resend** as the email provider for this product | `PHASES.md` Phase 12, `CONTEXT.md` |

### 0.2 What `pages/06_vrm_monitor.py` gives us to port (read it before writing anything)

| Internal function | Becomes, in the portal |
|---|---|
| `tab_sites()` L177–285 | **Admin → Sitios** (near-verbatim) *and* **Customer → My Sites** (customer field removed, list filtered to `customer_id`) |
| `tab_upload()` L291–559 | **Admin → Cargar CSV** (verbatim, customer picker kept) *and* **Customer → Upload** (customer field removed and *never* passed to `ingest.upsert_customer`) |
| `tab_report()` L565–782 | **Admin → Reporte** (both schemas) *and* **Customer → Reports** (`vrm` only, sites filtered) |
| `_metric_card` / `_chip_row` / `_feature_card` / `_report_feature_cards` L40–123 | Copied into `vrm_portal/components.py`. **Copy, do not import from `pages/`** — importing would couple the two apps and `pages/06` must stay free to change. |
| `_timezones()` / `_tz_index()` L132–151 | Copied into `vrm_portal/components.py` |
| The `_pending_*` session-state staging pattern L304–311 | Reused verbatim in the upload view (same Streamlit constraint applies) |
| `@st.cache_data(ttl=30)` + explicit `.clear()` after writes L157–172 | Same pattern, but **cache keys must include `customer_id`** — see §1.6 |

### 0.3 Open questions for Oscar — answered 2026-08-16

1. **Hosting target.** **Deferred deliberately.** Steps 1–5 are all locally verifiable and do
   not need a hosting decision; only Step 6 (going live) is blocked on this. Do not let it
   block starting. When it's time, the recommendation on record is Render or Railway with a
   Dockerfile and a custom domain — revisit then.
2. **Portal UI language.** **Confirmed: English by default**, with the per-customer
   `ui_language` column so Oscar can flip a customer to Spanish. Admin views stay Spanish.
3. **Admin v1 scope.** **Confirmed as proposed**: Clientes (list/create/invite/edit/deactivate),
   Sitios (cross-customer, editable), Cargar CSV (on behalf of), Reporte (both schemas),
   Actividad (`vrm.ingestion_log` across customers). Billing, usage metering, branding upload,
   and impersonation stay out of scope.
4. **Landing page "Request Early Access."** **Confirmed: stays a `mailto:`, unchanged.** The
   only landing-page edit in this phase is adding a **Log in** link to the nav pointing at the
   portal URL.
5. **Site limits.** Not re-asked separately — the §1.4 `PLANS` vocabulary (`starter`=10,
   `growth`=50, `fleet`=NULL, `single_report`=1, `trial`=1) already mirrors the tiers publicly
   listed on the landing page, so it stands as written.

Steps 1–5 are fully unblocked. Step 6 (landing-page link + deploy) proceeds up through
building the Dockerfile/host config, but actually going live waits on a hosting choice.

---

## 1. Resolved decisions (these are not open questions)

### 1.1 Access control: **service_role + enforced application-layer scoping.** No per-user JWTs, no RLS policies yet.

**Decision:** the portal keeps using `get_client()` (service_role) for every data read and
write, exactly as `pages/06_vrm_monitor.py` does. Supabase Auth is used **only** to prove who
the person is; the resulting user JWT is never used to talk to PostgREST. `vrm.*` stays
RLS-enabled-with-no-policies, and `anon`/`authenticated` keep getting nothing.

**Why, concretely** (this is the expensive-to-reverse call, so the reasoning is written down):

- **RLS buys literally zero protection for this app's queries.** `service_role` bypasses RLS
  by definition. Adding policies would only matter if we *also* granted `authenticated`
  table privileges and started issuing per-user JWTs — i.e. it would create a brand-new
  access path that does not exist today, not harden the existing one. "Defence in depth"
  requires two locks on the same door; this would be a second door.
- **Streamlit has no per-request auth context.** Making per-user JWTs correct means a
  per-session `Client` living in `st.session_state`, plus refresh-token handling, plus
  passing that client down into `database/vrm_report_db.py`, `victron/ingest.py` and
  `victron/weekly_report.py` — all of which are **shared with the internal app that must not
  be modified**. Any code path that forgets the session client silently falls back to
  service_role, which is a failure mode that looks like success.
- **The singleton makes it actively dangerous.** `supabase-py` swaps the PostgREST auth
  header on `SIGNED_IN` (verified: `supabase/_sync/client.py:334–341`). Signing a user in on
  the `get_client()` singleton would re-scope *every* caller in the process — including
  Oscar's admin queries — to that user. See the hard rule in §1.2.
- **Migration 012 already anticipated exactly this shape**, in writing, and this plan honours
  it rather than second-guessing it.

**What replaces RLS as the real control:** a single choke point, `vrm_portal/db.py`, where
every tenant-facing function takes `customer_id` as its **required first positional argument**
and no function returns an unscoped result set. Site-keyed operations go through
`assert_owns_site(customer_id, site_id)` which raises `NotAuthorized` rather than returning
False. Customer views may import **only** `vrm_portal/db.py` — never `database/vrm_report_db.py`,
`victron/ingest.py`, or `get_client()` directly. Step 2 ships an automated test that proves
cross-tenant access fails.

**Revisit trigger** (write this into the migration's header comment): the moment anything
other than this Streamlit process talks to Supabase on a customer's behalf — a mobile app, a
JS frontend, a public API — per-user JWTs + RLS policies become mandatory and this decision
must be reopened. Not before.

### 1.2 Two Supabase clients, never one

```
get_client()                  → service_role, singleton, ALL data access.  Never call .auth.sign_in_* on it.
vrm_portal.auth.auth_client() → anon key, a FRESH client per auth operation. Auth only. Never .table()/.schema().
```

**Hard rule for the coder:** `vrm_portal/auth.py` is the only module allowed to call anything
under `.auth`, and it must never call `.auth.*` on the object returned by `get_client()`. A
comment saying why (the `_listen_to_auth_events` behaviour above) goes at the top of
`auth.py`. Admin-API calls (`invite`/`generate_link`/`update_user_by_id`) need a
**service_role-keyed** client and must use a *separate* instance from the data singleton, for
the same reason: `SyncSupabaseClient(url, SERVICE_ROLE_KEY).auth.admin`.

### 1.3 Auth ↔ tenant linkage: columns on `vrm.customers`, soft pointer, no FK

**Decision:** 1:1, on the existing row. No companion table.

```sql
ALTER TABLE vrm.customers
  ADD COLUMN IF NOT EXISTS auth_user_id uuid,          -- auth.users(id). Soft pointer: NO foreign key.
  ADD COLUMN IF NOT EXISTS auth_email   text,          -- the login email (may differ from contact_email)
  ADD COLUMN IF NOT EXISTS invited_at   timestamptz,
  ADD COLUMN IF NOT EXISTS activated_at timestamptz,
  ADD COLUMN IF NOT EXISTS account_type text NOT NULL DEFAULT 'owner'
                             CHECK (account_type IN ('installer','owner')),
  ADD COLUMN IF NOT EXISTS site_limit   int,           -- NULL = unlimited; enforced in app, not DB
  ADD COLUMN IF NOT EXISTS ui_language  text NOT NULL DEFAULT 'en'
                             CHECK (ui_language IN ('es','en'));

CREATE UNIQUE INDEX IF NOT EXISTS idx_vrm_customers_auth_user
  ON vrm.customers (auth_user_id) WHERE auth_user_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_vrm_customers_auth_email
  ON vrm.customers (lower(auth_email)) WHERE auth_email IS NOT NULL;
```

Reasoning:
- **A companion table buys nothing at 1:1.** It would add a join to the single hottest query
  in the app (resolve session → tenant) to model a relationship that is, by the user's own
  decision, one-to-one and permanent.
- **No FK to `auth.users`, deliberately** — this mirrors `vrm.sites.public_client_id`'s
  existing precedent and reasoning (migration 012 L126–131): the whole schema is designed to
  be dumpable into its own Supabase project without cross-schema constraints to untangle. A
  dangling `auth_user_id` is harmless (it resolves to "this customer can't log in"), whereas
  `ON DELETE CASCADE` from `auth.users` would mean deleting a login **deletes the customer's
  telemetry history** — categorically the wrong blast radius.
- The partial unique indexes are what actually prevent two customers sharing a login, since
  there is no FK doing it.
- `account_type` mirrors the landing page's installer/owner toggle; it drives copy ("Your
  sites" vs "Your customers' sites") and which plan set is offered.

### 1.4 `plan` gets a Python vocabulary, not a DB CHECK

`vrm.customers.plan` stays a free-text column. The vocabulary lives in
`vrm_portal/plans.py` as a dict, seeded from the landing page's published tiers:

```python
PLANS = {
    "trial":         {"label": "Trial",         "sites": 1,    "account_types": ("owner", "installer")},
    "single_report": {"label": "Single Report", "sites": 1,    "account_types": ("owner",)},
    "starter":       {"label": "Starter",       "sites": 10,   "account_types": ("installer", "owner")},
    "growth":        {"label": "Growth",        "sites": 50,   "account_types": ("installer",)},
    "fleet":         {"label": "Fleet",         "sites": None, "account_types": ("installer",)},
}
```

Reasoning: pricing is marketing-owned and changes faster than migrations; a CHECK constraint
would turn a pricing experiment into a database migration, and adding one to a live column is
a needless failure mode. `site_limit` is stored per customer (defaulted from `PLANS` at
create time, overridable by Oscar) so a hand-negotiated deal doesn't require a code change.

### 1.5 Admin identity: `app_metadata.vrm_role`, not a table

Oscar's admin rights come from the auth user's `app_metadata`, set with the service_role
admin API at account creation:

```python
admin.update_user_by_id(uid, {"app_metadata": {"vrm_role": "admin"}})
```

`sign_in_with_password()` returns `response.user.app_metadata` directly, so no extra lookup.
`app_metadata` is **not** user-writable (unlike `user_metadata`), so it is tamper-proof
without a table. Role resolution at login, in this exact order:

1. `app_metadata.get("vrm_role") == "admin"` → admin session, no `customer_id`.
2. else look up `vrm.customers` by `auth_user_id` → customer session with that `customer_id`.
3. else → sign the user straight back out with *"This account isn't linked to a VRM Monitor
   customer yet. Contact proyectos@paulyco.com."* Never a partially-authenticated state.

Also check `vrm.customers.active` at step 2 — inactive → same clean rejection. Deactivating a
customer must not require deleting their auth user.

### 1.6 New-app layout: Python in a root package, entry point under `victron-monitor/`

```
vrm_portal/                       # NEW root package — all portal Python lives here
  __init__.py
  auth.py                         # sign in/out, session, role resolution, invite verification
  db.py                           # THE tenant-scoped choke point (§1.1)
  admin_db.py                     # cross-customer reads/writes; admin-only by construction
  invites.py                      # generate_link + Resend send + resend/reset
  mailer.py                       # thin Resend wrapper (Phase 12 reuses this — see §1.8)
  plans.py                        # PLANS dict (§1.4)
  strings.py                      # customer-facing copy, {"en": {...}, "es": {...}}
  components.py                   # _metric_card/_chip_row/_feature_card/_timezones, copied from pages/06
  templates/invite_email.html     # Jinja2, brand-matched
  views/
    __init__.py
    login.py  activate.py
    customer_reports.py  customer_upload.py  customer_sites.py  customer_profile.py
    admin_customers.py  admin_sites.py  admin_upload.py  admin_reports.py  admin_activity.py

victron-monitor/portal/
  app.py                          # ~40-line entry point: sys.path bootstrap + st.navigation + pg.run()
  README.md                       # how to run locally, env vars, deploy notes
```

Reasoning:
- **Python at the repo root, product assets under `victron-monitor/`** is the convention this
  product already chose: the V1 plan doc's "Module placement" decision put the pipeline in
  `victron/` at the root "next to `calculations/` and `proposals/`, with a pointer from
  `victron-monitor/README.md`", while `victron-monitor/` holds `docs/`, `landing-page/`,
  `node-red/`, `apps-script/`. This follows it exactly.
- **The entry point must NOT be at the repo root.** Streamlit auto-discovers a `pages/`
  directory *next to the entry script* — a root-level `portal_app.py` would pull the entire
  internal app (Cotizaciones, Proyectos, Admin, and `06_vrm_monitor`) into the customer
  portal's sidebar. Putting the entry under `victron-monitor/portal/` makes that structurally
  impossible. **Do not create a `pages/` folder next to `app.py`** — navigation is defined
  explicitly with `st.navigation`.
- **Nothing is imported flat from the entry script's directory.** Streamlit puts the entry
  script's folder at `sys.path[0]`; a sibling module named `config.py`, `database.py`, or
  `utils.py` there would *shadow the repo's own modules of those names*. Keeping the entry
  script alone in its folder removes that hazard entirely.

**The `sys.path` bootstrap is load-bearing** — Streamlit adds the *script's* directory to
`sys.path`, not the CWD, so `from victron import ...` fails without it. First lines of
`victron-monitor/portal/app.py`, before any repo import:

```python
from __future__ import annotations
import pathlib, sys
_ROOT = pathlib.Path(__file__).resolve().parents[2]      # repo root
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
```

**Run command (document it in the README and use it everywhere):**
`streamlit run victron-monitor/portal/app.py` **from the repo root** — CWD matters for
`.streamlit/config.toml` (the 200 MB upload cap) and for `load_dotenv()`.

### 1.7 Navigation: `st.navigation` with callables, role-gated

```python
if not session:                       pages = [st.Page(login.render, ...)]
elif session.role == "admin":         pages = {"Admin": [...5 admin pages...]}
else:                                 pages = {"VRM Monitor": [...4 customer pages...]}
st.navigation(pages).run()
```

`st.Page` accepts a **callable**, so no page files and no `pages/` directory are needed. The
activation deep-link (`?token_hash=…&type=invite`) is handled *before* this branch — see §1.9.

Every view function still calls `require_customer()` / `require_admin()` as its first
statement. Navigation-level gating is UX; the function-level guard is the control. Never rely
on "the page isn't in the menu."

### 1.8 Invitations: `generate_link()` + our own email via Resend

**Decision:** `admin.generate_link({"type": "invite", "email": ...})` → take `hashed_token`
from the response → build `{PORTAL_BASE_URL}/?token_hash=<hashed_token>&type=invite` → send
that in a brand-matched Jinja2 email through **Resend**. We do **not** use
`admin.invite_user_by_email()` and we do **not** rely on Supabase's SMTP.

Why not the simpler `invite_user_by_email()`:
- Supabase's built-in email service is rate-limited to a handful of messages per hour and is
  documented as not-for-production; making it usable requires configuring custom SMTP anyway.
- The default invite template's `{{ .ConfirmationURL }}` routes through
  `/auth/v1/verify?...&redirect_to=…`, which lands the tokens in the **URL fragment**
  (`#access_token=…`). **A fragment is never sent to the server, and Streamlit cannot read
  it** — `st.query_params` sees nothing. That alone disqualifies the default flow for a
  Streamlit app. Getting `?token_hash=` instead requires hand-editing an email template in
  the Supabase dashboard: un-diffable, un-reviewable state that no one can see from the repo.
- Phase 12 has already committed to Resend for weekly report emails. Building
  `vrm_portal/mailer.py` here means Phase 12 inherits it instead of the reverse. **Write
  `mailer.py` generic** (`send(to, subject, html, from_=None, reply_to=None)`) with no
  invite-specific logic, so Phase 12 can import it unchanged.

**Fallback if Resend setup stalls:** configure Resend as Supabase's custom SMTP, edit the
"Invite user" template to `{{ .SiteURL }}?token_hash={{ .TokenHash }}&type=invite`, and call
`invite_user_by_email(email, {"redirect_to": PORTAL_BASE_URL})`. ~30 minutes, same activation
screen. Documented as plan B only.

**Resend, not invite, for re-sends and password resets.** `generate_link(type="invite")` errors
if the auth user already exists. So:

| Action | Call |
|---|---|
| First invite | `generate_link({"type": "invite", "email": e})` |
| Resend an invite / "forgot password" | `generate_link({"type": "recovery", "email": e})`, link carries `&type=recovery` |

The activation screen handles `type=invite` and `type=recovery` **identically** (verify →
session → set password), so this costs one branch, not two screens.

> **Verify empirically in Step 5, don't assume:** whether GoTrue issues a `recovery` link for
> a user who was invited but never activated (email unconfirmed). Test with a throwaway
> address. If it errors, fall back to `generate_link({"type": "magiclink", ...})` and record
> the finding in this doc.

Invite/recovery tokens expire (default 24 h). The activation screen must say so, and an
expired token must produce *"This link has expired — ask for a new one"*, never a stack trace.

### 1.9 Activation / password-set screen

Handled at the very top of `app.py`, before the session branch:

```
read st.query_params → token_hash + type in {invite, recovery}
  → auth_client().auth.verify_otp({"token_hash": ..., "type": ...})   # anon client, fresh
  → session in hand → render "Set your password" (password + confirm, min 8 chars)
  → auth.update_user({"password": ...}) on that same client
  → stamp vrm.customers.activated_at (service_role)
  → st.query_params.clear()   # token must not linger in the URL/history
  → drop into the normal logged-in flow
```

`verify_otp` is a POST that returns the session in the response body — it works fine
server-side, which is exactly why the `token_hash` variant exists.

### 1.10 Session persistence: in-memory only for V1

The signed-in session lives in `st.session_state`. A hard browser refresh or a new tab means
logging in again. **Accepted for V1**, deliberately:

- Streamlit cannot set cookies natively (`st.context.cookies` is read-only), so persistence
  means adding a third-party component that stores a refresh token in a JS-readable cookie —
  a new, unaudited dependency holding a credential, on Python 3.9.
- Putting the token in a query param is worse (URL history, shoulder-surfing, referrer leak).

Mitigation: `st.session_state` survives normal navigation and idle tabs — only a hard refresh
logs you out. If Oscar finds it annoying in real use, "Remember me" via
`extra-streamlit-components`' `CookieManager` is the documented upgrade path. Listed as a
non-goal in §4, not a gap.

Also store `expires_at` from the session and call `refresh_session()` when within 60 s of
expiry, so a long dashboard sitting open doesn't fail its next auth-touching action.

### 1.11 What the customer surface must never do

Enumerated because these are the ways a port of `tab_upload()` leaks tenancy:

1. **Never call `ingest.upsert_customer()`.** `tab_upload()` L526 does — from a customer
   session that would let a customer create or rename a tenant. The customer path resolves
   the customer row from the session and uses `customer["slug"]` for `make_site_id()`.
2. **Never render a customer picker, a schema picker, or `monitoring` data.** Customer
   reports are `rdb.VRM` only, hardcoded.
3. **Never pass a `site_id` from a widget straight into `ingest.*` or `rdb.*`** — it goes
   through `assert_owns_site()` first, every time, even when the dropdown was already
   filtered. The dropdown is UI; the guard is the control.
4. **Never let a customer create site N+1 past `site_limit`** — checked in `db.py`, not in
   the view.
5. **Never write `battery_usable_kwh`** — it is a GENERATED column since migration 019 and
   Postgres rejects the write. Set `battery_nominal_kwh` + `battery_dod_pct`.

---

## 2. Build steps

Each step is a vertical slice ending in something runnable plus a validation you can execute.
**Do not start step N+1 until step N's validation passes.**

---

### Step 1 — Migration + runnable shell + login

**Build**

- `database/migrations/0NN_vrm_portal_auth.sql` — **check `ls database/migrations/` and take
  the next unused number.** This plan says `021` on the assumption Phase 6's `020` lands
  first; if `020` is still free, use it and correct this line. Contents: the `ALTER TABLE
  vrm.customers` + two partial unique indexes from §1.3, with a header comment in the
  explanatory style of `012_vrm_schema.sql` / `016_equipment_cost_iva.sql` covering: why a
  soft pointer and not an FK, why no companion table, why RLS policies are deliberately still
  absent, and the §1.1 revisit trigger.
- `.env.example`: add `SUPABASE_ANON_KEY`, `PORTAL_BASE_URL`, `RESEND_API_KEY`,
  `PORTAL_FROM_EMAIL`. **Rewrite the existing L30–31 comment** ("The anon key is deliberately
  absent from this file: this app has no use for it") — it is about to be false, and this repo
  does not leave docs lying. New wording should say the anon key is used by the VRM portal's
  auth client only, never for data access.
- `victron-monitor/portal/app.py` — bootstrap (§1.6), `st.set_page_config`, the §1.9
  activation hook (stub returning False for now), the §1.7 navigation branch.
- `vrm_portal/auth.py`:
  - `auth_client()` — fresh anon-key client per call, with the §1.2 comment.
  - `admin_client()` — service_role-keyed client, separate instance from `get_client()`.
  - `sign_in(email, password) -> Session | raises`, `sign_out()`, `current_session()`.
  - `resolve_role(user) -> ("admin", None) | ("customer", customer_id) | raises NotLinked`,
    implementing §1.5 exactly including the `active` check.
  - `require_admin()` / `require_customer()` returning the session or calling `st.stop()`.
- `vrm_portal/views/login.py` — email + password + submit, brand-styled, generic error copy
  ("Incorrect email or password" — never "no such user"), plus a "Forgot your password?"
  link that is inert until Step 5.
- `vrm_portal/strings.py` with the login/nav strings in `en` + `es`, and a
  `t(lang, key)` accessor. Every customer-facing literal goes through it from here on.

**Validate**
- Migration runs; running it a second time is a clean no-op.
- Create one auth user by hand in the Supabase dashboard; `UPDATE vrm.customers SET
  auth_user_id = '<uid>', auth_email = '<email>' WHERE slug = '<an existing test customer>';`
- `streamlit run victron-monitor/portal/app.py` from the repo root → login page → sign in →
  a placeholder page that prints the resolved role and `customer_id`.
- Set `app_metadata.vrm_role = 'admin'` on a second user → confirm it resolves as admin with
  no `customer_id`.
- A third user linked to nothing → confirm the clean rejection message, not a crash.
- **Confirm `streamlit run app.py` (the internal app) still works and its sidebar is
  unchanged** — no `pages/` leakage in either direction.

---

### Step 2 — `vrm_portal/db.py`: the scoping choke point

**Build**

`vrm_portal/db.py` — every tenant function takes `customer_id: str` first:

```
get_customer(customer_id)
update_customer_profile(customer_id, **fields)      # whitelisted fields only, see below
list_sites(customer_id, active_only=False)
get_site(customer_id, site_id)                      # via assert_owns_site
upsert_own_site(customer_id, site_name, **fields)   # uses the customer's own slug
update_site(customer_id, site_id, **fields)
site_count(customer_id) / can_add_site(customer_id) -> (bool, reason)
list_ingestions(customer_id, limit=50)
available_dates(customer_id, site_id)               # wraps rdb.get_available_dates
assert_owns_site(customer_id, site_id)              # raises NotAuthorized
```

- Reads go through `database/vrm_report_db.py` where it already does the job (`list_sites`
  then filter, or a scoped query) — **do not add a `customer_id` parameter to
  `vrm_report_db.py`**; it is shared with the untouchable internal app. Filter here.
- `update_customer_profile` accepts a hardcoded whitelist:
  `name, contact_name, contact_email, country, ui_language`. **Never**
  `plan, site_limit, active, slug, auth_user_id, auth_email` — a customer must not be able to
  raise their own limits. Admin edits those through `admin_db.py`.
- `update_site` whitelist: `display_name, pv_kwp, battery_nominal_kwh, battery_dod_pct,
  system_type, report_language, location, timezone, latitude, longitude, country,
  savings_rate, savings_currency, exports_to_grid, active`. Never `customer_id`, `site_id`,
  `battery_usable_kwh` (generated), `vrm_installation_id`.
- `vrm_portal/admin_db.py` — the cross-customer counterpart:
  `list_customers()` (with site counts + last-upload timestamp), `create_customer()`,
  `update_customer()`, `set_active()`, `list_all_sites()`, `list_all_ingestions()`. Module
  docstring must state that nothing here is tenant-scoped and it may only be imported by
  `views/admin_*.py`.

**Validate**
- `tools/test_vrm_portal_scoping.py` (a plain script, matching the repo's tooling style —
  there is no pytest suite): create two throwaway customers each with a site, then assert
  every one of `get_site`, `update_site`, `available_dates`, `assert_owns_site` raises
  `NotAuthorized` when called with A's `customer_id` and B's `site_id`, and that
  `list_sites(A)` never contains B's site. Clean up after itself.
- `update_customer_profile(cid, plan="fleet", site_limit=999)` silently ignores both (or
  raises) — pick one and assert it.

---

### Step 3 — Customer dashboard: My Sites + Profile

**Build**

- `views/customer_sites.py` — port of `tab_sites()`'s table + form, scoped:
  - Table of the customer's sites (same columns as L193–208, minus "Cliente").
  - Per-site edit form with the §2 whitelist. Reuse the live "Batería utilizable: nominal ×
    DoD/100" caption (L235–237) — it explains a generated column that would otherwise look
    like a missing field.
  - "Add a site" form gated by `can_add_site()`; over the limit → upgrade copy + a
    `mailto:proyectos@paulyco.com` link, never a silent failure.
  - Reuse `components._timezones()` and the coordinate/reverse-geocode helper from
    `calculations/pvgis.reverse_geocode` (L357–372) including the `_pending_*` staging
    pattern — the Streamlit constraint behind it applies identically here.
- `views/customer_profile.py`:
  - Read-only: login email, plan label (from `PLANS`), sites used / limit, member since.
  - Editable: `name`, `contact_name`, `contact_email`, `country`, `ui_language`.
  - **Change password**: current + new + confirm. Re-authenticate by calling
    `sign_in_with_password(email, current)` on a *fresh* anon client first, then
    `update_user({"password": new})` on that same client. Never on the singleton.

**Validate**
- Log in as customer A: see exactly A's sites, no customer picker anywhere.
- Edit a site's `pv_kwp` and `report_language`; confirm in Supabase, and confirm
  `battery_usable_kwh` recomputed itself.
- Try to add a site with `site_limit = 1` already used → blocked with the upgrade message.
- Change the password, sign out, sign back in with the new one.
- Set `ui_language = 'es'` → the UI switches; no English strings left behind (this is the
  test that catches literals that bypassed `strings.py`).

---

### Step 4 — Customer dashboard: Upload CSV + Reports

The two ports that carry the product's actual value. Both are near-mechanical translations of
`pages/06_vrm_monitor.py`; the risk is entirely in §1.11.

**Build**

- `views/customer_upload.py` — port of `tab_upload()` (L291–559) with:
  - The "Cliente" text input **deleted**; the customer comes from the session.
  - Site chosen from a dropdown of their existing sites **or** "New site…" + a name field,
    gated by `can_add_site()`.
  - Everything else kept: the parse→preview→confirm two-step (never write on first click),
    the warnings list, the partial-day explainer (L514–521), the savings/country captions
    (L493–502), the 200 MB caption.
  - `ingest.upsert_site(...)` + `ingest.ingest_parsed(...)` are reused as-is;
    `ingest.upsert_customer()` is **not called** (§1.11.1).
  - Add a lightweight "Uploads" history table under the form from `db.list_ingestions()` —
    `vrm.ingestion_log` exists precisely to answer "why did this report look wrong" and no UI
    has ever read it.
- `views/customer_reports.py` — port of `tab_report()`'s `vrm` branch (L621–782):
  - Schema radio **deleted** (`rdb.VRM` hardcoded); site dropdown from `db.list_sites`.
  - Keep: the range picker bounded to real data, `MAX_OVERVIEW_RANGE_DAYS` /
    `MAX_CUSTOM_RANGE_DAYS` handling and the Detallado/Overview caption, the coverage warning,
    `_report_feature_cards()`, the KPI cards + chips + Plotly mix bar, the weather-error and
    battery-stress/grid-quality warnings, and the download button.
  - `wr.build_report_data(...)` / `wr.render_pdf(...)` called unchanged.

**Validate**
- As customer A, upload a real VRM CSV to a new site → preview matches the internal tool's
  preview for the same file → confirm → rows land under A's `customer_id`.
- Re-upload the same file → row count does not grow (the `UNIQUE (site_id, date)` upsert) and
  alarm episodes do not double.
- Generate a report for a 7-day range and a >31-day range → correct mode caption each time;
  PDF byte-identical in its numbers to the same range generated from `pages/06_vrm_monitor.py`.
- With DevTools, tamper the site dropdown's submitted value to another customer's `site_id` →
  `NotAuthorized`, nothing written.
- Confirm `pages/06_vrm_monitor.py` still works unchanged against the same data.

---

### Step 5 — Admin dashboard + the invite flow

**Build**

- `vrm_portal/mailer.py` — Resend wrapper. Generic `send(to, subject, html, from_=None,
  reply_to=None) -> dict`, `RESEND_API_KEY` / `PORTAL_FROM_EMAIL` from env, raises a typed
  error on failure. **No invite-specific logic** (Phase 12 imports this).
- `vrm_portal/templates/invite_email.html` — Jinja2, table-layout + inline styles, no `data:`
  URIs (the same constraint Phase 12 documents for Gmail), brand colours from `config.py`.
- `vrm_portal/invites.py`:
  - `send_invite(customer_id)` → `generate_link(type="invite")` → build
    `{PORTAL_BASE_URL}/?token_hash=…&type=invite` → render → `mailer.send` → set
    `invited_at`, `auth_user_id`, `auth_email` on the customer row.
  - `resend_invite(customer_id)` / `send_password_reset(email)` → `type="recovery"`
    (see the §1.8 empirical check — do it here, and write the result into §1.8).
  - Handle "email already registered": if an auth user with that email exists and is linked
    to a *different* customer, refuse with a clear message; if unlinked, offer to link it.
- `views/admin_customers.py` (Spanish): table of every customer — name, account type, plan,
  sites, last upload, auth status (`Sin invitar` / `Invitado <date>` / `Activo <date>`),
  active flag. Actions: create customer (name → slug preview, account type, plan → `site_limit`
  prefilled from `PLANS`, contact fields, login email, `ui_language`) + **Enviar invitación**;
  resend invite; edit; activate/deactivate.
- `views/admin_sites.py` — `tab_sites()` near-verbatim (it already shows the "Cliente" column
  and cross-customer counts), plus per-site edit and a customer-reassignment control.
- `views/admin_upload.py` — `tab_upload()` verbatim, customer picker kept (this is what Oscar
  does today, preserved).
- `views/admin_reports.py` — `tab_report()` verbatim, both schemas.
- `views/admin_activity.py` — `vrm.ingestion_log` across all customers, newest first, with the
  `warnings` jsonb expandable.

**Validate**
- Create a customer with a real address you control → email arrives → link opens the
  activation screen → set a password → land on the customer dashboard → the customer's
  `activated_at` is stamped.
- Click the same link a second time → "expired / already used", no crash.
- Resend the invite to a never-activated account → works (or the documented fallback does,
  and §1.8 is updated with what actually happened).
- Forgot-password from the login page → email → new password → sign in.
- Deactivate a customer → their login is rejected cleanly; reactivate → works again.
- Admin sees every customer's sites; a customer sees only their own. Same browser, two
  sessions, one after the other.

---

### Step 6 — Landing-page link, deployment, and docs

**Blocked on §0.3 Q1 (hosting) and Q4 (landing page).**

**Build**
- `victron-monitor/landing-page/landing_template.html`: add a **Log in** link to the nav
  (L421–427) pointing at `PORTAL_BASE_URL`, styled like the existing ghost button. Re-run
  `python3 build.py` to regenerate `landing_page.html` (never hand-edit the output) and
  republish. The `mailto:` early-access form is unchanged.
- `Dockerfile` (or `packages.txt`, host-dependent) covering WeasyPrint's system libs, plus the
  host's start command `streamlit run victron-monitor/portal/app.py --server.port $PORT
  --server.address 0.0.0.0`. Must run with the repo root as WORKDIR (§1.6).
- Set the host's env vars: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_ANON_KEY`,
  `ANTHROPIC_API_KEY` (the AI narrative), `RESEND_API_KEY`, `PORTAL_FROM_EMAIL`,
  `PORTAL_BASE_URL`. **Never committed.**
- `victron-monitor/portal/README.md` — run locally, env vars, deploy, and an explicit note
  that this app shares the repo's pipeline modules and must not import from `pages/`.
- Update `victron-monitor/README.md` and `ARCHITECTURE.md` (the portal is a new box: browser →
  portal → Supabase `vrm` + Resend), and add a CONTEXT.md entry in the existing style.

**Validate**
- From the published landing page, click Log in → the deployed portal → sign in → generate a
  report end to end on the deployed host (this is the real WeasyPrint/system-libs test).
- Upload a ~140 MB CSV on the deployed instance and watch memory — if it OOMs, size up the
  instance and record the required tier in the README.
- Confirm the internal Streamlit app is untouched: `git diff --stat` shows **no changes** to
  `app.py` or anything under `pages/`.

---

## 3. Repo conventions the coder must follow

- **`from __future__ import annotations` as the first line of every new `.py`** (Python 3.9;
  repo-wide). In `victron/` and `database/` modules the docstring comes *after* it
  (`victron/ingest.py`, `database/vrm_report_db.py`); in `pages/` it comes first. New
  `vrm_portal/` modules: future import first, then docstring — match `victron/`.
- **No ORM.** `get_client()` singleton from `database/supabase_client.py`, then
  `.schema("vrm").table(x).select/insert/update/upsert().execute()`, exactly as
  `victron/ingest.py` does.
- **Never write a generated column** (`vrm.sites.battery_usable_kwh`, migration 019).
- **Formatting** via `utils/formatting.py` (`fmt_usd`, `fmt_kwh`, `fmt_kw`, `fmt_pct`,
  `fmt_crc`). `fmt_pct` expects 0–100, not 0–1. Money in the report/savings path goes through
  `victron/savings.format_money`.
- **Brand constants** from `config.py` (`BRAND_GREEN`, `BRAND_NAVY`, `BRAND_GREEN_LIGHT`),
  countries from `config.COUNTRIES`. Do not redefine them in `vrm_portal/`.
- **Streamlit idioms from `pages/06_vrm_monitor.py`:** `@st.cache_data(ttl=30)` for list reads
  with an explicit `.clear()` after every write; `st.rerun()` after writes;
  `try/except Exception as exc:  # noqa: BLE001` → `st.error(f"…: {exc}")`; the `_pending_*`
  session-state staging pattern for widgets written by a button callback; no `st.dialog`
  anywhere in this repo — use an inline container/expander.
  **Cache keys must include `customer_id`** — `@st.cache_data` is process-wide, not
  per-session, so a cached `_sites()` with no tenant in its key would serve one customer's
  list to another. This is the single most likely tenancy bug in the phase.
- **Language:** admin views Spanish (port the existing copy verbatim where it applies);
  customer views through `vrm_portal/strings.py` only — no bare user-facing literals.
- **Do not modify** `app.py`, anything under `pages/`, or the *signatures* of
  `database/supabase_client.py`, `database/vrm_report_db.py`, `victron/*.py`. Additive-only if
  a change is truly unavoidable, and say so in the step's notes.
- **Comments explain the non-obvious, in this repo's voice** — every surprising line in
  `pages/06_vrm_monitor.py` and migration 012 carries a comment saying *why*, including what
  was tried and rejected. Match that. In particular, comment: the `sys.path` bootstrap, the
  two-client rule, the fragment-vs-query-param reason for `generate_link`, and every
  `assert_owns_site` call site that looks redundant.
- **Secrets:** never commit a key; never `st.write` a client object or a session; never log a
  token or a `token_hash`.
- **git on this machine:** stage files in batches of 5–10 (`git-lfs` is configured but not
  installed — bulk `git add` and `git show --stat` hang). Use `timeout 90 git commit`.

---

## 4. Explicit non-goals

Named so scope doesn't creep, and so the tester doesn't file them as bugs:

- **Public self-serve signup.** Accounts are created by Oscar only. The landing page's
  early-access `mailto:` stays a `mailto:`.
- **Billing, payments, plan enforcement beyond `site_limit`, usage metering.** `plan` is a
  label plus a site cap. No Stripe, no invoices, no "you owe $29".
- **Multiple users per customer.** One login per tenant, by the user's explicit decision.
- **RLS policies / per-user JWTs.** §1.1 — deliberate, with a written revisit trigger.
- **Persistent login across a hard refresh.** §1.10.
- **VRM API token ingestion** (`source = 'vrm_api'`). Still V2, unchanged.
- **Scheduled/automatic report emails to customers.** That is Phase 12's automation shell.
  Phase 13 only leaves `mailer.py` behind for it.
- **Per-customer report branding** (`vrm.customers.branding` jsonb, logo upload, white-label).
  The column exists and stays empty; Growth-tier white-labelling is sold on the landing page
  but is a separate piece of work in the report renderer, not in the portal.
- **Retiring `pages/06_vrm_monitor.py`.** It stays live and untouched. Once the admin
  dashboard has proven itself in real use, retiring it is a follow-up decision.
- **Impersonation / "log in as this customer" from admin.** Admin sees everything through
  admin views; it does not assume a customer session.

---

## 5. Risks and tradeoffs

| Risk | Assessment / mitigation |
|---|---|
| **A cached-data tenancy leak** | Highest-probability real bug. `@st.cache_data` is process-wide. Mitigation: `customer_id` in every cache key, plus the Step 2 scoping test, plus a manual two-session check in Step 4's validation. |
| **service_role key on a public host** | The portal holds a key that bypasses RLS. Mitigation: host secrets only (never the repo/image), the §1.1 choke point, no page that renders unscoped data to a customer session. This is the honest cost of the §1.1 decision and should be stated plainly to Oscar. |
| **A 140 MB CSV through pandas on a small instance** | Real OOM risk; the internal tool has only ever run on Oscar's Mac. Mitigation: measure in Step 6, size the instance accordingly, document the tier. Longer term this wants a background worker. |
| **Streamlit concurrency** | One process, one Python. Two simultaneous uploads or report renders will make each other slow. Fine at first-customers scale; the upgrade path (queue/worker) is the arch doc's §6 recommendation and is not being taken now. |
| **Two Streamlit apps sharing `victron/` and `database/`** | A change made for the portal can break the internal app silently — there is no test suite. Mitigation: the additive-only rule in §3, and Step 4/6 validations that explicitly re-run `pages/06_vrm_monitor.py`. |
| **The invite/recovery link mechanics are the least-verified part of the plan** | `verify_otp(token_hash)` and `generate_link` are confirmed present in the installed library and the flow is documented by Supabase, but the recovery-for-unactivated-user case is genuinely unknown. Mitigation: it is called out as an explicit empirical check in Step 5, with a named fallback. |
| **Session loss on refresh may read as broken to a paying customer** | Accepted for V1 (§1.10) with a documented upgrade path. Worth watching in the first weeks of real use. |
| **Deployment is genuinely undecided** (§0.3 Q1) | Steps 1–5 are all locally verifiable, so this blocks only Step 6. Do not let it block starting. |
