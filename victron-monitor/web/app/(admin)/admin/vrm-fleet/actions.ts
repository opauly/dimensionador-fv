'use server';

import 'server-only';

// Server Actions for `/admin/vrm-fleet` (PLAN_PHASE15.md §3.3 / §8 Step 4b)
// — the plain reads this page needs that aren't the link/sync flow itself
// (those go through `app/api/admin/pipeline/vrm-fleet/*`, matching
// `JobProgress`'s fetch-based polling contract for the sync job). Same
// "plain async Server Action, called via startTransition" shape
// `app/(admin)/admin/upload/actions.ts` and `app/(admin)/admin/reports/actions.ts`
// already establish.
import { requireAdmin } from '@/lib/server/auth';
import { listSites, type SiteRecord } from '@/lib/server/db';
import { listVrmFleetInstallations, type VrmFleetInstallation } from '@/lib/server/pipeline';

export async function listVrmFleetInstallationsAction(): Promise<VrmFleetInstallation[]> {
  await requireAdmin();
  return listVrmFleetInstallations();
}

// The "existing customer" branch of the link form needs THAT customer's own
// sites (for the "link to an existing site" dropdown) — same tenant-scoped
// `listSites()` `getCustomerUploadContextAction()` already uses, not
// `admin.ts:listAllSites()` (which is cross-customer and would make the
// dropdown show every customer's sites, not just the chosen one's).
export async function listCustomerSitesAction(customerId: string): Promise<SiteRecord[]> {
  await requireAdmin();
  if (!customerId) return [];
  return listSites(customerId);
}
