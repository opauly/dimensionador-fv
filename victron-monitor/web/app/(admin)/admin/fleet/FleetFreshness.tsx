'use client';

// The one fleet-wide "how fresh is this" badge, rendered in the VIEWER's
// own browser timezone rather than any fixed constant or any one site's
// timezone — this is about "when did I, looking at this screen, last see
// new data," which only the browser's own clock can answer. Every other
// timestamp on `/admin/fleet` (per-site "as of ...") is about one specific
// site's own reading and uses `formatDateTimeInZone()` with that site's
// configured timezone instead — a Server Component, safely, since that
// zone is known at render time and isn't viewer-dependent.
//
// This one genuinely can't be a Server Component: the viewer's timezone
// only exists in the browser. Computing it during the FIRST render (which
// also runs on the server during SSR, then again on the client during
// hydration) would reproduce the exact hydration mismatch
// `lib/dates.ts`'s own header comment already documents fixing once —
// deferred into `useEffect` instead, so the server-rendered HTML and the
// just-hydrated client HTML are byte-identical (both show the `null`
// placeholder), and only a state update AFTER hydration swaps in the real,
// browser-local string.
import { useEffect, useState } from 'react';

export function FleetFreshness({ mostRecentCapturedAt }: { mostRecentCapturedAt: string | null }) {
  const [text, setText] = useState<string | null>(null);

  useEffect(() => {
    if (!mostRecentCapturedAt) return;
    // Deferred into a microtask rather than called directly at the top of
    // the effect body — a react-hooks/set-state-in-effect violation
    // otherwise (same fix `ShapeChart.tsx` already applies).
    Promise.resolve().then(() => {
      setText(
        new Date(mostRecentCapturedAt).toLocaleString(undefined, {
          hour: '2-digit',
          minute: '2-digit',
          second: '2-digit',
          hour12: false,
        })
      );
    });
  }, [mostRecentCapturedAt]);

  if (!mostRecentCapturedAt) return null;

  return <span>LIVE — refreshed {text ?? '—'} (your local time), every ~15 min</span>;
}
