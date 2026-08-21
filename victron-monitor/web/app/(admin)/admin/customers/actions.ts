'use server';

import 'server-only';

// Server Actions for `/admin/customers` (PLAN_PHASE14.md §2 Step 7).
// `requireAdmin()` first in every one — never inferred from
// `AdminLayout` already having called it (PLAN_PHASE14.md §3).
import { revalidatePath } from 'next/cache';
import { z } from 'zod';
import { requireAdmin } from '@/lib/server/auth';
import { createCustomer, updateCustomer, setActive, type AdminCustomerUpdateFields, type CreateCustomerFields } from '@/lib/server/db/admin';
import { sendInvite, resendInvite } from '@/lib/server/invites';
import { billingCancel, billingRefresh, vrmLinkDisconnect, PipelineError } from '@/lib/server/pipeline';

const stringOrNull = z.preprocess((v) => (typeof v === 'string' && v.trim() !== '' ? v.trim() : null), z.string().nullable());
const numberOrNull = z.preprocess((v) => {
  if (v === null || v === undefined || v === '') return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}, z.number().nullable());

const createSchema = z.object({
  name: z.string().trim().min(1),
  accountType: z.enum(['owner', 'installer']),
  plan: z.string().trim().min(1),
  siteLimit: numberOrNull,
  contactName: stringOrNull,
  contactEmail: stringOrNull,
  country: stringOrNull,
  authEmail: z.string().trim().email(),
  uiLanguage: z.enum(['en', 'es']),
});

export type CreateCustomerState = {
  error?: string;
  success?: boolean;
  /** Distinct from `error` — creation itself succeeded, but the invite
   * email didn't go out (e.g. Resend unreachable, or the email is already
   * registered to a different customer). Surfaced separately so an admin
   * doesn't think the whole operation failed when only the send did — the
   * customer row exists either way and "Resend invite" (or fixing the
   * conflict first) recovers from here without re-creating anything. */
  inviteWarning?: string;
};

export async function createCustomerAction(_prevState: CreateCustomerState, formData: FormData): Promise<CreateCustomerState> {
  await requireAdmin();

  const parsed = createSchema.safeParse({
    name: formData.get('name'),
    accountType: formData.get('accountType'),
    plan: formData.get('plan'),
    siteLimit: formData.get('siteLimit'),
    contactName: formData.get('contactName'),
    contactEmail: formData.get('contactEmail'),
    country: formData.get('country'),
    authEmail: formData.get('authEmail'),
    uiLanguage: formData.get('uiLanguage'),
  });
  if (!parsed.success) {
    return { error: 'Please check the form fields.' };
  }

  let customerId: string;
  try {
    const created = await createCustomer(parsed.data as CreateCustomerFields);
    customerId = created.id;
  } catch (err) {
    // A duplicate `auth_email` (migration 021's case-insensitive unique
    // index) is the one expected failure here — everything else collapses
    // to the same generic message rather than a raw Postgres error string
    // reaching this admin surface (PLAN_PHASE14.md §1.12 rule 6 applies to
    // `/admin/*` too, not just customer-facing pages).
    const message = err instanceof Error ? err.message : '';
    if (/duplicate key|unique/i.test(message)) {
      return { error: 'A customer with that login email or name already exists.' };
    }
    return { error: 'Could not create the customer. Please try again.' };
  }

  revalidatePath('/admin/customers');

  const inviteResult = await sendInvite(customerId);
  if (inviteResult.ok) {
    return { success: true };
  }
  const inviteWarning =
    inviteResult.reason === 'already_linked_elsewhere'
      ? `Customer created, but that email is already linked to "${inviteResult.otherCustomerName ?? 'another customer'}" — use a different login email or reassign the existing one.`
      : inviteResult.reason === 'no_login_email'
        ? 'Customer created, but no login email is configured.'
        : 'Customer created, but the invite could not be sent. Try "Resend invite" from the table.';
  return { success: true, inviteWarning };
}

// Same field whitelist `admin.ts:updateCustomer()` already enforces at
// runtime — this Zod schema only narrows the *shape*, per PLAN_PHASE14.md
// §3's "Zod ... only checks the shape" distinction.
const updateSchema = z.object({
  name: z.string().trim().min(1),
  accountType: z.enum(['owner', 'installer']),
  plan: z.string().trim().min(1),
  siteLimit: numberOrNull,
  contactName: stringOrNull,
  contactEmail: stringOrNull,
  country: stringOrNull,
  uiLanguage: z.enum(['en', 'es']),
  notes: stringOrNull,
});

export type UpdateCustomerState = { error?: string; success?: boolean };

