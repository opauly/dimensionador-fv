import type { MetadataRoute } from 'next';
import { SITE_URL } from '@/lib/site';

// Nothing under /app or /admin exists yet (Steps 3-4), so there's nothing
// customer-private to disallow today — this only needs to widen once those
// routes land, which is a one-line addition to `disallow` at that step, not
// a redesign of this file.
export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: '*',
      allow: '/',
    },
    sitemap: `${SITE_URL}/sitemap.xml`,
  };
}
