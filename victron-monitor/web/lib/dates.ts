// Deterministic date/time formatting for server-rendered pages
// (2026-08-19 — caught from a real Next.js hydration error on
// `/admin/activity`). `toLocaleString()`/`toLocaleDateString()` called with
// no explicit `timeZone`/`hour12` can produce genuinely different strings
// on the server (Node's bundled ICU) vs. the client (the browser's own
// ICU) for the exact same `Date` value — most commonly a different
// AM/PM-marker spacing character (Chrome's `Intl` uses a narrow no-break
// space; Node's has been inconsistent across versions) — even though the
// two strings can look byte-identical when copy/pasted into a bug report.
// `Intl.DateTimeFormat` output is only guaranteed deterministic across
// runtimes when every option is explicit — never relying on either
// runtime's ambient default locale/timezone.
//
// `TIME_ZONE` is fixed to `America/Costa_Rica` because every site and
// customer this product serves today is Costa-Rica-based (migration 012's
// own default) — the same assumption the rest of this codebase already
// makes. `hour12: false` sidesteps the AM/PM-marker inconsistency at its
// root rather than hoping the marker character matches between server and
// client; it's also the locally idiomatic choice for a Costa Rica product
// regardless of `lang`, the same way this repo already keeps `/admin`
// Spanish-only by product decision (`PLAN_PHASE14.md` §1.10) independent of
// a customer-facing page's own `lang`.
const TIME_ZONE = 'America/Costa_Rica';

export type DateLocale = 'es-CR' | 'en-US';

/** `"19/08/2026, 14:05"` (es-CR) / `"08/19/2026, 14:05"` (en-US) — minute
 * precision, matching what every "when did this happen" column in this app
 * actually needs; every field explicit, so server and client render
 * byte-identical text for the same ISO timestamp regardless of either
 * one's own ambient locale/timezone. */
export function formatDateTime(iso: string, locale: DateLocale = 'es-CR'): string {
  return new Date(iso).toLocaleString(locale, {
    timeZone: TIME_ZONE,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
}

/** Same shape as `formatDateTime()`, but for the one case where the fixed
 * `America/Costa_Rica` assumption is actually wrong: a live VRM reading is
 * timestamped in THAT SITE's own configured timezone (`vrm.sites.timezone`
 * — already what `victron/vrm_live.py`/`vrm_shape.py` use to talk to VRM),
 * not necessarily Costa Rica, even though every real site today happens to
 * be there. Still fully deterministic server/client (the timezone is an
 * explicit argument, never an ambient default) — this only differs from
 * `formatDateTime()` in WHICH explicit zone gets passed to `Intl`, not in
 * whether one is. `siteTimeZone` falls back to the same
 * `America/Costa_Rica` constant when a site's own `timezone` column is
 * unset. */
export function formatDateTimeInZone(iso: string, siteTimeZone: string | null, locale: DateLocale = 'es-CR'): string {
  return new Date(iso).toLocaleString(locale, {
    timeZone: siteTimeZone || TIME_ZONE,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
}

/** Date only, no time — `"19 ago 2026"` (es-CR) / `"Aug 19, 2026"` (en-US). */
export function formatDate(iso: string, locale: DateLocale = 'es-CR'): string {
  return new Date(iso).toLocaleDateString(locale, {
    timeZone: TIME_ZONE,
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}
