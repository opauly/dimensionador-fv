import type { ReactNode } from 'react';
import Image from 'next/image';
import Link from 'next/link';
import { signOutAction } from '@/lib/server/auth-actions';
import { t, type Lang } from '@/lib/i18n/strings';
import styles from './AppShell.module.css';

export type AppNavItem = {
  href: string;
  label: string;
  /** Renders in a visually distinct group, separated from the rest of
   * `navItems` by a divider and floated toward the account/sign-out corner,
   * instead of sitting in the main nav cluster (2026-08-19, Oscar's own
   * request: "so I can distinguish what's from my subscribers from my
   * personal sites"). Built for `/admin`'s "Flota VRM" tab specifically —
   * everything else under `/admin` reads/writes *subscriber* data
   * (`vrm.customers`/`vrm.sites` scoped to a `customer_id`), while Flota
   * VRM is the one tab that's Oscar's own VRM account, nothing to do with
   * any subscriber until he explicitly links it to one. Optional and
   * unused by `/app`'s customer nav — no behavior change there. */
  personal?: boolean;
};

export type AppShellProps = {
  /** Drives which nav items render — a *display* concern only. The actual
   * access control already happened in `requireCustomer()`/`requireAdmin()`
   * before this component is ever reached (PLAN_PHASE14.md §1.2 rule 4:
   * "navigation-level gating is UX, never the control"). */
  role: 'customer' | 'admin';
  email: string;
  navItems: AppNavItem[];
  /** English/Spanish label language for the chrome around `navItems`
   * (signed-in-as / log out). Customer sessions pass their own
   * `vrm.customers.ui_language`; admin sessions are always `'en'` (admin
   * views went English-only 2026-08-19). The `navItems` labels themselves
   * are supplied pre-translated by the caller, since Step 4/7 build the
   * real routes each one points at. */
  lang: Lang;
  children: ReactNode;
};

// Shared nav/header chrome for both `/app` and `/admin` — the one
// `components/app/AppShell` PLAN_PHASE14.md §1.7 lists, first used here at
// Step 3 with placeholder pages, reused as-is once Steps 4-7 fill in real
// dashboard content. Server Component: nothing here needs client state, and
// keeping it a Server Component means `signOutAction` can be wired directly
// to a `<form action>` with no client-side plumbing at all.
export function AppShell({ role, email, navItems, lang, children }: AppShellProps) {
  // Two groups, not one — see `AppNavItem.personal`'s own doc comment.
  // `/app`'s customer nav never sets `personal` on anything, so
  // `personalItems` is always empty there and this renders exactly as
  // before (no second <nav>, no divider) — additive, not a role branch.
  const mainItems = navItems.filter((item) => !item.personal);
  const personalItems = navItems.filter((item) => item.personal);

  return (
    <div className={styles.shell}>
      <header className={styles.header}>
        <div className={styles.brandRow}>
          <Link href={role === 'admin' ? '/admin' : '/app'} className={styles.brand}>
            <Image src="/pauly_logo.png" alt="Pauly & Co." width={567} height={156} className={styles.logoImg} />
            <span className={styles.divider} aria-hidden="true" />
            VRM Monitor
            {role === 'admin' && <span className={styles.adminTag}>Admin</span>}
          </Link>
        </div>
        <nav className={styles.nav}>
          {mainItems.map((item) => (
            <Link key={item.href} href={item.href} className={styles.navLink}>
              {item.label}
            </Link>
          ))}
        </nav>
        {personalItems.length > 0 && (
          <nav className={styles.navPersonal}>
            <span className={styles.divider} aria-hidden="true" />
            {personalItems.map((item) => (
              <Link key={item.href} href={item.href} className={styles.navLinkPersonal}>
                {item.label}
              </Link>
            ))}
          </nav>
        )}
        <div className={styles.account}>
          <span className={styles.email}>{t(lang, 'signed_in_as').replace('{email}', email)}</span>
          <form action={signOutAction}>
            <button type="submit" className={styles.signOut}>
              {t(lang, 'log_out')}
            </button>
          </form>
        </div>
      </header>
      <main className={styles.main}>{children}</main>
    </div>
  );
}
