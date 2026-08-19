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
import { vrmLinkDisconnect } from '@/lib/server/pipeline';

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
