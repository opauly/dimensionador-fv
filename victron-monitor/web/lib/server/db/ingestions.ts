import 'server-only';

// `vrm.ingestion_log` reads, scoped to one customer. The table itself has
// no `customer_id` column — it's keyed on `site_id` (migration 012), one
// join-shape below the rest of this directory — so "this customer's
// uploads" means "uploads for sites this customer owns," computed via
// `listSites()` rather than a direct filter.
import { getSupabaseAdmin } from '@/lib/server/supabase';
import { assertOwnsSite, listSites } from './sites';
import type { IngestionLogRecord } from './types';

export type ListIngestionsOptions = {
  limit?: number;
  /** Scopes to one site instead of every site the customer owns. Routes
   * through `assertOwnsSite()` first — this is what lets
   * `scripts/test-scoping.ts` exercise `listIngestions()` the same way it
   * exercises `getSite()`/`updateSite()`: calling it with customer A's id
   * and customer B's site_id must throw `NotAuthorized`, not silently
   * return an empty list (an empty list would be indistinguishable from
   * "this customer just has no uploads yet," which is the wrong failure
   * mode for a cross-tenant probe to produce). */
  siteId?: string;
};

export async function listIngestions(
  customerId: string,
  opts: ListIngestionsOptions = {},
): Promise<IngestionLogRecord[]> {
  const limit = opts.limit ?? 50;

  let siteIds: string[];
  if (opts.siteId) {
    await assertOwnsSite(customerId, opts.siteId);
    siteIds = [opts.siteId];
  } else {
    // Deliberately not `{ activeOnly: true }` — a deactivated site's upload
    // history is still real history ("why did this report look wrong" per
    // §2 Step 4's own framing of what `ingestion_log` is for), and hiding it
    // just because the site itself was later deactivated would make this
    // table lie about the past.
    siteIds = (await listSites(customerId)).map((s) => s.site_id);
  }

  if (siteIds.length === 0) return [];

  const { data, error } = await getSupabaseAdmin()
    .schema('vrm')
    .from('ingestion_log')
    .select('*')
    .in('site_id', siteIds)
    .order('uploaded_at', { ascending: false })
    .limit(limit);
  if (error) throw error;
  return (data ?? []) as IngestionLogRecord[];
}
