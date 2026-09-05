import 'server-only';

// Aggregate-only, cross-customer totals for the public marketing page's
// animated stats banner (2026-09-04) — COUNT/SUM only, never a per-site or
// per-customer row, so this is safe to call with no session at all, unlike
// `lib/server/db/admin.ts` (deliberately never imported here — see that
// file's own "ADMIN-ONLY" header). Backed by `vrm.get_marketing_stats()`
// (migration 042), a single round trip rather than fetching every
// `energy_daily` row into the app to sum client-side.
import { getSupabaseAdmin } from '@/lib/server/supabase';

export type MarketingStats = {
  sitesMonitored: number;
  installedKwp: number;
  kwhTracked: number;
};

/** `null` on any failure (missing migration, RPC error) rather than
 * throwing — a vanity stats banner must never take the whole marketing
 * page down; the caller just skips rendering it. */
type MarketingStatsRow = {
  sites_monitored: number;
  installed_kwp: number;
  kwh_tracked: number;
};

export async function getMarketingStats(): Promise<MarketingStats | null> {
  const { data, error } = await getSupabaseAdmin().schema('vrm').rpc('get_marketing_stats').single();
  if (error || !data) {
    console.error('getMarketingStats failed', error);
    return null;
  }
  const row = data as MarketingStatsRow;
  return {
    sitesMonitored: Number(row.sites_monitored),
    installedKwp: Number(row.installed_kwp),
    kwhTracked: Number(row.kwh_tracked),
  };
}
