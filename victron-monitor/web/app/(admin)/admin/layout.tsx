import type { ReactNode } from 'react';
import { AppShell, type AppNavItem } from '@/components/app';
import { requireAdmin } from '@/lib/server/auth';

// First statement of the layout — see the matching comment in
// app/(portal)/app/layout.tsx; same reasoning, admin side.
//
// Nav labels are inline English literals, not `lib/i18n/strings.ts` keys —
// admin views were originally Spanish by explicit product decision
// (PLAN_PHASE14.md §1.10 / PLAN_PHASE13.md §0.3 Q2), ported near-verbatim
// from `pages/06_vrm_monitor.py`'s own tab names ("Sitios", "Cargar CSV",
// "Reporte"); that decision was reversed 2026-08-19 ("now let's use English
// only across all account types") and every admin string was translated in
// place. Routes below don't exist until Step 7 (customers/sites) or
// Step 5-7 (upload/reports/activity) and 404 until then — same precedent
// as Nav's "Log in" link in Step 2 and AppShell's own /app links here.
export default async function AdminLayout({ children }: { children: ReactNode }) {
  const session = await requireAdmin();

  // "VRM Fleet" is `personal: true` (2026-08-19, Oscar's own request) — the
  // one tab here that isn't subscriber data: every other route reads/writes
  // `vrm.customers`/`vrm.sites` scoped to a `customer_id`, while VRM Fleet
  // is Oscar's own VRM account, unrelated to any subscriber until he
  // explicitly links an installation to one. `AppShell` renders it in a
  // separated, highlighted group so that distinction is visible, not just
  // documented here.
  const navItems: AppNavItem[] = [
    { href: '/admin/customers', label: 'Customers' },
    { href: '/admin/sites', label: 'Sites' },
    { href: '/admin/upload', label: 'Upload' },
    { href: '/admin/reports', label: 'Reports' },
    { href: '/admin/activity', label: 'Activity' },
    { href: '/admin/fleet', label: 'Fleet Health' },
    { href: '/admin/vrm-fleet', label: 'VRM Fleet', personal: true },
    { href: '/admin/help', label: 'Help' },
  ];

  return (
    <AppShell role="admin" email={session.email} navItems={navItems} lang="en">
      {children}
    </AppShell>
  );
}
