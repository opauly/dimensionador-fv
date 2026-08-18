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
   * customer row exists either way and "Reenviar invitación" (or fixing the
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
    return { error: 'Revisá los campos del formulario.' };
  }

  let customerId: string;
  try {
    const created = await createCustomer(parsed.data as CreateCustomerFields);
    customerId = created.id;
  } catch (err) {
    // A duplicate `auth_email` (migration 021's case-insensitive unique
    // index) is the one expected failure here — everything else collapses
    // to the same generic message rather than a raw Postgres error string
    // reaching this Spanish-admin surface (PLAN_PHASE14.md §1.12 rule 6
    // applies to `/admin/*` too, not just customer-facing pages).
    const message = err instanceof Error ? err.message : '';
    if (/duplicate key|unique/i.test(message)) {
      return { error: 'Ya existe un cliente con ese correo de acceso o ese nombre.' };
    }
    return { error: 'No se pudo crear el cliente. Intentá de nuevo.' };
  }

  revalidatePath('/admin/customers');

  const inviteResult = await sendInvite(customerId);
  if (inviteResult.ok) {
    return { success: true };
  }
  const inviteWarning =
    inviteResult.reason === 'already_linked_elsewhere'
      ? `Cliente creado, pero ese correo ya está vinculado a "${inviteResult.otherCustomerName ?? 'otro cliente'}" — usá otro correo de acceso o reasigná el existente.`
      : inviteResult.reason === 'no_login_email'
        ? 'Cliente creado, pero no tiene correo de acceso configurado.'
        : 'Cliente creado, pero no se pudo enviar la invitación. Probá "Reenviar invitación" desde la tabla.';
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
  if (!parsed.success) return { error: 'Revisá los campos del formulario.' };

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
    return { error: 'No se pudo guardar. Intentá de nuevo.' };
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
          ? 'Este cliente no tiene correo de acceso configurado — editalo primero.'
          : 'No se pudo reenviar la invitación. Intentá de nuevo.',
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
      return { error: `Ese correo ya está vinculado a "${result.otherCustomerName ?? 'otro cliente'}".` };
    }
    if (result.reason === 'no_login_email') {
      return { error: 'Este cliente no tiene correo de acceso configurado — editalo primero.' };
    }
    return { error: 'No se pudo enviar la invitación. Intentá de nuevo.' };
  }
  return { ok: true };
}
