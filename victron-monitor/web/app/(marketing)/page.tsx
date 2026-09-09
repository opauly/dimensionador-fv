import type { Metadata } from 'next';
import { FlowSteps, Footer, Hero, LiveDashboard, ModuleGrid, Nav, Pricing, ReportPreview, StatsBanner } from '@/components/marketing';
import { getFeaturedSelfServePlanIds } from '@/lib/server/db/signup';
import { getMarketingStats } from '@/lib/server/db/marketingStats';

// Page-specific metadata layered on top of the root layout's defaults
// (app/layout.tsx) — the marketing home page is the one URL that should
// carry the full title/description/OG copy; other routes (styleguide,
// eventually /app, /admin) don't want to be indexed the same way.
// `title.absolute` opts out of the root layout's "%s · VRM Monitor"
// template — the home page's title already reads as a full sentence, not a
// page name that wants "VRM Monitor" appended a second time.
export const metadata: Metadata = {
  title: { absolute: 'VRM Monitor — Live dashboard + weekly reports for your Victron system' },
  description:
    'Watch your Victron system live, and get a branded, AI-narrated report every week — for your own home, or every customer on an installer fleet.',
  openGraph: {
    title: 'VRM Monitor — Live dashboard + weekly reports for your Victron system',
    description:
      'Watch your Victron system live, and get a branded, AI-narrated report every week — for your own home, or every customer on an installer fleet.',
    images: [{ url: '/sample_report.png', width: 1819, height: 2573, alt: 'A sample VRM Monitor weekly report' }],
  },
};

// ISR, not static-forever (2026-09-08) — found live via `npm run build`'s
// own route table: with no revalidate/dynamic export at all, this page had
// been fully static (`○ /`, "prerendered as static content"), meaning
// StatsBanner's numbers were frozen at whatever they happened to be at the
// last deploy, not actually "auto-updated each day" the way the banner's
// own "Tracked so far" framing implies. 86400s (24h) matches that stated
// expectation exactly: Next.js serves the cached page for up to a day, then
// regenerates it in the background on the next request past that window —
// still CDN-cacheable in between, no per-request Supabase round trip, but
// genuinely fresh at most once a day rather than only at the next
// unrelated deploy.
export const revalidate = 86400;

// (marketing) is a route group — it does not add a URL segment, so this is
// still the site root ("/"). Grouped so later steps' (auth)/(portal)/(admin)
// route groups can each carry their own layout without this one's Nav/
// Footer leaking into /app or /admin, which get their own AppShell
// (PLAN_PHASE14.md §1.7's component tree, Steps 3-4).
//
// `AccessForm` (the mailto "request early access" section) is retired as
// of PLAN_PHASE16.md §8 Step 5.5 — Oscar's explicit decision, now that
// `/signup` is a real self-serve flow rather than a waitlist. A Server
// Component (unlike `Pricing`, a client component) so it can fetch the two
// featured plans' real `vrm.plans.id`s directly and hand them down as
// props — `Pricing`'s own "Get started" buttons need a real id to
// preselect, not the marketing `plan_key` string.
export default async function MarketingPage() {
  const [featuredPlans, stats] = await Promise.all([getFeaturedSelfServePlanIds(), getMarketingStats()]);

  return (
    <>
      <Nav />
      {stats && (
        <StatsBanner
          sitesMonitored={stats.sitesMonitored}
          installedKwp={stats.installedKwp}
          kwhTracked={stats.kwhTracked}
        />
      )}
      <Hero />
      <FlowSteps />
      <ModuleGrid />
      <ReportPreview />
      <LiveDashboard />
      <Pricing starterPlanId={featuredPlans.starter} growthPlanId={featuredPlans.growth} />
      <Footer />
    </>
  );
}
