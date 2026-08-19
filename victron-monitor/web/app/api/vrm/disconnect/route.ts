// `POST /api/vrm/disconnect` — PLAN_PHASE15.md §3.1, "disconnect is a
// first-class action on the same panel". Proxies `vrm_api`'s own
// `POST /v1/vrm-link/disconnect`, which destroys the Vault-backed token,
// stamps `vrm_token_revoked_at`, and reverts every `source='vrm_api'` site
// of this customer's back to `source='csv_upload'`/`vrm_sync_enabled=false`
// — telemetry already ingested (`energy_daily`/`alarm_events`/`daily_health`)
// is NEVER touched (§3.1: "disconnecting a credential must not delete a
// year of a customer's history"). No request body — there is nothing to
// carry beyond `customer_id`, which is always `session.customerId`.
import { NextResponse } from 'next/server';
import { requireCustomerForRoute } from '@/lib/server/auth';
import { vrmLinkDisconnect, toErrorResponse } from '@/lib/server/pipeline';

export async function POST() {
  const session = await requireCustomerForRoute();
  if (session instanceof NextResponse) return session;

  try {
    const result = await vrmLinkDisconnect(session.customerId);
    return NextResponse.json(result);
  } catch (err) {
    const res = toErrorResponse(err);
    if (res) return res;
    throw err;
  }
}
