// Shared between app/robots.ts and app/sitemap.ts, both of which need an
// absolute URL and neither of which can rely on request context (they're
// static-by-default special routes — see their own "Good to know" note in
// the Next.js docs about caching). The real domain is still open
// (PLAN_PHASE14.md §0.4 Q1); SITE_URL lets Step 8 override this via env
// without touching either file, and the fallback keeps `npm run build`
// producing a valid absolute URL today rather than failing.
export const SITE_URL = process.env.SITE_URL ?? 'https://monitor.paulyco.com';
