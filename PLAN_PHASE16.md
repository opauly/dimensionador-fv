# Phase 16 — VRM Monitor: customer self-service billing on ONVO Pay (public signup, subscription, payment method, billing address)

**Status:** All 14 open questions in §0.6 are now answered by Oscar (2026-08-19). Q7 (tax/factura
electrónica) is answered as **deliberately deferred** — a conscious risk acceptance for v1, revisit
before going live (§0.6 Q7), does not block test-mode work. Final tier pricing (Q1/Q13/Q14, resolved
together): **Single Report $9.99 one-time; Starter $29.99/mo or $299.99/yr; Growth $99.99/mo or
$999.99/yr; Fleet custom** — flat per-tier (not per-site, resolving the landing-page-vs-schema conflict
Q13 surfaced), USD only, both self-serve at signup. **Q6 reversed this plan's own non-goal** — Oscar
wants public self-serve signup, not invite-first — and that scope amendment is designed, not just
flagged: see §1.1 (where the public entry points live), §3.6/§3.7 (schema), §5.5 (the signup surface),
§6.6 (the new trust boundary), and §8 Step 5.5 (build + gate). **Step 0 is done (2026-08-20) — see
§0.2b.** `tools/onvo_probe.py` ran live against the test-mode account end to end; every `[V]` row in
§0.2 is now resolved, with two exceptions carrying a named workaround per Step 0's own gate: (1) **no
item/price-swap mechanism exists for upgrade/downgrade** — this contradicts §0.2's and §3.1's working
assumption ("change the item's `priceId`") and needs an architect decision (cancel + recreate, with or
without a manually-computed credit) before Step 3; (2) the `subscription.renewal.succeeded`/`.failed`
webhook payload shape is known with high confidence from ONVO's own OpenAPI schema but has not yet been
proven against a real byte-for-byte delivery (no API-triggerable "send test event" exists; Oscar's
webhook.site endpoint should capture one before Step 4's gate is considered met). Everything else Step
1 onward needs — exact request/response shapes, the closed `status` vocabularies for subscriptions and
invoices, minor-units confirmation, the card-replacement mechanism (fully resolved, simpler than every
candidate §0.2 listed), and confirmation that `Idempotency-Key` is not honored — is confirmed in §0.2b.
**Schema (Step 1) has not started; per Step 0's own gate, item 1 above should be resolved first.**
**Author:** architect agent, 2026-08-19 (signup scope amendment: same agent, same day, after Oscar's
answers)
**Builds on:** [`PLAN_PHASE14.md`](PLAN_PHASE14.md) (the Next.js app, `vrm_api`, the trust boundary,
the tenancy choke points, **and the invite/activation machinery this phase's signup flow reuses rather
than parallels**), [`PLAN_PHASE15.md`](PLAN_PHASE15.md) (§2 secret storage, §3 the three-control
tenancy model, §0.4 the naming rule, and the Step-0-spike-before-design discipline this plan copies
wholesale), `database/migrations/021_vrm_portal_auth.sql` (`plan`/`site_limit`/`account_type`/
`auth_email`), `victron-monitor/web/lib/plans.ts` (the plan vocabulary).
**Spec sources:** `docs.onvopay.com` — every external claim in §0.2 is marked **[C] confirmed by a
live fetch on 2026-08-19** or **[V] to verify at Step 0**. Nothing in this plan invents an endpoint
shape.
**Plan doc convention:** same shape as `PLAN_PHASE15.md` — confirmed context, resolved decisions with
their reasoning, then vertical build steps each ending in something runnable behind its own
validation gate.

---

## Goal

Someone who has never spoken to Oscar can find VRM Monitor's landing page, sign up, verify their
email, enter a card in ONVO's own form, and be a working customer minutes later. And a customer who is
already signed in can see what they are paying for, change it (upgrade / downgrade / cancel), keep the
card on file current, and keep their billing address accurate — without emailing Oscar. And
`vrm.customers.plan` / `vrm.customers.site_limit` stop being values a human types into
`/admin/customers` and become a **derived consequence of a real, paid, verified ONVO subscription**.

"Done" means two things:

1. **Signup:** a visitor submits `/signup`, receives a verification email, clicks it, sets a password,
   picks a plan, enters a card — and only at that point does the account become a real tenant. An
   abandoned signup (never verified, or verified but never paid) leaves **no usable account** and
   **no ONVO object of any kind**.
2. **Billing:** a customer opens `/app/billing`, picks a plan, enters a card in ONVO's own
   SDK-rendered form (their card number never touching our servers), and within seconds their `plan`
   and `site_limit` reflect the subscription — **because we re-read the subscription from ONVO**, not
   because the browser told us it worked. They can then downgrade, cancel at period end, resume,
   replace the card, and see their renewal history. If ONVO's webhook never arrives, or arrives twice,
   or arrives out of order, the customer's entitlement is still correct within one reconcile cycle.

**Four hard constraints, stated up front because they shape every decision below:**

1. **ONVO is the source of truth; our database is a cache; webhooks are cache-invalidation hints and
   nothing more.** ONVO documents no `subscription.created` / `.updated` / `.canceled` event, warns
   that events can arrive out of order, and states no retry policy for a failed delivery (§0.2). A
   design that *applies* event payloads would be wrong on day one. §4 is the answer.
2. **A card number, CVV, or raw PAN must never reach any server we operate.** The ONVO web SDK
   renders the card form; we hold only opaque ids. If Step 0 discovers any flow in which our server
   would receive raw card data, **stop and escalate** — do not build it (§6.3).
3. **A customer must only ever be able to touch their own subscription**, and the mechanism for that
   is the one Phase 15 already proved: **no ONVO object id is ever accepted from a request body**
   (§6.4 control 3).
4. **New in this amendment: a request with no session may never create anything of value.** The public
   signup surface can stage an intent and send one email. It cannot create a `vrm.customers` row, an
   ONVO customer, a subscription, a site, or a charge. Only possession of a single-use token emailed
   to the address being claimed moves the flow forward (§6.6).

---

## 0. Confirmed context (do not re-derive)

### 0.1 What already exists in this repo

| Fact | Where |
|---|---|
| `vrm.customers.plan text NOT NULL DEFAULT 'trial'` — free text, deliberately no CHECK ("pricing is marketing-owned and changes faster than a migration") | migration 012 L67, `lib/plans.ts` header |
| `vrm.customers.site_limit int` — `NULL` = unlimited; "Enforced in `vrm_portal/db.py`, not here — a hand-negotiated deal just needs this value changed, not a migration" | migration 021 L67–71 |
| `vrm.customers.account_type IN ('installer','owner')` — already gates which plans are offered | migration 021 L65–66 |
| The plan vocabulary (`trial`, `single_report`, `starter`, `growth`, `fleet`) and each one's site cap live in **TypeScript only**, `lib/plans.ts:PLANS`. There are **no prices anywhere in the codebase** — but there *are* prices on the landing page, see two rows down | `victron-monitor/web/lib/plans.ts` |
| `PLANS` already encodes who may buy what: `growth`/`fleet` are `installer`-only, `single_report` is `owner`-only, `starter` is both. The signup plan picker must respect this, and does — by reading `vrm.plans.account_types` (§3.1), not by re-deriving it | `lib/plans.ts` L25–31 |
| **`planSiteLimit()` fails *open*** — an unrecognized plan string returns `null`, which means **unlimited**. Anything that defaults a `site_limit` from a plan string must therefore never be handed a value it didn't validate. Signup does not use it at all (§5.5) | `lib/plans.ts` L47–49 |
| `site_limit` is enforced by `canAddSite()` against **active** sites only; deactivating a retired site frees a slot | `lib/server/db/sites.ts` L141–172 |
| `PROFILE_WHITELIST = ['name','contact_name','contact_email','country','ui_language']` — enforced twice (type level + a runtime key filter). `plan`/`site_limit`/`active` are deliberately absent | `lib/server/db/customers.ts` L22–60 |
| **This changes in this phase:** the only writer of `plan`/`site_limit` today is `lib/server/db/admin.ts:updateCustomer()`, reachable only from `/admin/*`. After Phase 16 there are **three** writers, and the split is deliberate: **(a)** admin (unchanged, human override), **(b)** `vrm_api/billing.py:apply_entitlements()` (§4.5, the money→entitlement path), **(c)** the signup verification handler, which **inserts** a brand-new row with `plan='trial'`, `site_limit=0`, `provisioning_state='pending_subscription'`, `site_limit_source='plan'` and then never touches those columns again (§5.5 step 2). Nothing else. `PROFILE_WHITELIST` is **not** widened — a customer still cannot edit their own plan | that file, plus §4.5 and §5.5 |
| `vrm_api` has exactly **one unauthenticated route**, `GET /health`; every router carries `dependencies=[Depends(require_pipeline_key)]`; **no CORS middleware is installed anywhere, deliberately**. **This phase adds zero public `vrm_api` routes** — signup is entirely a Next.js concern (§6.6) | `vrm_api/main.py` L9–26, L139–145 |
| Bearer comparison already uses `hmac.compare_digest`, never `==`, and explicitly refuses to treat an empty/unset key as "anything matches" | `vrm_api/deps.py` L23–50 |
| `vrm_api` reads env via `database/supabase_client.py`'s bare `load_dotenv()` → the **root `.env`**. It has no env file of its own. `PIPELINE_API_KEY`, `RESEND_API_KEY`, `VRM_ADMIN_TOKEN` all live there | PLAN_PHASE15.md §3.3, verified |
| Customer route handlers follow a fixed shape: `requireCustomerForRoute()` as the **first statement**, Zod-parse the body, `customer_id` injected from `session.customerId` and **never** from the body, re-run `assertOwnsSite()`/`canAddSite()` server-side, forward via `lib/server/pipeline.ts` | `app/api/vrm/connect/route.ts` (read it — it is the template) |
| `lib/server/pipeline.ts` handles **both** vrm_api error body shapes (flat `{code}` from a custom handler, nested `{detail:{code}}` from a plain `HTTPException`) and never lets a raw message reach the browser | that file L84–109 |
| Customer copy goes through `t(lang, key)` with paired `en`/`es` dicts; `FORCE_LANG = 'en'` currently short-circuits `t()` to English. New keys **still go in both dicts** | `lib/i18n/strings.ts` L595–618 |
| Portal nav is built in one place, `app/(portal)/app/layout.tsx` L15–20 | that file |
| `/app/profile` renders a compact **status card + link** for VRM connection rather than an inline flow — the precedent this phase copies for billing | `app/(portal)/app/profile/page.tsx` L76–93 |
| Latest applied migration is **024**. Next free number: **025** | `database/migrations/` |
| Phase 12 locked **GitHub Actions `cron:`** as this project's scheduling mechanism. There is still no scheduler in the repo | PHASES.md Phase 12; PLAN_PHASE15.md §0.1 |
| `scripts/test-scoping.ts` is the live-HTTP cross-tenant regression test (11 cases today, including a tamper case aimed straight at a running `vrm_api`) | that file |

**Facts specific to the signup amendment, read out of the code on 2026-08-19:**

| Fact | Where | Why it matters here |
|---|---|---|
| **The whole account-creation machinery already exists and is proven.** `generateLink({type:'invite'\|'recovery'\|'magiclink'})` → `properties.hashed_token` → `{SITE_URL}/activate?token_hash=…&type=…` → `renderActivationEmail()` → `sendEmail()` (Resend) → `stampInvited()` writes `auth_user_id`/`auth_email`/`invited_at`. `/activate` then runs `verifyOtp()` in a **Server Action** (a Server *Component* cannot set cookies), the visitor sets a password, `markActivated()` stamps `activated_at`, redirect to `/app` | `lib/server/invites.ts`, `app/(auth)/activate/{page,actions}.tsx` | **Signup reuses this end-to-end.** There is no second activation path, no second email template, no second password-set form. §5.5's only structural change to it is factoring `generateLink`-plus-fallback out of `sendInvite()` so the signup verify route can call it without sending a *second* email |
| `invites.ts` already handles the three-way "email already exists" ladder: another customer claims it → refuse; an unlinked auth user exists → link it via `type:'recovery'`; otherwise `type:'invite'` | `lib/server/invites.ts` L126–159 | Signup hits exactly these cases, from the internet, at volume. Reusing the ladder is the difference between a designed behaviour and a 500 |
| `sendPasswordReset()` is **already a public, unauthenticated entry point** and is written to be non-enumerating: it returns `void`, swallows Resend failures, and `/forgot`'s Server Action returns the identical `{submitted:true}` no matter what happened | `lib/server/invites.ts` L267–313, `app/(auth)/forgot/actions.ts` | The signup action copies this discipline verbatim. It is the house pattern for "a public form that touches accounts," and it already exists — signup is not the first such surface, only the first that *writes* |
| `/login`, `/forgot`, `/activate` live in the **`(auth)` route group** with a shared layout; the landing page lives in **`(marketing)`** (`app/(marketing)/page.tsx`, route group = still `/`) and renders its own `<Nav/>…<Footer/>` | `app/(auth)/*`, `app/(marketing)/page.tsx` | Decides where `/signup` goes (§1.1) |
| The landing page **already sells**: Starter "Up to 10 sites · **$14 / site / mo**", Growth "Up to 50 sites · **$9 / site / mo**", Fleet "**Custom** · Talk to us" (a `mailto:`), and a Single Report at "**$29 / report**", one-time | `components/marketing/Pricing/Pricing.tsx` | Q1 is not a blank page — but §3.1 models a **flat `amount_minor` per tier**, and §9 lists metered billing as a non-goal. See **Q13**. Also: Fleet's own CTA is already "Talk to us," which is the natural answer to "which tiers are self-serve" (**Q14**) |
| The landing page's `AccessForm` is a **`mailto:` composer**, not a server-backed form — nothing on the public site posts to us today | `components/marketing/AccessForm/AccessForm.tsx` | Signup is genuinely the first public write in this product's life. It also means `AccessForm` stays: it is the Fleet / single-report / "send me a sample" path, which is *not* self-serve |
| `vrm.customers.slug text NOT NULL UNIQUE CHECK (slug ~ '^[a-z0-9][a-z0-9-]*$')`, and it is the **permanent namespace of every `site_id`** (`<customer-slug>-<site-slug>`) — it cannot be changed after sites exist. `admin.ts:createCustomer()` does a bare `slugify(name)` with **no collision handling** | migration 012 L42–45, `lib/slug.ts`, `admin.ts` L119–142 | Fine when Oscar types the name and sees the duplicate-key error. **Not** fine when the internet types it. Signup needs deterministic collision suffixing (§5.5 step 2) |
| `vrm.customers` has a case-insensitive partial unique index on `lower(auth_email)` | migration 021 L92–93 | The database is the backstop for "two signups, same email" — but signup must not *surface* that as a distinguishable response (§6.6) |
| `resolveRole()` resolves a customer only if the row is **`active`**; an inactive customer is indistinguishable from an unlinked one. `getSessionContext()` re-derives on **every** request (no cached session state) | `lib/server/auth.ts` L77–158 | Directly constrains the pending-account design: a not-yet-paid signup **must** be `active = true` or they cannot reach the checkout page at all. The compensating controls are §5.5 step 2's `site_limit = 0` and §6.6's `requireCustomer()` gate |
| `login/actions.ts`'s own comment justifies its generic error copy partly with *"a portal with no public signup"* | `app/(auth)/login/actions.ts` L14 | **That comment becomes stale in this phase.** The behaviour stays correct (and matters *more* now); the justification needs rewriting. Listed as a concrete edit in Step 5.5 |
| **There is no rate-limiting infrastructure anywhere in this repo** — one grep hit, and it is a comment about *Supabase's* rate limit | grepped `victron-monitor/web` | Signup has to bring its own. And because the Next.js app is deployed serverless, an in-process counter is close to useless there — §6.6 uses the database instead |
| `sendEmail()` is a thin Resend client that throws `MailerError` and logs a rejection reason server-side only | `lib/server/resend.ts` | Signup's abuse budget is measured in **Resend sends**, not ONVO calls. That is what the rate limit is protecting |

### 0.2 ONVO Pay — what is actually verified, and what is not

Fetched live from `docs.onvopay.com` on **2026-08-19**. `[C]` = confirmed from the docs or the
brief's own verified payloads. `[V]` = **must be verified at Step 0 — do not build against a guess.**

| | Finding |
|---|---|
| [C] | **Base URL is `https://api.onvopay.com/v1`**, and the paths are **English**, not the Spanish doc slugs. Confirmed literals from the docs' own subscription guide: `POST /v1/products`, `POST /v1/prices`, `POST /v1/payment-methods`, `POST /v1/subscriptions`, `POST /v1/subscriptions/{id}/confirm`. This resolves the brief's `/v1/subscriptions` vs `/v1/cargos-recurrentes` question: **`/v1/subscriptions`**. The Spanish "Cargos recurrentes" is a docs label, not a path. |
| [C] | Auth is `Authorization: Bearer <key>`. Publishable (`onvo_{test,live}_publishable_key_…`, client-side) and secret (`onvo_{test,live}_secret_key_…`, server-side only) are separate key types; test and live are separate worlds distinguished by the key prefix. |
| [C] | The **subscription creation flow** documented by ONVO: create a Product → create a Price with `type: "recurring"` → create/collect a payment method → create a subscription with `customerId` + `priceId` (+ `paymentMethodId` to charge immediately) → listen for webhooks. |
| [C] | **`paymentBehavior: "allow_incomplete"`** lets you create the subscription **without** `paymentMethodId` and confirm the charge in a later request (`POST /v1/subscriptions/{id}/confirm`). This is the hook the client-side SDK flow hangs off, and it is why §5.2's design does not need our server to ever hold a card. (The brief's example payload also shows `paymentBehavior: "default_incomplete"` — **two different values appear in two ONVO sources; Step 0 must establish the real enum.**) |
| [C] | **The web SDK is a plain script tag, not an npm package**: `<script src="https://sdk.onvopay.com/sdk.js">`, then `onvo.pay({...}).render("#container")`. Verified parameter list: `publicKey`, `paymentIntentId` *or* `subscriptionId`, `paymentType: "one_time" \| "subscription"`, `customerId`, `manualSubmit` (bool, hides the SDK's own button), `locale` (`"es"`/`"en"`, defaults Spanish), `onSuccess(data)`, `onError(data)`. Verbatim sample from the docs: `const onvoInstance = onvo.pay({ onError, onSuccess, publicKey, paymentIntentId, paymentType: "one_time", manualSubmit: true }); onvoInstance.render("#container");` |
| [C] | The SDK is **resource-driven**: "lets you render a payment component on your site using a publishable key and **a resource created from your server**." It renders a card form, handles the card data internally, and does **not** appear to hand a `paymentMethodId` back to the merchant — `onSuccess(data)`'s exact shape is undocumented. Design consequence: our server creates the subscription first, hands the browser only an id, and learns the outcome by **re-reading from ONVO**, not from `onSuccess`. |
| [C] | The **Customers** resource documents: create, list, retrieve, update, delete, **list a customer's payment methods**, **list a customer's subscriptions**, list a customer's payment intents. That "list a customer's subscriptions" endpoint is the backbone of §4's reconciliation — it is how we discover a subscription we were never told about (there is no `subscription.created` event). |
| [C] | The **Payment Methods** resource documents: create, list, retrieve, update, **disconnect (DELETE)**, verify, retrieve-verification, validate-bank-account. |
| [C] | **Recurring Charges (= subscriptions)** documents: create, list, retrieve, update, cancel, confirm, and add/update/delete an **item** on an existing subscription. Upgrade/downgrade is therefore "change the item's `priceId`/`quantity`," not "cancel and re-create." |
| [C] | The subscription object carries **both** cancellation semantics natively: `cancelAtPeriodEnd` (graceful) and `cancelAt`/`canceledAt` (scheduled/immediate). We choose which to expose; we do not build cancellation logic. |
| [C] | It also carries `trialPeriodDays` / `trialStart` / `trialEnd`, `billingCycleAnchor`, `currentPeriodStart`/`End`, `status` (observed value: `"trialing"`), `mode` (`"test"`/`"live"`), `items[]` (`{id, priceId, quantity}`), `metadata` (free-form; the docs' own example uses `{orderId, plan}`), and an embedded `latestInvoice`. |
| [C] | **Renewals** (`Renovaciones`) is the invoice resource. The embedded `latestInvoice` shows `total`, `subTotal`, `originalTotal`, `currency`, `status`, `attemptCount`, `attempted`, `lastPaymentAttempt`, `nextPaymentAttempt`, `periodStart`/`End`, `paymentIntentId`, `invoiceAdditionalItems[]`. |
| [C] | Amounts appear to be in **minor units** (the example's `total: 2099` alongside `currency: "USD"`). Both `USD` and `CRC` appear in ONVO's own examples in different places. |
| [C] | **Webhooks are authenticated by a plain shared secret, not an HMAC payload signature**: header `X-Webhook-Secret: webhook_secret_…`, registered per-endpoint in the ONVO Dashboard's "Desarrolladores" section. |
| [C] | Documented event types: `payment-intent.succeeded`, `payment-intent.failed`, `payment-intent.deferred`, `subscription.renewal.succeeded`, `subscription.renewal.failed`, `checkout-session.succeeded`, `mobile-transfer.received`. **There is no `subscription.created`, `.updated`, or `.canceled` event.** The docs explicitly warn events can arrive **out of order**, and a non-2xx response is merely logged — **no retry policy is stated**. |
| [C] | The only sample webhook body is `{ "type": "...", "data": { "id", "accountId", "amount", "currency", "status" } }` — note it carries **no event id and no timestamp**, which is why §4.2 cannot dedupe or order by anything in the payload. |
| [C] | **This repo has no ONVO API integration of any kind today.** The `onvo_commission_pct`/`onvo_iva_pct` columns on `project_payments` and `DEFAULT_ONVO_COMMISSION = 0.024` in `config.py` are a **fee model** in the unrelated Streamlit Solar Design Tool — a percentage recorded against a manually-entered payment. There is no client, no key, no webhook, nothing to reuse. This is genuinely greenfield. |
| **[V]** | **The exact method + path + request/response body of every operation we will actually call.** The docs site renders its per-endpoint pages through an interactive API-explorer widget that plain HTML fetching does not fully capture — only the guide pages exposed literal paths. Confirmed-by-guide: `POST /v1/subscriptions`, `POST /v1/subscriptions/{id}/confirm`, `POST /v1/prices`, `POST /v1/products`, `POST /v1/payment-methods`. **Everything else (retrieve/update/cancel a subscription, the item sub-resource, customers CRUD, list-customer-subscriptions, list-customer-payment-methods, renewals) is an inference from resource naming and must be confirmed.** |
| **[V]** | **The full `status` vocabulary** for a subscription and for a renewal/invoice. We have seen exactly one value (`"trialing"`). Everything downstream — what counts as "entitled," what counts as "past due" — depends on knowing the real set. |
| **[V]** | **Proration on an item price change.** Does `PATCH`ing an item's `priceId` mid-period prorate automatically, and if so how is it surfaced (`invoiceAdditionalItems`? `originalTotal` vs `total`?), or is there a proration flag? **Measure it**, do not read about it. |
| **[V]** | **How a customer replaces the card on an existing subscription.** The SDK's documented parameters are `paymentIntentId` / `subscriptionId` — there is **no documented "setup mode"** that saves a card without charging, and `onSuccess` does not appear to return a `paymentMethodId`. This is the single largest unknown in the plan and it can change §5.3's UX entirely. Candidate answers to test: (a) the SDK renders against an existing `subscriptionId` and updating the card is a side effect of re-confirming; (b) a zero/low-amount payment intent is created as a setup proxy; (c) `POST /v1/payment-methods` accepts a token the SDK produces; (d) ONVO expects a Checkout Session for this. **Ask ONVO support directly.** |
| **[V]** | Whether `Idempotency-Key` (or any equivalent) is honored on `POST /v1/subscriptions`. Common on this class of API; **not documented here**. §5.4's duplicate guard is designed to work *without* it, and to use it if it exists. |
| **[V]** | The real payload of `subscription.renewal.succeeded` / `.failed` — only the generic `payment-intent.succeeded` shape was published. In particular: does it name the subscription, or only the invoice? |
| **[V]** | Tax/IVA. Does a Price's amount include Costa Rica's 13% IVA, is IVA added by ONVO (`total` vs `subTotal` hints at *something*), or is it entirely our problem? Related and bigger: whether a **factura electrónica** (Hacienda) is required for these subscriptions and whether ONVO issues it. See Q7. |
| **[V]** | Currency support per price, and whether one ONVO account can sell both `CRC` and `USD` prices. |
| **[V]** | Whether a subscription can be created against a customer with **no** payment method at all and left in a pending state indefinitely, and what `status` that shows as (this is what a failed first payment looks like, and the UI has to say something honest about it). |
| **[V]** | **New, and specific to the signup flow:** does `trialPeriodDays: 7` combined with a `paymentMethodId` supplied at creation time (Q2's answer — card required upfront) produce `status: "trialing"` **with no charge**, and does ONVO auto-charge at `trialEnd` without any further call from us? And what `status` does a subscription show if the card is declined at trial *end* rather than at creation? Step 0 must observe both, because §5.5's promotion rule (`provisioning_state → 'active'` on first entitled reconcile) and §7's signup failure rows depend on it. |

**Step 0 also has a non-technical half:** ask ONVO support for a **Postman collection or OpenAPI
export**, and for written confirmation on proration, idempotency, and the card-replacement flow. A
90-minute email exchange may save the entire probe. Do both in parallel; do not wait.

### 0.2b Step 0 findings (probed live against `ONVO_MODE=test`, 2026-08-20)

Run with `tools/onvo_probe.py` (committed) against Oscar's real test-mode account
(`ONVO_SECRET_KEY`/`ONVO_PUBLISHABLE_KEY` from the root `.env`). Every object created carries
`"Phase 16 Step 0 probe — safe to delete"` in its name/description/metadata and was left in place for
Oscar to inspect in the ONVO dashboard — nothing was deleted. Two independent sources were used and are
labelled per row: **live HTTP calls** (the probe script itself) and **ONVO's own OpenAPI document**
(`https://docs.onvopay.com/openapi.yaml` — a real, fetchable 3.1 spec; the *docs site* itself is a
client-rendered Docusaurus app that a plain `requests.get` cannot read, which is why the brief's own
guide-page scrape in §0.2 was incomplete, but the underlying spec file is plain YAML and answers nearly
everything §0.2 marked `[V]`).

**Two findings below contradict PLAN_PHASE16.md §0.2's working assumptions and need the architect's
eyes before Step 1/Step 3 proceed on them** — flagged inline as **CONTRADICTS §0.2** and summarized
once more at the end of this sub-section.

| # | Finding | Source |
|---|---|---|
| 1 | **Method+path for every operation, confirmed:** `POST /v1/customers` (create), `GET /v1/customers/{id}` (get), `GET /v1/customers` (list, cursor pagination — `limit`/`startingAfter`/`endingBefore`, response `{data:[...], meta:{total,limit,pages,cursorNext,cursorBefore}}`), **`POST /v1/customers/{id}` is the update call — `PUT`/`PATCH` both 404 with `"Cannot PUT/PATCH /v1/customers/{id}"`.** Same POST-to-id pattern confirmed for payment methods (`POST /v1/payment-methods/{id}`, not `PUT`/`PATCH`) and subscriptions (`POST /v1/subscriptions/{id}`, response is `201` even though it's an update). `POST /v1/products` (create). `POST /v1/prices` (create). `POST /v1/payment-methods` (create), `GET /v1/payment-methods` (list), `GET /v1/payment-methods/{id}` (get). **`POST /v1/payment-methods/{id}/detach` disconnects a payment method — §0.2's "disconnect (DELETE)" was wrong; it is a `POST`, not a `DELETE`.** `POST /v1/subscriptions` (create), `GET /v1/subscriptions/{id}` (get), `GET /v1/subscriptions` (list, filters: `customerId`, `status`, `email`, date-range, pagination), `DELETE /v1/subscriptions/{id}` (cancel immediately), `POST /v1/subscriptions/{id}/confirm` (confirm an `incomplete` subscription), `POST /v1/subscriptions/{id}/items` (add), `PATCH /v1/subscriptions/{id}/items/{itemId}` (update — this one genuinely is `PATCH`, not `POST`), `DELETE /v1/subscriptions/{id}/items/{itemId}` (delete). `GET /v1/customers/{id}/subscriptions`, `GET /v1/customers/{id}/payment-methods` — both confirmed to exist exactly as §0.2 hoped. `GET /v1/invoices` (list, filters: `subscriptionId`, `customerId`, `paymentIntentId`, `status`, `currency`, date/amount ranges, `expand`), `GET /v1/invoices/{id}` (get). | live + spec |
| 2 | **Exact request bodies that were guessed wrong in §0.2 and had to be found via live validation errors:** Price creation needs `unitAmount` (integer, minor units) + a **non-empty `recurring` object** — `{interval, intervalCount}` — not a flat `recurringInterval` field and not a bare `amount`. First live attempt (`amount`, `recurringInterval`) returned `400` naming exactly these two invalid properties. Payment method creation (`type: "card"`) needs `card: {number, expMonth, expYear, cvv, holderName}` + `billing: {address: {country}, name, phone}`; `customerId` is required for a card attached to a customer. Subscription creation needs `customerId`, `items: [{priceId, quantity}]`, optional `paymentMethodId`/`trialPeriodDays`/`paymentBehavior`/`description`/`metadata`. **Confirmed at Step 1 seeding (2026-08-20): price creation additionally REJECTS `description` outright** (`400 "property description should not exist"`) — a product accepts one, a price does not; `tools/seed_onvo_plans.py` hit this live and was fixed to stop sending it. **Confirmed at Step 3
(2026-08-20): customer creation similarly REJECTS `metadata` outright** (`400 "property metadata
should not exist"`) — the same class of surprise, third time now (price/`description`,
customer/`metadata`): ONVO's create endpoints are consistently stricter than their own documented
request shapes suggest fields exist as optional. **Pattern worth remembering for any future ONVO
endpoint work**: verify an optional-looking field against a real `400` before trusting it's accepted,
don't assume from the docs alone. `vrm_api/onvo.py:create_customer()` was fixed live. | live |
| 3 | **`paymentBehavior` enum resolved: `allow_incomplete` \| `default_incomplete`.** `default_incomplete` is the true default (omit the field entirely and ONVO reports `paymentBehavior: "default_incomplete"` back) — §0.2's "two different values in two sources" is resolved in favor of the spec's `default_incomplete`, not a bare `"default"`. | spec + live (every create response echoed `paymentBehavior` back) |
| 4 | **Subscription `status` vocabulary, complete and closed:** `active`, `past_due`, `canceled`, `unpaid`, `incomplete`, `incomplete_expired`, `trialing`. **Invoice/renewal `status` vocabulary, complete and closed:** `draft`, `open`, `paid`, `void`, `uncollectible`. Both are `enum`s in ONVO's own schema (not just examples) — §3.3's "no CHECK constraint, because we've only seen `trialing`" caution can be relaxed once §4.5's mapping table exists, but a CHECK is still not recommended (ONVO can add a value with no notice; the `raw jsonb` + no-CHECK design in §3.3 stays as designed, this just means the mapping table itself is now written with full confidence). | spec |
| 5 | **Amounts are minor units, confirmed by direct observation**: created a price with `unitAmount: 2999` and every downstream object (invoice `total`, payment intent `amount`) echoed `2999` for a $29.99 price. **Multiple currencies coexist on one account and even one product**: created a `USD` price and a `CRC` price on the *same* `productId` with no error. Full currency enum seen across Price/Invoice/Refund schemas: `USD, CRC, GTQ, NIO, PAB, PEN, MXN, COP, HNL`. Since Q1 settled on USD-only for v1, this is confirmatory, not blocking. | live + spec |
| 6 | **CONTRADICTS §0.2 — proration on an item price change: there is no such mechanism at all.** §0.2 assumed "Upgrade/downgrade is therefore 'change the item's `priceId`/`quantity`.'" This is false. Three separate live calls confirm it: `POST /v1/subscriptions/{id}` with `{"items":[{"priceId":...}]}` → `400 "property items should not exist"`; `PATCH /v1/subscriptions/{id}/items/{itemId}` with `{"priceId":...}` → `400 "property priceId should not exist"`; `POST /v1/subscriptions/{id}/items` (add) with `{"priceId":...}` → same rejection, and its accepted fields (`description`, `amount`, `currency`, `quantity` — confirmed by both the schema and a live 201) show this sub-resource is for **ad-hoc one-off "additional items" charged on the *next* invoice** (confirmed live: adding one attaches an `invoiceId` pointing at the upcoming, not-yet-collected invoice), a completely different concept from the subscription's own recurring `items[]`. **No documented or discoverable mechanism changes a subscription's `priceId` in place.** **Still-unknown, no live proration numbers exist to report** — the deliverable's "measure the actual before/after numbers" cannot be produced because there is nothing to measure yet. **Named workaround, until ONVO support confirms otherwise:** upgrade/downgrade must be implemented as **cancel the existing subscription + create a new one** at the new price. ONVO computes no automatic credit for an immediate `DELETE` cancel (confirmed: no refund/credit field appeared anywhere in the cancel response). The closest thing ONVO documents to proration is setting a future `cancelAt` date, which computes a **daily-cost-based partial final charge**, not a credit — confirmed present in the schema description, but its actual settlement wasn't observed live in this session (it only fires when the target date arrives, which was set 15 days out and not waited for). **This changes §3.1/§5.3's design and should go back to the architect before Step 3** — Q3's "upgrades immediate, prorated" now has no known ONVO-side mechanism to hang the proration math on; a manual proration credit (computed by us, applied via `POST /v1/refunds` if desired) or "no proration, just re-bill at the new price" are the live options, and that is a product decision, not a technical one. | live |
| 7 | **CONTRADICTS §0.2 — card replacement is fully resolved, and is simpler than every candidate answer §0.2 listed.** `POST /v1/payment-methods` accepts **either** the secret key **or the publishable key** (`security: [SecretApiKey, PublishableApiKey]` in the spec; confirmed live with a call authenticated by `ONVO_PUBLISHABLE_KEY` alone, no secret key involved) and returns a real payment-method `id` **directly in the response body** — there is no dependence on the SDK's undocumented `onSuccess(data)` shape at all; even if the SDK wraps this call, the raw endpoint's contract is exactly what a hand-rolled client-side form would need. Attaching the new id to an existing subscription is `POST /v1/subscriptions/{id}` with `{"paymentMethodId": "<new id>"}` — already a documented `UpdateSubscription` field, confirmed live end-to-end (created a PM with the publishable key, attached it to an active subscription, re-fetched, `paymentMethodId` matched). **This is candidate answer (c) from §0.2, confirmed as the actual mechanism** — no zero-amount setup intent, no Checkout Session, no separate "setup mode" needed. One open detail for Step 5's design (not Step 0's job to resolve): our backend must not blindly trust a client-supplied `paymentMethodId` per §6.4's no-id-from-request-body rule — it should re-read the payment method from ONVO (`GET /v1/payment-methods/{id}`) and confirm `customerId` matches the session's customer before attaching it, the same pattern §6.4 already uses elsewhere. | live |
| 8 | **`Idempotency-Key` is NOT honored on `POST /v1/subscriptions` — confirmed by a live duplicate-create test, with and without the header.** Fired twice with identical parameters and no special header: two distinct subscription ids created. Fired twice with identical parameters **and** an `Idempotency-Key` header carrying the *same* key both times: **still two distinct subscription ids** — no deduplication occurred. The string `idempot` does not appear anywhere in ONVO's OpenAPI spec (0 hits), confirming this isn't a documented-but-unobserved feature — it plausibly doesn't exist at all. **§5.4's duplicate guard must be entirely our own responsibility** (the partial unique index in §3.3, plus an application-level check-then-create with the guard §5.4 already designed) — do not add an `Idempotency-Key` header expecting it to help; it is inert. | live |
| 9 | **`subscription.renewal.succeeded`/`.failed` payload shapes, resolved from ONVO's own OpenAPI schema (`WebhookSucceedeSubscriptionResponse` / `WebhookErrorSubscriptionResponse`) — high confidence, but NOT captured from an actual live delivery in this session.** Succeeded: `{"type":"subscription.renewal.succeeded","data":{mode,status,currency,description,total,periodStart,periodEnd,subscriptionId,paymentIntentId,customerId}}` — **it does name the subscription** (`subscriptionId`), resolving §0.2's open question. Failed: `{"type":"subscription.renewal.failed","data":{accountId,subscriptionId,paymentIntentId,currency,invoiceStatus,subscriptionStatus,attemptCount,invoicePeriodStart,invoicePeriodEnd,periodStart,periodEnd,nextPaymentAttempt,lastPaymentAttempt,customer:{id,name,phone,email},error:{message,code,type}}}`. **Neither payload carries an event id or a timestamp field** — confirmed by reading every property in both schemas, not just the one sample body §0.2 saw; this closes §0.2's "confirm" ask. **Still-unknown / not captured live:** this probe found **no API endpoint to trigger a test webhook delivery on demand** — `/v1/webhooks*` does not appear anywhere in ONVO's OpenAPI spec (0 matches), so if a "send test event" button exists at all, it is dashboard-only and this script cannot reach it. **Named workaround (per the task brief, already in motion):** Oscar's temporary webhook.site endpoint stays registered in the ONVO dashboard; the actual byte-for-byte delivered payload should be captured manually once a real test-mode renewal fires (the probe's own trial subscriptions will hit `trialEnd` in 7 days, or a shorter-interval test subscription could be created for this specific purpose) before Step 4 is built. The schema-sourced shape above is strong enough to design §4's webhook receiver and `billing_events` schema against now; it is not yet proven byte-for-byte. | spec (payload shape) + live (webhook-trigger absence) |
| 10 | **Tax/IVA: confirmed technically absent from the API, supporting Q7's deferral.** Zero mentions of `tax`, `iva`, or `impuesto` (case-insensitive) anywhere in ONVO's ~333KB OpenAPI spec — no field on Price, Invoice, Subscription, or Refund that references tax in any way. ONVO neither computes, displays, nor breaks out a tax amount; `unitAmount`/`total`/`subTotal` are exactly what gets charged, no more, no less. This doesn't resolve the *legal* half of Q7 (factura electrónica / Hacienda compliance, which is an Oscar-facing question ONVO's API can't answer), but it confirms the *technical* half cleanly: whatever tax handling this product eventually needs, ONVO will not do any part of it automatically, and there is nothing hidden in a `total` vs `subTotal` split to account for (`subTotal`/`originalTotal`/`total` all matched the plain price amount in every live invoice observed). | spec |
| 11 | **Trial mechanics — mostly confirmed live, one part not directly observable in a single session.** `trialPeriodDays: 7` + a `paymentMethodId` supplied at creation → `status: "trialing"` immediately, **and the trial-period invoice is `total: 0`, `status: "paid"` instantly** (nothing charged). ONVO **pre-creates the next-period invoice** in `open` status, with the full plan amount already set (`total: 2999` for the $29.99 plan observed), `attemptCount: 0`, `attempted: false`, no `paymentIntentId` yet — strong evidence it auto-charges at `trialEnd` with no further call from us, but this session could not wait 7 real days to observe the actual charge attempt, so **this is still-unknown in the strictest sense.** **Named workaround:** treat "ONVO auto-charges at `trialEnd`" as the working assumption for §4.5/§7 (backed by the pre-created invoice evidence above), and confirm it for real either by asking ONVO support directly (already planned, per §0.2's non-technical half) or by revisiting one of this probe's own trialing subscriptions after 2026-08-27 and reading its resulting `status`. **What a first-payment decline looks like was fully confirmed live** (not deferred): a subscription created with ONVO's documented always-declining test card (`4000000000000002` — tokenizes fine, `status: "active"` at the payment-method level; the decline happens at charge time, not card creation) immediately shows `status: "incomplete"`, with `latestInvoice.status: "open"`, `attemptCount: 1`, `attempted: true`, and a `nextPaymentAttempt` roughly 24 hours later — this is what a signup with a bad card looks like, and it matches `incomplete`'s general meaning (subscription created, first charge failed, retry scheduled). **A subscription can be left in `incomplete` indefinitely with no payment method at all** (`paymentBehavior: allow_incomplete`, no `paymentMethodId`): created and re-fetched after a short delay, still `incomplete`, confirming it does not auto-expire on any short timescale; calling `POST /v1/subscriptions/{id}/confirm` with a `paymentMethodId` at any later point moves it straight to `active` with an immediate real charge. | live (all except the literal trial-end auto-charge event) |
| 12 | **`cancelAtPeriodEnd` "resume" — confirmed to work, resolving §0.2's named risk.** Setting `cancelAtPeriodEnd: true` via `POST /v1/subscriptions/{id}` and then, in a second call, setting `cancelAtPeriodEnd: false` **clears the pending cancellation** — confirmed live (`GET` after each call showed the flag flip both ways, subscription `status` unaffected). **Immediate cancel (`DELETE /v1/subscriptions/{id}`) works as expected**: `status` flips to `canceled` and `canceledAt` is stamped synchronously, in the same response. | live |

**Summary of the two findings that changed this plan's assumptions:** (a) **finding 6** — there is no
item/price-swap mechanism for upgrade/downgrade. **Resolved directly by Oscar, 2026-08-20, no architect
pass needed** — see Q3's updated answer above: cancel-and-restart, immediate for both directions, no
credit. §3.1's schema is unaffected (still one `vrm.plans` row per tier per interval); §5.3 is updated
in place. (b) **finding 9** — the webhook payload shape is now known with high confidence from ONVO's
own schema, but has not been proven against a byte-for-byte real delivery; Step 4 should still capture
one via Oscar's webhook.site endpoint before the receiver is considered done, per that endpoint's own
validation gate. Every other `[V]` row from §0.2 is resolved above. **Step 0's gate is met — every
`[V]` row is either resolved or has a named workaround. Step 1 can start.**

### 0.3 The naming rule (PLAN_PHASE15.md §0.4, extended)

- **`vrm_api/onvo.py`** — the authenticated HTTP client for **ONVO's** API. Transport only: it knows
  paths, headers, retries, and error mapping; it knows nothing about `vrm.customers`.
- **`vrm_api/billing.py`** — the domain layer: reconcile-from-ONVO, write the mirror, derive
  entitlements. This is where all the judgement lives.
- **`vrm_api/routers/billing.py`** — the customer-facing HTTP surface.
- **`victron-monitor/web/lib/server/signup.ts`** — the signup flow's domain layer: stage a request,
  mint and verify a token, create the customer row, hand off to the existing activation path. Sits
  beside `lib/server/invites.ts` and imports from it; it is **not** `lib/server/db/admin.ts`'s
  neighbour and must never import that file (§11).
- **`victron-monitor/web/lib/server/db/signup.ts`** — the narrow data layer for the above: the
  `vrm.signup_requests` CRUD and the one documented `vrm.customers` insert. Separate from
  `signup.ts` for the same reason `db/customers.ts` is separate from `invites.ts`: the file that
  writes tenant rows should be small enough to read in one sitting.
- **`victron-monitor/web/lib/server/ratelimit.ts`** — the database-backed counter §6.6 needs. Generic
  (`(bucket, key, windowSeconds, max) -> allowed`), so the webhook receiver (§6.5) can use the same
  thing instead of an in-process counter that a serverless deployment would silently reset.
- **Deliberately NOT in `victron/`.** That package is the shared library the Streamlit Solar Design
  Tool also imports; billing is VRM-Monitor-SaaS-only and must never become reachable from
  `app.py`/`pages/`. Putting it under `vrm_api/` is the enforcement, not a preference.
- **Prose rule:** the payment processor is always written "**ONVO**"; the Solar Design Tool's
  unrelated commission columns are always written "**`project_payments.onvo_commission_pct`**" in
  code font, so a future reader never conflates the two.

### 0.4 What this phase deliberately does NOT change

`victron/`, `pages/`, `app.py`, the `monitoring` schema, Node-RED, Apps Script, the report pipeline,
the CSV ingest path, and the VRM link/sync work from Phase 15. `git diff --stat` at the end must show
**zero** changes under `pages/` or `victron/`. If billing work starts wanting to touch either, the
design is wrong — come back to this file.

**Also unchanged, and worth stating because signup could tempt otherwise:** `resolveRole()`'s
resolution order, `getSessionContext()`'s re-derive-every-request behaviour, and the `/activate`
password-set flow. Signup **feeds** that machinery; it does not fork it.

### 0.5 The one decision that shapes everything else

**Read-through, not event-sourced.** Stated once here so no step re-litigates it:

> We never mutate billing state from a webhook payload. A webhook tells us *"something about this
> account may have changed"* — we then call ONVO with our own secret key and overwrite our mirror
> with whatever ONVO says. Every mutation we ourselves perform is likewise followed by a fresh read,
> never by inferring the result from the request we sent.

Three independent problems collapse into one solution with this choice:
1. **No `subscription.created`/`.updated`/`.canceled` events** → we never needed them; we re-read.
2. **Out-of-order delivery** → a payload's position in a sequence is irrelevant if we never apply it.
   The only ordering left is between two concurrent *reads*, resolved by a fetch-time comparison
   (§4.3), not by trusting a timestamp inside someone else's payload.
3. **A forged webhook** (the shared secret is static, the body unsigned, with no nonce or timestamp —
   §0.2) → the worst a forgery achieves is causing us to ask ONVO a question we already know the
   answer to. It cannot write state. This is a security property, not just an availability one, and
   it is the strongest single argument for this design.

The cost, recorded honestly: more outbound API calls than an event-sourced design, and a freshness
window between "ONVO changed" and "we noticed." §4.4 bounds that window.

**A fourth problem this same principle solves, discovered while designing signup:** "when does a
signup become a real account?" is *also* a read-through question. The answer is not "when the browser
said the card worked" and not "when we POSTed the subscription" — it is "when a reconcile we performed
observed an entitled subscription." That is why §5.5's promotion rule lives in `apply_entitlements()`
(§4.5 rule 8) and nowhere else.

### 0.6 Open questions for Oscar

**Q1–Q5 are the product decisions the architect is explicitly not guessing.** Q1 blocks Step 1
(nothing can be seeded), Q3–Q5 block Step 3/5, Q2 blocks Step 1's entitlement rules. **Q12–Q14 are
new, raised by the signup amendment**; Q13 additionally blocks Q1.

1. **Plan tiers, prices, currency, cadence.** How many sellable tiers, at what price, in **CRC or
   USD**, billed **monthly, annually, or both**? Note the schema (§3.1) supports all combinations —
   this question is about what to *seed and sell*, not what to build. Also: do `single_report`,
   `growth`, and `fleet` from `lib/plans.ts` all become sellable, or is v1 a narrower set with the
   rest staying hand-negotiated? **Blocks Step 1.**
   **Answered (2026-08-19):** **USD only** — drop `CRC` from `vrm.plans.currency`'s real value set for
   v1 (the column stays `text`, no CHECK, per §3.1's own reasoning; this just means only `USD` rows get
   seeded). **Both monthly and annual**, annual discounted ~16.7% ("2 months free"). **Fully resolved,
   final numbers** (also resolves Q13 in favor of option (a), flat per-tier pricing, and confirms Q14's
   tier selection):

   | Plan | Monthly | Annual | Sites | `self_serve` |
   |---|---|---|---|---|
   | Single Report | $9.99 one-time (not a `vrm.plans`/subscription row — a one-off purchase, §9 non-goal territory, unchanged flow) | — | 1 | n/a |
   | Starter | **$29.99** | **$299.99** (16.6% off the annualized monthly rate) | up to 10 | true |
   | Growth | **$99.99** | **$999.99** (16.7% off) | up to 50 | true |
   | Fleet | Custom | Custom | 50+ | false (`mailto:` CTA, unchanged) |

   Landing page (`components/marketing/Pricing/Pricing.tsx`) needs updating at Step 5/build time:
   Single Report's price changes from the currently-live $29 to $9.99, and Starter/Growth's copy
   changes from per-site pricing ("$14/site/mo", "$9/site/mo") to these flat numbers — this is the
   real-world resolution of Q13's "landing page sells per-site, schema sells flat" conflict. **No
   longer blocks Step 1.**
2. **Trial policy, and what happens to today's `plan = 'trial'`.** ONVO has native
   `trialPeriodDays`/`trialStart`/`trialEnd`. Do we want a trial, how long, and does it require a
   card up front? Separately: `vrm.customers.plan` already defaults to `'trial'` informally today,
   with no subscription behind it. Should that become the same mechanism (an ONVO subscription in
   `trialing` status), or stay a separate "not yet a paying customer" state that billing simply
   doesn't manage? *Architect's recommendation, not a decision:* keep them separate —
   `plan='trial'` stays the "no subscription exists" state, and an ONVO trial, if wanted, is a
   property of a real subscription. Conflating them means a customer with no billing relationship at
   all becomes indistinguishable from one whose trial is counting down.
   **Answered (2026-08-19):** **Yes, a trial — 7 days (`trialPeriodDays: 7`), card required upfront**
   (the subscription is created *with* a `paymentMethodId` from the start, not via the no-card
   `allow_incomplete` path — ONVO auto-charges when the trial ends, no separate "convert" action
   needed). Given Q6's answer below (self-serve signup), the architect's recommended separation still
   holds and is now the *natural* reading, not just a recommendation: every self-serve signup creates a
   real ONVO subscription in `trialing` status from minute one, so `plan='trial'` as "no subscription
   exists at all" becomes the state of a **legacy/hand-created customer, or a signup that hasn't paid
   yet** — worth a code comment at the entitlement writer (§4.5) saying exactly this, so the
   distinction doesn't get "simplified" away later. **Amendment note:** those two cases are told apart
   by `provisioning_state` (§3.6), not by `plan` — a legacy row is `'active'` with `plan='trial'`; an
   unfinished signup is `'pending_subscription'` with `plan='trial'` and `site_limit = 0`.
   **A second, welcome consequence of "card required upfront":** it very nearly eliminates trial abuse
   through disposable email addresses. A throwaway inbox alone gets a visitor nothing — the trial does
   not start until a real card is accepted by ONVO. That is why this plan does **not** propose a
   disposable-domain blocklist (§9), and why the residual risk (one person cycling trials on one card
   under many emails) is recorded in §10 as low-priority rather than raised as a question.
3. **Upgrade/downgrade proration.** Step 0 will *measure* what ONVO does. This question is what we
   *want*: immediate switch with proration, immediate switch with no proration (customer keeps the
   period they paid for and the new price starts next cycle), or upgrades immediate / downgrades
   deferred to period end? The last is the most common SaaS answer and the least surprising, but it
   is a product call. **Blocks Step 3.**
   **Superseded by Step 0 (2026-08-20):** §0.2b finding 6 established there is no ONVO-side mechanism
   to change a subscription's price in place at all — the original answer above (immediate prorated
   upgrade / deferred downgrade, assuming an in-place item swap) is no longer buildable as written.
   **Final answer, Oscar's explicit choice: option (a), simple cancel-and-restart, no manual proration
   credit.** Resolved to the simplest possible version of that: **both upgrades and downgrades take
   effect immediately** — cancel the existing subscription, create a new one at the new price, a fresh
   billing period starts now. No "pending downgrade, applies at period end" state, no scheduled job to
   execute it later — that asymmetry only made sense against the old in-place-swap mechanism, and
   keeping it under cancel-and-restart would mean tracking a deferred state machine for a $0 cost
   saving, which contradicts "simple." **This must be stated plainly in the change-plan UI copy** —
   "switching plans starts a new billing period immediately; there's no credit for unused time on your
   current plan" — precisely because it is a real, if small, customer cost with no ONVO mechanism to
   soften it. §5.3's `POST /v1/billing/subscription/change` becomes: cancel the current
   `onvo_subscription_id` (`DELETE /v1/subscriptions/{id}`, confirmed synchronous per §0.2b finding 12),
   create a new one at the target plan's `onvo_price_id`, reconcile. No refund call, no credit
   computation — §5.4's existing duplicate-guard logic (reconcile-before-create, the partial unique
   index, UI-level submit-disable) applies unchanged to this new subscription the same way it does to
   a first-time signup.
4. **Cancellation UX.** Offer graceful only (`cancelAtPeriodEnd` — access until the period they paid
   for ends), immediate only, or both? *Recommendation:* graceful only in v1, with immediate
   available to Oscar from `/admin` as a support action. A self-service "cancel and lose access now"
   button mostly generates refund requests. **Blocks Step 5.**
   **Answered (2026-08-19):** **Graceful only** — confirmed independently by Oscar ("if cancels
   customer can enjoy the rest of the active period"), matching the recommendation exactly. Immediate
   cancel stays admin-only, as designed.
5. **Downgrade/cancel when the customer is over the new `site_limit`.** Nothing in this codebase ever
   silently deletes a customer's sites, and this plan will not start. The real choice is: **(a)**
   block the downgrade until they deactivate enough sites, or **(b)** allow it, keep every existing
   site fully working, and block *adding* new ones until they are under the limit — with a plain
   banner saying so. *Recommendation: (b)*, because (a) makes us the obstacle to a customer trying to
   spend less money, which is a support ticket every time. `canAddSite()` already implements exactly
   the enforcement (b) needs, with no change. **Blocks Step 3 and Step 5.**
   **Answered (2026-08-19):** going with the recommendation — **(b)**.
6. **Who may subscribe.** Phase 14 has no public signup — customers are invited by Oscar. So billing
   attaches to an already-invited `vrm.customers` row. Confirm that stays true in v1 (i.e. no
   self-serve signup + pay flow). *Working assumption: yes, invite-first stays.*
   **Answered (2026-08-19) — REVERSED the working assumption:** Oscar wants **public self-serve signup
   from the landing page** — "anyone can subscribe from the landing page in a Sign Up form."
   **Designed (2026-08-19, same day):** this is no longer a flag, it is scope. The design is:
   - **Entry points:** `/signup` in the `(auth)` route group (sibling of `/login`, `/forgot`,
     `/activate`, inheriting their layout), reached from the landing page's `Pricing` CTAs and a new
     `Nav` button — §1.1.
   - **Email verification before anything exists.** The public action writes only a
     `vrm.signup_requests` staging row and sends one email. No `vrm.customers` row, no Supabase auth
     user, no ONVO object is created until a single-use token from that email is redeemed — §5.5.
   - **Sequencing:** local row **before** card, ONVO objects **after**; the account is only *promoted*
     to a real tenant when a reconcile observes an entitled subscription. The reasoning is in §5.5's
     "Why this order" and it follows directly from §0.5. An abandoned signup leaves a verified-email
     lead with `site_limit = 0` and no capability — never a phantom provisioned account, and never an
     orphan ONVO customer.
   - **Abuse defenses:** database-backed rate limiting (per email, per hashed IP, global), a honeypot
     field, Server-Action origin checking, and a CAPTCHA seam — §6.6. Whether to *enable* a CAPTCHA,
     and whose, is **Q12**.
   - **Which tiers are self-serve:** data-driven, via a new `vrm.plans.self_serve` column, so the
     answer is a seed value rather than a code change. Which rows get it is **Q14**.
   - **Reuse, not a parallel path:** `generateLink` → `/activate` → set password → `markActivated()`
     is the *existing* machinery and signup joins it mid-flow rather than reimplementing it. The one
     refactor is extracting `createOrLinkAuthUser()` out of `invites.ts:sendInvite()` — §5.5 step 2.
   §9 no longer lists self-serve signup as a non-goal; it lists what remains out of scope *within*
   signup. §6.4 and the new §6.6 state the new trust boundary. Step 5.5 builds it, behind its own gate.
7. **Tax / factura electrónica.** Does the price include CR's 13% IVA? And does a recurring SaaS
   subscription to a Costa Rican customer require an electronic invoice filed with Hacienda, and does
   ONVO produce it? **If it does not, that is a significant scope item that is not in this plan** and
   should be its own phase. Flagging it now rather than discovering it after the first live charge.
   **Answered (2026-08-19):** **deliberately deferred, not resolved** — Oscar's call: "let's not worry
   about IVA or factura electrónica for now." Recorded precisely because this is a conscious risk
   acceptance for v1, not an oversight: Costa Rican tax/invoicing compliance for a recurring SaaS
   subscription is unresolved, prices are **not** confirmed to include or exclude the 13% IVA, and no
   factura electrónica is issued. If Hacienda requires one and ONVO doesn't produce it automatically,
   that surfaces after the first live (non-test-mode) charge, not before — worth Oscar's own eyes
   before flipping `ONVO_MODE` to `live` in production (§0.6 Q9), even though it doesn't block Step 0
   or any test-mode work. Public signup keeps raising the stakes on this the longer it stays deferred:
   an invited customer who needs a factura can be handled by hand; a stranger who subscribes at 02:00
   and asks for one cannot.
8. **Delinquency policy.** When a renewal fails: how long a grace period before entitlement drops,
   and what actually degrades — only new-site creation, or report generation too? *Recommendation:*
   a grace window (propose 7 days) during which everything keeps working with a banner, then
   entitlement drops to `plan='trial'`-equivalent limits, and **never** data deletion.
   **Answered (2026-08-19):** going with the recommendation — **7-day grace window**, banner-only
   degradation, then drop to `trial`-equivalent limits, never delete data.
9. **Test vs live mode.** Confirm dev/staging points at `onvo_test_secret_key_…` and production at
   live. §3.1 puts `mode` on both `vrm.plans` and `vrm.subscriptions` so a dev row can never point at
   a live price, but the deployment split needs confirming. *Working assumption: `ONVO_MODE` env var,
   test locally, live in production only.*
   **Answered (2026-08-19):** going with the working assumption — **`ONVO_MODE` env var, test
   locally, live in production only.**
10. **Where ONVO's webhook should point.** *Recommendation and working assumption:* at the **Next.js
    app** (`/api/webhooks/onvo`), not directly at `vrm_api` on Render — §4.1 explains why. Confirm,
    because it determines what URL goes in the ONVO dashboard and which env holds the webhook secret.
    **Answered (2026-08-19):** going with the recommendation — **Next.js app**, `/api/webhooks/onvo`.
11. **Does Oscar need to be able to subscribe a customer on their behalf** (the billing analogue of
    Phase 15's admin fleet path)? *Recommendation:* **no card entry by Oscar, ever** — same liability
    reasoning as PLAN_PHASE15.md §0.5 Q6. Admin gets *view*, *refresh/reconcile*, and *cancel*; a
    customer's card is entered by the customer, in ONVO's own form.
    **Answered (2026-08-19):** going with the recommendation — **no card entry by Oscar, ever**;
    admin keeps view/refresh/cancel only. (With Q6's self-serve signup now in scope, this becomes even
    more clearly correct — there's no "Oscar onboards them" step left to attach a manual subscribe
    action to.)

---

**New questions raised by the signup amendment (2026-08-19):**

12. **CAPTCHA: yes or no, and whose?** `/signup` will be the first form in this product's life that
    anyone on the internet can POST to, and the thing it spends on each submission is a **Resend
    email** — a real cost and, more importantly, a sender-reputation asset that a spam flood can
    damage in a way money can't fix quickly.
    *Architect's recommendation:* build the **seam**, decide the **vendor** later. §6.6 specifies
    rate limiting + a honeypot + Server-Action origin checking as unconditional, and a single
    `verifyHumanChallenge(token)` function that is a no-op when `SIGNUP_CAPTCHA_PROVIDER` is unset.
    If Oscar wants one, **Cloudflare Turnstile** is the default suggestion — free at any volume this
    product will see, no per-call cost, privacy-preserving, one `<script>` plus one server-side verify
    POST, and removable without touching anything else. But this is a product/cost call, not an
    architecture one, and the plan deliberately does not lock it in.
    **Blocks nothing.** Step 5.5 ships with the seam and the provider unset; enabling it later is an
    env var plus one component. Answer whenever convenient.
13. **The landing page sells per-site pricing; the schema models flat per-tier pricing. Which is
    real?** `components/marketing/Pricing/Pricing.tsx` currently advertises Starter at
    **"$14 / site / mo, up to 10 sites"** and Growth at **"$9 / site / mo, up to 50 sites"**. §3.1's
    `vrm.plans` row holds **one `amount_minor` per (plan, interval, currency)** — a flat subscription
    price — and §9 lists usage-based/metered billing as an explicit non-goal.
    Until now that mismatch was invisible: Oscar quoted a number by hand. **Public signup makes the
    landing page's price and the checkout page's price the same promise, sixty seconds apart**, and if
    they disagree that is a chargeback conversation, not a copy bug.
    Three coherent resolutions, all of which the schema can express — this question is which one Oscar
    wants, not which one is buildable:
    - **(a) Flat tier pricing, marketing copy updated.** "Starter — up to 10 sites, $X/mo." One
      `vrm.plans` row per tier per interval. **No schema or code change from this plan.** Simplest,
      and the architect's lean.
    - **(b) Per-site pricing implemented as quantity.** ONVO's subscription `items[]` carries a
      `quantity` (§0.2 [C]), so "10 sites × $14" is expressible. But it makes the amount change every
      time a site is added or removed, which means a quantity-sync path, proration on every site
      change, and a customer-visible bill that moves — a materially larger phase, and it collides with
      §9's metered-billing non-goal.
    - **(c) Per-site *presentation*, flat *charge*.** Keep flat `vrm.plans` rows but display them as
      an implied per-site rate at the cap ("$140/mo — up to 10 sites, from $14/site"). Honest only if
      the copy is careful; cheap to do.
    **Blocks Q1** (there is no "price per tier" to answer until this is settled) **and therefore
    Step 1's seed data.** Does not block Step 0.
    **Answered (2026-08-19):** **(a), flat tier pricing** — see Q1's table for final numbers. Landing
    page copy update ("$X/site/mo" → flat "$X/mo") is now a concrete Step 5 task, not just a
    consequence noted here.
14. **Which tiers are selectable at signup, and which stay hand-negotiated?** Mechanically this is
    already solved and data-driven: §3.1 adds `vrm.plans.self_serve boolean`, and the public plan list
    (§5.5) selects `WHERE active AND self_serve AND mode = <ONVO_MODE> AND account_types @> …`. So the
    answer is a seed value Oscar can flip later without a deploy — the signup flow accommodates
    whatever tier list Q1/Q13 eventually produce, including zero self-serve tiers.
    *Architect's recommendation, drawn from the landing page's own copy rather than invented:*
    - `starter`, `growth` → `self_serve = true` (the page already has "Get started" buttons on both).
    - `fleet` → `self_serve = false` (the page already says **"Custom · Talk to us"** with a `mailto:`
      — Fleet is a conversation, and its `site_limit` is `NULL`/unlimited, which is not something to
      hand out on a form).
    - `single_report` → **no `vrm.plans` row at all in v1.** It is a **one-off $29 purchase**, not a
      subscription, and one-off payments / Checkout Sessions are an explicit non-goal of this phase
      (§9). The landing page's "Get a report" CTA keeps going to `AccessForm`.
    Confirm these three. **Blocks Step 1's seed only** (and trivially — it is three boolean values).
    **Answered (2026-08-19):** confirmed as recommended — `starter`/`growth` self-serve, `fleet`
    contact-only, `single_report` no `vrm.plans` row (now $9.99, see Q1).

**Every step below is blocked on Step 0. Step 0 is blocked only on a test-mode ONVO account + secret
key from Oscar.**

---

## 1. Information architecture: where signup and billing live

### 1.1 The public entry points (new)

**Decision: `/signup` lives in the `(auth)` route group, not `(marketing)`, and there is no separate
checkout page — a new customer lands on `/app/billing` itself.**

Three sub-decisions, each with its reason:

- **`app/(auth)/signup/page.tsx` → `/signup`.** Signup is an account-creation flow, a sibling of
  `/login`, `/forgot`, and `/activate`, and it inherits `(auth)`'s existing centered-card layout and
  English-only convention (`login/actions.ts`'s `const LANG = 'en'` — the visitor's language
  preference is unknowable before their row exists). Putting it in `(marketing)` would mean either
  re-rendering `<Nav/>`/`<Footer/>` by hand or inventing a marketing layout that doesn't exist today.
- **The landing page links *to* it, and keeps `AccessForm`.** `components/marketing/Pricing/Pricing.tsx`'s
  "Get started" buttons change from `href="#cta"` to `href="/signup?plan=<vrm.plans.id>"`, and
  `Nav` gains a "Sign up" action next to the existing sign-in link. `AccessForm` **stays exactly as
  it is** — it is now the *non*-self-serve path (Fleet, single reports, "send me a sample"), which is
  precisely what Q14 says those are. Deleting it would remove the only route for the two tiers that
  are deliberately not self-serve.
- **`app/(auth)/signup/verify/route.ts` → `GET /signup/verify?token=…`.** A **Route Handler**, not a
  page: it is clicked from an email, it must consume a token exactly once, and it ends in a redirect.
  Route Handlers can set cookies and redirect; Server Components cannot set cookies
  (`activate/actions.ts`'s header documents this exact constraint).
- **No separate checkout page. `/app/billing` is the checkout page.** A newly-activated customer is
  redirected to `/app/billing?plan=…`, where a first-run variant of the same `BillingManager` renders
  a plan picker and the ONVO SDK. Reason, and it is the important one: **card entry should exist in
  exactly one place in this codebase.** A dedicated `/signup/checkout` would be a second surface that
  mounts the ONVO SDK, a second call site of `POST /api/billing/subscribe`, and a second thing to keep
  correct when Step 0's card-replacement finding lands. The first-run difference is a prop
  (`firstRun`) that hides cancel/invoices/address-edit and changes the heading copy — not a page.

**Route inventory after this phase** (the complete list of routes reachable with **no session**, which
is the list §6.6 polices):

| Route | Auth | What it does |
|---|---|---|
| `/` (marketing), `/styleguide`, `robots`, `sitemap` | none | static, unchanged |
| `/login`, `/forgot`, `/activate` | none | unchanged |
| **`/signup`** (page + its Server Action) | **none** | stages a signup request, sends one email. Writes only `vrm.signup_requests` |
| **`/signup/verify`** | **token** | redeems a single-use token; creates the `vrm.customers` row; redirects into `/activate` |
| `/api/webhooks/onvo` | shared secret | §4.1, machine-to-machine |

Anything not on that list requires a session. Adding a row to it requires editing this table and §6.6.

### 1.2 Where billing lives (unchanged from the original plan)

**Decision: a new top-level page, `/app/billing`, plus a compact status card on `/app/profile`.**

The `/app/profile` VRM-connection card (`profile/page.tsx` L76–93) is the precedent and it is the
right one — but it is the *card*, not the whole flow. Billing has four distinct surfaces (plan
picker, third-party-rendered card form, billing address form, renewal history) and one of them is an
embedded iframe from another origin. Inlining that into a settings page that also changes your
display name is how you get a page where nobody is sure what "Save" saves.

- **`/app/billing`** — a nav item in `app/(portal)/app/layout.tsx`, not only a link from Profile.
  Reason: hiding cancellation two clicks deep inside "Profile" is both a usability problem and a
  consumer-protection smell. Billing is a top-level customer concern. **Also the first-run checkout
  surface**, per §1.1.
- **`/app/profile`** — gains a card in the same shape as the VRM one: current plan, next renewal
  date or "canceling on <date>", and a **Manage billing** button pointing at `/app/billing`. The
  existing read-only `profile_plan` row stays, now sourced from the same status object.
- **`/admin/customers`** — gains a billing column and per-customer actions (§7), plus a
  pending-signups filter (Step 6).
- **Nothing about billing or signup appears in `pages/06_vrm_monitor.py`.** The Streamlit operator
  tool never learns ONVO exists (§0.3).

---

## 2. Reading order for the coder

Before writing anything: `PLAN_PHASE15.md` §2–§3 (the security and tenancy model this inherits),
`vrm_api/routers/vrm_link.py` (the structural template for a router that talks to a third party on a
customer's behalf), `app/api/vrm/connect/route.ts` (the route-handler template), `vrm_api/deps.py`
(why comparison is constant-time and why an empty secret must fail closed), and — per
`victron-monitor/web/AGENTS.md` — **`node_modules/next/dist/docs/`** for anything Next.js-shaped,
because this repo's Next.js version has breaking changes relative to training data.

**Before Step 5.5 specifically, read these five files in this order** — the signup flow is 80% reuse
and you cannot see that without them:

1. `lib/server/invites.ts` — the whole invite lifecycle, including the "email already exists" ladder
   signup inherits and the non-enumeration discipline in `sendPasswordReset()`.
2. `app/(auth)/activate/page.tsx` + `actions.ts` — why `verifyOtp` runs in a Server Action, why the
   token is passed as a **bound action** and never as a client prop, and where signup joins this flow.
3. `app/(auth)/forgot/actions.ts` — the house pattern for a public, unauthenticated, non-enumerating
   form action. Signup's action is this shape.
4. `lib/server/auth.ts` — `resolveRole()`'s `active` requirement and `getSessionContext()`'s
   re-derive-every-request behaviour, both of which constrain the pending-account design.
5. `lib/server/db/admin.ts` — read its header, then **do not import it from signup code** (§11).

---

## 3. Schema — migration 025

Six new tables, five new columns, one comment correction. All in the `vrm` schema (already exposed
to PostgREST). Idempotent, same house style as migration 024, with a header that records the
reasoning rather than just the DDL.

### 3.1 `vrm.plans` — the sellable catalogue, and the join to ONVO

The one place our plan vocabulary meets an ONVO `priceId`.

```
id                uuid pk
plan_key          text not null          -- 'starter' | 'growth' | ... — matches lib/plans.ts:PlanKey. No CHECK (same reasoning as customers.plan)
billing_interval  text not null          -- 'month' | 'year'  (CHECK — this one IS a closed set)
currency          text not null          -- 'CRC' | 'USD'
amount_minor      bigint not null        -- minor units, matching ONVO's own convention ([V] confirm at Step 0)
mode              text not null          -- 'test' | 'live'   (CHECK)
onvo_product_id   text not null
onvo_price_id     text not null
site_limit        int                    -- NULL = unlimited, same convention as vrm.customers.site_limit
account_types     text[] not null        -- which vrm.customers.account_type may buy this
self_serve        boolean not null default false   -- NEW: may a stranger buy this from /signup?
active            boolean not null default true
sort_order        int not null default 0
created_at        timestamptz not null default now()
```

- `UNIQUE (onvo_price_id)`; partial `UNIQUE (plan_key, billing_interval, currency, mode) WHERE active`.
- **Why a table and not a constant in `lib/plans.ts`:** an ONVO `priceId` differs between test and
  live mode, prices change over time, and **a customer already subscribed to a retired price must
  keep it** — their `vrm.subscriptions` row points at an `onvo_price_id` whose `vrm.plans` row is
  `active = false`, and that must still render a correct label and site limit. A TS constant cannot
  express "retired but still honored."
- **`site_limit` lives here, and `lib/plans.ts` keeps labels/marketing.** This is a deliberate split
  of a value that currently exists in two places already (`PLANS[x].sites` and
  `vrm.customers.site_limit`). The rule going forward: **`vrm.plans.site_limit` is what a paid
  subscription *grants*; `vrm.customers.site_limit` is what is *enforced*;** the entitlement writer
  (§4.5) is the only thing that copies one to the other. `lib/plans.ts:planSiteLimit()` becomes
  display-only and its docstring must say so — **especially** given §0.1's note that it fails *open*
  (unknown plan → `null` → unlimited).
- **`self_serve` defaults to `false`, not `true`.** This is the fail-closed direction: a plan row
  seeded by a future migration, or hand-inserted during a support call, is **not** on the public
  signup form unless someone deliberately said so. It also means the public plan list is empty until
  Q14 is answered, which is the correct behaviour for "we haven't decided what to sell yet."
- **`self_serve` is enforced server-side, in the query, twice** — once when rendering the public plan
  list (§5.5) and again in `POST /v1/billing/subscription` when the subscriber's
  `provisioning_state = 'pending_subscription'`. A first subscription must be to a self-serve plan;
  an *existing* customer changing plans is not restricted by it (Oscar can put someone on Fleet by
  hand and they can still manage it).

### 3.2 `vrm.billing_customers` — one row per customer that has ever touched billing

```
customer_id               uuid pk references vrm.customers(id) on delete cascade
onvo_customer_id          text not null unique
mode                      text not null                 -- 'test' | 'live'
billing_name              text
billing_email             text
billing_address           jsonb not null default '{}'   -- mirrors ONVO's {city,country,line1,line2,postalCode,state}
default_payment_method_id text
pm_brand                  text            -- display-only mirror, e.g. 'visa'
pm_last4                  text
pm_exp_month              int
pm_exp_year               int
last_synced_at            timestamptz
created_at / updated_at   timestamptz not null default now()
```

- `billing_address` as `jsonb` rather than six columns: it is ONVO's shape, we mirror it verbatim,
  and if they add a field we do not need a migration. It is displayed and round-tripped, never
  computed on.
- **`billing_email` is separate from both `auth_email` and `contact_email`** — migration 021 already
  established that a customer's login and their report recipient are not the same person; the address
  that receives a receipt is a third. Do not reuse either. (For a self-serve signup all three start
  out as the same string. They are still three columns; the flow copies, it does not alias.)

### 3.3 `vrm.subscriptions` — the mirror

```
id                     uuid pk
customer_id            uuid not null references vrm.customers(id)
onvo_subscription_id   text not null unique
mode                   text not null
plan_key               text                    -- resolved from onvo_price_id via vrm.plans; NULL if unrecognized (do not fail the sync)
onvo_price_id          text
billing_interval       text
currency               text
amount_minor           bigint
status                 text not null           -- ONVO's RAW status string. NO CHECK constraint — see below
cancel_at_period_end   boolean not null default false
cancel_at              timestamptz
canceled_at            timestamptz
current_period_start   timestamptz
current_period_end     timestamptz
trial_start            timestamptz
trial_end              timestamptz
latest_invoice_id      text
latest_invoice_status  text
raw                    jsonb not null default '{}'   -- the last full payload as ONVO returned it
last_synced_at         timestamptz not null
created_at / updated_at
```

- **`status` has no CHECK constraint, on purpose.** We have confirmed exactly one value (`trialing`).
  A CHECK built on a guessed vocabulary turns "ONVO introduced a status we hadn't seen" into a failed
  sync and a customer stuck in a stale state — the worst possible failure for a billing mirror. The
  entitlement mapping (§4.5) lives in code, in one function, where an unknown value can be handled
  loudly and safely instead of fatally.
- **`raw jsonb` is not laziness.** We are integrating against an API whose full response shape we do
  not know. Keeping the last payload verbatim is what makes a production support question answerable
  without adding a column and waiting for the next renewal.
- Partial `UNIQUE (customer_id) WHERE status IN (<entitled-or-pending set>)` — **the exact set comes
  from Step 0.** This index is the database's own guarantee that one customer cannot end up with two
  live subscriptions, backing up §5.4's application-level guard. If Step 0's status vocabulary makes
  this impractical, fall back to `UNIQUE (customer_id) WHERE canceled_at IS NULL` and say so here.

### 3.4 `vrm.subscription_invoices` — mirrored renewals

```
id, customer_id, subscription_id (fk), onvo_invoice_id text unique,
status, currency, total_minor, subtotal_minor, original_total_minor,
period_start, period_end, attempt_count, last_payment_attempt, next_payment_attempt,
payment_intent_id, raw jsonb, created_at, last_synced_at
```

Read-only from the customer's perspective. Populated by reconcile, never by a webhook payload.

### 3.5 `vrm.billing_events` — append-only receipt log

```
id uuid pk, received_at timestamptz not null default now(),
event_type text, payload jsonb not null,
secret_ok boolean not null,
customer_id uuid, subscription_id text,      -- resolved during processing, both nullable
status text not null default 'received',     -- 'received' | 'applied' | 'ignored' | 'error'
processed_at timestamptz, error text
```

- **Every** webhook that arrives gets a row, **including ones that fail the secret check**
  (`secret_ok = false`, payload retained) — that is the only way an attempted forgery is visible at
  all. Cap/prune these separately so a flood cannot fill the table (§6.5).
- No unique constraint on anything from the payload: **ONVO's webhook body carries no event id and
  no timestamp** (§0.2), so there is nothing to dedupe on. Duplicate delivery is harmless under
  read-through (it causes a redundant reconcile), which is the point.
- This table is also where §4.4's sweeper finds work: rows in `error` get retried.

### 3.6 Columns added to existing tables

- `vrm.customers.site_limit_source text NOT NULL DEFAULT 'manual' CHECK (site_limit_source IN ('manual','plan'))`.
  **This exists to stop a real bug**: migration 021 explicitly supports a hand-negotiated
  `site_limit`, and the moment §4.5's entitlement writer starts running, the next reconcile would
  silently overwrite that negotiated value with the plan's default. `'manual'` (the default, so every
  existing row is protected by the migration itself) means "the entitlement writer must not touch
  `site_limit` for this customer." `'plan'` is set when a customer subscribes through the portal —
  **and is set at row-creation time for every self-serve signup** (§5.5 step 2). That last part is
  load-bearing and easy to miss: a signup row created with the `'manual'` default would have its
  `site_limit` frozen at `0` forever, because the entitlement writer would politely refuse to raise
  it. The Step 5.5 gate tests exactly this.
- `vrm.customers.billing_status text` — a small, *derived*, denormalized cache of the entitlement
  decision (`'none' | 'trialing' | 'active' | 'past_due' | 'canceled'` — final vocabulary after
  Step 0), written only by §4.5. Exists so `/admin/customers` and the portal banner can render
  without joining and re-deriving. It is a cache of a cache; `vrm.subscriptions` remains the mirror.
- **`vrm.customers.provisioning_state text NOT NULL DEFAULT 'active' CHECK (provisioning_state IN ('pending_subscription','active'))`** — **new, for signup.**
  - `'active'` = a real tenant. **The default, so every existing row and every admin-created row is
    unaffected by this migration** — the same protective-default trick `site_limit_source` uses.
  - `'pending_subscription'` = an email-verified signup that has not yet produced an entitled
    subscription. Can sign in (it must — see §0.1's note that `resolveRole()` requires `active`), but
    `requireCustomer()` sends it straight to `/app/billing` and its `site_limit` is `0`.
  - **Written by exactly two things:** the signup verify handler (sets it), and
    `apply_entitlements()` (clears it — §4.5 rule 8). Plus one admin escape hatch (Step 6) for the
    support case "their card works, ONVO says trialing, but the promotion didn't happen."
  - **Why a separate column and not `billing_status`:** §3.6 defines `billing_status` as a derived
    cache owned solely by the entitlement writer. Overloading it with an account-lifecycle state
    would give it two owners and two meanings, which is how a cache becomes a source of truth by
    accident. And **not** `plan`: `plan` is customer-facing free text that feeds `planLabel()`;
    inventing a `'pending'` plan value would render as literal "pending" in the UI and would make
    `planSiteLimit()`'s fail-open behaviour (unknown plan → unlimited) reachable.
  - **Why not `active = false`:** because `resolveRole()` treats an inactive customer exactly like an
    unlinked one — no session at all. A pending customer who cannot sign in cannot reach the page
    where they would pay us. `active` keeps its existing meaning ("Oscar revoked this account").
- **`vrm.customers.origin text NOT NULL DEFAULT 'admin' CHECK (origin IN ('admin','self_serve'))`** —
  **new.** Cheap, permanent, and answers two questions nothing else can: "did a human vet this
  account?" and "which of these abandoned rows came in off the street?" Used by `/admin/customers`'
  filter (Step 6) and by any future decision about pruning. Never used in an authorization decision.
- `COMMENT ON COLUMN vrm.customers.plan` — restate that it is still free text, that it is now
  **written by `vrm_api/billing.py`'s entitlement writer for customers with `site_limit_source =
  'plan'`**, that admin override remains legitimate, and that `plan='trial'` now means one of two
  things distinguished by `provisioning_state`: a legacy hand-created customer (`'active'`), or a
  signup that never paid (`'pending_subscription'`).

### 3.7 `vrm.signup_requests` — the staging table for unverified signups (new)

The single most important structural decision in the signup design: **an unverified signup does not
touch `vrm.customers` at all.** It lives here until a token proves the email address is real.

```
id             uuid pk
email          text not null              -- stored lowercased; see the index note below
token_hash     text not null unique       -- sha256 of a 32-byte random token. The token itself is NEVER stored
name           text not null              -- company or personal name, as typed; the slug is derived at redemption, not here
account_type   text not null              -- CHECK ('installer','owner')
plan_id        uuid                       -- references vrm.plans(id); nullable — a UI preselect only, re-validated at subscribe time
ui_language    text not null default 'en' -- CHECK ('en','es')
ip_hash        text                       -- sha256(ip + SIGNUP_IP_SALT). Never the raw IP — see below
user_agent     text                       -- truncated to 200 chars, diagnostics only
created_at     timestamptz not null default now()
expires_at     timestamptz not null       -- created_at + 24h
consumed_at    timestamptz                -- set exactly once, atomically, at redemption
customer_id    uuid                       -- the row this became, once redeemed. Nullable. Diagnostics + support
```

- Index on `lower(email)` and on `created_at` (both are rate-limit lookups), and on `token_hash`
  (unique, the redemption lookup).
- **`token_hash`, never the token.** Same reasoning Supabase's own `hashed_token` uses, and the same
  reasoning this repo already applies to Vault-stored VRM tokens in a different direction: a database
  dump must not be a set of working account-creation links. The token exists only in the email and in
  the URL the customer clicks.
- **`ip_hash`, never the raw IP.** These are addresses of people who are *not* customers and may
  never become customers — many of them will be bots, and some will be people who typed their email
  and changed their mind. A salted hash is enough to rate-limit and enough for abuse forensics, and
  it is not a log of who visited. `SIGNUP_IP_SALT` is a server-side secret (§6.1); rotating it
  resets the rate-limit history, which is acceptable and worth a comment.
- **Not a queue, not an audit log.** Prune aggressively (Step 7's cron): unconsumed rows past
  `expires_at + 7 days`, consumed rows past `consumed_at + 30 days`. The `customer_id` link is what
  makes the 30-day retention useful ("how did this account get created?") and 30 days is enough for
  that question to be asked.
- **This table is the rate-limit substrate too** — see §6.6. Counting rows in a window is a real,
  durable rate limit on a serverless deployment, which an in-process counter is not.

### 3.8 `vrm.rate_limits` — a generic, durable counter (new, small)

```
bucket      text not null       -- 'signup_email' | 'signup_ip' | 'signup_global' | 'onvo_webhook' | ...
key         text not null       -- the hashed/normalized subject; '' for a global bucket
window_start timestamptz not null
count       int not null default 0
primary key (bucket, key, window_start)
```

- Incremented with a single upsert (`ON CONFLICT … DO UPDATE SET count = vrm.rate_limits.count + 1
  RETURNING count`), so the check and the increment are one atomic round trip and two concurrent
  requests cannot both see "count = max - 1".
- `window_start` is the timestamp truncated to the window (a fixed window, not a sliding one).
  Deliberately the simple algorithm: a fixed window lets 2× the limit through at a window boundary in
  the worst case, and at this product's scale that is completely fine. Do not build a token bucket.
- Pruned by the same Step 7 cron that prunes `vrm.signup_requests`.
- **Also retrofits §6.5's webhook rate limit**, replacing the "simple in-process counter" that section
  originally proposed — which would have been near-useless on a serverless Next.js deployment where
  each invocation may be a fresh process. Same table, different `bucket`.

### 3.9 What migration 025 must NOT do

No RLS policies (`anon`/`authenticated` still hold zero grants on `vrm` — nothing to police; and note
that **`vrm.signup_requests` is written by the service-role key from server-only code, never by
`anon`** — the public signup route is public at the *HTTP* layer, not at the *database* layer). No
`SECURITY DEFINER` functions: **nothing in this phase stores a credential**, so migration 024's Vault
machinery is deliberately not extended here (§6.2 argues why ONVO object ids are not credentials, and
§6.6 argues the same for a hashed, single-use, 24-hour signup token). No CHECK on `status`/`plan_key`.
No backfill that invents a subscription for an existing customer. **No change to any existing row's
`provisioning_state`, `origin`, or `site_limit_source`** — all three defaults are chosen so that
`ALTER TABLE … ADD COLUMN … DEFAULT` is the entire migration and every existing customer keeps
behaving exactly as they do today.

---

## 4. Reconciliation — the source-of-truth strategy

This section is the answer to the brief's hardest question. §0.5 states the principle; this is the
mechanism.

### 4.1 Where the webhook lands, and why

**Recommendation: ONVO → `POST https://<the Next.js app>/api/webhooks/onvo` → `vrm_api`.**

The alternative — pointing ONVO straight at `vrm_api` on Render — is fewer hops, and it is defensible.
It is rejected because `vrm_api`'s entire security posture is *"one caller, one bearer key, exactly
one public route (`/health`), no CORS middleware installed at all."* That invariant is written into
`vrm_api/main.py`'s own header and is unusually well-kept. Adding a second internet-facing route
authenticated by a different mechanism erodes it permanently, and the erosion is invisible in a diff
six months later. The Next.js app is *already* public, already handles untrusted requests, and
already has the forwarding pattern. (The signup amendment strengthens this argument rather than
weakening it: the public surface stays entirely on the app that was designed to be public, and
`vrm_api` still ends this phase with exactly one unauthenticated route.)

So:
- `victron-monitor/web/app/api/webhooks/onvo/route.ts` — **no** `requireCustomerForRoute()` (there is
  no session; this is machine-to-machine), verifies `X-Webhook-Secret` in constant time (§6.1),
  forwards the body to `vrm_api` with the pipeline key, returns 200. It contains **no billing logic**
  — parse, verify, forward, respond. If it grows a business rule, that rule is in the wrong file.
- `vrm_api` `POST /v1/billing/webhook-event` — pipeline-key-authenticated like every other route.
  Writes the `vrm.billing_events` row **first** (durability before work), then reconciles.

Confirmed by Oscar (Q10) — this is the URL to register in the ONVO dashboard.

**Response policy, given no documented retry:**
- Bad/missing secret → **401**, row written with `secret_ok = false`, nothing else happens.
- Recorded successfully → **200**, even if the subsequent reconcile fails. A non-2xx buys nothing
  (ONVO merely logs it) and risks whatever undocumented retry behavior does exist doing something
  worse. The row is durable and §4.4's sweeper will retry the reconcile.
- Could not even record it (database down) → **500**. This is the one case where a failure in their
  dashboard is genuinely informative.

### 4.2 What a webhook is allowed to do

Exactly two things: get itself recorded, and name a customer/subscription to re-read. The handler
extracts the **id only** from `data`, resolves it to one of our customers, and calls the same
reconcile function everything else calls. It never reads `status`, `amount`, or any other field from
the payload into a column.

Resolution needs care, since `subscription.renewal.*`'s payload shape is unverified (§0.2 `[V]`) and
`payment-intent.succeeded` names a payment intent, not a subscription. The resolution ladder:
`data.id` matched against, in order, `vrm.subscriptions.onvo_subscription_id` →
`vrm.subscription_invoices.onvo_invoice_id` / `.payment_intent_id` →
`vrm.billing_customers.onvo_customer_id`. **If none match, the event is recorded with
`status = 'ignored'` and a resolved-nothing note — never dropped, never an error.** An unmatched
event is normal: this ONVO account may also be processing the Solar Design Tool's one-off project
payments, whose events are none of this system's business.

### 4.3 The reconcile function — the only thing that writes the mirror

`vrm_api/billing.py:reconcile_customer(customer_id) -> BillingState`

1. Stamp `fetched_at = now()` **before** the first request.
2. `GET` the customer's subscriptions from ONVO (`list a customer's subscriptions`, §0.2 [C] — exact
   path is Step 0's). This is deliberately the **list** call, not a get-by-id: it is the only way to
   discover a subscription created out-of-band (in ONVO's dashboard, or by a create call of ours
   whose response we lost). There is no `subscription.created` event to tell us otherwise.
3. `GET` the customer's payment methods, and the customer object (for the address).
4. `GET` renewals for the active subscription.
5. Upsert every mirror row **wholesale** — overwrite, do not merge. Set `last_synced_at = fetched_at`.
6. **Concurrency guard:** the upsert is conditional on `last_synced_at < fetched_at`. Two concurrent
   reconciles therefore resolve to the one that *read* later, not the one that *wrote* later. This is
   last-writer-wins on read time and it is the only ordering rule the system needs — note that it
   depends on nothing inside ONVO's payload, which is exactly why out-of-order delivery is a
   non-issue.
7. Call the entitlement writer (§4.5).
8. Return a `BillingState` — the same shape the status endpoint returns. **Never** returns raw ONVO
   payloads.

Every mutation endpoint (§5) ends by calling this. No endpoint infers the result of its own write.

### 4.4 The four triggers, and the freshness bound

| Trigger | When | Covers |
|---|---|---|
| **Post-mutation** | Immediately after any create/change/cancel/resume/address write we make | Our own actions. Removes any need to parse our own POST's response into state. |
| **Webhook** | On any resolvable event | Renewal succeeded/failed — the events that actually exist |
| **On-read staleness** | `GET /v1/billing/status` refreshes if `last_synced_at` is older than **5 minutes**, and **always** refreshes when the current status is transitional (anything not settled — `incomplete`/`past_due`-equivalents, final vocabulary from Step 0) | A customer who opens the page after a change they made elsewhere; a lost webhook |
| **Scheduled sweep** | `POST /v1/billing/reconcile-due`, hit by GitHub Actions `cron:` (the mechanism Phase 12 locked), **daily**, plus retrying `vrm.billing_events` rows stuck in `error` | The case nothing else covers: **a renewal that happened while nobody was looking and whose webhook never arrived.** Selects every subscription whose `current_period_end` is in the past, plus every transitional status, plus every row not synced in 48h |

**Freshness bound, stated as a promise the design keeps:** entitlement is correct within one
customer page-load, or within 24 hours, whichever comes first — even if **every** webhook is lost.
That sentence is the acceptance criterion for Step 4's validation, and it is testable by simply not
delivering the webhook (§8 Step 4).

**One signup-specific note on the "post-mutation" trigger:** a brand-new customer sitting on
`/app/billing` after entering a card is the one case where the freshness window is felt as *waiting*.
The subscribe flow already reconciles immediately after creating the subscription, and `onSuccess`
triggers a second `POST /api/billing/refresh` — so the promotion (§4.5 rule 8) normally happens
within a second or two. If it does not, the on-read staleness trigger picks it up when they reload,
and the page's first-run copy must say something honest in the meantime ("we're confirming your
payment — this page will update"), never a spinner that lies.

### 4.5 The entitlement writer — the only path from money to `plan`/`site_limit`

`vrm_api/billing.py:apply_entitlements(customer_id)` — a single function, called only from
`reconcile_customer()`, and the **only** code in the system besides admin that writes
`vrm.customers.plan` / `site_limit` / `billing_status` / `provisioning_state`.

Rules:
1. Resolve the customer's current subscription (the non-canceled one; if several, the most recently
   created — and log loudly, because §3.3's partial unique index should have made that impossible).
   **Added at Step 5's own fix (2026-08-20) — status alone is not sufficient.** Live testing found
   ONVO reports a freshly-created `trialPeriodDays: 7` subscription as `status: trialing` **immediately**,
   even with zero payment methods attached — contradicting this plan's original assumption that an
   unpaid subscription would show `incomplete` until a card was attached. That meant a customer could
   call subscribe then refresh directly, skipping the SDK's card-entry widget entirely, and receive a
   full trial with no card ever collected — a direct bypass of §0.6 Q2 ("card required upfront").
   **An entitled-shaped status now also requires `vrm.billing_customers.default_payment_method_id` to
   be non-null before granting anything** — the same "hold, don't grant, log loudly" treatment rule 2
   already gives an unrecognized status. This was fixed before Step 5.5 (public signup) began, since
   self-serve signup would have turned a narrow risk (only an already-invited customer could try it)
   into a public, repeatable, zero-cost free-trial abuse vector.
2. Map `status` → entitled / grace / not-entitled. **The mapping table is filled in at Step 0** once
   the real vocabulary is known; an **unrecognized status is treated as "grace"** (keep existing
   entitlement) and logged as an error, never as "not entitled." Rationale: the failure mode of
   guessing wrong in the generous direction is a customer keeps access they may not have paid for
   for one day; guessing wrong in the strict direction locks a paying customer out of their own data
   because a third party added an enum value. Those are not symmetric.
3. Entitled → `plan = subscription.plan_key`; `site_limit = vrm.plans.site_limit` **only if
   `customers.site_limit_source = 'plan'`**.
4. Canceled-at-period-end → **fully entitled until `current_period_end`**, then dropped. `cancelAt`/
   `cancelAtPeriodEnd` are native ONVO fields; the drop happens on the next reconcile after the
   period ends, which the daily sweep guarantees.
5. Not entitled → `plan` falls back to the no-subscription state (`'trial'`, per Q2); `site_limit`
   falls back to that plan's limit.
6. **Never deactivates, hides, or deletes a site, ever, under any transition.** If the new
   `site_limit` is below the customer's active site count, the customer is simply over limit:
   `canAddSite()` already refuses new sites, everything existing keeps working, and the UI says so
   plainly (Q5, recommendation (b)).
7. Every entitlement change writes a line to the application log with old→new values. When a customer
   asks "why did my plan change," that log is the answer.
8. **New, for signup — the promotion rule.** If the customer is `provisioning_state =
   'pending_subscription'` **and** rule 2 resolved to *entitled* (which, per Q2, includes ONVO's
   `trialing`), set `provisioning_state = 'active'` in the same write as `plan`/`site_limit`, and log
   it as a distinct, greppable event (`signup.promoted`). This is the **only** automatic promotion
   path in the system.
   - It is deliberately here and not in the subscribe endpoint: a subscription we POSTed is not a
     subscription that exists until we have re-read it (§0.5). Promoting on our own POST's response
     would be exactly the mistake this plan spends §4 avoiding.
   - Promotion is **one-way and never reversed**. A customer who later goes `past_due`, or cancels, is
     a lapsed customer with a `billing_status` that says so — **not** a pending signup. Demoting them
     would reset a real tenant to a checkout screen and (worse) hide their existing sites behind a
     first-run flow. `site_limit` dropping is the whole enforcement; `provisioning_state` is
     account lifecycle, not entitlement, and the two must not be conflated.
   - Rules 3 and 5 apply to a pending customer with no change: a pending customer has
     `site_limit_source = 'plan'` (§5.5 step 2), so their `site_limit` moves from `0` to the plan's
     grant in the same write that promotes them.

---

## 5. Backend — the endpoints

`vrm_api` endpoints are in §5.1–5.4, all under `vrm_api/routers/billing.py`, all carrying
`dependencies=[Depends(require_pipeline_key)]`, all calling `tenancy.get_customer(customer_id)` as
their first statement. Request/response models in `vrm_api/schemas.py`, mirrored field-for-field in
`lib/server/pipeline.ts` (the repo's established "restated, not re-derived" convention).

§5.5 is the signup surface, which is **entirely Next.js-side and adds no `vrm_api` route at all.**

### 5.1 Read endpoints

- `GET /v1/billing/status?customer_id=` → `BillingStatusOut`: `plan_key`, `plan_label_key`, `status`,
  `billing_interval`, `currency`, `amount_minor`, `current_period_end`, `cancel_at_period_end`,
  `trial_end`, payment-method display fields (`brand`/`last4`/`exp`), billing address, `site_limit`,
  `active_sites`, `over_limit` (bool), **`provisioning_state`** (so `/app/billing` can render its
  first-run variant from the same object it already fetches, rather than a second query). Applies
  §4.4's staleness refresh. **No ONVO ids in the response** beyond what the SDK genuinely needs
  (§5.2) — the browser has no use for `onvo_customer_id`, so it does not get it.
- `GET /v1/billing/plans?customer_id=` → the `vrm.plans` rows that are `active`, match the configured
  `mode`, and whose `account_types` include this customer's `account_type`, each annotated
  `is_current`. Filtering by account type on the **server**, not in the picker component. **When the
  customer is `pending_subscription`, additionally filter `self_serve = true`** (§3.1).
- `GET /v1/billing/invoices?customer_id=` → mirrored renewals, newest first, paginated.

### 5.2 Subscribe

`POST /v1/billing/subscription {customer_id, plan_id}` — `plan_id` is **our** `vrm.plans.id`, never
an ONVO `priceId` from the browser (§6.4).

1. Re-reconcile first. If an entitled/pending subscription already exists → **409
   `subscription_already_exists`**, not a second subscription (§5.4).
2. Ensure an ONVO customer exists for this `vrm.customers` row: reuse `vrm.billing_customers`, or
   create one and store the id in the same transaction. Never create a second ONVO customer for the
   same `customer_id` — the unique constraint enforces it.
3. **Corrected at Step 5 (2026-08-20) — the original text here described two incompatible flows at
   once, caught only when the SDK widget was actually rendered against real data.** §0.2b finding 7
   is still true as a fact about the *raw* `POST /v1/payment-methods` endpoint (it accepts the
   publishable key alone) — but §6.3 requires the **SDK widget**, not a hand-rolled form calling that
   endpoint directly, and the widget (confirmed live, Step 5) will not function without a real
   `subscriptionId` (for `paymentType: "subscription"`) already in hand **before** it renders — it is
   what the card the customer is about to enter gets attached to. A browser cannot possess a
   `paymentMethodId` before rendering the one thing that collects the card. The real sequence:
   (a) create the ONVO subscription **immediately**, with `paymentBehavior: allow_incomplete`,
   `trialPeriodDays: 7` (Q2), and **no `paymentMethodId`** — comes back `status: incomplete`; (b)
   return `{onvo_subscription_id, onvo_customer_id, publishable_key}` to the browser **before any card
   has been entered**; (c) the browser renders the SDK widget against that real `subscriptionId` —
   confirmed live to work: a real subscription id produces a genuine card form, and `onSuccess` was
   confirmed (Step 5's spike test) to return `{..., paymentMethodId}`; (d) `onSuccess` is still a
   **hint to refresh, never trusted state** (§0.2 — its shape is undocumented beyond what one spike
   observed) — the browser calls `POST /api/billing/refresh`, which reconciles from ONVO and is the
   only source of truth for whether the subscription actually moved off `incomplete`. Under **no**
   variant does our server receive raw card data (§6.3) — the SDK's iframe is the only thing that ever
   sees it, and our server only ever reads back an opaque `paymentMethodId` via the *next* reconcile,
   never accepted at face value from the browser for anything security-relevant (§6.4 control 3).
   **Known accepted risk, not fixed by this step**: §0.2b finding 11 confirmed a card **tokenizes
   successfully even when it will later decline** (ONVO's own always-declining test card creates a
   real `active`-status payment method; the decline only happens at charge time) — and finding 11 also
   confirmed the trial period's own invoice is `$0`, charged nothing. That means a bad/fake card can
   sail through signup and only fail 7 days later at trial-end, not at signup. Q2's "card required
   upfront" is friction against casual abuse, not a guarantee the card is real. Not worth a $0.01
   verification charge for v1 — flagged here so it isn't mistaken for an oversight later.
4. Set ONVO `metadata` to `{vrm_customer_id, plan_key, env}`. Not load-bearing — we never read state
   back from metadata — but it makes ONVO's own dashboard legible to Oscar during a support call, and
   it is how an orphan is identified.
5. Return `{onvo_subscription_id, onvo_customer_id, publishable_key}` **right after creating the
   incomplete subscription** (step 3b) — not after a reconcile, since nothing entitled exists yet to
   reconcile toward. The browser renders the SDK against that `subscriptionId` immediately.

**This is the same endpoint a self-serve signup uses.** There is no signup-specific subscribe path.
The only difference for a pending customer is the `self_serve = true` filter in step 1's plan lookup
and the fact that the reconcile in step 5 will promote them (§4.5 rule 8).

### 5.3 Change plan, cancel, resume, payment method, address

- `POST /v1/billing/subscription/change {customer_id, plan_id}` — **superseded by §0.2b finding 6 +
  Q3's final answer**: there is no item/price-swap mechanism at all (three separate live 400s
  confirmed it), so this is **cancel the current `onvo_subscription_id`
  (`DELETE /v1/subscriptions/{id}`, confirmed synchronous per finding 12) + create a new subscription
  at the target plan's price**, then reconcile. No proration, no credit — both upgrades and downgrades
  take effect immediately, a fresh billing period starts now (Q3, final). The new subscription reuses
  the existing `vrm.billing_customers.default_payment_method_id` (no new card entry needed just to
  change plans). **Guard, unchanged:** if the target plan's `site_limit` is below the customer's active
  site count, the response includes `requires_confirmation: true` with the numbers, and a second call
  with `confirm: true` proceeds (Q5's answer, (b)). The decision lives in one server-side branch, not
  in the UI. **Response copy must say plainly** that switching plans starts a new billing period with
  no credit for unused time (Q3's own requirement).
- `POST /v1/billing/subscription/cancel {customer_id, mode}` — `mode: 'at_period_end'` sets
  `cancelAtPeriodEnd`; `'immediate'` is implemented but **only reachable from `/admin`** (Q4).
- `POST /v1/billing/subscription/resume {customer_id}` — clears a pending `cancelAtPeriodEnd`.
  **Confirmed working by Step 0 (§0.2b finding 12)**: `POST /v1/subscriptions/{id}` with
  `{"cancelAtPeriodEnd": false}` clears it live, no create-a-new-subscription fallback needed.
- `POST /v1/billing/payment-method/session {customer_id}` — **corrected alongside §5.2 point 3 (Step
  5, 2026-08-20)**: returns `{onvo_subscription_id, onvo_customer_id, publishable_key}` for the
  customer's **existing** live subscription (already exists — this is the replace-card path, not
  first-time subscribe) — the SDK widget needs that real `subscriptionId` to render, exactly like
  first-time subscribe does, not just a `customerId`. The browser renders the SDK against it, the
  customer enters a new card in the SDK's own widget, `onSuccess` is a hint (not trusted) to call
  `POST /api/billing/refresh`, and the **reconcile** — not the request that triggered it — is what
  actually updates `vrm.billing_customers.default_payment_method_id`, by re-reading the subscription's
  real `paymentMethodId` from ONVO (§6.4 control 3: no ONVO id is trusted from the caller without a
  fresh re-read). Our server never sees card data at any point.
- `DELETE`-equivalent for a payment method is **not** exposed to customers in v1 — removing the only
  card on an active subscription just produces a failed renewal. Changing the card is the supported
  action.
- `PUT /v1/billing/address {customer_id, address}` — Zod/pydantic-validated against ONVO's address
  shape, written to ONVO first, then mirrored from the reconcile (not from our own request body).
- `POST /v1/billing/refresh {customer_id}` — plain reconcile. Rate-limited per customer (§6.5).
- `POST /v1/billing/reconcile-due` — the sweeper (§4.4). No `customer_id`; pipeline-key only; called
  by cron and by `/admin`.
- `POST /v1/billing/webhook-event` — intake from the Next.js receiver (§4.1).

### 5.4 Duplicate-subscription safety, without relying on idempotency keys

Because `Idempotency-Key` support is unverified (§0.2 `[V]`), three independent guards, all of which
must be built:
1. **Reconcile-before-create** — a fresh list-subscriptions call immediately before creating, so a
   subscription created by a previous attempt whose response we lost is found rather than duplicated.
2. **The partial unique index** on `vrm.subscriptions` (§3.3) — the database refuses a second live
   row even if the application logic is wrong.
3. **UI-level:** the create button disables on submit and the page reflects server state after the
   reconcile, never optimistic local state.
If Step 0 finds `Idempotency-Key` *is* supported, add it as a fourth guard (derived from
`customer_id + plan_id + a client-supplied request id`) — do not remove the other three.

### 5.5 The public signup surface (Next.js only — zero new `vrm_api` routes)

Three server entry points, of which two are public. All in `victron-monitor/web`.

#### Step 1 — `signUpAction` (Server Action, public)

`app/(auth)/signup/actions.ts`. A **Server Action**, not a Route Handler, to match
`app/(auth)/forgot/actions.ts` exactly — and because Next.js applies its own Origin/Host validation to
Server Action POSTs, which is a free CSRF-shaped defense on the one public write in the app.

Input (Zod-parsed, all of it typed by the visitor, none of it trusted):
`{ name, email, account_type: 'installer'|'owner', plan_id?: uuid, ui_language: 'en'|'es', website?: string }`.
`website` is the **honeypot** — a visually hidden, `autocomplete="off"`, `tabindex="-1"` field. If it
is non-empty, the action returns the same neutral success and does nothing at all.

Sequence:
1. Rate-limit checks against `vrm.rate_limits` (§6.6's numbers), in order: global, per-`ip_hash`,
   per-`lower(email)`. A rejection returns the **same neutral state** as success — never "you're doing
   that too much," which is itself an oracle.
2. `verifyHumanChallenge(token)` — a no-op unless `SIGNUP_CAPTCHA_PROVIDER` is set (Q12).
3. Look up `lower(email)` in `vrm.customers.auth_email`.
   - **Match →** do **not** create a staging row. Send the "you already have an account" email
     instead (a `renderActivationEmail()` call with sign-in / reset-password copy and a link to
     `/login`). Return the neutral state. This is the single most important non-enumeration branch in
     the flow: a stranger probing addresses gets the identical response either way, and the real
     account holder gets a useful email if it was actually them.
   - **No match →** insert a `vrm.signup_requests` row: `token = crypto.randomBytes(32)` (hex),
     `token_hash = sha256(token)`, `expires_at = now() + 24h`, plus the submitted fields and the
     hashed IP/UA. Send the verification email — `renderActivationEmail()` again, CTA pointing at
     `{SITE_URL}/signup/verify?token=<token>`.
4. Return `{ submitted: true }` **unconditionally**, including when Resend threw. Errors are
   swallowed and logged server-side, exactly as `requestPasswordResetAction` does and for exactly the
   same reason (a thrown error renders Next's error boundary, which is an observable difference).

The page (`app/(auth)/signup/page.tsx`) renders the form and, on `submitted`, replaces it with
"Check your email — we sent a link to <the address they typed>." Never "we sent a link to an existing
account" or any variant that differs by case.

#### Step 2 — `GET /signup/verify?token=…` (Route Handler, token-authenticated)

`app/(auth)/signup/verify/route.ts`. This is the step that creates a real row, and it is the only
public-facing code in the app that ever will.

1. `sha256` the token; look up `vrm.signup_requests` by `token_hash`.
2. **Consume atomically**: `UPDATE … SET consumed_at = now() WHERE token_hash = $1 AND consumed_at IS
   NULL AND expires_at > now() RETURNING *`. Zero rows returned = already used, expired, or never
   existed — all three redirect to `/signup?status=link_used`, which renders one friendly message
   with links to `/login` and `/forgot`. **Not three different messages**, and not an error page.
   The atomic conditional update is what makes a double-clicked email link create one customer, not
   two.
3. Create the `vrm.customers` row via `lib/server/db/signup.ts:createSelfServeCustomer()` — a new,
   narrow, heavily-commented insert that is **not** `admin.ts:createCustomer()` (that module is
   admin-only by its own header, §11) and **not** reachable from any customer-facing update path:
   ```
   name              = the submitted name
   slug              = uniqueSlug(slugify(name))     -- see below
   account_type      = the submitted account_type
   plan              = 'trial'
   site_limit        = 0                              -- explicitly 0; NEVER planSiteLimit(), which fails OPEN
   site_limit_source = 'plan'                         -- load-bearing; see §3.6
   provisioning_state= 'pending_subscription'
   origin            = 'self_serve'
   active            = true                           -- required by resolveRole(); see §3.6
   auth_email        = the verified email (lowercased)
   contact_email     = the same address (a separate column, deliberately copied not aliased — §3.2)
   ui_language       = the submitted preference
   ```
   **`uniqueSlug()`**: `slugify(name)`, then `-2`, `-3`, … on a unique violation, up to a small cap
   (say 50), then fall back to `slugify(name) + '-' + a 6-char random suffix`. This is not
   defensiveness for its own sake — `vrm.customers.slug` is `UNIQUE` and is the **permanent namespace
   of every `site_id`** this customer will ever mint (§0.1), so it can neither collide nor be changed
   later. `admin.ts:createCustomer()`'s bare `slugify(name)` is fine when Oscar sees the error; it is
   not fine when the internet picks the names. If `slugify()` itself throws (a name with no
   ASCII-able characters at all — it throws by design), fall back to a random slug rather than
   rejecting the signup; the slug is an internal identifier, not the display name.
4. Create/link the Supabase auth user and mint an activation token, by calling a **newly extracted**
   `lib/server/invites.ts:createOrLinkAuthUser(email) → { userId, hashedToken, linkType }`. This is the
   `generateLink({type:'invite'})` → `email_exists` → `findOtherCustomerByEmail` →
   `findAuthUserByEmail` → `generateLink({type:'recovery'})` ladder **lifted verbatim out of
   `sendInvite()`**, which then calls it too. Two callers, one implementation — the refactor is the
   whole point: the "email already exists but belongs to nobody" case is rare for Oscar's invites and
   *routine* for public signup (Phase 13 test users, a deleted-and-recreated account, a person who
   started signup twice), and it must behave identically in both.
   If it returns the `already_linked_elsewhere` case, roll back: delete the just-created customer row
   and redirect to `/signup?status=link_used`. (This should be unreachable — step 1 already checked
   the email — but the check and the insert are not in one transaction, so it is reachable by race,
   and a half-created account is worse than a confusing redirect.)
5. `stampInvited(customerId, userId, email)` — the existing `invites.ts` function, which needs
   exporting. It already carries the comment explaining that it is the one place allowed to write
   `auth_user_id`/`auth_email`/`invited_at`; that comment gains a second sanctioned caller.
6. Write `customer_id` back onto the `vrm.signup_requests` row (diagnostics, §3.7).
7. **302 to `/activate?token_hash=<hashedToken>&type=<linkType>&next=/app/billing%3Fplan%3D<plan_id>`.**
   From here the visitor is on the **existing, unmodified** activation path.

**On putting a `hashed_token` in a redirect URL:** it is the same value the existing invite email puts
in a link the customer clicks, with the same single-use, short-lived properties, ending up in the same
place (the address bar). The redirect is same-origin, server-issued, and immediately consumed by
`verifyOtp`. The alternative — emailing a second link — would mean two emails for one signup and a
strictly worse conversion rate for no security gain. Do **not** log the URL (§11).

#### Step 3 — `/activate` gains a `next` parameter (small, existing file)

`setActivationPasswordAction` currently ends in `redirect('/app')`. It gains an optional `next`,
**validated to be a same-origin relative path beginning with `/app`** (a literal prefix check on a
string that must also not begin with `//` — an open-redirect check, written as such, with a comment).
Anything else falls back to `/app`. Bound server-side in `page.tsx` alongside the token, the same way
`token_hash`/`type` already are — never read from a client component prop.

#### Step 4 — the public plan list

The signup form shows prices, and it has no session, so it cannot call
`GET /v1/billing/plans?customer_id=`. It calls a small **server-side function**
(`lib/server/db/signup.ts:listSelfServePlans(accountType)`) directly from the Server Component, not a
new public HTTP endpoint — there is no browser-side fetch to expose in the first place if the page
renders the list server-side, and the `?plan=` preselect is just a query param.

It selects `id, plan_key, billing_interval, currency, amount_minor, site_limit` from `vrm.plans`
`WHERE active AND self_serve AND mode = ONVO_MODE AND account_types @> ARRAY[accountType]`, ordered by
`sort_order`. **`onvo_price_id` and `onvo_product_id` are never selected and never leave the server** —
they are not secrets (§6.2), but there is no reason for the public internet to hold a map of our ONVO
catalogue, and the omission costs nothing.

If the list is empty (Q14 unanswered, or the wrong `ONVO_MODE`), the page renders "Signups are
temporarily closed — get in touch" with a link to `AccessForm`, **not** an empty picker and a dead
button.

#### Why this order — local row before card, ONVO objects after

The sequencing question in Q6 has one defensible answer under §0.5, and the architecture very nearly
forces it:

- **The ONVO customer cannot be created first.** `ONVO_SECRET_KEY` lives only in `vrm_api` (§6.1), and
  every billing endpoint there begins with `tenancy.get_customer(customer_id)`. Creating an ONVO
  customer before a local row would require a second, customer-less code path through `onvo.py` and a
  later orphan-adoption step — strictly more code, strictly more failure modes, and it would put an
  unauthenticated public route into `vrm_api`, breaking the invariant §4.1 exists to protect.
- **The local row cannot be created before verification** without handing anyone on the internet the
  ability to insert rows into the tenant table and squat permanent `slug`s. Hence §3.7's staging
  table.
- **So: verify the email → create a `pending_subscription` local row → the normal, already-designed
  §5.2 subscribe flow creates the ONVO customer and subscription → a reconcile promotes.** The local
  row exists before the card, but it grants nothing: `site_limit = 0`, no sites, no reports, gated by
  `requireCustomer()` to the billing page.
- **What an abandoned signup leaves behind, stated precisely** — because "does it leave a phantom
  account?" is the question that motivated this design:
  | Abandoned at | Leaves behind | Can it do anything? |
  |---|---|---|
  | Form submitted, email never opened | one `vrm.signup_requests` row, pruned in 31 days | No. No auth user, no customer row |
  | Link clicked, password never set | customer row (`pending_subscription`, `site_limit 0`) + an unconfirmed auth user | No — no password, no session. Recoverable by the customer via `/forgot`, which works because `auth_user_id` and `active` are both set |
  | Password set, card never entered | the same, plus a usable login | Sign in, and land on `/app/billing`. That is the entire surface. No sites, no uploads, no reports |
  | Card entered, payment failed | the above, plus an ONVO customer and a non-entitled subscription | The same, plus an honest "we couldn't complete your payment" (§7) |
  Nothing in that table is a provisioned account, and the only ONVO object that can exist is one the
  visitor deliberately created by entering a card.
- **No automatic deletion of any of it** (§9). Abandoned signups are leads; `/admin/customers` filters
  on `provisioning_state = 'pending_subscription'` and `origin = 'self_serve'` (Step 6) so Oscar can
  see them and decide.

---

## 6. Security

### 6.1 Secrets: what goes where, and why

| Secret | Lives in | Read by | Never |
|---|---|---|---|
| `ONVO_SECRET_KEY` | root `.env`, next to `PIPELINE_API_KEY`/`VRM_ADMIN_TOKEN` | `vrm_api/onvo.py` only | Never in `victron-monitor/web/.env.local`, never `NEXT_PUBLIC_*`, never in a log line, never in a job's `params`, never in an error message returned to a browser |
| `ONVO_WEBHOOK_SECRET` | the Next.js server env (given §4.1's decision) | the webhook route handler only | Never client-side; never compared with `===` |
| `ONVO_PUBLISHABLE_KEY` | the Next.js **server** env | read server-side, **passed to the client component as a prop** | Deliberately **not** a `NEXT_PUBLIC_*` var — see below |
| `ONVO_MODE` (`test`/`live`) | root `.env` + Next.js env | both | — |
| **`SIGNUP_IP_SALT`** | the Next.js server env | `lib/server/signup.ts` only | Never client-side, never logged. Rotating it resets rate-limit history (acceptable; comment it) |
| **`SIGNUP_CAPTCHA_SECRET`** (only if Q12 says yes) | the Next.js server env | the `verifyHumanChallenge()` implementation only | Never client-side. Its *public* sitekey counterpart follows `ONVO_PUBLISHABLE_KEY`'s prop rule, not `NEXT_PUBLIC_` |

**Why the publishable key is a prop and not `NEXT_PUBLIC_`:** the value is designed to be public and
ends up in the page either way. But Phase 15 established a leak check phrased as *"no `NEXT_PUBLIC_*`
addition"*, and that check is worth keeping literally true and mechanically greppable. Passing it as
a server-rendered prop costs nothing and preserves the invariant. **Update the leak check for this
phase** to also grep a production build for the literal substrings `_secret_key_` and
`webhook_secret_` — those are the strings that actually matter, and ONVO's key prefixes make them
trivially greppable.

**Signup tokens are not in this table on purpose.** A signup token is not a stored secret: it is
generated per request, never persisted in plaintext (only `sha256`, §3.7), single-use, and expires in
24 hours. It is closer to a `hashed_token` from Supabase's own invite flow than to an API key — which
is exactly the model it copies.

### 6.2 Why Vault is NOT used here (and when that would change)

Migration 024's Vault machinery exists because a Victron personal access token **grants access on its
own** — it reads every installation on a customer's account, with no further secret needed. That is
what makes it a credential.

`onvo_customer_id`, `onvo_subscription_id`, and `paymentMethodId` are **opaque object identifiers,
not credentials**: they move no money and reveal nothing without our secret key. ONVO's own design
confirms this reading — `onvo.pay()` takes `customerId` **client-side, in the browser, alongside a
publishable key** (§0.2 [C]). A vendor does not put a credential in a `<script>` parameter. Storing
these in plain columns is correct, and wrapping them in Vault would be cargo-culting the pattern
rather than applying it.

The same reasoning covers the signup token, from the other direction: it *is* capability-bearing for
24 hours, which is why it is **hashed at rest** — but it is short-lived, single-use, and
self-destructs on redemption, so Vault (built for long-lived credentials that must be *retrievable*)
is the wrong tool. We never need to read a signup token back; we only need to compare a hash.

**What would change this:** if Step 0 discovers any flow where our server receives a raw card number,
a CVV, or a durable card token usable without our secret key, **stop and re-plan** — that is a
PCI-scope change, not a schema change, and it is out of scope for this phase (§9).

Two things remain true regardless: `pm_last4`/`pm_brand`/`pm_exp_*` are **display-only** and are
never used in any decision; and no endpoint returns another customer's ONVO ids under any
circumstance.

### 6.3 Card data never touches our servers

The SDK renders the card form; the card goes from the browser to ONVO. Our servers hold ids. This is
what keeps the product at a PCI SAQ-A posture. Concrete rules for the coder:
- No `<input>` for a card number, expiry, or CVV exists anywhere in this repo. Not disabled, not
  hidden — **absent**. (This now explicitly includes the signup form: signup collects a name, an
  email, an account type, and a plan choice. Nothing else. It never sees a card, because the card is
  entered two pages later in ONVO's own component.)
- No request body schema anywhere accepts a field that could hold one.
- The SDK container element is the only place card entry happens, and it is a third-party-rendered
  component we do not style the internals of.

### 6.4 Tenancy — the three controls, restated for billing

1. **Next.js**: `requireCustomerForRoute()` as the first statement of every `app/api/billing/*` route
   handler; `customer_id` is **always** `session.customerId` and never read from the body. Same shape
   as `app/api/vrm/connect/route.ts`, which is the file to copy.
2. **`vrm_api`** re-derives ownership itself via `tenancy.get_customer()` — it does not trust that
   Next.js checked. Unchanged rule, new call sites.
3. **New in this phase: no ONVO object id is ever accepted from a request.** Not a `subscriptionId`,
   not a `customerId`, not a `priceId`, not an `invoiceId`. Every endpoint takes our own ids
   (`customer_id`, `vrm.plans.id`) and looks the ONVO id up from a mirror row already scoped to the
   tenancy-checked customer. This is the exact analogue of PLAN_PHASE15.md §3.2's installation-binding
   control, and it exists for the same reason: it converts "an id got confused somewhere" from
   cross-tenant data exposure — here, *charging the wrong person's card* — into a lookup that simply
   finds nothing.
   - **A clarification the signup flow makes necessary:** `?plan=<vrm.plans.id>` travels through the
     signup URL, the staging row, and the redirect into `/app/billing`. That is **not** a violation —
     it is *our* id, not ONVO's, and it is re-validated server-side at subscribe time against
     `active`/`mode`/`account_types`/`self_serve`. The rule is about ONVO ids specifically, and the
     coder should expect this to look wrong at a glance and find a comment saying why it isn't.

**The fourth control, new and specific to signup: the pending-account gate.**

`lib/server/auth.ts` gains one behaviour, and it is deliberately placed in the **default** function so
that it is fail-closed for code that doesn't know about it:

- `requireCustomer()` and `requireCustomerForRoute()` — after resolving a customer session, if
  `provisioning_state !== 'active'`, redirect (or 403) to `/app/billing`. **Every existing portal page
  and API route inherits this with no edit**, and so does every page written after this phase by
  someone who never read this document. That is the point.
- `requireCustomerAllowPending()` — the explicit opt-out, used by exactly three places: the
  `/app/billing` page, the `app/api/billing/*` routes, and `/app/profile` (a pending customer must be
  able to sign out and change their password like anyone else — and `/app/profile` is where the
  "sign out" affordance lives). Every call site carries a comment naming this section.
- **Defense in depth, because a guard is a guard and bugs exist:** a pending customer has
  `site_limit = 0`, so `canAddSite()` refuses on its own, with no knowledge of `provisioning_state`.
  Two independent mechanisms, neither of which relies on the other.

`scripts/test-scoping.ts` gains billing **and signup** cases and must pass at every step: customer A
cannot read B's status, invoices, payment method, or address; cannot change, cancel, or resume B's
subscription; cannot do any of it by aiming a crafted request straight at a running `vrm_api` with a
valid pipeline key but the wrong `customer_id` (the existing tamper-case pattern); **and a
`pending_subscription` customer with a perfectly valid session cannot list sites, upload, generate a
report, or create a site — via the UI or by calling `app/api/*` directly.**

### 6.5 The webhook endpoint specifically

- **Constant-time secret comparison.** In Node, `crypto.timingSafeEqual` **throws** on
  buffers of differing length, and that throw itself leaks length. The correct shape is to SHA-256
  both the provided and expected secret and `timingSafeEqual` the two 32-byte digests — always equal
  length, no throw, no length leak. Mirror `vrm_api/deps.py`'s reasoning in a comment.
- **An empty or unset `ONVO_WEBHOOK_SECRET` must fail closed.** `deps.py` L40–43 documents this exact
  trap (`compare_digest("","")` is `True`); the same bug is available here and must be guarded the
  same way.
- **Rate-limit the endpoint** — using `vrm.rate_limits` (§3.8), **not** an in-process counter, which
  a serverless deployment would reset per invocation. Two reasons it matters: a forged-event flood
  must not fill `vrm.billing_events`, and — more importantly — must not turn into us hammering ONVO's
  API with our secret key on their behalf.
- **No session, no cookies, no CSRF token.** This is machine-to-machine; the shared secret is the
  whole authentication story. Make sure the route is not accidentally caught by any middleware that
  expects a session.
- **The response body is `{"ok":true}` or nothing.** Never echo the payload, never include an error
  message, never confirm whether the event resolved to a known customer — that is an account
  enumeration oracle for anyone holding a leaked secret.

### 6.6 The public signup surface specifically — a genuinely new trust boundary

**State the change plainly, because it is the largest security delta in this phase:** until now, every
request that wrote anything to this product's database carried either a Supabase session
(`requireCustomer`/`requireAdmin`) or the `PIPELINE_API_KEY`. `/forgot` was the only unauthenticated
POST, and it *writes nothing* — it reads a row and asks Supabase to send an email. After this phase,
**a request with no credential of any kind can cause a row to be inserted and an email to be sent.**
Everything below exists because of that sentence.

**What the public surface can and cannot do:**

| Can | Cannot |
|---|---|
| Insert one `vrm.signup_requests` row | Insert or modify a `vrm.customers` row |
| Cause one Resend email | Cause any ONVO API call, or any call to `vrm_api` at all |
| Read the self-serve plan list (`plan_key`, interval, currency, amount, site cap) | Read `onvo_price_id`, `onvo_product_id`, or anything about any customer |
| Learn that the form accepted its input | Learn whether an email address is already a customer |

The second row is worth dwelling on: **signup cannot spend money or trigger an outbound call to a paid
API.** §6.5 worries about a webhook flood turning into us hammering ONVO with our own secret key;
signup has no equivalent, by construction — the ONVO-touching code is behind
`requireCustomerAllowPending()` + a real session + `tenancy.get_customer()`. **The signup abuse budget
is denominated entirely in Resend sends and database rows**, which is what the limits below are sized
against.

**Rate limits** (via `vrm.rate_limits`, §3.8 — all values are starting points, all in one exported
constant so they are tunable without hunting):

| Bucket | Key | Window | Max | Rationale |
|---|---|---|---|---|
| `signup_email` | `lower(email)` | 24h | 3 | Caps mailbombing a specific person's inbox to three messages a day |
| `signup_ip` | `sha256(ip + salt)` | 1h | 5 | A shared office NAT should never legitimately produce more |
| `signup_global` | `''` | 1h | 100 | The circuit breaker. At this product's scale, 100 signups in an hour is a flood, not a launch. It fails **closed** and Oscar finds out from the log, which is the correct trade for a business with tens of customers |

**Every rate-limit rejection returns the same neutral `{submitted:true}`** as a success. A visitor who
is limited is told "check your email," receives nothing, and can try tomorrow. That is a slightly
worse experience for a rare legitimate case and a much worse experience for an enumeration script,
which is the right way round. Every rejection is logged server-side with the bucket and key so a real
attack is visible.

**Other unconditional defenses:**
- **Honeypot** `website` field (§5.5 step 1) — catches naive form-fillers for zero cost.
- **Server Action origin validation** — Next.js's own, free by choosing a Server Action over a Route
  Handler.
- **Zod at the boundary**, with a hard length cap on every string (name ≤ 120, email ≤ 254 per RFC,
  UA truncated to 200) so no field can be used to bloat a row.
- **`lower(email)` normalization before every lookup, insert, and rate-limit key** — otherwise
  `Bob@x.com` and `bob@x.com` are three signups each per day instead of three total. Note the existing
  unique index is on `lower(auth_email)` (§0.1), so the database agrees.
- **No enumeration, anywhere:** identical response for existing/new email, identical response for
  rate-limited, identical page for expired/used/invalid token. This is the discipline
  `sendPasswordReset()` already documents; signup adopts it wholesale and Step 5.5's gate tests it by
  diffing responses, not by reading the code.

**CAPTCHA** is a **seam, not a decision** (Q12): `verifyHumanChallenge(token: string|null):
Promise<boolean>` in `lib/server/signup.ts` returns `true` immediately when
`SIGNUP_CAPTCHA_PROVIDER` is unset, and the form renders the widget only when a sitekey is present.
Turnstile is the suggested default if Oscar wants one. The plan does not depend on the answer.

**What this section deliberately does not do:** no email-domain blocklist, no disposable-address
detection, no "corporate email required" rule. Q2's card-required-upfront trial makes a throwaway
inbox worthless on its own (§0.6 Q2), and every blocklist of this kind eventually rejects a real
customer — a failure this business would rather not have. Recorded as a non-goal (§9), not an
omission.

---

## 7. Failure modes — what happens and what each party sees

| Event | Detected as | State written | Customer sees | Oscar sees |
|---|---|---|---|---|
| First payment fails at signup | reconcile after `onSuccess`/timeout shows a non-entitled status | subscription mirrored in its real status; **no entitlement granted, no promotion** (§4.5 rule 8) | "We couldn't complete your payment — try a different card." Stays on `/app/billing`; the plan does not change | `/admin/customers` billing column; the row shows `pending_subscription` |
| Renewal fails | `subscription.renewal.failed`, or the daily sweep | `billing_status='past_due'`; entitlement held through the grace window (Q8) | Banner: payment failed, update your card, with the date access ends | Same, plus the invoice row |
| Renewal succeeds | `subscription.renewal.succeeded`, or the sweep | period advanced, new invoice row | Next renewal date updates | — |
| **Webhook never arrives** | nothing — by design | the daily sweep reconciles anyway | Nothing; state is correct within 24h, or immediately on their next page load | — |
| Webhook arrives twice / out of order | — | a redundant reconcile; §4.3's fetch-time guard resolves ordering | Nothing | Two `billing_events` rows, both `applied` |
| Forged webhook, correct secret | resolves to a real customer | one redundant reconcile against ONVO | Nothing | An unexplained `billing_events` row — **worth investigating**, it means the secret leaked |
| Forged webhook, wrong secret | 401 | `billing_events` row with `secret_ok=false` | Nothing | The row, which is the only evidence an attempt happened |
| ONVO API down during a customer action | timeout/5xx from `onvo.py` | nothing written; the mutation did not happen | "Billing is temporarily unavailable — please try again shortly." Existing access is **unaffected** | Logged with the real cause |
| ONVO down during a reconcile | same | mirror keeps its previous values, `last_synced_at` unchanged | Stale-but-correct state; nothing degrades | — |
| Downgrade puts customer over `site_limit` | entitlement writer | `site_limit` lowered; **no site touched** | Banner: over limit, sites keep working, can't add more until under (Q5(b)) | `/admin/customers` |
| Unknown subscription status from ONVO | entitlement mapping | **entitlement held** (grace), error logged | Nothing | An error log line — this is the one Oscar should actually look at |
| Two live subscriptions for one customer | §3.3's index should prevent it | most recent wins, loud log | Nothing | Error log — a real bug, escalate |
| **Signup: email already a customer** | `signUpAction` step 3 | **nothing** — no staging row | "Check your email" (identical to a new signup); the real owner receives a "you already have an account, sign in or reset" email | Nothing, unless they look at the send log |
| **Signup: Resend is down** | `sendEmail` throws | staging row exists, no email sent | "Check your email" — and nothing arrives. They can retry; the second attempt is a second staging row (rate limit: 3/day) | The swallowed error, logged with the reason |
| **Signup: link clicked twice** | the atomic consume returns zero rows on the second click | nothing on the second click | `/signup?status=link_used` → "This link has already been used. Sign in, or reset your password." | Nothing — this is normal (mail clients prefetch links) |
| **Signup: link expired (>24h)** | same branch | nothing | The **same** page as "already used" — no distinction is drawn | Nothing |
| **Signup: verified, password never set** | nothing — no detection needed | customer row `pending_subscription`, auth user unconfirmed | Can recover unaided via `/forgot`, which works because `auth_user_id` and `active` are both set (verified in Step 5.5's gate) | The row, in the pending-signups filter |
| **Signup: verified, never paid** | nothing | customer row `pending_subscription`, `site_limit 0` | Signs in → lands on `/app/billing`, every other page redirects there | The row, in the pending-signups filter. **Never auto-deleted** (§9) |
| **Signup: slug collision** | unique violation on insert | retried with `-2`, `-3`, … | Nothing — invisible | Nothing |
| **Signup: rate-limited or honeypot-tripped** | the limiter | one `vrm.rate_limits` increment | "Check your email" — indistinguishable from success | A log line naming the bucket and key. A spike here is the abuse signal |
| **Signup: promotion doesn't happen despite ONVO saying `trialing`** | the customer is stuck on `/app/billing` and says so | — | The first-run page keeps saying "we're confirming your payment" | The support escape hatch: `/admin/customers` → **Refresh** (reconcile), which is the same code path and normally fixes it; a manual promote exists as a last resort (Step 6) |

**Not in v1:** dunning emails. `victron/mailer.py` exists and the hook is one call, but automated
"your payment failed" mail is a product decision with legal-copy implications, not a technical one.
Noted here so it isn't quietly added. **Also not in v1:** abandoned-signup nudge emails ("you didn't
finish signing up") — same reasoning, and the data to send them (`vrm.signup_requests`,
`provisioning_state`) exists whenever Oscar wants them.

---

## 8. Build steps

Each step ends in something runnable behind its own gate. Nothing proceeds past a failed gate.

### Step 0 — ONVO discovery spike (**hard blocker on everything**; ~1 day + support turnaround)

**Needs from Oscar:** an ONVO **test-mode** account with a secret key + publishable key + a webhook
endpoint registerable in their dashboard.

**Build:** `tools/onvo_probe.py` — same role and spirit as the existing `tools/vrm_remote_probe.py`
(committed, not scratch, so the next person can re-run it). It exercises, against test mode:
customers create/get/update/list-subscriptions/list-payment-methods; products + prices create;
subscriptions create (both `paymentBehavior` values seen in the docs, **and with `trialPeriodDays: 7`
both with and without a payment method**) / get / update / cancel (`cancelAtPeriodEnd` and immediate)
/ confirm / resume; item add/update/delete; renewals list; a deliberate duplicate
`POST /v1/subscriptions` with and without an `Idempotency-Key` header.

**Deliverables — a findings table appended to this file as §0.2b**, every row marked
*confirmed-by-probe* or *still-unknown*, answering at minimum:
1. Exact method + path + request/response for every operation listed above.
2. The complete `status` vocabulary for subscriptions and for renewals.
3. Are amounts minor units? Which currencies can coexist on one account?
4. **Proration**: change an item's `priceId` mid-period and read what actually happens to the next
   renewal's `total`/`originalTotal`/`invoiceAdditionalItems`. Report the observed numbers, not a
   description.
5. **Card replacement on an existing subscription** — the §0.2 `[V]` that can reshape §5.3. If the
   probe can't establish it, ONVO support must.
6. `Idempotency-Key`: honored or ignored?
7. The real `subscription.renewal.succeeded` / `.failed` payloads, captured from a live test-mode
   delivery (a temporary webhook.site-style endpoint is fine for this — **use a throwaway secret, not
   the one that will go to production**).
8. Whether the webhook body carries any event id or timestamp (we believe not — confirm).
9. Tax/IVA behavior on a price (Q7's technical half).
10. **The trial mechanics** (§0.2's new `[V]` row): does `trialPeriodDays: 7` + a card produce
    `trialing` with no charge, does ONVO auto-charge at `trialEnd` unprompted, and what status appears
    if that first real charge declines? §4.5 rule 8 and §7's signup rows depend on the answer.

**In parallel:** email ONVO support for a Postman collection / OpenAPI export and written answers on
proration, idempotency, and card replacement.

**Gate:** §0.2b exists and every `[V]` row above is either resolved or explicitly marked unresolved
with a named workaround. **No schema is written before this.**

### Step 1 — Migration 025 + the plan catalogue (~1.25 days; blocked on Q1, Q2, Q13, Q14) — ✅ DONE 2026-08-20

Migration applied (manually, via the Supabase SQL Editor — no agent in this environment has direct DDL
access, same as every prior migration). Every validation-gate assertion ran for real and passed:
the partial unique index rejected a genuine duplicate live-subscription insert while correctly allowing
a second *canceled* row; all 8 pre-existing `vrm.customers` rows defaulted to
`site_limit_source='manual'` / `provisioning_state='active'` / `origin='admin'` with zero exceptions;
25 concurrent `vrm.increment_rate_limit()` calls landed as exactly 25, no lost updates.
`tools/seed_onvo_plans.py` hit one real bug on its first run — ONVO's price-creation endpoint rejects a
`description` field outright (`400`), unlike product creation, which accepts one — fixed and re-run
clean; four `vrm.plans` rows now exist against four real ONVO test-mode prices, one refetched directly
from ONVO and confirmed byte-for-byte against what's stored in Postgres. **One harmless leftover from
the failed first attempt:** an orphan ONVO product (`cmt0v92gm1druk560mnfsoyv7`, "VRM Monitor —
Starter", no price attached, never referenced by any `vrm.plans` row) — safe to delete from the ONVO
test-mode dashboard whenever convenient, costs nothing left alone.


**Build:** migration 025 (§3 — six tables including `vrm.signup_requests` and `vrm.rate_limits`, five
columns including `provisioning_state` and `origin`) with a header in migration 024's style;
`tools/run_migration_025.py` (mirroring `tools/run_migration_024.py`); seed `vrm.plans` in **test
mode** from Oscar's Q1/Q13/Q14 answers, against real ONVO product/price ids created by the Step 0
probe.

**Validate:** every table exists with the intended constraints; the partial unique index on
`vrm.subscriptions` actually refuses a second live row (insert one and watch it fail);
`site_limit_source` defaults to `'manual'` on **every existing customer row** (so no existing
hand-negotiated limit is exposed to the entitlement writer); **`provisioning_state` defaults to
`'active'` and `origin` to `'admin'` on every existing row** (so no existing customer is suddenly
gated into a checkout screen — run a count and assert zero rows are `pending_subscription`);
`vrm.rate_limits`'s upsert-and-return really is atomic (fire N concurrent increments, assert the final
count is exactly N); `lib/plans.ts` still compiles and `/app/profile` still renders (nothing
customer-facing changed yet).

### Step 2 — `onvo.py` + `billing.py`, no HTTP surface (~2 days)

**Build:** `vrm_api/onvo.py` (transport: bearer auth, timeouts, typed errors that **never** carry the
key or a raw body into an exception message, retry/backoff on 5xx and 429 only, and a hard rule that
no function logs a request body); `vrm_api/billing.py` (`reconcile_customer`, `apply_entitlements`,
the status→entitlement mapping table filled in from Step 0).

**Validate — against the real test-mode account, from a script, with no UI:**
- Create an ONVO customer + subscription for a throwaway `vrm.customers` row → reconcile → the mirror
  matches ONVO field-for-field and `plan`/`site_limit` changed as expected.
- Set `site_limit_source='manual'` on that customer, reconcile again → **`site_limit` is untouched**.
  This is the trap §3.6 exists for; prove it rather than assume it.
- **Promotion (§4.5 rule 8):** a throwaway row with `provisioning_state='pending_subscription'`,
  `site_limit=0`, `site_limit_source='plan'` → subscribe → reconcile → **`provisioning_state='active'`
  and `site_limit` raised to the plan's grant, in the same write**. Then take the subscription to
  `past_due`/canceled → reconcile → **`provisioning_state` stays `'active'`** (rule 8 is one-way).
- Cancel at period end → reconcile → entitlement **retained**, `cancel_at_period_end=true`.
- Simulate the period ending (or use a short test-mode interval, per Step 0) → reconcile →
  entitlement **dropped**, and **no site was deactivated or deleted** (assert on row counts, don't
  eyeball).
- Feed the mapping an invented status string → entitlement **held**, error logged (§4.5 rule 2).
- Run two `reconcile_customer` calls concurrently → exactly one coherent final state, no interleaved
  half-write.
- **Leak check:** `ONVO_SECRET_KEY` appears in no log line and no exception message. Grep the process
  output for `_secret_key_`.

### Step 3 — `vrm_api/routers/billing.py` (~2 days; blocked on Q3, Q4, Q5) — ✅ DONE 2026-08-20

All endpoints from §5.1–5.3 built and validated live (56/56 assertions). One real design addition
beyond the plan's own text: the duplicate-create guard needed a genuine database-level mutex
(`_acquire_subscribe_lock()` in `billing.py`, claiming migration 025's own partial unique index by
inserting a placeholder row *before* ever calling ONVO) — "reconcile-before-create" alone left a real
race window under genuine concurrency, confirmed by an actual concurrent test, not just reasoning about
it. Verified independently: read the lock-acquire/release/promote functions directly, confirmed correct
handling of the failure-cleanup path (a failed ONVO call must not permanently lock a customer out) and
correct NOT NULL coverage on the placeholder insert. A third instance of the "ONVO's create endpoints
reject fields their own docs imply are optional" pattern was found (`metadata` on customer creation) —
recorded in §0.2b finding 2 alongside the two from Steps 1/2.


**Build:** all endpoints in §5.1–5.3, `vrm_api/schemas.py` models, `main.py` router registration, typed
error codes in `main.py`'s handler style (`subscription_already_exists`, `plan_not_available`,
`over_site_limit`, `billing_unavailable`).

**Validate:** each endpoint end-to-end via `curl` against test mode; the duplicate-create guard
holds (fire two creates concurrently → one subscription, one 409); a change that would put the
customer over their site limit returns `requires_confirmation` rather than silently applying; a
`pending_subscription` customer is refused a **non-`self_serve`** plan (`plan_not_available`) while an
`active` customer is not; **the tamper cases**: a valid pipeline key with another customer's
`customer_id` → 403 and nothing written; any attempt to pass an ONVO id in a body → the field does not
exist on the model, so it is rejected by construction (assert this by reading the models, and by an
actual request that tries).

### Step 4 — Webhook receiver + sweeper (~1.5 days) — ✅ DONE 2026-08-20

Built across two passes (a session-limit interruption split it — the `vrm_api` half survived intact and
was verified unchanged; only the Next.js half needed finishing). `app/api/webhooks/onvo/route.ts`
correctly fails closed on an empty/unset `ONVO_WEBHOOK_SECRET` and compares secrets via
SHA-256-then-`timingSafeEqual` (never the raw strings) — verified by reading the code directly, not
just the report. The rejected-secret path writes its own `vrm.billing_events` row and never calls
`vrm_api` at all, confirmed live (rejected requests never advanced a row past `status='received'`).
`lib/server/ratelimit.ts` fails **open** on a DB error — a deliberate, explicit choice, since rate
limiting here is an abuse control, not the auth boundary (the secret check is, and that one fails
closed) — the asymmetry is reasoned about in the code, not accidental. `_resolve_webhook_customer()`
on the `vrm_api` side was found to have generalized beyond the plan's own simplified "data.id"
description once real payload shapes were confirmed at Step 0 (`subscriptionId`/`paymentIntentId`/
`customerId`/`customer.id`, no generic `id` field) — a real, correct catch, not a deviation worth
flagging as a problem.


**Build:** `victron-monitor/web/app/api/webhooks/onvo/route.ts` (§4.1, §6.5);
`lib/server/ratelimit.ts` (§0.3, §3.8 — built here because the webhook is its first consumer and
Step 5.5 is its second); `POST /v1/billing/webhook-event` and `POST /v1/billing/reconcile-due` in
`vrm_api`.

**Validate:**
- A real test-mode renewal fires a real webhook → `billing_events` row → reconcile → invoice row.
- **Wrong secret → 401**, row written with `secret_ok=false`, **no ONVO call made** (assert the
  outbound call count, not just the response).
- **Missing secret header** behaves identically to a wrong one.
- **Empty `ONVO_WEBHOOK_SECRET` env → every request rejected**, never accepted (§6.5's fail-closed).
- Same event delivered **twice** → two rows, one coherent state.
- The rate limiter actually limits **across processes** (hit it from two shells at once; a counter
  that only works in one process is the bug §3.8 exists to prevent).
- **The headline test: disable the webhook entirely, let a renewal happen, and confirm the daily
  sweep converges the state anyway.** This is §4.4's freshness promise; if it does not hold, the
  reconciliation design is not done.
- An event for an unrelated ONVO object (e.g. a Solar Design Tool payment intent) → recorded as
  `ignored`, no error, no state change.

### Step 5 — The customer billing UI (~2.5 days; blocked on Q3, Q4, Q5, and Step 0's card-replacement finding) — ✅ DONE 2026-08-20

Built across three passes: the UI itself (plan picker, cancel/resume/address/invoices, profile card,
nav item — all confirmed live), then a real architecture fix (the SDK card widget needs a real
`subscriptionId` to exist *before* it renders, so subscribe now creates an `incomplete`-then-`trialing`
ONVO subscription immediately with no payment method, rather than requiring one upfront), then a
security fix that pass's own validation surfaced: ONVO reports a trial subscription as `trialing`
immediately even with zero payment methods attached, which meant status alone let a customer skip the
card-entry widget entirely and get a free trial. `apply_entitlements()` (§4.5) now also requires a real
payment method on file before granting anything — fixed and live-verified before Step 5.5 (public
signup) began, since that step would have turned a narrow risk into a public, repeatable one.


**Build:**
- `app/(portal)/app/billing/page.tsx` (Server Component, reads status) + `BillingManager.tsx`,
  `PlanPicker.tsx`, `PaymentMethodPanel.tsx` (hosts the ONVO SDK), `BillingAddressForm.tsx`,
  `InvoiceList.tsx`, `CancelDialog.tsx`. **`BillingManager` takes a `firstRun` prop** (derived from
  `provisioning_state`) that hides cancel/invoices/address and swaps the heading copy — the hook §1.1
  needs, built now so Step 5.5 adds no new billing UI.
- `app/api/billing/{status,subscribe,change,cancel,resume,payment-method,address,refresh}/route.ts`
  — every one following `app/api/vrm/connect/route.ts`'s shape exactly.
- `lib/server/db/billing.ts` (`import 'server-only'`, `customerId` first) and
  `lib/server/pipeline.ts` additions.
- `app/(portal)/app/layout.tsx`: a `nav_billing` item. `/app/profile`: the billing status card,
  matching the VRM card's shape.
- SDK loading: `<script src="https://sdk.onvopay.com/sdk.js">` via `next/script`, publishable key
  passed as a **prop from the server** (§6.1), `locale` bound to the customer's `ui_language`
  (a rare place where a customer's real language reaches a component even while `FORCE_LANG='en'` —
  the SDK is not our string table, so pass the real preference and comment why).
- New `lib/i18n/strings.ts` keys, **EN and ES both**, no inline literals.

**Validate:**
- Full browser round trip on test mode with a test card: subscribe → `plan`/`site_limit` update →
  upgrade → downgrade → cancel-at-period-end → resume → replace card → edit address → see invoices.
- After each action, the rendered state comes from a **server reconcile**, never from `onSuccess`
  data (verify by making `onSuccess` fire with garbage and confirming the page still shows truth).
- **Leak checks:** grep a production build for `_secret_key_` and `webhook_secret_` — zero hits. No
  new `NEXT_PUBLIC_*` var. No card-field input anywhere in the source (grep for `cvv`, `cardNumber`).
- Over-limit downgrade shows the confirmation with real numbers and, after confirming, **every
  existing site still loads and still reports**; only "add site" is blocked.
- `scripts/test-scoping.ts` extended with the §6.4 cases and passing.
- `npm run typecheck` and `npm run lint` clean.

### Step 5.5 — Public self-serve signup (~2.5 days; blocked on Step 5 and on Q14 for the seed; Q12 optional) — ✅ DONE 2026-08-20

Built across two passes (a session-limit interruption split it — the backend/session half survived
intact: `requireCustomer()`'s pending-account gate, `createOrLinkAuthUser()`'s extraction, and
`lib/server/db/signup.ts` were all already correct when the second pass picked up). Live-verified: the
full round trip (signup → staging row only, no customer yet → verify → real customer row with every
field exactly per spec → activate → password set → lands on `/app/billing` in `firstRun`), true
non-enumeration (byte-identical responses across existing-email/rate-limited/honeypot-filled cases),
the double-click race (atomic token consumption, confirmed one customer row not two), the open-redirect
guard, slug collision handling, and DB-backed rate limits surviving a dev-server restart. `AccessForm`
is fully retired — deleted, zero remaining imports, only historical comments reference it. **Known,
purely cosmetic gap, not yet fixed:** `/app/billing?plan=<id>` doesn't actually preselect that plan in
`PlanPicker.tsx` — the customer sees every plan and has to pick again. Not a security or correctness
issue, flagged for a small follow-up.


The scope amendment from Q6. Deliberately its own step, and deliberately **after** Step 5: signup's
last mile is `/app/billing`, and building the public front door before the room it opens into is how
you end up with two checkout implementations.

**Build:**
1. **The `invites.ts` refactor, first and on its own.** Extract `createOrLinkAuthUser(email)` from
   `sendInvite()` (§5.5 step 2), export `stampInvited()`, and change nothing else. **Land and verify
   this before writing any signup code** — the existing admin invite flow must be provably unchanged
   at this point, because it is the flow Oscar depends on today.
2. `lib/server/signup.ts` (flow: rate limits, honeypot, token mint/verify, the two email variants via
   the existing `renderActivationEmail()`, `verifyHumanChallenge()` seam) and
   `lib/server/db/signup.ts` (`vrm.signup_requests` CRUD, `createSelfServeCustomer()` with
   `uniqueSlug()`, `listSelfServePlans()`).
3. `app/(auth)/signup/page.tsx` + `SignupForm.tsx` + `actions.ts` (§5.5 step 1). The plan cards render
   from `listSelfServePlans()`, server-side.
4. `app/(auth)/signup/verify/route.ts` (§5.5 step 2).
5. `app/(auth)/activate/`: the `next` parameter and its open-redirect check (§5.5 step 3).
6. `lib/server/auth.ts`: the `provisioning_state` gate in `requireCustomer()` /
   `requireCustomerForRoute()`, plus `requireCustomerAllowPending()` and its three call sites (§6.4).
   **This is the highest-blast-radius edit in the phase** — it changes the behaviour of every guarded
   page at once. Do it in its own commit with its own test run.
7. Landing page wiring: `Pricing.tsx`'s "Get started" CTAs → `/signup?plan=…`, a `Nav` sign-up action.
   `AccessForm` untouched. If Q13 lands on option (a) or (c), the price copy in `Pricing.tsx` changes
   here too — **and must be checked against the seeded `vrm.plans` rows by eye, one at a time**, since
   nothing mechanically ties marketing copy to the catalogue (and this plan is not going to build
   that; see §9).
8. `login/actions.ts`: rewrite the stale *"a portal with no public signup"* comment (§0.1). The
   behaviour it justifies is unchanged and now matters more, not less — say that.
9. New `lib/i18n/strings.ts` keys, **EN and ES both**.
10. `.env.example`: `SIGNUP_IP_SALT`, and the CAPTCHA vars if Q12 says yes.

**Validate — this gate is longer than the others because it is the only public write in the product:**
- **Happy path, end to end, in a browser, with a real inbox:** `/` → "Get started" → `/signup?plan=…`
  → submit → email arrives → click → `/activate` → set password → land on `/app/billing` with the
  chosen plan preselected → enter a test card → **`provisioning_state` flips to `'active'`,
  `site_limit` becomes the plan's grant, the portal nav unlocks, and a site can be created.**
- **The `site_limit_source` trap:** confirm the new row was created with `'plan'`, not the `'manual'`
  default. Assert it in the database, not by reading the code. (A row created `'manual'` would be
  permanently stuck at `site_limit = 0` and the bug would look like "the plan didn't apply.")
- **Non-enumeration, tested by response diffing, not by inspection:** submit a brand-new email and an
  email that already belongs to a customer; capture both rendered responses and both HTTP status
  codes; **assert they are byte-identical** apart from the address echoed back. Repeat for a
  rate-limited submission.
- **The pending gate:** sign in as a `pending_subscription` customer and attempt, by direct URL and by
  direct `fetch` to `app/api/*`: `/app`, `/app/sites`, `/app/upload`, create-site, upload, generate a
  report. **All refused or redirected.** Then confirm `/app/profile` and `/app/billing` **do** work
  (they must — sign-out and password change live there).
- **Token discipline:** click the same verification link twice → exactly **one** `vrm.customers` row
  (count it), second click shows the friendly used-link page. Hand-expire a row's `expires_at` → the
  **same** page, not a different one. Tamper one character of a token → the same page again.
- **Slug collision:** sign up twice with the same company name (different emails) → two customers,
  slugs `acme` and `acme-2`, and each one's first site gets a correctly namespaced `site_id`.
- **Rate limits:** 4 submissions for one email in a day → the 4th sends no email but responds
  identically. 6 from one IP in an hour → same. Confirm the counters are in `vrm.rate_limits` and
  survive a server restart (this is the property an in-process counter would not have).
- **Abandonment:** verify an email, never set a password → `/forgot` for that address sends a working
  reset link and lands the customer at `/app/billing` (proving the "verified but never activated"
  state is not a dead end). Verify, set a password, never pay → sign out, sign back in, land on
  `/app/billing`, and confirm **no ONVO customer was ever created** for that account.
- **The admin flow is untouched:** create a customer from `/admin/customers` and send an invite. It
  must behave exactly as it did before step 1's refactor — same email, same activation, same
  `provisioning_state = 'active'` (so an Oscar-created customer never sees the checkout gate).
- `scripts/test-scoping.ts` extended with the pending-customer cases (§6.4) and passing.
- **Leak checks:** the raw signup token appears in **no** log line (grep the dev server output during
  a full run); `SIGNUP_IP_SALT` appears in no client bundle; no raw IP address is stored anywhere
  (inspect the `ip_hash` column).
- `npm run typecheck` and `npm run lint` clean.

### Step 6 — Admin + failure surfacing (~1.25 days) — ✅ DONE 2026-08-20

No `vrm_api` changes needed — every admin action reuses the existing refresh/cancel endpoints, including
confirming "Promote to active" is correctly just a refresh call (the same `apply_entitlements()` already
built handles it) rather than needing new backend logic. Verified directly: the admin-attribution log
line on Promote-to-active correctly identifies the acting admin, and the no-op case (a customer who
genuinely never paid) returns an honest "no change" message rather than a false success. `secret_ok=false`
webhook rows render with a spelled-out badge, not color alone. No card-entry field anywhere in any new
admin file (Q11), confirmed by direct grep. Admin strings stayed inline English literals; only the two
customer-facing banner keys went into `lib/i18n/strings.ts` (en+es) — the established split held.
**Honestly disclosed, not fixed**: the "fix the card → banner clears" sequence was proven via its
underlying mechanism (reconcile unconditionally overwrites `billing_status` from ONVO's real state) but
not the exact end-to-end renewal-failure narrative, since ONVO has no documented way to trigger a
renewal on demand in test mode. No authenticated-browser session was run (no browser automation in this
environment) — covered by direct-function/live-HTTP checks instead.


**Build:** `/admin/customers` billing column (plan, status, next renewal, cancel-pending) with
per-customer **Refresh** (reconcile) and **Cancel** actions — **no card entry, ever** (Q11); a
customer-facing `past_due` banner on `/app` and `/app/billing`; an over-limit banner; a
`/admin/billing-events` view (or an `/admin/activity` tab) showing recent events including
`secret_ok=false` rows, which is the only place an attempted forgery is visible.

**Plus, for signup:** an `origin` + `provisioning_state` column and filter on `/admin/customers`
("Self-serve", "Pending signup"), so Oscar can see who came in off the street and who never finished;
a **Promote to active** support action (the §7 escape hatch for "ONVO says trialing but the promotion
didn't happen") that is a deliberate, confirm-dialog action and writes a log line naming the admin; and
a small recent-signups panel reading `vrm.signup_requests` (email, created, consumed?) that is the
only place a signup spam wave is visible before it shows up in the Resend bill.

**Validate:** force a failed renewal in test mode → banner appears for the customer and in
`/admin/customers`; fix the card → banner clears on the next reconcile; admin cancel works and the
customer's next visit reflects it; a wrong-secret webhook shows up in the admin events view; a pending
signup appears under the filter and **Promote to active** moves it (and logs it); the recent-signups
panel shows a submission within seconds of one being made.

### Step 7 — Scheduling + docs (~1 day) — ✅ DONE 2026-08-21 — **PHASE 16 COMPLETE**

`.github/workflows/billing-reconcile.yml` — this repo's first GitHub Actions workflow (Phase 15's own
Step 7 was deferred and never built). Daily cron + manual dispatch, calling the existing
`reconcile-due` sweeper and a new `prune-signups` endpoint (§3.7/§3.8's retention job — genuinely wired
into the schedule, not left as a TODO). Verified directly: reads secrets only via `${{ secrets.NAME }}`,
zero `actionlint` issues, the prune endpoint live-tested with real backdated rows (deleted exactly the
stale ones, left fresh ones untouched). Docs updated: `vrm_api/README.md`, `victron-monitor/web/README.md`
(§1.1's public-route inventory reproduced verbatim), `ARCHITECTURE.md`, `CONTEXT.md`, `PHASES.md` all
now reflect Phase 16 as shipped. Final phase-wide check passed: `git diff --stat -- pages/ victron/` is
empty.


**Build:** `.github/workflows/billing-reconcile.yml` (`cron:` daily, `PIPELINE_API_URL` +
`PIPELINE_API_KEY` from repo secrets, non-zero exit on non-2xx so a failure is visible in the Actions
tab — the same shape PLAN_PHASE15.md §8 Step 7 specifies), **and the prune job for
`vrm.signup_requests` / `vrm.rate_limits`** (§3.7, §3.8 — the same daily workflow, one extra call; a
retention job that never runs is a retention policy that doesn't exist). Docs: `vrm_api/README.md` (the
new router, the env vars, the trust boundary for the webhook), `victron-monitor/web/README.md` (**a
"Public surface" section listing §1.1's route inventory verbatim** — the list is only useful if it is
somewhere a reviewer will look), `.env.example` (`ONVO_SECRET_KEY`, `ONVO_PUBLISHABLE_KEY`,
`ONVO_WEBHOOK_SECRET`, `ONVO_MODE`, `SIGNUP_IP_SALT`, CAPTCHA vars if any), `ARCHITECTURE.md` (new
boxes: `vrm_api` → ONVO, outbound; ONVO → Next.js, inbound webhook; **and the public signup path, which
is the first arrow into this system that starts outside it**), `CONTEXT.md`, `PHASES.md` Phase 16
status.

**Validate:** a real scheduled run reconciles every due customer, isolates one deliberately broken
customer's failure without blocking the rest, and stays within a sane request budget; the prune job
deletes an expired staging row and leaves a fresh one alone. `git diff --stat` shows **no** changes
under `pages/` or `victron/`; `streamlit run app.py` still works.

---

**Estimate:** **13–18 days** at this repo's part-time pace (Step 0: 1 + support turnaround; Steps 1–5:
9–11; Step 5.5: 2.5; Step 6: 1.25; Step 7: 1). Up from the pre-amendment 11–15: signup adds ~2.5 days
of its own plus ~0.5 spread across Steps 1, 6 and 7. Step 0's card-replacement finding remains the
largest single schedule risk; Step 5.5's `requireCustomer()` change is the largest single *blast-radius*
risk, which is why it is isolated into its own commit with its own test run.

---

## 9. Explicit non-goals

- **One-off payments / Checkout Sessions.** This phase is subscriptions only. ONVO's Checkout
  Sessions resource is not used. **This is why `single_report` gets no `vrm.plans` row** and is not
  purchasable from `/signup` (Q14) — the landing page's "Get a report" CTA keeps going to the contact
  form.
- **Anything touching the Streamlit Solar Design Tool's ONVO usage** —
  `project_payments.onvo_commission_pct`, `onvo_iva_pct`, `config.DEFAULT_ONVO_COMMISSION`. Different
  product, different money, not reused, not refactored, not "unified."
- ~~**Self-serve signup.**~~ **In scope as of Q6's answer** (§1.1, §3.7, §5.5, §6.6, Step 5.5). What
  remains explicitly **out** of scope *within* signup:
  - **Social / OAuth login** (Google, Apple, "sign in with Victron"). Email + password only, through
    the existing Supabase Auth path. Adding a provider is a Supabase dashboard toggle plus a callback
    route, and it is not free: it introduces a second identity source that `resolveRole()`'s
    `auth_user_id` linkage has never seen, and a second set of "this email already exists" cases on
    top of the three `invites.ts` already handles. Worth doing later, deliberately, not smuggled in.
  - **Multi-user accounts / team invites.** One `vrm.customers` row still has exactly one login. A
    customer cannot invite a colleague. This is the same constraint the product has today; signup does
    not change it, and nothing in this plan should be built "ready for" it.
  - **Self-serve account deletion or data export.** A cancel is a cancel; deleting an account remains
    an Oscar operation. (Worth a future phase on its own terms — there are real obligations here —
    but not one to improvise alongside a payment integration.)
  - **Self-serve `account_type` change.** It is chosen once at signup and thereafter gates which plans
    are offered; it stays in `ADMIN_CUSTOMER_WHITELIST` only. A customer who picked wrong emails
    Oscar. (It is self-declared segmentation, not a security boundary — which is precisely why it does
    not need a customer-facing editor.)
  - **Email-domain blocklists, disposable-address detection, "corporate email required."** Q2's
    card-upfront trial already makes a throwaway inbox worthless, and every such list eventually
    rejects a real customer (§6.6).
  - **Automatic deletion of abandoned signups.** `vrm.signup_requests` is pruned; `vrm.customers` rows
    are not. An unfinished signup is a lead, not garbage (§5.5).
  - **Any mechanism tying the landing page's marketing copy to `vrm.plans`.** The prices in
    `Pricing.tsx` stay hand-written and are checked by eye against the seed (Step 5.5). Generating
    marketing copy from the billing catalogue is a genuinely good idea and a genuinely separate one.
- **Factura electrónica / Hacienda filing.** Flagged as Q7. If required and not provided by ONVO,
  it is its own phase — do not improvise it here.
- **Refunds, credits, coupons, promo codes, marketplace/split payments, SINPE Móvil.** All exist in
  ONVO; none are in this phase. (Note for whoever gets the first "do you have a discount code?" email
  the week after signup opens: the answer is a phase, not a field.)
- **Dunning email sequences, and abandoned-signup nudge emails** (§7).
- **Invoice PDF generation.** We mirror and display ONVO's renewal records; we do not render
  documents.
- **Multi-currency per customer**, or changing currency after subscribing.
- **Usage-based / metered billing.** Plans are flat, site-limited. **If Q13 resolves to option (b)
  (true per-site pricing), this non-goal is violated and Phase 16 needs re-planning** — that is exactly
  why Q13 blocks Q1.
- **Automatic site deactivation on downgrade.** Stated as a non-goal, not just an omission (§4.5
  rule 6).
- **Any change to `victron/`, `pages/`, `app.py`, the `monitoring` schema, Node-RED, or Apps Script.**
- **RLS policies, a real job queue, a test framework.** Unchanged from PLAN_PHASE14/15's positions.
  (Note that public signup does **not** change the RLS calculus: the signup route is public over HTTP
  but reaches the database through the service-role key from `server-only` code, exactly like every
  other write in this app — `anon` still holds zero grants on `vrm`.)
- **Storing card data of any kind** (§6.3).

---

## 10. Risks and tradeoffs

| Risk | Blast radius | How this plan addresses it |
|---|---|---|
| **Building against a guessed endpoint shape** | Wasted work, or worse: code that "works" in test and fails on a field we assumed | §0.2 marks every unverified claim `[V]`; Step 0 is a hard gate; the plan explicitly refuses to name a path it hasn't seen |
| **Charging the wrong customer's card** | Catastrophic, unrecoverable trust damage | §6.4 control 3: no ONVO id is ever accepted from a request; every id is looked up from a tenancy-checked mirror row. `test-scoping.ts` extended |
| **A forged webhook mutates billing state** | An attacker with a leaked secret grants themselves a plan, or cancels a paying customer's | Structurally impossible under §0.5: no state is ever written from an event payload. A forgery causes one redundant read. Plus 401 + constant-time compare + rate limit + an audit row |
| **A webhook is lost and a customer silently loses (or keeps) access** | Silent, and discovered by the customer | §4.4's four triggers, with the daily sweep as the backstop; the Step 4 gate literally disables the webhook and requires convergence anyway |
| **Out-of-order events corrupt state** | Stale entitlement that never self-corrects | Read-through (§0.5) plus §4.3's fetch-time ordering guard. Payload order is irrelevant because payloads are never applied |
| **A reconcile stomps a hand-negotiated `site_limit`** | A customer on a special deal silently loses sites' worth of allowance | `site_limit_source` (§3.6), defaulting to `'manual'` so **every existing row is protected by the migration itself**. Proven, not assumed, in Step 2's gate |
| **ONVO adds a `status` value we don't know** | A paying customer locked out of their own data by a third party's enum change | §4.5 rule 2: unknown status → hold entitlement + log loudly. Deliberately generous, with the asymmetry argued rather than assumed. And **no CHECK on `status`** (§3.3), so a sync never fails outright |
| **Double-charging via a duplicated subscription** | Direct financial harm | Three independent guards (§5.4), none of which depends on the unverified `Idempotency-Key` |
| **Card data reaching our servers** | PCI scope, an entirely different compliance posture | §6.3's absolute rules + a Step 5 grep gate; and an explicit "stop and escalate" if Step 0 finds such a flow |
| **Punching a public route into `vrm_api`** | Slow erosion of a security posture that is currently exact | §4.1 puts the public surface on the app that is already public; `vrm_api` still ends this phase with exactly one unauthenticated route, **signup included** |
| **ONVO downtime taking the portal with it** | The whole product looks broken because billing is | Mirror-first reads: every page renders from our own tables. ONVO being unreachable degrades *changing* a subscription, never *using* the product. **One exception created by signup:** a new customer who cannot reach ONVO cannot finish signing up. They keep their account and can finish later; the copy must say that rather than implying the signup failed |
| **`timingSafeEqual` throwing on unequal lengths** | A crash that leaks length, in the one function whose whole job is not leaking | §6.5: hash both sides to fixed-length digests before comparing. Called out because it is the standard mistake in this exact pattern |
| **Billing logic drifting into the Next.js layer** | Two places to look, one of them without the secret key | §4.1: the route handler parses, verifies, forwards, responds — nothing else. Stated as a review criterion |
| **Scope creep into invoicing/tax** | A CR-specific compliance problem discovered after the first live charge | Q7 asked now, explicitly, before any code |
| **The `requireCustomer()` gate change breaks every portal page at once** | The entire signed-in product, for everyone, in one commit | It is deliberately the *default* (fail-closed) and the opt-out is explicit and three-call-sites wide (§6.4). Isolated into its own commit in Step 5.5 with its own full test run. And `provisioning_state` defaults to `'active'`, so **no existing customer's behaviour changes at all** — the gate is unreachable for every row that existed before this phase |
| **Signup spam burning Resend reputation** | Deliverability damage that outlives the attack — every invite and report email is affected, and it is slow to repair | §6.6's three-layer rate limit (email/IP/global), fail-closed at the global bucket, database-backed so it works on serverless; honeypot; a CAPTCHA seam ready if it is not enough (Q12). Step 6's recent-signups panel is the detection surface |
| **Account enumeration through the signup form** | A verified list of this product's customers' email addresses, harvestable by anyone | Identical responses on every branch — existing/new, limited/not, expired/used/invalid — enforced at the function that knows the real answer (the `sendPasswordReset()` pattern), and tested by **diffing the responses** in Step 5.5's gate, not by reading the code |
| **A stranger squatting a `slug`** | `slug` is permanent and namespaces every `site_id`; a taken slug can never be recovered for the customer who should have had it | Verification before insertion (§3.7) means a slug costs an attacker a working mailbox and a rate-limit slot each. `uniqueSlug()` means a collision is invisible rather than fatal. Not perfectly preventable, and not worth more than this |
| **Trial abuse: many trials, one card** | Free service, bounded by 7 days each | Card-required-upfront (Q2) already stops the disposable-email version, which is the version that scales. The residual — one person, one card, many emails — is manual, slow, and visible in `/admin`. **Deliberately not defended against**; revisit only if it actually happens |
| **A phantom account from an abandoned signup** | Support confusion, and an account with capabilities nobody paid for | The whole of §5.5's sequencing: no `vrm.customers` row before email verification, no ONVO object before a card, `site_limit = 0` and the `provisioning_state` gate until a reconcile confirms an entitled subscription. The abandonment table in §5.5 enumerates every stopping point and what it leaves |
| **Landing-page price ≠ checkout price** | A chargeback conversation, or worse, sixty seconds after the customer decided to trust us | **Q13, raised before any code.** And Step 5.5's gate requires checking the copy against the seeded catalogue by eye, because nothing mechanically ties them (§9) |

---

## 11. Conventions the coder must follow

All of `PLAN_PHASE14.md` §3 and `PLAN_PHASE15.md` §12 apply unchanged. Additions:

- **Read `node_modules/next/dist/docs/` before writing Next.js code** — `victron-monitor/web/AGENTS.md`
  warns this version has breaking changes relative to training data. Applies especially to
  `next/script`, Server Actions, and route-handler signatures.
- **Never write `vrm.customers.plan` or `site_limit` from anywhere except `apply_entitlements()`,
  admin, or `createSelfServeCustomer()`'s single insert.** Three writers, named in §0.1, and no
  fourth. If a new call site seems necessary, the design is wrong — come back here.
- **`lib/server/signup.ts` and `lib/server/db/signup.ts` must never import `lib/server/db/admin.ts`.**
  That module's own header says only `app/(admin)/admin/**` may import it, and it returns
  cross-customer data by design. Signup needs one narrow insert, not the admin surface. (There is no
  build-time enforcement of this — see admin.ts's own honest note about that — so it is a review
  criterion.)
- **Never parse our own POST's response into state.** Every mutation ends in a reconcile. If you find
  yourself reading a `status` out of a create-subscription response, stop. The same rule is why
  `provisioning_state` is promoted by `apply_entitlements()` and not by the subscribe endpoint.
- **The raw signup token is never logged, never stored, and never put in an error message.** Only its
  `sha256` reaches the database. The same rule PLAN_PHASE14.md §3 already states for `token_hash`.
- **A public endpoint's response must not vary with facts the caller shouldn't know.** Existing vs.
  new email, rate-limited vs. not, expired vs. used vs. forged token — one response each. Where a
  branch is unavoidable, put it in the function that knows the real answer (as
  `sendPasswordReset()` does), not in the caller.
- **Every new customer-facing string goes in both `en` and `es`** in `lib/i18n/strings.ts`, even
  though `FORCE_LANG='en'` means only English renders today. Signup pages follow `(auth)`'s
  English-only convention (`const LANG = 'en'`) since the visitor's preference isn't known yet — but
  the keys still go in both dicts.
- **Money is `bigint` minor units end to end**, formatted only at the edge. No floats, anywhere, for
  a currency amount.
- **Comment every place an ONVO id is looked up rather than accepted**, naming §6.4 control 3 — the
  same discipline PLAN_PHASE15.md required for installation ids. And comment the one place *our* id
  (`vrm.plans.id`) *is* accepted from a URL, naming §6.4's clarification, because it will look wrong.
- **`vrm_api/onvo.py` never logs a request body or a header.** Exceptions carry the HTTP status and
  the endpoint, nothing else — same rule as `victron/vrm_remote.py`.
- Existing git rules: stage in batches of 5–10, `timeout 90 git commit`.

---

## 12. Step 0 for the coder: make Phase 16 legible in `PHASES.md`

The architect agent has no `Edit` tool and `PHASES.md` is >1000 lines, so these mechanical edits are
handed over verbatim, same as PLAN_PHASE14/15 did. **Do these before any code.**

**Edit 1 — status table.** After the Phase 15 row (currently line ~26), add:

```
| 16 — VRM Monitor: public signup + customer self-service billing on ONVO Pay | ⬜ Not started (see PLAN_PHASE16.md; Step 0 blocked on an ONVO test-mode account from Oscar, plus tier/pricing decisions Q1/Q13/Q14) |
```

**Edit 2 — a new section**, immediately after the Phase 15 section and before `## Timeline summary`:

```markdown
## Phase 16 — VRM Monitor: public signup + customer self-service billing on ONVO Pay (13–18 days, scoped 2026-08-19)

**Goal:** a stranger can sign up from the landing page, verify their email, enter a card, and be a
working customer minutes later — and an existing customer manages their own subscription (upgrade,
downgrade, cancel), the card on file, and their billing address from `/app/billing`. And
`vrm.customers.plan`/`site_limit` stop being values a human types into `/admin/customers` and become a
derived consequence of a real, paid, verified ONVO subscription.

Full build plan, the verified-vs-unverified ONVO API findings, and per-step validation gates:
[`PLAN_PHASE16.md`](PLAN_PHASE16.md). Not duplicated in full here.

### Why this phase exists

Every plan change today is Oscar editing a row, and every customer arrives because Oscar invited them.
That doesn't scale past the people he can remember, and it means the product has no revenue mechanism
and no acquisition mechanism of its own — `plan` and `site_limit` are assertions, not consequences of
anyone having paid.

### Decisions locked (see PLAN_PHASE16.md §0.5, §3, §4, §5.5, §6)

- **ONVO is the source of truth; our database is a cache; webhooks are cache-invalidation hints and
  nothing more.** ONVO documents no `subscription.created`/`.updated`/`.canceled` event, warns events
  can arrive out of order, and states no retry policy — so state is never written from an event
  payload; it is always re-read from ONVO with our own secret key. This also makes a forged webhook
  structurally unable to change anything.
- **Four reconcile triggers** — post-mutation, webhook, on-read staleness, and a daily GitHub Actions
  `cron:` sweep (the mechanism Phase 12 locked) — with a stated promise: entitlement is correct
  within one page load or 24 hours, *even if every webhook is lost*.
- **Public signup verifies the email before anything exists.** A submission writes only a
  `vrm.signup_requests` staging row and sends one email; the `vrm.customers` row is created only when
  a single-use, hashed, 24-hour token is redeemed; the ONVO customer and subscription are created only
  when the visitor enters a card; and the account is promoted to a real tenant only when a *reconcile*
  observes an entitled subscription. An abandoned signup leaves nothing usable and no ONVO object.
- **The signup flow reuses the existing invite/activation machinery** (`generateLink` → `/activate` →
  set password → `markActivated()`) rather than paralleling it. The only refactor is extracting the
  "email already exists" ladder out of `sendInvite()` so both callers share one implementation.
- **A pending account grants nothing**: `site_limit = 0`, and `requireCustomer()` itself — the default,
  fail-closed guard every portal page already calls — redirects it to the billing page. Two
  independent mechanisms, neither relying on the other.
- **No ONVO object id is ever accepted from a request body.** Every id is looked up from a mirror row
  already scoped to a tenancy-checked customer — the direct analogue of Phase 15's installation-id
  binding, and here it is what stands between us and charging the wrong person's card.
- **No card data ever touches our servers.** ONVO's web SDK (`sdk.onvopay.com/sdk.js`) renders the
  card form; our servers hold opaque ids only. Card entry exists in exactly one place in the codebase —
  which is why signup ends at `/app/billing` rather than getting a checkout page of its own.
- **Not Vault.** ONVO customer/subscription/payment-method ids are opaque identifiers, not
  credentials — ONVO's own SDK takes `customerId` client-side. Migration 024's Vault machinery is for
  things that grant access on their own, and is deliberately not extended here.
- **`site_limit_source`** (new column, defaulting to `'manual'`) protects every existing
  hand-negotiated `site_limit` from being overwritten by the first entitlement run.
  **`provisioning_state`** and **`origin`** (new, defaulting to `'active'`/`'admin'`) mean no existing
  customer's behaviour changes at all when signup ships.
- **A downgrade never deactivates or deletes a site.** An over-limit customer keeps everything and is
  simply blocked from adding more.

### Explicit non-goals

One-off payments/Checkout Sessions (so the $29 single report is not purchasable at signup), the Solar
Design Tool's unrelated `onvo_commission_pct` columns, social/OAuth login, multi-user accounts,
self-serve account deletion, disposable-email blocklists, factura electrónica/Hacienda filing,
refunds/coupons/marketplace/SINPE, dunning and abandoned-signup emails, invoice PDFs, metered billing,
automatic site deactivation, and any change to `victron/`, `pages/`, or `app.py`.

### Open questions for Oscar (see PLAN_PHASE16.md §0.6)

Ten of the original eleven are answered. Still open: the exact tier list and price points (Q1) —
itself blocked on whether the landing page's advertised **per-site** pricing or the schema's **flat
per-tier** model is the real one (Q13); whether Costa Rican electronic invoicing is required and
whether ONVO provides it (Q7, potentially its own phase); whether to enable a CAPTCHA on the public
signup form and whose (Q12, non-blocking — the seam is built either way); and which tiers are
self-serve versus hand-negotiated (Q14 — recommended: Starter and Growth yes, Fleet "talk to us",
single report not sold as a subscription at all).
```

**Edit 3 — timeline table**, after the Phase 15 row:

```
| 16 | VRM Monitor: public signup + customer self-service billing on ONVO Pay | 13–18 | Whenever needed — triggered by the first plan change Oscar doesn't want to make by hand, or the first customer he'd rather not onboard personally |
```

**Edit 4 — critical path notes**, after the Phase 15 paragraph:

```
**Phase 16 (public signup + ONVO billing) is off the critical path but is the first phase that makes
the VRM Monitor product self-sustaining**: until it lands, every plan change is a manual database edit
and every customer is an invitation Oscar sends by hand — the product has neither a revenue mechanism
nor an acquisition mechanism of its own. Like Phase 15 it depends on Phase 14's web app, `vrm_api`,
and tenancy model. Unlike every previous phase, its failure modes are financial rather than
informational, and it opens this system's first door that starts outside it — which is why its plan
spends most of its length on reconciliation, tenancy, and the trust boundary rather than on features.
```

**Validate:** both files render on GitHub; `git diff` on `PHASES.md` shows only additions.
