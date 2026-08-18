import type { MetadataRoute } from 'next';
import { SITE_URL } from '@/lib/site';

// One entry: the marketing home page is the only public, indexable route
// this step ships. /login (Step 3) is a form, not content to index; /app
// and /admin (Steps 3-4) are behind auth. Extend this array as later steps
// add public marketing routes — there are none planned yet (§4's non-goals
// rule out a blog/CMS).
export default function sitemap(): MetadataRoute.Sitemap {
  return [
    {
      url: SITE_URL,
      lastModified: new Date(),
      changeFrequency: 'monthly',
      priority: 1,
    },
  ];
}
