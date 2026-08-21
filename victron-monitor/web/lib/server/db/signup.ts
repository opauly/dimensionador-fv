import 'server-only';

// Narrow data layer for the public signup flow (PLAN_PHASE16.md §0.3,
// §5.5). Two — and only two — things live here:
//   1. `vrm.signup_requests` CRUD — the staging table (§3.7) an
//      unverified signup lives in before anything real exists.
//   2. The ONE `vrm.customers` INSERT signup is ever allowed to perform
//      (`createSelfServeCustomer()`) — a brand-new, heavily-commented
//      insert that is NOT `lib/server/db/admin.ts:createCustomer()`
//      (admin-only, §11) and is not reachable from any customer-facing
//      update path (`lib/server/db/customers.ts`'s `PROFILE_WHITELIST`
//      stays untouched by this file).
// Plus the public plan-list read (§5.5 step 4) — data-layer-shaped in the
// same way, so it lives here rather than a third file.
//
// This module must NEVER import `lib/server/db/admin.ts` (§0.3, §11) — a
// review criterion, not a build-time check (admin.ts's own header note
// about the same limitation).
import crypto from 'node:crypto';
import { getSupabaseAdmin } from '@/lib/server/supabase';
import { slugify } from '@/lib/slug';
import type { AccountType, CustomerRecord, Lang } from './types';

// ── vrm.signup_requests ──────────────────────────────────────────────────

export type SignupRequestRecord = {
  id: string;
  email: string;
  token_hash: string;
  name: string;
  account_type: AccountType;
  plan_id: string | null;
  ui_language: Lang;
  ip_hash: string | null;
  user_agent: string | null;
  created_at: string;
  expires_at: string;
  consumed_at: string | null;
  customer_id: string | null;
};

export type NewSignupRequest = {
  /** Already lowercased by the caller (`lib/server/signup.ts`) — this
   * module trusts its inputs and normalizes nothing itself, matching
   * `customers.ts`'s "the caller decides, this file just writes" shape. */
  email: string;
  tokenHash: string;
  name: string;
  accountType: AccountType;
  planId: string | null;
  uiLanguage: Lang;
  ipHash: string | null;
  userAgent: string | null;
  /** ISO 8601 — `created_at + 24h`, computed by the caller. */
  expiresAt: string;
};

export async function insertSignupRequest(fields: NewSignupRequest): Promise<void> {
  const { error } = await getSupabaseAdmin()
    .schema('vrm')
    .from('signup_requests')
    .insert({
      email: fields.email,
      token_hash: fields.tokenHash,
      name: fields.name,
      account_type: fields.accountType,
      plan_id: fields.planId,
      ui_language: fields.uiLanguage,
      ip_hash: fields.ipHash,
      user_agent: fields.userAgent,
      expires_at: fields.expiresAt,
    });
  if (error) throw error;
}

/**
 * Whether ANY `vrm.customers` row already claims `email` as its login
 * (case-insensitive — matches migration 021's own partial unique index on
 * `lower(auth_email)`). This is the ONLY thing signup is allowed to learn
 * about an existing account before a token exists — used once, at Step 1,
 * to choose "stage a new signup" vs. "send a you-already-have-an-account
 * email" (PLAN_PHASE16.md §5.5 step 1) — never surfaced to the caller
 * either way (§6.6 non-enumeration: `lib/server/signup.ts` is the only
 * thing that ever sees this boolean, and it returns the identical
 * `{submitted:true}` regardless of what it did with it).
 */
export async function customerExistsByEmail(email: string): Promise<boolean> {
  const { data, error } = await getSupabaseAdmin()
    .schema('vrm')
    .from('customers')
    .select('id')
    .ilike('auth_email', email)
    .limit(1);
  if (error) throw error;
  return (data?.length ?? 0) > 0;
}

/**
 * Atomically redeems a signup token: `consumed_at` is set in the SAME
 * statement that checks it's unset and unexpired (a single conditional
 * `UPDATE ... WHERE token_hash = $1 AND consumed_at IS NULL AND
 * expires_at > now()`, via PostgREST's chained filters — not a
 * check-then-write in application code), so a double-clicked verification
 * link can create at most one `vrm.customers` row (PLAN_PHASE16.md §5.5
 * step 2, §6.6's own "double-click" gate). Returns `null` for all three of
 * "already used," "expired," and "never existed" — deliberately
 * indistinguishable to the caller, which shows the same friendly page for
 * all three (§5.5 step 2: "Not three different messages").
 */
