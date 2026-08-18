import 'server-only';

// Coordinates -> location name + ISO country code, the TS behavioral port
// of `calculations/pvgis.py:reverse_geocode()`'s Nominatim half
// (PLAN_PHASE14.md §2 Step 4: "port the *behavior*, not literally reusing
// Python code from a TS file"). One deliberate scope cut from the Python
// original, flagged here rather than silently dropped:
//
// The Python version ALSO resolves an IANA timezone offline via
// `timezonefinder`'s boundary geodata. There is no small JS equivalent —
// the closest npm package (`geo-tz`) ships ~70MB of precomputed timezone
// polygons, which is a real cost to bundle into a Vercel function for a
// "nice to auto-fill" convenience field. Timezone stays a manual, searchable
// <select> here (`lib/timezones.ts`) instead of being auto-filled by this
// helper. Once `vrm_api` (Step 5) exists, the honest fix is a tiny
// `GET /v1/geocode` endpoint backed by the same `timezonefinder` dependency
// the Python pipeline already has installed for other reasons — noted for
// whoever builds Step 5, not solved here.
export type ReverseGeocodeResult = {
  location: string | null;
  countryCode: string | null;
};

export async function reverseGeocode(lat: number, lng: number): Promise<ReverseGeocodeResult | null> {
  try {
    const url = new URL('https://nominatim.openstreetmap.org/reverse');
    url.searchParams.set('lat', String(lat));
    url.searchParams.set('lon', String(lng));
    url.searchParams.set('format', 'json');
    url.searchParams.set('zoom', '10');
    url.searchParams.set('addressdetails', '1');
    // Spanish first, English fallback — matches the Python original's own
    // reasoning verbatim: without this, Nominatim returns names in the
    // LOCAL language of wherever the point resolves to (Ukrainian in
    // Ukraine, Thai in Bangkok), and this app's operators/customers
    // typing coordinates in read Spanish or English, never the local
    // language of a site they're locating on a map.
    url.searchParams.set('accept-language', 'es,en');

    const resp = await fetch(url, {
      headers: { 'User-Agent': 'PaulyCoSolarTool/1.0 (VRM Monitor web)' },
      signal: AbortSignal.timeout(8000),
    });
    if (!resp.ok) return null;
    const data = (await resp.json()) as { address?: Record<string, string> };
    const addr = data.address ?? {};
    const countryCode = addr.country_code ? addr.country_code.toUpperCase() : null;
    const location = addr.city || addr.town || addr.village || addr.county || addr.state || null;
    if (!location && !countryCode) return null;
    return { location, countryCode };
  } catch {
    // Network failure, timeout, or a malformed response — none of these are
    // the caller's fault, and none should crash a form submission. The
    // Server Action that calls this treats `null` as "couldn't resolve
    // those coordinates," the same message the Python original shows.
    return null;
  }
}
