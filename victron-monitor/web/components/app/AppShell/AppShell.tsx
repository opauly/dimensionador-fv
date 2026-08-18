import type { ReactNode } from 'react';
import Image from 'next/image';
import Link from 'next/link';
import { signOutAction } from '@/lib/server/auth-actions';
import { t, type Lang } from '@/lib/i18n/strings';
import styles from './AppShell.module.css';

export type AppNavItem = { href: string; label: string };

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
   * `vrm.customers.ui_language`; admin sessions are always `'es'`. The
   * `navItems` labels themselves are supplied pre-translated by the caller,
   * since Step 4/7 build the real routes each one points at. */
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
          {navItems.map((item) => (
            <Link key={item.href} href={item.href} className={styles.navLink}>
              {item.label}
            </Link>
          ))}
        </nav>
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
