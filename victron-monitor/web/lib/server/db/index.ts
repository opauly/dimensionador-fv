import 'server-only';

// The tenant-scoped choke point (PLAN_PHASE14.md §1.2 rule 4): "Page and
// route-handler code may import only this module — never a raw Supabase
// client." `admin.ts` is deliberately NOT re-exported here — see its own
// header comment. Importing `@/lib/server/db` gets you the tenant-scoped
// surface; importing `@/lib/server/db/admin` is a visible, separate choice
// only `/admin/*` code should make.
export { getCustomer, updateCustomerProfile } from './customers';
export type { ProfileUpdateFields } from './customers';

export {
  assertOwnsSite,
  listSites,
  getSite,
  updateSite,
  siteCount,
  canAddSite,
  createSite,
} from './sites';
export type { SiteUpdateFields, CreateSiteFields, CanAddSiteResult } from './sites';

export { listIngestions } from './ingestions';
export type { ListIngestionsOptions } from './ingestions';

export { getVrmLinkStatus } from './vrmLink';
export type { VrmLinkStatusOut, VrmLinkSiteStatus } from './vrmLink';

export { NotAuthorized } from './errors';

export type { CustomerRecord, SiteRecord, IngestionLogRecord, Lang, AccountType, SystemType } from './types';
