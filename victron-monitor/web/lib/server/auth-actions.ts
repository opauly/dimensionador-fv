'use server';

import 'server-only';

// The one Server Action shared by both AppShells (PLAN_PHASE14.md §2
// Step 3: "AppShell ... and a sign-out action"). `'use server'` has to be
// the file's first line for Next to treat every export here as a Server
// Function; `import 'server-only'` still follows it — belt-and-suspenders
// with a rule that's already structurally true for a `'use server'` module
// (Next never ships this file's real implementation to the client either
// way), matching "every module under lib/server/, no exceptions"
// (PLAN_PHASE14.md §3).
import { redirect } from 'next/navigation';
import { createSupabaseServerClient } from './supabase';

export async function signOutAction(): Promise<void> {
  const supabase = await createSupabaseServerClient();
  await supabase.auth.signOut();
  redirect('/login');
}
