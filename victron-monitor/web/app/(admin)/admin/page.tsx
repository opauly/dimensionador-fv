import { redirect } from 'next/navigation';
import { requireAdmin } from '@/lib/server/auth';

// `/admin` itself has never been a real destination in the nav (AdminLayout
// links straight to /admin/customers, /admin/sites, etc.) — it's only ever
// reached via `requireAdmin()`'s own redirect target after sign-in
// (`login/actions.ts`) or a cross-role guard bounce
// (`requireCustomer()` sending an admin session here). Step 3's temporary
// "which role/customerId did I resolve to" placeholder is replaced here, at
// Step 7, by the real landing page (PLAN_PHASE14.md §2 Step 7).
// `requireAdmin()` still runs first, even though it only decides where to
// send someone — the same "never inferred from layout nesting" rule as
// every other guarded page in this app.
export default async function AdminHomePage() {
  await requireAdmin();
  redirect('/admin/customers');
}
