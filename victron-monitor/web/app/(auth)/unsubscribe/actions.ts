'use server';

import 'server-only';

// Server Action for `/unsubscribe` (PLAN_PHASE17.md §0.6 Q5, §8 Step 8).
// Mirrors `../activate/actions.ts`'s own shape for the same reason that
// file states: the token is bound into this action server-side in
// `page.tsx`, never handed to the client component as an inspectable prop
// (Next.js serializes a bound Server Action as an opaque reference, not
// data). Re-verifies the token itself rather than trusting that `page.tsx`
// already did — a Server Action is a real network endpoint a browser could
// call directly with any bound-looking payload; the signature check is the
// actual control, the page-level check is only what decides what to render
// before a click.
import { removeReportRecipient, verifyUnsubscribeToken } from '@/lib/server/reportUnsubscribe';

export type UnsubscribeResult = { ok: true } | { ok: false };

export async function confirmUnsubscribeAction(token: string): Promise<UnsubscribeResult> {
  const target = verifyUnsubscribeToken(token);
  if (!target) return { ok: false };
  await removeReportRecipient(target.siteId, target.email);
  return { ok: true };
}
