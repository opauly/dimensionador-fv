'use client';

// The one client boundary in AppShell's otherwise all-Server-Component nav
// (see AppShell.tsx's own comment on why it stays a Server Component) —
// `usePathname()` is the only way to know which tab is current, so it's
// isolated to this leaf rather than converting the whole shell to a client
// component. Matches `href` as a prefix, not just exact equality, so a
// sub-route (e.g. `/admin/fleet/[site_id]`) still highlights its parent
// tab (`/admin/fleet`) — plain equality would leave every tab dark while
// looking at a site's own drill-down page.
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import type { ReactNode } from 'react';

export function NavLink({ href, className, activeClassName, children }: { href: string; className: string; activeClassName: string; children: ReactNode }) {
  const pathname = usePathname();
  const isActive = pathname === href || pathname.startsWith(`${href}/`);
  return (
    <Link href={href} className={isActive ? `${className} ${activeClassName}` : className}>
      {children}
    </Link>
  );
}
