// Slug generation — a near-verbatim port of `victron/ingest.py:slugify()` /
// `make_site_id()`. Kept here, not `lib/server/`, because it's pure string
// logic with no Supabase call and no secret: `lib/server/db/sites.ts`'s
// `createSite()` is the only real caller today, but nothing about the
// function itself needs to be server-only.
//
// `site_id` is the global key every child table in `vrm` references
// (`vrm.energy_daily.site_id`, `vrm.ingestion_log.site_id`, ...), namespaced
// `<customer-slug>-<site-slug>` so two different customers can each have a
// site they'd naturally call "casa-principal" without colliding — see
// migration 012's own comment on `vrm.sites.site_id`.

// U+0300-U+036F is the "Combining Diacritical Marks" block that
// `String.prototype.normalize('NFKD')` produces when it decomposes a
// precomposed accented character (é -> e + U+0301). Stripping just this
// range — not stripping every non-ASCII character wholesale — is what turns
// "José" into "jose", matching `unicodedata.normalize('NFKD', ...)` +
// `unicodedata.combining()` in the Python original, rather than the
// mangled "jos-" an earlier version of that tool produced by dropping the
// accented character outright (ingest.py's own docstring records this).
const COMBINING_MARKS_RE = /[\u0300-\u036f]/g;

/**
 * Lowercase ASCII slug, matching `vrm.customers.slug`'s CHECK constraint
 * (`^[a-z0-9][a-z0-9-]*$`). The slug *is* the site's identity (namespaced
 * into `site_id`), so two spellings of the same name must not silently
 * produce two different site_ids — see `COMBINING_MARKS_RE` above for why
 * this transliterates accents instead of stripping them.
 */
export function slugify(value: string): string {
  const decomposed = value.trim().toLowerCase().normalize('NFKD');
  const asciiOnly = decomposed.replace(COMBINING_MARKS_RE, '');
  const s = asciiOnly.replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
  if (!s || !/^[a-z0-9]/.test(s)) {
    throw new Error(`Cannot build a slug from ${JSON.stringify(value)}`);
  }
  return s;
}

/** Namespaced `site_id` — see the module comment for why this must stay
 * globally unique and customer-prefixed. */
export function makeSiteId(customerSlug: string, siteSlug: string): string {
  return `${slugify(customerSlug)}-${slugify(siteSlug)}`;
}
