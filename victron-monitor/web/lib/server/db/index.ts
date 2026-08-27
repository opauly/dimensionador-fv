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
  applyScheduleToAllSites,
  countSchedulableSites,
  ScheduleRequiresVrmApi,
  MAX_REPORT_RECIPIENTS,
  getReportModulesAccess,
  REPORT_MODULES,
} from './sites';
export type { SiteUpdateFields, CreateSiteFields, CanAddSiteResult, BulkScheduleFields } from './sites';

export { listIngestions } from './ingestions';
export type { ListIngestionsOptions } from './ingestions';

export { getVrmLinkStatus } from './vrmLink';
export type { VrmLinkStatusOut, VrmLinkSiteStatus } from './vrmLink';

export { getBillingStatus, getBillingPlans, getBillingInvoices } from './billing';
export type { BillingStatusOut, BillingPlanOut, BillingInvoiceOut, BillingInvoicesOut, BillingAddressIn } from './billing';

export { getManualReportLimits, getWhiteLabelAllowed, getScheduledCapLimit, estimatedReportsPerPeriod } from './reportLimits';
export type { ManualReportLimits } from './reportLimits';

export { getBranding, getBrandingAccess, updateBranding, BrandingNotAllowed } from './branding';
export type { BrandingFields } from './branding';

export { listReportRuns, getReportRunScoped } from './reportRuns';
export type { ReportRunRecord } from './reportRuns';

export { NotAuthorized } from './errors';

export type { CustomerRecord, SiteRecord, IngestionLogRecord, Lang, AccountType, SystemType, ReportSchedule } from './types';
