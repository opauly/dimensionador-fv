import type { Metadata } from 'next';
import { AccessForm, FlowSteps, Footer, Hero, ModuleGrid, Nav, Pricing, ReportPreview } from '@/components/marketing';

// Page-specific metadata layered on top of the root layout's defaults
// (app/layout.tsx) — the marketing home page is the one URL that should
// carry the full title/description/OG copy; other routes (styleguide,
// eventually /app, /admin) don't want to be indexed the same way.
// `title.absolute` opts out of the root layout's "%s · VRM Monitor"
// template — the home page's title already reads as a full sentence, not a
// page name that wants "VRM Monitor" appended a second time.
export const metadata: Metadata = {
  title: { absolute: 'VRM Monitor — Weekly reports from your Victron system' },
  description:
    'The Victron VRM export nobody opens, turned into a branded, AI-narrated report your customers actually read — automatically, every week. For one home or a whole installer fleet.',
  openGraph: {
    title: 'VRM Monitor — Weekly reports from your Victron system',
    description:
      'The Victron VRM export nobody opens, turned into a branded, AI-narrated report your customers actually read — automatically, every week.',
    images: [{ url: '/sample_report.png', width: 1819, height: 2573, alt: 'A sample VRM Monitor weekly report' }],
  },
};

// (marketing) is a route group — it does not add a URL segment, so this is
// still the site root ("/"). Grouped so later steps' (auth)/(portal)/(admin)
// route groups can each carry their own layout without this one's Nav/
// Footer leaking into /app or /admin, which get their own AppShell
// (PLAN_PHASE14.md §1.7's component tree, Steps 3-4).
export default function MarketingPage() {
  return (
    <>
      <Nav />
      <Hero />
      <FlowSteps />
      <ModuleGrid />
      <ReportPreview />
      <Pricing />
      <AccessForm />
      <Footer />
    </>
  );
}