export async function consumeSignupRequest(tokenHash: string): Promise<SignupRequestRecord | null> {
  const nowIso = new Date().toISOString();
  const { data, error } = await getSupabaseAdmin()
    .schema('vrm')
    .from('signup_requests')
    .update({ consumed_at: nowIso })
    .eq('token_hash', tokenHash)
    .is('consumed_at', null)
    .gt('expires_at', nowIso)
    .select('*');
  if (error) throw error;
  const rows = (data ?? []) as SignupRequestRecord[];
  return rows[0] ?? null;
}

/** Diagnostics + support only (§3.7) — never worth failing the signup
 * over if this write itself fails; the caller treats it as best-effort. */
export async function linkSignupRequestToCustomer(id: string, customerId: string): Promise<void> {
  const { error } = await getSupabaseAdmin().schema('vrm').from('signup_requests').update({ customer_id: customerId }).eq('id', id);
  if (error) throw error;
}

// ── The one vrm.customers INSERT (§5.5 step 2) ──────────────────────────

export type CreateSelfServeCustomerFields = {
  name: string;
  accountType: AccountType;
  /** Verified by the redeemed signup token — lowercased already. */
  authEmail: string;
  uiLanguage: Lang;
};

function isSlugUniqueViolation(error: { code?: string; message?: string }): boolean {
  return error.code === '23505' && /slug/i.test(error.message ?? '');
}

const MAX_SLUG_SUFFIX_ATTEMPTS = 50;

/**
 * The one `vrm.customers` INSERT signup is ever allowed to perform
 * (PLAN_PHASE16.md §5.5 step 2, §0.1, §11 — "three writers of plan/
 * site_limit ... and no fourth"). Every field value below is fixed by the
 * plan, not derived from caller input beyond
 * name/accountType/authEmail/uiLanguage:
 *
 *   - `plan='trial'`, `site_limit=0` EXPLICITLY — NEVER
 *     `lib/plans.ts:planSiteLimit()`, which fails OPEN on an unrecognized
 *     plan string (§0.1) and would be catastrophic here.
 *   - `site_limit_source='plan'` — load-bearing (§3.6): a row created with
 *     the 'manual' default would have `site_limit` frozen at 0 forever,
 *     because `apply_entitlements()` would refuse to ever raise it.
 *   - `provisioning_state='pending_subscription'`, `origin='self_serve'`.
 *   - `active=true` — required for `resolveRole()` to resolve this row at
 *     all (§0.1) — a pending signup must be able to sign in and reach
 *     `/app/billing`, just nothing else (§6.4's pending-account gate).
 *   - `contact_email` is a deliberate COPY of `authEmail`, not an alias
 *     (§3.2/§5.5 step 2) — the app's three email columns (`auth_email`,
 *     `contact_email`, `vrm.billing_customers.billing_email`) stay three
 *     columns even when they start out identical.
 *
 * Does NOT touch `auth_user_id`/`invited_at`/`activated_at` — those are
 * invite-flow state, stamped by `lib/server/invites.ts` once the signup
 * verify handler calls `createOrLinkAuthUser()` + `stampInvited()`, the
 * same rule `admin.ts:createCustomer()` already follows for the identical
 * reason.
 *
 * `uniqueSlug` collision handling: `slugify(name)`, then `-2`, `-3`, ... up
 * to `MAX_SLUG_SUFFIX_ATTEMPTS`, then a random 6-hex-char suffix as a last
 * resort. `vrm.customers.slug` is `UNIQUE` and is the PERMANENT namespace
 * of every `site_id` this customer will ever mint (§0.1) — unlike
 * `admin.ts:createCustomer()`'s bare `slugify(name)` (fine when Oscar sees
 * the duplicate-key error and retypes), nobody is watching a self-serve
 * signup who could retype anything, so collisions are resolved
 * automatically. Retried against the ACTUAL insert's unique-violation
 * error (not just a pre-check), so a race between two concurrent signups
 * for the same name is closed by Postgres, not by a check-then-write gap
 * in this function. If `slugify()` itself throws (a name with no
 * ASCII-able characters at all — it throws by design, `lib/slug.ts`),
 * falls back to a random slug rather than rejecting the signup: the slug
 * is an internal identifier, not the display name.
 */
