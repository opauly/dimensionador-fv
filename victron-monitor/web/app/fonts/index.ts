// next/font/local, not <link> tags or @font-face in a stylesheet: this gets
// Next.js's automatic self-hosting, preload wiring, and font-display: swap
// for free, and — unlike the landing page — never needs the files inlined
// as base64. landing-page/build.py's base64 inlining exists only to satisfy
// the Claude Artifact CSP (no external font requests allowed on an
// Artifact); on a real host that inlining is pure page weight with no
// upside, so this side of the port drops it (PLAN_PHASE14.md §1.7).
import localFont from 'next/font/local';

// Big Shoulders and IBM Plex Sans ship as one variable-weight file each —
// landing_template.html declares each with a font-weight *range* in a
// single @font-face, so one src entry with a weight range reproduces that
// exactly. IBM Plex Mono ships as two static-weight files because that is
// what the template itself has two separate @font-face blocks for (400 body
// copy, 500 the eyebrow/label/button weight) — matched here, not merged.
export const bigShoulders = localFont({
  src: './bigshoulders.woff2',
  weight: '300 900',
  style: 'normal',
  display: 'swap',
  variable: '--font-big-shoulders',
});

export const plexSans = localFont({
  src: './plexsans.woff2',
  weight: '100 900',
  style: 'normal',
  display: 'swap',
  variable: '--font-plex-sans',
});

export const plexMono = localFont({
  src: [
    { path: './plexmono400.woff2', weight: '400', style: 'normal' },
    { path: './plexmono500.woff2', weight: '500', style: 'normal' },
  ],
  display: 'swap',
  variable: '--font-plex-mono',
});

// One string of every face's CSS variable class name, applied once on
// <html> in app/layout.tsx. styles/tokens.css's --font-* tokens reference
// these variable names, not the literal family strings, which is what next/
// font/local actually requires (it renames each family to a scoped/hashed
// name at build time — the token can't just say 'Big Shoulders').
export const fontVariables = [bigShoulders.variable, plexSans.variable, plexMono.variable].join(' ');
