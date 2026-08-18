import 'server-only';

// Customer-record half of the tenant-scoping choke point
// (PLAN_PHASE14.md §1.2 rule 4 / §2 Step 4). `getCustomer()` is read-only
// and takes the row's own id (already trusted — it comes from
// `getSessionContext().customerId`, never from a request body); the write
// side, `updateCustomerProfile()`, is where the whitelist lives.
import { getSupabaseAdmin } from '@/lib/server/supabase';
import type { CustomerRecord, Lang } from './types';

export async function getCustomer(customerId: string): Promise<CustomerRecord> {
  const { data, error } = await getSupabaseAdmin()
    .schema('vrm')
    .from('customers')
    .select('*')
    .eq('id', customerId)
    .single();
  if (error) throw error;
  return data as CustomerRecord;
}

// ── The profile whitelist, enforced twice ───────────────────────────────
//
// 1. At the type level: `ProfileUpdateFields` is built from this exact key
//    list via `Pick<CustomerRecord, ...>`, so passing `{ plan: 'fleet' }` (or
//    `site_limit`, `active`, `slug`, `auth_user_id`, `auth_email`) to
//    `updateCustomerProfile()` is a compile error — TypeScript's excess-
//    property check catches it on an object literal at the call site, and
//    even a variable typed as `ProfileUpdateFields` structurally can't carry
//    those keys in the first place.
// 2. At runtime, in case a caller routes around the type check with an `as
//    any`/`as ProfileUpdateFields` cast: `pickWhitelisted()` below only
//    copies keys that are *both* present on the incoming object *and* in
//    `PROFILE_WHITELIST`, so a forced-through `plan` key is silently
//    dropped before the Supabase call is even built — the update payload
//    genuinely never contains it, not just "the type says you can't."
//
// A customer must never be able to raise their own `site_limit`, flip
// `active`, or repoint `auth_user_id`/`auth_email` (that's invite-flow
// state, Step 7) — those are `admin.ts`'s `updateCustomer()`, reachable only
// from `/admin/*`.
const PROFILE_WHITELIST = ['name', 'contact_name', 'contact_email', 'country', 'ui_language'] as const;

export type ProfileUpdateFields = Partial<Pick<CustomerRecord, (typeof PROFILE_WHITELIST)[number]>>;

function pickWhitelisted<T extends Record<string, unknown>>(
  fields: T,
  allowed: readonly (keyof T)[],
): Partial<T> {
  const allowedSet = new Set<keyof T>(allowed);
  const out: Partial<T> = {};
  // Iterating the *input's* own keys — not the whitelist — is what makes
  // this a real runtime filter rather than type-level theatre: an object
  // forced through `as any` can carry keys `ProfileUpdateFields` doesn't
  // declare, and this only copies the ones both present here AND allowed.
  for (const key of Object.keys(fields) as (keyof T)[]) {
    if (allowedSet.has(key)) out[key] = fields[key];
  }
  return out;
}

export async function updateCustomerProfile(
  customerId: string,
  fields: ProfileUpdateFields,
): Promise<CustomerRecord> {
  const payload = pickWhitelisted(fields as Record<string, unknown>, PROFILE_WHITELIST as readonly string[]);
  if (Object.keys(payload).length === 0) {
    // Nothing whitelisted survived — treat as a no-op read rather than
    // sending Supabase an empty `.update({})` (which errors: PostgREST
    // requires at least one column in the payload).
    return getCustomer(customerId);
  }
  const { data, error } = await getSupabaseAdmin()
    .schema('vrm')
    .from('customers')
    .update(payload)
    .eq('id', customerId)
    .select('*')
    .single();
  if (error) throw error;
  return data as CustomerRecord;
}

export type { Lang };
