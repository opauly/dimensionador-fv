import type { Metadata } from 'next';
import { fontVariables } from './fonts';
import '../styles/tokens.css';
import '../styles/base.css';

// No `metadataBase` here on purpose: Next.js needs it to turn the marketing
// page's relative `openGraph.images` path into an absolute URL, but the
// real domain is PLAN_PHASE14.md §0.4 Q1 — still open, resolved only at
// Step 8. Leaving it unset produces a harmless build-time console warning
// (Next falls back to resolving against the request's own origin) instead
// of baking in a domain guess (`monitor.paulyco.com`) that Oscar hasn't
// confirmed; revisit this once §0.4 Q1 is answered.
export const metadata: Metadata = {
  title: {
    default: 'VRM Monitor',
    template: '%s · VRM Monitor',
  },
  description:
    'VRM Monitor turns the Victron VRM export nobody opens into a branded, AI-narrated report your customers actually read — automatically, every week.',
};

export default function RootLayout({ children }: LayoutProps<'/'>) {
  // Font variable classNames go on <html> (not <body>) so every CSS Module
  // in the tree — including ones rendered inside <head>-adjacent contexts —
  // can resolve --font-big-shoulders / --font-plex-sans / --font-plex-mono.
  return (
    <html lang="en" className={fontVariables}>
      <body>{children}</body>
    </html>
  );
}
