import type { ReactNode } from 'react';
import { AppShell, type AppNavItem } from '@/components/app';
import { requireCustomer } from '@/lib/server/auth';
import { t } from '@/lib/i18n/strings';

// First statement of the layout, per PLAN_PHASE14.md §1.2 rule 4 —
// `requireCustomer()` is what actually keeps a signed-out visitor or a
// wrong-role (admin) session out of everything under `/app/*`; the fact
// that this same layout also happens to build the nav is incidental. Every
// page under `app/(portal)/app/**` inherits this without repeating the
// check, because Next.js always renders a route's layouts before its page.
export default async function PortalLayout({ children }: { children: ReactNode }) {
  const session = await requireCustomer();

  const navItems: AppNavItem[] = [
    { href: '/app', label: t(session.uiLanguage, 'nav_reports') },
    { href: '/app/upload', label: t(session.uiLanguage, 'nav_upload') },
    { href: '/app/sites', label: t(session.uiLanguage, 'nav_my_sites') },
    { href: '/app/profile', label: t(session.uiLanguage, 'nav_profile') },
  ];

  return (
    <AppShell role="customer" email={session.email} navItems={navItems} lang={session.uiLanguage}>
      {children}
    </AppShell>
  );
}
