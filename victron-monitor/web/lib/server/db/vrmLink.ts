import 'server-only';

// Connection-state reads for the "Victron VRM account" panel
// (PLAN_PHASE15.md §3.1 / §8 Step 5) — the `vrmLink.ts` sibling of
// `sites.ts`/`customers.ts`, with one deliberate difference: it wraps
// `vrm_api`'s own `GET /v1/vrm-link/status` (via `lib/server/pipeline.ts`)
// rather than querying Supabase directly. Connection state — whether a live
// Vault-backed token exists, `vrm_account_email`, `connected_since`, and
// per-site last-synced/last-error — is `vrm_api`'s own fact to report, not
// something this app should re-derive from `vrm.customers` columns it has
// no business reading directly (this app's own tenancy tables are
// customers/sites/ingestion_log/jobs, PLAN_PHASE14.md §1.11 — token-secret
// bookkeeping columns on `vrm.customers` are deliberately not among them).
//
// No function here ever returns a token — `VrmLinkStatusOut` has no field
// that could carry one (see that model's own docstring in
// `vrm_api/schemas.py`), so this module is naturally token-free by
// construction, not by a rule this file has to remember to follow.
import { vrmLinkStatus, type VrmLinkStatusOut } from '@/lib/server/pipeline';

export type { VrmLinkStatusOut, VrmLinkSiteStatus } from '@/lib/server/pipeline';

/** `customerId` first, same convention as every other function in this
 * directory (`sites.ts`, `customers.ts`) — always `session.customerId`,
 * never a value from a request body. */
export async function getVrmLinkStatus(customerId: string): Promise<VrmLinkStatusOut> {
  return vrmLinkStatus(customerId);
}