export async function createSelfServeCustomer(fields: CreateSelfServeCustomerFields): Promise<CustomerRecord> {
  let base: string;
  try {
    base = slugify(fields.name);
  } catch {
    base = `customer-${crypto.randomBytes(4).toString('hex')}`;
  }

  const admin = getSupabaseAdmin();
  const baseRow = {
    name: fields.name,
    account_type: fields.accountType,
    plan: 'trial',
    site_limit: 0,
    site_limit_source: 'plan',
    provisioning_state: 'pending_subscription',
    origin: 'self_serve',
    active: true,
    auth_email: fields.authEmail,
    contact_email: fields.authEmail,
    ui_language: fields.uiLanguage,
  };

  for (let attempt = 1; attempt <= MAX_SLUG_SUFFIX_ATTEMPTS + 1; attempt++) {
    const slug = attempt === 1 ? base : `${base}-${attempt}`;
    const { data, error } = await admin
      .schema('vrm')
      .from('customers')
      .insert({ ...baseRow, slug })
      .select('*')
      .single();
    if (!error) return data as CustomerRecord;
    // Only retry on a slug collision specifically — any other error
    // (including a race on the `lower(auth_email)` partial unique index,
    // which Step 1 already checked and should therefore be vanishingly
    // rare) propagates to the caller, which turns it into the same
    // friendly "link used" page rather than a raw error, after logging it
    // server-side (`app/(auth)/signup/verify/route.ts`).
    if (!isSlugUniqueViolation(error)) throw error;
  }

  // Exhausted the small, deterministic suffix range — last-resort random
  // suffix (§5.5 step 2's own named fallback), astronomically unlikely to
  // collide itself; if it somehow still does, this throws and the caller
  // handles it exactly like any other unexpected error.
  const fallbackSlug = `${base}-${crypto.randomBytes(3).toString('hex')}`;
  const { data, error } = await admin
    .schema('vrm')
    .from('customers')
    .insert({ ...baseRow, slug: fallbackSlug })
    .select('*')
    .single();
  if (error) throw error;
  return data as CustomerRecord;
}

/** Rollback helper for the `already_linked_elsewhere` race
 * (PLAN_PHASE16.md §5.5 step 2) — deletes the `vrm.customers` row this
 * module just inserted, when `createOrLinkAuthUser()` reports that the
 * email is claimed by a DIFFERENT customer than the one just created
 * (documented there as an expected-rare race, not a bug). Not a general
 * "delete a customer" capability — only ever called immediately after
 * `createSelfServeCustomer()`, on the row it just returned, within the
 * same request. */
export async function deleteSelfServeCustomer(customerId: string): Promise<void> {
  const { error } = await getSupabaseAdmin().schema('vrm').from('customers').delete().eq('id', customerId).eq('origin', 'self_serve');
  if (error) throw error;
}

// ── The public plan list (§5.5 step 4) ──────────────────────────────────

export type SelfServePlanOut = {
  id: string;
  plan_key: string;
  billing_interval: string;
  currency: string;
  amount_minor: number;
  site_limit: number | null;
};

function onvoMode(): string {
  return process.env.ONVO_MODE ?? 'test';
}

/**
 * The `/signup` Server Component's own plan picker — called directly, no
 * new HTTP endpoint (§5.5 step 4: "there is no browser-side fetch to
 * expose in the first place if the page renders the list server-side").
 * `onvo_price_id`/`onvo_product_id` are NEVER selected and never leave the
 * server — no reason for the public internet to hold a map of our ONVO
 * catalogue (§5.5 step 4's own note; the omission costs nothing since
 * nothing downstream of this function needs them).
 */
export async function listSelfServePlans(accountType: AccountType): Promise<SelfServePlanOut[]> {
  const { data, error } = await getSupabaseAdmin()
    .schema('vrm')
    .from('plans')
    .select('id, plan_key, billing_interval, currency, amount_minor, site_limit')
    .eq('active', true)
    .eq('self_serve', true)
    .eq('mode', onvoMode())
    .contains('account_types', [accountType])
    .order('sort_order', { ascending: true });
  if (error) throw error;
  return (data ?? []) as SelfServePlanOut[];
}

export type FeaturedSelfServePlanIds = { starter: string | null; growth: string | null };

/**
 * The landing page's own "Get started" buttons need a real
 * `vrm.plans.id` to preselect (§1.1: `href="/signup?plan=<vrm.plans.id>"`)
 * — not the marketing plan_key, an actual DB row. Picks the MONTHLY row
 * for each tier (the number shown big on the pricing card); `/signup`
 * itself lists every self-serve plan (including annual) regardless of
 * which one a visitor arrived with preselected. `null` for a tier that
 * isn't currently seeded/self-serve/active in this `ONVO_MODE` — the
 * caller falls back to a bare `/signup` link rather than a dead id.
 */
export async function getFeaturedSelfServePlanIds(): Promise<FeaturedSelfServePlanIds> {
  const { data, error } = await getSupabaseAdmin()
    .schema('vrm')
    .from('plans')
    .select('id, plan_key')
    .eq('active', true)
    .eq('self_serve', true)
    .eq('mode', onvoMode())
    .eq('billing_interval', 'month')
    .in('plan_key', ['starter', 'growth']);
  if (error) throw error;
  const rows = (data ?? []) as { id: string; plan_key: string }[];
  return {
    starter: rows.find((r) => r.plan_key === 'starter')?.id ?? null,
    growth: rows.find((r) => r.plan_key === 'growth')?.id ?? null,
  };
}
