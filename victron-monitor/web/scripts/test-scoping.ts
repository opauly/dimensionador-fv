// The regression test for PLAN_PHASE14.md §1.2's whole tenant-scoping
// model — "must keep passing at every future step" (§2 Step 4's own
// validation gate). A plain script, not a test-framework suite: this repo
// has none (§4's explicit non-goal for this phase), and the Python side's
// equivalent convention is a runnable script under `tools/`
// (`PLAN_PHASE13.md §2 Step 2`'s `tools/test_vrm_portal_scoping.py`) — this
// is that pattern's TypeScript counterpart.
//
// Run from `victron-monitor/web/`:
//
//   source "$HOME/.nvm/nvm.sh" && nvm use
//   npm run test:scoping
//
// `npm run test:scoping` is `tsx --conditions=react-server
// --env-file=.env.local scripts/test-scoping.ts` (see `package.json`) — the
// equivalent direct invocation, if you need it without going through npm:
//
//   node --conditions=react-server --env-file=.env.local -r tsx/cjs scripts/test-scoping.ts
//
// ── Why `--conditions=react-server` ─────────────────────────────────────
// Every module under `lib/server/` starts `import 'server-only'`. That
// package's whole trick (`node_modules/server-only/package.json`'s
// `exports` map) is resolving to a no-op file under Next's bundler-injected
// `react-server` condition, and to a file that unconditionally throws
// otherwise — which is exactly the "accidental client import becomes a
// build error" property PLAN_PHASE14.md §1.2 rule 2 relies on. Running this
// script through plain Node (no Next.js bundler in the loop) hits that same
// throw unless the same condition is supplied by hand. This is not a
// workaround that weakens the guarantee: the guarantee is about *client
// bundles*, and a standalone Node script run from a terminal is exactly as
// much "a server context" as `vrm_api` or this app's own Server Components
// are — there is no browser anywhere near this process.
import 'server-only';

import { createSite, listIngestions, listSites, updateSite, getSite, assertOwnsSite, NotAuthorized } from '@/lib/server/db';
import { createCustomer } from '@/lib/server/db/admin';
import { getSupabaseAdmin } from '@/lib/server/supabase';
import { vrmSync, PipelineError } from '@/lib/server/pipeline';

type Check = { name: string; pass: boolean; detail?: string };
const checks: Check[] = [];

function record(name: string, pass: boolean, detail?: string) {
  checks.push({ name, pass, detail });
  const mark = pass ? 'PASS' : 'FAIL';
  console.log(`[${mark}] ${name}${detail ? ` — ${detail}` : ''}`);
}

async function expectNotAuthorized(name: string, fn: () => Promise<unknown>) {
  try {
    await fn();
    record(name, false, 'expected NotAuthorized to be thrown, but the call succeeded');
  } catch (err) {
    if (err instanceof NotAuthorized) {
      record(name, true);
    } else {
      record(name, false, `threw, but not NotAuthorized: ${(err as Error)?.message ?? err}`);
    }
  }
}

