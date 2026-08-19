// `POST /api/vrm/validate` — PLAN_PHASE15.md §3.1 step 1, "paste + validate
// (nothing stored)". Proxies `vrm_api`'s `POST /v1/vrm-link/validate`, which
// itself writes NOTHING to Postgres or Vault — it only calls Victron's
// `GET /users/me` + `GET /users/{id}/installations` with the pasted token
// and reports back what it saw. `requireCustomerForRoute()` first statement,
// same as every other route in this app; `customer_id` is always
// `session.customerId`, never anything from the request body (the body only
// ever carries the token itself).
import { NextResponse } from 'next/server';
import { z } from 'zod';
import { requireCustomerForRoute } from '@/lib/server/auth';
import { vrmLinkValidate, toErrorResponse } from '@/lib/server/pipeline';

const bodySchema = z.object({ token: z.string().trim().min(1) });

export async function POST(request: Request) {
  const session = await requireCustomerForRoute();
  if (session instanceof NextResponse) return session;

  const parsed = bodySchema.safeParse(await request.json().catch(() => null));
  if (!parsed.success) return NextResponse.json({ error: 'invalid_request' }, { status: 400 });

  try {
    const result = await vrmLinkValidate({ customer_id: session.customerId, token: parsed.data.token });
    return NextResponse.json(result);
  } catch (err) {
    const res = toErrorResponse(err);
    if (res) return res;
    throw err;
  }
}
