import 'server-only';

// The tenant-scoping choke point's one error type (PLAN_PHASE14.md §1.2
// rule 4). `assertOwnsSite()` — and everything in this directory built on
// top of it — throws this rather than returning `false` or `null`
// specifically so a call site can't accidentally treat "not yours" the same
// way it treats "not found and that's fine" (e.g. `?? defaultValue`).
// Callers that need to turn this into user-facing copy (a route handler, a
// Server Action) catch it explicitly; letting it propagate uncaught is also
// safe — it becomes an unhandled 500, never a leaked row.
export class NotAuthorized extends Error {
  constructor(message = 'Not authorized.') {
    super(message);
    this.name = 'NotAuthorized';
  }
}