export async function updateCustomerAction(customerId: string, _prevState: UpdateCustomerState, formData: FormData): Promise<UpdateCustomerState> {
  await requireAdmin();

  const parsed = updateSchema.safeParse({
    name: formData.get('name'),
    accountType: formData.get('accountType'),
    plan: formData.get('plan'),
    siteLimit: formData.get('siteLimit'),
    contactName: formData.get('contactName'),
    contactEmail: formData.get('contactEmail'),
    country: formData.get('country'),
    uiLanguage: formData.get('uiLanguage'),
    notes: formData.get('notes'),
  });
  if (!parsed.success) return { error: 'Please check the form fields.' };

  try {
    await updateCustomer(customerId, {
      name: parsed.data.name,
      account_type: parsed.data.accountType,
      plan: parsed.data.plan,
      site_limit: parsed.data.siteLimit,
      contact_name: parsed.data.contactName,
      contact_email: parsed.data.contactEmail,
      country: parsed.data.country,
      ui_language: parsed.data.uiLanguage,
      notes: parsed.data.notes,
    } as AdminCustomerUpdateFields);
  } catch {
    return { error: 'Could not save. Please try again.' };
  }
  revalidatePath('/admin/customers');
  return { success: true };
}

export async function setActiveAction(customerId: string, active: boolean): Promise<void> {
  await requireAdmin();
  await setActive(customerId, active);
  revalidatePath('/admin/customers');
}

export type ResendState = { ok?: boolean; error?: string };

export async function resendInviteAction(customerId: string): Promise<ResendState> {
  await requireAdmin();
  const result = await resendInvite(customerId);
  revalidatePath('/admin/customers');
  if (!result.ok) {
    return {
      error:
        result.reason === 'no_login_email'
          ? 'This customer has no login email configured — edit it first.'
          : 'Could not resend the invite. Please try again.',
    };
  }
  return { ok: true };
}

export async function sendInviteAction(customerId: string): Promise<ResendState> {
  await requireAdmin();
  const result = await sendInvite(customerId);
  revalidatePath('/admin/customers');
  if (!result.ok) {
    if (result.reason === 'already_linked_elsewhere') {
      return { error: `That email is already linked to "${result.otherCustomerName ?? 'another customer'}".` };
    }
    if (result.reason === 'no_login_email') {
      return { error: 'This customer has no login email configured — edit it first.' };
    }
    return { error: 'Could not send the invite. Please try again.' };
  }
  return { ok: true };
}

export type VrmLinkDisconnectState = { ok?: boolean; error?: string };

/**
 * Admin-triggered VRM disconnect (PLAN_PHASE15.md §8 Step 6 / §0.5 Q6 —
 * "Oscar can sever a connection he cannot create"). Calls the exact same
 * `vrm_api` endpoint a customer's own "Disconnect" button on `/app/sites`
 * calls (`vrmLinkDisconnect()` → `POST /v1/vrm-link/disconnect`) — there is
 * no second, admin-only disconnect code path. That endpoint destroys the
 * Vault-backed token, stamps `vrm_token_revoked_at`, and reverts every
 * `source='vrm_api'` site of this customer's back to
 * `source='csv_upload'`/`vrm_sync_enabled=false`; telemetry already
 * ingested is never touched.
 */
export async function disconnectVrmLinkAction(customerId: string): Promise<VrmLinkDisconnectState> {
  await requireAdmin();
  try {
    await vrmLinkDisconnect(customerId);
  } catch {
    return { error: "Could not disconnect this customer's VRM account. Please try again." };
  }
  revalidatePath('/admin/customers');
  return { ok: true };
}

// ══════════════════════════════════════════════════════════════════════
// Billing (PLAN_PHASE16.md §0.6 Q11, §8 Step 6) — view, refresh/reconcile,
// and cancel only. NO field or action here ever collects card data — a
// customer's card is entered by the customer, in ONVO's own form, never by
// Oscar (Q11's own answer). All three functions below call straight
// through `lib/server/pipeline.ts` (the same `vrm_api` endpoints
// `/app/billing` itself calls), never a second, admin-only billing code
// path — `vrm_api`'s own tenancy check only confirms `customerId` names a
// real row, so an admin session calling these for ANY customer is exactly
// as legitimate as that customer calling it for themselves; `requireAdmin()`
// below is what makes that call.
// ══════════════════════════════════════════════════════════════════════

export type BillingActionState = { ok?: boolean; error?: string };

