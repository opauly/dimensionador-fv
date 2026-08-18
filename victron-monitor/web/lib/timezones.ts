// IANA timezone list + default, the TS equivalent of
// `pages/06_vrm_monitor.py`'s `_timezones()` / `_tz_index()` (PLAN_PHASE14.md
// §2 Step 4: "port the *behavior*, not literally reusing Python code from a
// TS file"). The Python original reads `zoneinfo.available_timezones()` —
// the host's IANA tzdata, sorted, with a short hardcoded fallback if the
// host has none. `Intl.supportedValuesOf('timeZone')` is the direct
// behavioral equivalent: it reads from the *same* underlying ICU/tzdata the
// V8/Node runtime ships with, so this list agrees with what the Streamlit
// tool would show on the same day. Available in Node >= 18 and every
// evergreen browser, but not universally polyfilled everywhere React might
// render this — the try/catch mirrors the Python original's own defensive
// fallback for exactly that reason.
//
// Not `lib/server/` — this needs to run in the "New site..." client
// component (`app/(portal)/app/sites`) for the searchable <select>, not
// just on the server.

const FALLBACK_TIMEZONES = [
  'America/Costa_Rica',
  'America/New_York',
  'America/Mexico_City',
  'America/Bogota',
  'America/Sao_Paulo',
  'Europe/Madrid',
  'UTC',
];

let _cache: string[] | null = null;

export function listTimezones(): string[] {
  if (_cache) return _cache;
  try {
    _cache = [...Intl.supportedValuesOf('timeZone')].sort();
  } catch {
    _cache = FALLBACK_TIMEZONES;
  }
  return _cache;
}

export const DEFAULT_TIMEZONE = 'America/Costa_Rica';

/** Mirrors `_tz_index()`'s "fall back to the first entry if the default
 * isn't in the list" — used by the Python original to pick a <selectbox>'s
 * initial index; here it just validates a default is usable at all. */
export function isKnownTimezone(tz: string): boolean {
  return listTimezones().includes(tz);
}
