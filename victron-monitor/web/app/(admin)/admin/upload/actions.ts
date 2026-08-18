'use server';

import 'server-only';

// Server Action for `/admin/upload`'s customer picker (PLAN_PHASE14.md §2
// Step 7). Invoked directly (not through a `<form>`) from
// `AdminUploadManager.tsx` on every customer selection change — same
// "plain async Server Action, called via startTransition" shape
// `reverseGeocodeAction` already establishes; a Route Handler would be
// overkill for a read with no upload/job semantics attached to it.
import { requireAdmin } from '@/lib/server/auth';
import { canAddSite, listIngestions, listSites, type CanAddSiteResult, type IngestionLogRecord, type SiteRecord } from '@/lib/server/db';

export type AdminUploadContext = {
  sites: SiteRecord[];
  canAdd: CanAddSiteResult;
  ingestions: IngestionLogRecord[];
};

export async function getCustomerUploadContextAction(customerId: string): Promise<AdminUploadContext> {
  await requireAdmin();
  const [sites, canAdd, ingestions] = await Promise.all([listSites(customerId), canAddSite(customerId), listIngestions(customerId)]);
  return { sites, canAdd, ingestions };
}
