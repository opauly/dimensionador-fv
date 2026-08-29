// Static illustrative thumbnails for the report module selection checklist
// (PLAN_PHASE18.md — Oscar's own instruction, 2026-08-29: "show a preview
// of each one... to have more context on what it is tracking"). Plain,
// self-contained inline SVG icons, one per selectable module id — same
// icon for every site regardless of that site's own data, matching the
// "static illustrative thumbnail" option Oscar chose over a live per-site
// mini-render (which would mean computing real report data just to
// populate a checklist).
//
// Pure presentational data with no server-only imports, so it's safe to
// import from a Client Component on either side of the portal/admin
// boundary — same reasoning `lib/countries.ts`/`lib/timezones.ts` already
// establish for sharing plain data across that boundary, while the actual
// module-id lists and entitlement checks stay duplicated per that
// boundary's own established rule.
import type { ReactElement } from 'react';

const ICON_PROPS = {
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.6,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
};

export const REPORT_MODULE_ICONS: Record<string, ReactElement> = {
  energy_mix: (
    <svg {...ICON_PROPS}>
      <circle cx="12" cy="12" r="8.2" />
      <path d="M12 3.8 A8.2 8.2 0 0 1 19.3 15.5 L12 12 Z" fill="currentColor" stroke="none" opacity="0.35" />
      <path d="M12 12 L12 3.8" />
      <path d="M12 12 L19.3 15.5" />
    </svg>
  ),
  battery_health: (
    <svg {...ICON_PROPS}>
      <rect x="3" y="8" width="15" height="8" rx="1.5" />
      <rect x="19" y="10.5" width="2" height="3" fill="currentColor" stroke="none" />
      <path d="M6.5 12 L9 12 L10.2 9.8 L12.2 14.2 L13.6 12 L15.5 12" />
    </svg>
  ),
  grid_quality: (
    <svg {...ICON_PROPS}>
      <path d="M13 3 L5 13 h5 l-1 8 8-11 h-5 z" />
    </svg>
  ),
  events: (
    <svg {...ICON_PROPS}>
      <path d="M12 3 v3" />
      <path d="M12 21 v-3" />
      <circle cx="12" cy="12" r="6.5" />
      <path d="M12 8.5 v4 l2.5 2" />
    </svg>
  ),
  soc_chart: (
    <svg {...ICON_PROPS}>
      <path d="M3 20 h18" />
      <path d="M4 16 l4-6 4 3 4-8 4 5" />
    </svg>
  ),
  solar_performance: (
    <svg {...ICON_PROPS}>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 3 v2.2 M12 18.8 V21 M3 12 h2.2 M18.8 12 H21 M5.6 5.6 l1.6 1.6 M16.8 16.8 l1.6 1.6 M18.4 5.6 l-1.6 1.6 M7.2 16.8 l-1.6 1.6" />
    </svg>
  ),
  weather: (
    <svg {...ICON_PROPS}>
      <path d="M7 17.5 a4 4 0 1 1 1.2-7.8 5 5 0 0 1 9.6 1.8 3.5 3.5 0 0 1-1.3 6 z" />
    </svg>
  ),
  trend: (
    <svg {...ICON_PROPS}>
      <path d="M3 17 l6-6 4 4 8-9" />
      <path d="M15 6 h6 v6" />
    </svg>
  ),
  savings: (
    <svg {...ICON_PROPS}>
      <circle cx="12" cy="12" r="8.2" />
      <path d="M14.5 9 a2.6 2.6 0 0 0-2.5-1.8c-1.6 0-2.7 1-2.7 2.2 0 3 5.4 1.4 5.4 4.3 0 1.3-1.2 2.3-2.8 2.3a2.9 2.9 0 0 1-2.8-1.8" />
      <path d="M12 6 v1.2 M12 16.8 V18" />
    </svg>
  ),
  critical_alerts: (
    <svg {...ICON_PROPS}>
      <path d="M12 3.5 L21 19.5 H3 Z" />
      <path d="M12 9.5 v5" />
      <circle cx="12" cy="17" r="0.15" fill="currentColor" stroke="currentColor" strokeWidth="2.2" />
    </svg>
  ),
  grid_meter_detail: (
    <svg {...ICON_PROPS}>
      <path d="M4 16 a8 8 0 0 1 16 0" />
      <path d="M12 16 l4-5.5" />
      <circle cx="12" cy="16" r="1" fill="currentColor" stroke="none" />
      <path d="M3 20 h18" />
    </svg>
  ),
  generator_runtime: (
    <svg {...ICON_PROPS}>
      <rect x="3" y="7" width="13" height="10" rx="1.2" />
      <path d="M8 10 v4 M12 10 v4" />
      <path d="M18 10 l2.5-1.5 v9 L18 16" />
    </svg>
  ),
  tank_level: (
    <svg {...ICON_PROPS}>
      <path d="M7 4 h10 l1.5 4.5 v10 a1.5 1.5 0 0 1-1.5 1.5 H7 a1.5 1.5 0 0 1-1.5-1.5 v-10 Z" />
      <path d="M6 13 h12" />
    </svg>
  ),
};