/** "Refresh" (PLAN_PHASE16.md §8 Step 6) — a plain reconcile
 * (`POST /v1/billing/refresh`), the exact code path §7's failure-modes
 * table names as the first line of support for "their card works, ONVO
 * says trialing, but the promotion didn't happen." */
export async function billingRefreshAction(customerId: string): Promise<BillingActionState> {
  const admin = await requireAdmin();
  try {
    await billingRefresh(customerId);
  } catch {
    return { error: "Could not refresh this customer's billing status. Please try again." };
  }
  console.info(`admin.billing_refresh customer_id=${customerId} admin=${admin.email}`);
  revalidatePath('/admin/customers');
  return { ok: true };
}

/** "Cancel" (PLAN_PHASE16.md §0.6 Q4/Q11, §8 Step 6) — exposes BOTH
 * `at_period_end` (what the customer-facing UI already offers) and
 * `immediate` (Q4's admin-only escape hatch, built and tenancy-checked in
 * `vrm_api/routers/billing.py:post_subscription_cancel()` since Step 3 but
 * never callable from anywhere until this action — this IS "the one place
 * it's allowed to be reachable," per that endpoint's own docstring). Both
 * modes are logged with the acting admin's identity — this is a real
 * money/access action, not a read. */
export async function billingCancelAction(customerId: string, mode: 'at_period_end' | 'immediate'): Promise<BillingActionState> {
  const admin = await requireAdmin();
  try {
    await billingCancel({ customer_id: customerId, mode });
  } catch (err) {
    if (err instanceof PipelineError && err.code === 'no_active_subscription') {
      return { error: 'This customer has no active subscription to cancel.' };
    }
    return { error: 'Could not cancel the subscription. Please try again.' };
  }
  console.info(`admin.billing_cancel customer_id=${customerId} mode=${mode} admin=${admin.email}`);
  revalidatePath('/admin/customers');
  return { ok: true };
}

export type PromoteToActiveState = { ok?: boolean; promoted?: boolean; error?: string; message?: string };

/**
 * "Promote to active" (PLAN_PHASE16.md §3.6, §7, §8 Step 6) — the deliberate,
 * confirm-dialog-gated support escape hatch for "ONVO says trialing/entitled
 * but the promotion to `provisioning_state='active'` never fired"
 * (`vrm_api/billing.py:apply_entitlements()`'s own §4.5 rule 8 docstring).
 *
 * There is no separate "promote" mechanism to call: `POST
 * /v1/billing/refresh` -> `reconcile_customer()` -> `apply_entitlements()`
 * is the ONLY code that ever writes `provisioning_state`, and it already
 * does exactly what "promote" means (flips `pending_subscription` ->
 * `active` the moment it observes an entitled subscription WITH a payment
 * method on file — `billing.py`'s own "Entitled status is necessary but NOT
 * sufficient" note). Reusing it here (rather than building a second
 * `provisioning_state` writer, which §4.5 rule 8 explicitly reserves for
 * exactly two callers) means this action can genuinely be a no-op: a
 * customer with no entitled subscription at all — no card ever accepted —
 * stays `pending_subscription` after this runs, correctly, because a
 * promote button cannot manufacture money that was never paid.
 *
 * The one thing this function adds beyond a plain refresh is the log line
 * naming the acting admin (PLAN_PHASE16.md §8 Step 6: "writes a log line
 * naming the admin") — `apply_entitlements()` itself only ever logs
 * `customer_id` (`billing.entitlement_changed` / `signup.promoted`), never
 * who asked for the reconcile that triggered it, since most reconciles are
 * automatic (a webhook, the daily sweep, a customer's own page load). This
 * one is admin-initiated, so it is the one call site in this whole feature
 * where "who asked for this" is worth recording on its own line.
 */
export async function promoteToActiveAction(customerId: string): Promise<PromoteToActiveState> {
  const admin = await requireAdmin();
  let result;
  try {
    result = await billingRefresh(customerId);
  } catch {
    return { error: "Could not refresh this customer's billing status. Please try again." };
  }
  const promoted = result.provisioning_state === 'active';
  console.info(
    `admin.promote_to_active customer_id=${customerId} admin=${admin.email} (${admin.userId}) ` +
      `promoted=${promoted} provisioning_state=${result.provisioning_state} billing_status=${result.billing_status} ` +
      `plan_key=${result.plan_key} site_limit=${result.site_limit}`,
  );
  revalidatePath('/admin/customers');
  if (!promoted) {
    return {
      ok: true,
      promoted: false,
      message:
        'No change — ONVO does not currently report an entitled subscription with a payment method on file for this customer. If they genuinely have not paid, this is correct, not a bug.',
    };
  }
  return { ok: true, promoted: true };
}
