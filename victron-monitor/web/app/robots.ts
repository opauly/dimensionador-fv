import type { MetadataRoute } from 'next';
import { SITE_URL } from '@/lib/site';

// Widened at deploy time (PLAN_PHASE14.md §2 Step 8): /app and /admin were
// placeholders when this file was first written (Steps 3-4 of this phase),
// but both are real, auth-gated surfaces now. A signed-out request still
// gets redirected to /login either way — this is about not inviting a
// crawler into either path on a real, publicly indexable domain, not a
// security boundary (that's `requireCustomer()`/`requireAdmin()`).
export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: '*',
      allow: '/',
      disallow: ['/app', '/admin'],
    },
    sitemap: `${SITE_URL}/sitemap.xml`,
  };
}
