# VRM Monitor — web

Next.js app: marketing site + customer portal + admin dashboard, on one
design system. Built per [`PLAN_PHASE14.md`](../../PLAN_PHASE14.md); this
README grows with each step (deploy notes at Step 8). Today it covers what
Step 1 built (the scaffold, the design tokens, and `components/ui/*`), what
Step 2 added (the marketing site itself, as real pages), what Step 3 added
(auth: login, session, role resolution, and the `/app` / `/admin` shells),
what Step 4 added (the tenant-scoped data layer, My Sites, and Profile),
and what Step 7 added (the invite/activation/forgot-password flow and the
real `/admin/*` dashboard — `vrm_api/README.md` covers Step 5's env vars;
Step 6's upload/report proxies didn't get their own README section, a gap
from that step, not this one).

## Environment variables

Set in `.env.local` (gitignored — never committed). This is a **second,
separate key pair** from the root repo's `.env` (`SUPABASE_SERVICE_ROLE_KEY`
/ `SUPABASE_ANON_KEY`, which keep serving the existing Streamlit app
unchanged) — same Supabase project, Supabase's newer key format
(`PLAN_PHASE14.md` §0.4 Q6, §1.2):

```bash
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_PUBLISHABLE_KEY=sb_publishable_...   # auth/session client (lib/server/supabase.ts)
SUPABASE_SECRET_KEY=sb_secret_...             # data client — vrm.* reads/writes
```

**No `NEXT_PUBLIC_SUPABASE_*` variable is ever defined, and none should be
added.** That is the structural guarantee described in
`lib/server/supabase.ts`'s header comment: without a `NEXT_PUBLIC_` var
there is no legal way for client-side code to construct a Supabase client.

Step 5/6 additions (`lib/server/pipeline.ts` and everything under
`app/api/*/pipeline/*`, `app/api/*/uploads/sign`):

```bash
PIPELINE_API_URL=http://localhost:8000   # vrm_api, local dev
PIPELINE_API_KEY=...                     # same value as vrm_api's own env — see vrm_api/README.md
```

Step 7 additions (`lib/server/invites.ts`, `lib/server/resend.ts`):

```bash
RESEND_API_KEY=re_...          # same Resend key the repo-root .env already has
PORTAL_FROM_EMAIL=info@paulyco.com
SITE_URL=http://localhost:3000 # lib/site.ts — overrides the prod-domain-placeholder
                                # fallback so activation links resolve locally
```

`RESEND_API_KEY`/`PORTAL_FROM_EMAIL` are sent from **this app**, not
`vrm_api` — see `lib/server/resend.ts`'s header comment for why
`lib/server/invites.ts` doesn't call `victron/mailer.py` (the Python
counterpart Phase 12 will import unchanged) even though both exist.

Phase 16 Step 4 addition (`app/api/webhooks/onvo/route.ts`):

