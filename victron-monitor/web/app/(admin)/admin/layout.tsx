import type { ReactNode } from 'react';
import { AppShell, type AppNavItem } from '@/components/app';
import { requireAdmin } from '@/lib/server/auth';

// First statement of the layout — see the matching comment in
// app/(portal)/app/layout.tsx; same reasoning, admin side.
//
// Nav labels are inline Spanish literals, not `lib/i18n/strings.ts` keys —
// admin views are always Spanish by explicit product decision
// (PLAN_PHASE14.md §1.10 / PLAN_PHASE13.md §0.3 Q2), ported near-verbatim
// from `pages/06_vrm_monitor.py`'s own tab names ("Sitios", "Cargar CSV",
// "Reporte"). Routes below don't exist until Step 7 (customers/sites) or
// Step 5-7 (upload/reports/activity) and 404 until then — same precedent
// as Nav's "Log in" link in Step 2 and AppShell's own /app links here.
export default async function AdminLayout({ children }: { children: ReactNode }) {
  const session = await requireAdmin();

  const navItems: AppNavItem[] = [
    { href: '/admin/customers', label: 'Clientes' },
    { href: '/admin/sites', label: 'Sitios' },
    { href: '/admin/upload', label: 'Cargar' },
    { href: '/admin/reports', label: 'Reportes' },
    { href: '/admin/activity', label: 'Actividad' },
  ];

  return (
    <AppShell role="admin" email={session.email} navItems={navItems} lang="es">
      {children}
    </AppShell>
  );
}