async function main() {
  const stamp = Date.now();
  const admin = getSupabaseAdmin();

  // ── Setup: two throwaway customers, one site each ──────────────────
  const customerA = await createCustomer({
    name: `Scoping Test A ${stamp}`,
    accountType: 'owner',
    plan: 'trial',
  });
  const customerB = await createCustomer({
    name: `Scoping Test B ${stamp}`,
    accountType: 'owner',
    plan: 'trial',
  });

  try {
    const siteA = await createSite(customerA.id, `Site A ${stamp}`, { pv_kwp: 5 });
    const siteB = await createSite(customerB.id, `Site B ${stamp}`, { pv_kwp: 7 });

    try {
      // A real ingestion_log row for B's site, so `listIngestions` has
      // something to wrongly leak if the scoping were broken — an empty
      // result for a cross-tenant call is not evidence of correct scoping
      // by itself (see `ingestions.ts`'s own comment on this).
      const { error: logError } = await admin
        .schema('vrm')
        .from('ingestion_log')
        .insert({ site_id: siteB.site_id, source: 'csv_upload', filename: 'scoping-test.csv', rows_written: 1 });
      if (logError) throw logError;

      // ── The four cross-tenant probes: A's customerId + B's siteId ─────
      await expectNotAuthorized('getSite(A, B.site_id) throws NotAuthorized', () => getSite(customerA.id, siteB.site_id));

      await expectNotAuthorized('updateSite(A, B.site_id, ...) throws NotAuthorized', () =>
        updateSite(customerA.id, siteB.site_id, { display_name: 'Hijacked' }),
      );

      await expectNotAuthorized('assertOwnsSite(A, B.site_id) throws NotAuthorized', () =>
        assertOwnsSite(customerA.id, siteB.site_id),
      );

      await expectNotAuthorized('listIngestions(A, { siteId: B.site_id }) throws NotAuthorized', () =>
        listIngestions(customerA.id, { siteId: siteB.site_id }),
      );

      // ── PLAN_PHASE15.md §8 Step 5's own cases: customer A must never be
      // able to validate/connect/disconnect/sync using customer B's
      // customer_id/site_id through the four new `/api/vrm/*` routes. Those
      // routes are thin (`requireCustomerForRoute()` + Zod + a forward),
      // so what actually needs to keep passing is the two real controls
      // they're built on top of (§3.2): `assertOwnsSite()` on OUR side
      // (already proven generically above — restated here, named for these
      // specific call sites, exactly the way `app/api/vrm/connect/route.ts`'s
      // "existing site" branch and `app/api/vrm/sync/route.ts` both call it
      // before ever forwarding to `vrm_api`) and `vrm_api`'s OWN
      // `tenancy.assert_owns_site()` re-check (§3.2 control 2 — exercised for
      // real below, over HTTP, against the live `vrm_api`, not re-trusted).
      await expectNotAuthorized("/api/vrm/connect's assertOwnsSite(A, B.site_id) refuses an 'existing site' mapping", () =>
        assertOwnsSite(customerA.id, siteB.site_id),
      );
      await expectNotAuthorized('/api/vrm/sync\'s assertOwnsSite(A, B.site_id) refuses a sync request', () =>
        assertOwnsSite(customerA.id, siteB.site_id),
      );

      // A real HTTP call to `vrm_api`'s own `POST /v1/vrm-sync`, with
      // customer A's id and customer B's site_id — `vrm_api`'s
      // `tenancy.assert_owns_site()` (its own control, independent of
      // anything this Next.js app already checked) must refuse this with a
      // 403 before it ever touches Victron or writes a `vrm.jobs` row; this
      // is the live, network-level restatement of §3.2's "customer A's
      // token can never be used to pull customer B's data even if a
      // site_id gets confused somewhere". No real VRM token is exercised —
      // the tenancy check happens before `vrm_sync.py` ever reads one.
      try {
        await vrmSync({ customer_id: customerA.id, site_id: siteB.site_id, start: '2020-01-01', end: '2020-01-02' });
        record('vrmSync(A.id, B.site_id) refused by live vrm_api', false, 'expected a 403, but the call succeeded');
      } catch (err) {
        if (err instanceof PipelineError && err.status === 403) {
          record('vrmSync(A.id, B.site_id) refused by live vrm_api', true);
        } else {
          record(
            'vrmSync(A.id, B.site_id) refused by live vrm_api',
            false,
            `threw, but not a 403 PipelineError: ${(err as Error)?.message ?? err}`,
          );
        }
      }

      // ── listSites(A) must never contain B's site ───────────────────
      const sitesForA = await listSites(customerA.id);
      const leaked = sitesForA.some((s) => s.site_id === siteB.site_id);
      record('listSites(A) does not contain B.site_id', !leaked, leaked ? `found ${siteB.site_id} in A's list` : undefined);

      // ── Sanity checks the other direction, so a broken predicate that
      // rejects EVERYTHING (which would make every test above pass for the
      // wrong reason) can't hide ────────────────────────────────────────
      const ownSite = await getSite(customerA.id, siteA.site_id);
      record('getSite(A, A.site_id) succeeds (sanity)', ownSite.site_id === siteA.site_id);

      const ownIngestions = await listIngestions(customerB.id, { siteId: siteB.site_id });
      record(
        'listIngestions(B, { siteId: B.site_id }) returns B’s own row (sanity)',
        ownIngestions.length === 1 && ownIngestions[0].filename === 'scoping-test.csv',
      );

      await assertOwnsSite(customerB.id, siteB.site_id); // must not throw
      record('assertOwnsSite(B, B.site_id) does not throw (sanity)', true);
    } finally {
      // Clean up child rows first — `vrm.sites` has no ON DELETE CASCADE
      // *from* ingestion_log back up, but customers -> sites does cascade
      // (migration 012), so deleting the customers below would already
      // take the sites and their ingestion_log rows with them. Deleted
      // explicitly anyway so this script's cleanup doesn't rely on that
      // cascade being exactly right forever.
      await admin.schema('vrm').from('ingestion_log').delete().in('site_id', [siteA.site_id, siteB.site_id]);
      await admin.schema('vrm').from('sites').delete().in('site_id', [siteA.site_id, siteB.site_id]);
    }
  } finally {
    await admin.schema('vrm').from('customers').delete().in('id', [customerA.id, customerB.id]);
  }

  const failed = checks.filter((c) => !c.pass);
  console.log('');
  console.log(`${checks.length - failed.length}/${checks.length} checks passed.`);
  if (failed.length > 0) {
    console.error(`${failed.length} check(s) FAILED:`);
    for (const c of failed) console.error(`  - ${c.name}${c.detail ? `: ${c.detail}` : ''}`);
    process.exitCode = 1;
  }
}

main().catch((err) => {
  console.error('test-scoping.ts crashed:', err);
  process.exitCode = 1;
});