```bash
ONVO_WEBHOOK_SECRET=webhook_secret_...   # from the ONVO dashboard's "Desarrolladores"
                                          # section, this endpoint's own registered
                                          # webhook. NOT the same value as vrm_api's
                                          # ONVO_SECRET_KEY (root .env) — see
                                          # PLAN_PHASE16.md §6.1's table. Unset/empty
                                          # means every delivery is rejected (fail
                                          # closed), never "anything matches".
```
**Known account-config gap, not a code defect:** as of this writing the
`paulyco.com` domain is not verified in this project's Resend account, so
a real send to an arbitrary recipient (e.g. an actual customer) currently
gets a `403` from Resend itself ("The paulyco.com domain is not verified").
`lib/server/resend.ts` surfaces this as a typed `MailerError` correctly —
verified working end-to-end with a deliverable from/to pair
(`onboarding@resend.dev` → the account's own verified test address). Fix:
verify the domain at resend.com/domains before relying on real invites
sending in this environment.

Phase 16 Step 5.5 additions (`lib/server/signup.ts`, `app/(auth)/signup/*`
— public self-serve signup, `PLAN_PHASE16.md` §5.5/§6.6):

```bash
SIGNUP_IP_SALT=...              # server-side pepper for vrm.signup_requests.ip_hash
                                 # = sha256(ip + SIGNUP_IP_SALT) — never the raw IP is
                                 # stored. Rotating this resets the signup rate-limit
                                 # history (§3.7) — acceptable, worth knowing.
# SIGNUP_CAPTCHA_PROVIDER=turnstile   # commented out on purpose — a seam, not a
# SIGNUP_CAPTCHA_SECRET=...           # decision (§0.6 Q12, unanswered). Left unset,
                                       # lib/server/signup.ts:verifyHumanChallenge()
                                       # is a no-op that always returns "human".
                                       # Setting SIGNUP_CAPTCHA_PROVIDER without also
                                       # shipping a verifier for it makes every signup
                                       # fail closed — see that function's own comment.
```

`ONVO_SECRET_KEY`/`ONVO_PUBLISHABLE_KEY`/`ONVO_MODE` are **not** read by this
app at all — they live in the root `.env` and are read only by `vrm_api`
(`vrm_api/onvo.py`, `vrm_api/routers/billing.py`); see `vrm_api/README.md`.
This app only ever forwards a `plan_id`/`payment_method_id` through
`lib/server/pipeline.ts` to `vrm_api`'s pipeline-key-authenticated billing
router, and never holds an ONVO key of its own.

## Public surface

The complete list of routes reachable with **no session** — reproduced
verbatim from `PLAN_PHASE16.md` §1.1, which is the list `lib/server/
ratelimit.ts` and the signup/webhook handlers police. A reviewer auditing
"what can an unauthenticated request do to this app" should be able to find
the answer here, in one place, without reading the plan doc:

| Route | Auth | What it does |
|---|---|---|
| `/` (marketing), `/styleguide`, `robots`, `sitemap` | none | static, unchanged |
| `/login`, `/forgot`, `/activate` | none | unchanged |
| `/signup` (page + its Server Action) | none | stages a signup request, sends one email. Writes only `vrm.signup_requests` |
| `/signup/verify` | token | redeems a single-use token; creates the `vrm.customers` row; redirects into `/activate` |
| `/api/webhooks/onvo` | shared secret (`ONVO_WEBHOOK_SECRET`) | machine-to-machine, forwards to `vrm_api`'s `POST /v1/billing/webhook-event` after verifying the secret and rate-limiting |

Anything not on this list requires a session (`requireCustomer()` /
`requireAdmin()` / their `ForRoute` counterparts). A request with no session
can never create anything of value through any of the rows above — `/signup`
stages an intent and sends one email; `/signup/verify` requires possession of
a single-use token already emailed to the address being claimed; the webhook
route only re-triggers a read-through reconcile against a customer resolved
from **our own** mirror tables, never from anything in the request body
(§0.5, §4.2). Adding a row to this table means editing both this section and
`PLAN_PHASE16.md` §1.1/§6.6.

## Node version

This machine's default Node (`nvm`) is **v18.20.8**, but Next.js 16.3
requires **Node ≥ 20.9.0**. Node **20.20.0** is installed via `nvm` and is
pinned for this subproject only, via `.nvmrc` — the machine's global `nvm`
default is deliberately left alone (other tooling on this machine may
depend on Node 18).

Before any `npm`/`npx` command here, in the same shell invocation:

```bash
source "$HOME/.nvm/nvm.sh" && nvm use
```

(`nvm use` with no version reads `.nvmrc` from the current directory.) This
doesn't persist across separate shells/tool calls — run it every time.

## Local development

```bash
source "$HOME/.nvm/nvm.sh" && nvm use
npm install    # first time / after a dependency change
npm run dev    # http://localhost:3000
```

Other scripts:

```bash
npm run build      # production build (also regenerates .next/types)
npm run start       # serve the production build
npm run lint         # eslint
npm run typecheck    # tsc --noEmit
```

## What's here (Step 1)

- **No Tailwind.** Styling is component-scoped CSS Modules over a shared
  token file (`styles/tokens.css` + `styles/base.css`), ported near-verbatim
  from `victron-monitor/landing-page/landing_template.html` — see
  `PLAN_PHASE14.md` §1.7 for why a Tailwind rewrite was rejected here.
- `styles/tokens.css` — the single source of truth for every color, radius
  and type-scale value used across `components/ui/*`.
- `app/fonts/` — the same four `.woff2` files the landing page uses
  (copied, not moved — the landing page stays the design source of truth
  and must keep rendering standalone until Phase 14 Step 8's cutover, per
  §6.2), wired up with `next/font/local` instead of the landing page's
  build-time base64 inlining (that inlining exists only to satisfy the
  Claude Artifact CSP the landing page is published under).
- `components/ui/*` — Button, Panel, Stat, Eyebrow, Field, ModeToggle. Each
  is a near-verbatim move of the corresponding rule block from
  `landing_template.html`, in its own co-located `.module.css`.
- `app/styleguide` — every primitive above, in every state, plus the §1.8
  brand-blue A/B: append `?blue=0588B6|3481B8|0089B6` and/or
  `?btn=deep|flat` to re-bind `--victron`/`--btn-fill` and compare
  candidates on real rendered components. Defaults to `blue=0588B6,
  btn=deep` (the plan's recommendations) when no query param is given.

## What's here (Step 2)

- `app/(marketing)/page.tsx` — the real marketing home page (route group,
  so it's still served at `/`), composed from `components/marketing/*`: Nav,
  Hero (+ Readout), FlowSteps ("How it works"), ModuleGrid ("What's inside",
  with the Detallado/Resumen toggle), ReportPreview ("Sample report"),
  Pricing (Subscription/Single report toggle), AccessForm (the CTA band's
  installer/owner request form, `mailto:` composition ported to React
  state), Footer.
- `components/ui/SectionHead` — one more primitive than Step 1 shipped,
  added here: three of Step 2's sections open with the same eyebrow + h2 +
  lede shape, and `PLAN_PHASE14.md` §1.7 already lists SectionHead in
  `components/ui/*`.
- `public/pauly_logo.png` + `public/sample_report.png` — copied (not moved)
  from `landing-page/assets/`, same reasoning as the fonts in Step 1.
- Nav has a **Log in** link to `/login` (styled as the ghost `Button`
  variant) — the route doesn't exist until Step 3, so it 404s today. That's
  expected, not a bug.
- `app/robots.ts` + `app/sitemap.ts`, and marketing-page metadata (title,
  description, Open Graph image) in `app/(marketing)/page.tsx`. Neither sets
  `metadataBase` — the real domain is `PLAN_PHASE14.md` §0.4 Q1, still open;
  `lib/site.ts`'s `SITE_URL` fallback and a build-time console warning are
  the deliberate placeholder until Step 8 answers it.
- Copy is ported **verbatim** from `landing_template.html`. A couple of
  source quirks were kept as-is rather than "fixed" — see the header
  comments in `components/marketing/Pricing/Pricing.module.css` (the single-
  report card's tag label isn't actually styled as a tag on the live page,
  a `.single-report-card .tag` / `.card .tag` selector-scope mismatch) and
  `components/marketing/AccessForm/AccessForm.module.css` (the "See the
  sample report again" link never gets the `--victron-glow` hover treatment
  the CSS seems to intend, same class of mismatch). Both are visible on the
  live page today, not something this port introduced.

### Validating Step 2 locally

```bash
source "$HOME/.nvm/nvm.sh" && nvm use
npm run build && npm run typecheck && npm run lint
grep -r "NEXT_PUBLIC_SUPABASE" .            # must return nothing
```

Visual/interaction check against the design source of truth:

```bash
# serve the landing page with an explicit charset — plain
# `python3 -m http.server` omits charset from its Content-Type header,
# which makes browsers mis-render the template's em dashes/middle dots as
# mojibake on *both* pages equally, a serving artifact that has nothing to
# do with either codebase (confirmed while validating this step).
cd ../landing-page && python3 - <<'PY'
import http.server, socketserver
Handler = http.server.SimpleHTTPRequestHandler
Handler.extensions_map['.html'] = 'text/html; charset=utf-8'
socketserver.TCPServer(("", 8100), Handler).serve_forever()
PY
```

Then compare `http://localhost:8100/landing_page.html` against the running
Next.js app at 1440 / 920 / 560px — the three breakpoints `styles/*` and
every `components/*/*.module.css` actually define.

## What's here (Step 3)

Auth: server-only Supabase, login, session, role resolution
(`PLAN_PHASE14.md` §2 Step 3). This is the TypeScript port of the already-
validated `vrm_portal/auth.py` / `vrm_portal/strings.py` (Phase 13) — read
those two files first if something here is confusing; the role-resolution
order is a deliberate, exact port, not a reinterpretation.

- `lib/server/supabase.ts` — the only module allowed to construct a
  Supabase client. `createSupabaseServerClient()` (auth/session, cookie-
  bound, `SUPABASE_PUBLISHABLE_KEY`) and `getSupabaseAdmin()` (data,
  lazy singleton, `SUPABASE_SECRET_KEY`) — see its header comment for why
  the split survives even though the Python "two-client rule"'s original
  hazard doesn't, why there's no browser-exposed Supabase env var, why
  `getUser()` and not `getSession()`, and why every client here is
  constructed with `realtime: { transport: ws }` (a Node-version
  compatibility fix, not a feature — see the comment for the full reasoning).
- `lib/server/supabase-middleware.ts` + `proxy.ts` — the token-refresh
  entry point. **Named `proxy.ts`, not `middleware.ts`**: Next.js 16
  deprecated and renamed the `middleware.js` file convention to `proxy.js`
  between the plan being written and this step being built
  (`node_modules/next/dist/docs/.../proxy.md`). Functionally, this *is*
  `PLAN_PHASE14.md`'s "middleware.ts" — matched to `/app/*`, `/admin/*`,
  `/login`, `/activate`; it only refreshes the session cookie, it does not
  redirect or check role (that's `requireCustomer()`/`requireAdmin()`,
  which run as the first statement of the guarded page/action itself).
- `lib/server/auth.ts` — `resolveRole()` (the exact port of
  `resolve_role()`), `getSessionContext()` (wrapped in React's `cache()` so
  calling it from both a layout and its page costs one Supabase round trip,
  not two — see its doc comment), `requireCustomer()`/`requireAdmin()`
  (redirect, for pages/Server Actions) and
  `requireCustomerForRoute()`/`requireAdminForRoute()` (403 JSON, for Step
  4+'s Route Handlers — not exercised by anything yet, since none exist
  until Step 4).
- `lib/server/auth-actions.ts` — `signOutAction`, the one Server Action
  shared by both `AppShell`s.
- `lib/i18n/strings.ts` — straight port of `vrm_portal/strings.py`,
  including the `t(lang, key)` fallback chain (missing key → English → the
  raw key, never a crash).
- `app/(auth)/login/` — `page.tsx` (redirects an already-signed-in visitor
  to their own home instead of showing the form), `LoginForm.tsx` (client
  component: `useActionState` for pending/error display only — no Supabase
  import anywhere in it), `actions.ts` (`signInAction`, the port of
  `vrm_portal/auth.py:sign_in()` — same generic "Incorrect email or
  password" for every credential failure, same `signOut()`-before-rejecting
  behaviour for the `NotLinked` case).
- `app/(portal)/app/layout.tsx` + `app/(admin)/admin/layout.tsx` — call
  `requireCustomer()`/`requireAdmin()` and render `components/app/AppShell`
  (role-aware nav — English `lib/i18n/strings.ts` keys for the portal,
  inline Spanish literals for admin, per `PLAN_PHASE14.md` §1.10) around a
  placeholder page (`page.tsx` in each) that shows the resolved role,
  `customerId`, and a working sign-out button — proving the whole chain
  end to end before Step 4 builds real dashboard content. Both layouts *and*
  both pages call the guard independently (`PLAN_PHASE14.md` §3: "never
  inferred from layout nesting") — the `cache()` wrapper mentioned above is
  what keeps that cheap.

### Validating Step 3 locally

```bash
source "$HOME/.nvm/nvm.sh" && nvm use
npm run build && npm run typecheck && npm run lint
```

Functional checks (signed out, cross-role, sign-out, hard-refresh/new-tab)
need a running dev server (`npm run dev`) and either a browser or a script
that drives the login form's progressive-enhancement POST (no client-side
JS Supabase call exists to hit directly — the form posts to a Server
Action). What was actually run to validate this step, against the real
Supabase project referenced in `.env.local`:

- Signed out, `curl -I http://localhost:3000/app` and `/admin` → both
  `307` to `/login`.
- For each of an admin session, a linked+active customer session, an
  unlinked session, and an inactive-customer session: submit the login
  form (email/password), then `curl` `/app` and `/admin` with the resulting
  cookie jar. Admin → `/admin` 200, `/app` 307→`/admin`. Customer → `/app`
  200, `/admin` 307→`/app`. Unlinked/inactive → both credential-accepted
  paths show the identical "This account isn't linked..." message, **and**
  the session cookie set during `signInWithPassword` is not present in the
  jar afterwards (the action's `signOut()` clears it in the same response)
  — confirmed by inspecting the cookie jar's contents, not just the error
  copy.
- Session persistence: saved the customer session's cookie to disk, then
  opened a **brand new cookie jar + HTTP client process** (no shared
  in-memory state at all — the closest a script gets to "a new browser
  tab") pointed at the same saved cookie file, and confirmed `/app` still
  returns 200. This is Phase 13 §1.10's "no session persistence across a
  refresh" limitation being retired, confirmed rather than assumed.
- Sign-out: submitted the `AppShell` sign-out form with a live session,
  confirmed the cookie jar is empty afterwards and a subsequent `/app`
  request redirects to `/login`.

**Leak checks — the exact commands, re-run at every later step:**

```bash
# 1. No browser-exposed Supabase env var anywhere in the app's own code.
#    (This file's own mention of the variable name in prose is the one
#    expected self-match if you grep the whole web/ tree including *.md —
#    grep lib/ app/ components/ proxy.ts specifically to check real code.)
grep -r "NEXT_PUBLIC_SUPABASE" lib app components proxy.ts   # must return nothing

# 2. The secret key never reaches a client-shipped bundle. RESEND_API_KEY
#    and PIPELINE_API_KEY joined this check at Step 7 (any secret a later
#    step introduces belongs here going forward, not a step-specific copy).
npm run build
grep -rE "sb_secret|service_role|SUPABASE_SECRET|PIPELINE_API_KEY|RESEND_API_KEY" .next/static   # must return nothing

# 3. A real user's own access token cannot read vrm.* directly through
#    PostgREST — anon/authenticated still have zero grants on the schema
#    (unchanged since migration 012), so this must fail even with a
#    genuinely valid, unexpired token.
SUPABASE_URL=$(grep '^SUPABASE_URL=' .env.local | cut -d= -f2-)
PUBLISHABLE=$(grep '^SUPABASE_PUBLISHABLE_KEY=' .env.local | cut -d= -f2-)
TOKEN=$(curl -s -X POST "$SUPABASE_URL/auth/v1/token?grant_type=password" \
  -H "apikey: $PUBLISHABLE" -H "Content-Type: application/json" \
  -d '{"email":"<a real test user email>","password":"<their password>"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
curl -s -D - "$SUPABASE_URL/rest/v1/sites?select=*" \
  -H "apikey: $PUBLISHABLE" -H "Authorization: Bearer $TOKEN" -H "Accept-Profile: vrm"
# expect: HTTP 403, {"code":"42501", ..., "message":"permission denied for schema vrm"}
```

## What's here (Step 4)

The tenant-scoped data layer + My Sites + Profile (`PLAN_PHASE14.md` §2
Step 4) — the first place this app writes `vrm.*` data, and the first
place `PLAN_PHASE14.md` §1.2 rule 4's choke point actually has callers.

- `lib/server/db/` — every file `import 'server-only'`. `customers.ts`
  (`getCustomer`, `updateCustomerProfile`), `sites.ts` (`listSites`,
  `getSite`, `updateSite`, `siteCount`, `canAddSite`, `createSite`,
  `assertOwnsSite`), `ingestions.ts` (`listIngestions`), `errors.ts`
  (`NotAuthorized`), `types.ts` (row shapes), `index.ts` (the barrel —
  "page and route-handler code may import only this module," per §1.2).
  Profile and site updates each go through a field whitelist enforced
  **twice**: a `Pick<...>`-derived TypeScript type (an excess-property
  object literal like `{ plan: 'fleet' }` is a compile error) and a
  runtime `pickWhitelisted()` that only copies keys actually present on
  the input and in the allow-list (so a forced-through `as any` still
  can't reach `plan`/`site_limit`/`active`/`slug`/`auth_user_id`/
  `auth_email` on a customer, or `customer_id`/`site_id`/
  `battery_usable_kwh`/`vrm_installation_id` on a site).
- `lib/server/db/admin.ts` — the cross-customer counterpart
  (`listCustomers`, `createCustomer`, `updateCustomer`, `setActive`,
  `listAllSites`, `listAllIngestions`). Its header comment says plainly
  that "only `/admin/*` may import this" is a code-review convention, not
  a build-time guarantee — there's no ESLint boundary rule enforcing it.
- `lib/plans.ts`, `lib/countries.ts` (ported from `config.COUNTRIES`,
  Spanish labels kept as-is — see its own header comment), `lib/currencies.ts`
  (`SUPPORTED_FLAT_CURRENCIES`, from `victron/savings.py`), `lib/timezones.ts`
  (`Intl.supportedValuesOf('timeZone')` — the behavioral port of
  `pages/06_vrm_monitor.py`'s `_timezones()`), `lib/slug.ts` (`slugify`/
  `makeSiteId`, ported from `victron/ingest.py`).
- `lib/server/geocode.ts` — reverse-geocodes lat/lng to a location name +
  country via Nominatim, the same external call `calculations/pvgis.py`
  makes. **Scope cut, flagged rather than silently made:** the Python
  original also auto-fills the IANA timezone via `timezonefinder`'s
  offline boundary data; the closest npm equivalent (`geo-tz`) is a ~70MB
  dependency for what these pages treat as a manual, searchable `<select>`
  instead. Once `vrm_api` (Step 5) exists, a small `GET /v1/geocode`
  backed by the Python pipeline's own `timezonefinder` install is the
  honest fix — noted for whoever builds that step.
- `app/(portal)/app/sites/` — `page.tsx` (Server Component: fetches this
  customer's sites + `canAddSite()`), `SitesManager.tsx` (client: which
  row's edit form is open, add-site toggle), `SiteForm.tsx` (client: the
  shared edit/add form — live "usable battery" caption, the reverse-geocode
  button), `actions.ts` (`updateSiteAction`, `addSiteAction`,
  `reverseGeocodeAction`, all `requireCustomer()`-first, all Zod-validated
  before reaching `lib/server/db`).
- `app/(portal)/app/profile/` — `page.tsx` (read-only: login email, plan
  label, sites used/limit, member since), `ProfileForm.tsx` (the five
  whitelisted fields), `ChangePasswordForm.tsx` +
  `actions.ts:changePasswordAction` (re-authenticates with the current
  password via `signInWithPassword` before ever calling `updateUser`).
- `components/ui/Table` — new primitive (not ported from the marketing
  page, which has no data table); used by the sites list.
- `components/ui/Field` — `optional` now also accepts an `optionalLabel`
  override. The marketing/login forms keep the hardcoded `" (optional)"`
  default (English-only by design, §1.10); `ProfileForm.tsx` passes a
  translated one — found and fixed while validating this step's own "no
  English left behind" check.
- `scripts/test-scoping.ts` (`npm run test:scoping`) — the regression test
  for §1.2's whole tenant-scoping model: two throwaway customers, one site
  each, asserts `getSite`/`updateSite`/`assertOwnsSite`/`listIngestions`
  all throw `NotAuthorized` for customer A's id + customer B's site_id,
  and that `listSites(A)` never contains B's site. Cleans up after itself
  (`try`/`finally`). Needs `--conditions=react-server` because every module
  it imports starts `import 'server-only'`, which throws outside a
  bundler-supplied `react-server` condition — see the script's own header
  comment for why that flag doesn't weaken the guarantee it's working
  around. Re-run this at every later step.

## What's here (Step 7)

The invite/activation/forgot-password flow, and the real `/admin/*`
dashboard (`PLAN_PHASE14.md` §2 Step 7) — everything under `/admin` was a
Step 3 placeholder until now.

- `lib/server/resend.ts` — a generic Resend HTTP client (`sendEmail`,
  typed `MailerError`). Chosen over routing through `vrm_api` — see its own
  header comment for the full reasoning against `victron/mailer.py`
  (Step 7's Python-side deliverable, built for Phase 12, not called by this
  app).
- `lib/server/emailTemplates.ts` — `renderActivationEmail()`, a hand-kept
  visual port of `victron/templates/invite_email.html`'s Jinja2 design
  (table layout, inline styles, no `<style>`/`data:` URIs — Gmail strips/
  blocks both). The two files are **not** shared and can drift if one is
  edited without the other — flagged in both files' own comments.
- `lib/server/invites.ts` — `sendInvite`/`resendInvite`/`sendPasswordReset`,
  `markActivated`, `getCustomerByAuthUserId`. Handles "email already
  registered" (a different customer → refuse; an orphaned, unlinked auth
  user → link it instead of erroring — see its own comment for why the
  "different customer" case is actually unreachable via two co-existing
  rows, migration 021's unique index already blocks that at INSERT time).
- `lib/server/db/admin.ts` additions: `CreateCustomerFields.authEmail`
  (written to `auth_email` at creation, not `auth_user_id`/`invited_at`),
  `updateAnySite`/`reassignSite`/`getAnySite` (cross-customer site writes,
  `/admin/sites`-only).
- `lib/server/pipeline.ts` additions: `getAvailableDatesAdmin`,
  `listSitesForSchema` — call the schema/actor-gated extensions Step 7 made
  to `vrm_api/routers/meta.py` (see `vrm_api/README.md`).
- `app/(auth)/activate/` — `page.tsx` reads `token_hash`/`type` from
  `searchParams` server-side and hands a **bound Server Action** down to
  `ActivateClient.tsx`, never the token itself (`actions.ts`'s header
  comment has the full reasoning: a Server Component can't set cookies,
  `verifyOtp()` needs to, so the actual call has to live in a Server
  Action either way — the bound-action-as-prop trick is what keeps the
  token off the client-component boundary in the meantime, same mechanism
  `SitesManager.tsx` already uses for `site.site_id`).
- `app/(auth)/forgot/` — always the same neutral response
  (`ForgotForm.tsx`'s `state.submitted`), regardless of what
  `sendPasswordReset()` actually did internally.
- `app/(admin)/admin/{customers,sites,upload,reports,activity}/` — the
  five real admin pages, Spanish copy inline (§1.10). `/admin/upload` and
  `/admin/reports` proxy to `vrm_api` through new `app/api/admin/*` routes
  (mirroring the customer-facing ones, gated by `requireAdminForRoute()`
  instead of `requireCustomerForRoute()`, and — for `/admin/reports` only —
  actually allowed to set `schema: "monitoring"` / `actor: "admin"`).
- `components/app/JobProgress` — gained an `endpoint` prop (defaults to the
  customer proxy) so the same polling component serves both `/app/*` and
  `/admin/*` without a duplicate.
- `lib/uploadClient.ts` — moved here from
  `app/(portal)/app/upload/uploadClient.ts` (a plain function, no
  server-only concerns) so `AdminUploadManager.tsx` can reuse it instead of
  duplicating the raw signed-upload `XMLHttpRequest` call.

### Validating Step 7 locally

- `npm run typecheck && npx eslint . && npm run build` — all clean.
- `npm run test:scoping` — still 8/8 (must keep passing; unaffected by this
  step's changes).
- The three leak checks above, re-run after this step's build — all clean.
- `vrm_api`'s two Step 7 extensions (`GET /v1/sites`, the `schema`/`actor`
  params on `available-dates`) verified live against real `monitoring`
  data, including a full `POST /v1/reports` run
  (`schema: "monitoring", actor: "admin"`) that produced a real rendered
  PDF — see `vrm_api/README.md`.
- Auth mechanics (activate a throwaway account, click the same link twice,
  forgot-password, deactivate/reactivate) verified against the live
  Supabase project with a throwaway script (not committed — see the coder's
  report for the full transcript and results, including the real Resend
  account-config gap found while validating: `paulyco.com` is not yet a
  verified sending domain).

## Design-source-of-truth note

`victron-monitor/landing-page/` is **not** touched by this app and stays
the thing this design system is diffed against until cutover
(`PLAN_PHASE14.md` §6.2). If a component here and the same element on
`landing-page/landing_page.html` ever disagree, the landing page is right
and this app has drifted — not the other way around, until Step 2 replaces
it as the served marketing page.
