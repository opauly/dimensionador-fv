// The §1.8 brand-blue A/B: four candidates for --victron (the original
// shipped RAL 5012 value, two photo-matched candidates Oscar sampled off
// the real MultiPlus-II, and a fourth he added directly), and the two
// button-fill treatments from the same section's accessibility note. Kept
// as a small typed table, not a free-text query param, so an unrecognized
// value falls back to the shipped default instead of silently rendering an
// arbitrary color.
//
// DECIDED 2026-08-17: Oscar picked #0789D4 + flat (tokens.css's --victron
// and --btn-fill ship that combination now). The other three candidates —
// including §1.8's original #0588B6 recommendation — are kept selectable
// here as a live reference for why, not dead code; removing them would
// make a future re-litigation of this choice start from zero again.

export const BLUE_CANDIDATES = ['0789D4', '0588B6', '3481B8', '0089B6'] as const;
export type BlueCandidate = (typeof BLUE_CANDIDATES)[number];

export const DEFAULT_BLUE: BlueCandidate = '0789D4';

export const BLUE_LABELS: Record<BlueCandidate, string> = {
  '0789D4': '#0789D4 — shipped (Oscar’s pick, 2026-08-17)',
  '0588B6': '#0588B6 — photo-matched, was §1.8’s recommendation before #0789D4',
  '3481B8': '#3481B8 — photo-matched, greyer/softer alternative',
  '0089B6': '#0089B6 — original shipped value (RAL 5012 spec)',
};

export const BTN_TREATMENTS = ['flat', 'deep'] as const;
export type BtnTreatment = (typeof BTN_TREATMENTS)[number];

// DECIDED 2026-08-17, alongside the blue: flat (tokens.css's --btn-fill
// is var(--victron), unchanged from the original shipped default).
export const DEFAULT_BTN: BtnTreatment = 'flat';

export const BTN_LABELS: Record<BtnTreatment, string> = {
  flat: '--victron fill — shipped (status quo, ~4.0–4.2:1 with white — below AA for normal text)',
  deep: '--victron-deep fill (5.91:1 with white) — considered, not picked',
};

function firstValue(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export function parseBlueParam(value: string | string[] | undefined): BlueCandidate {
  const candidate = firstValue(value)?.toUpperCase();
  return (BLUE_CANDIDATES as readonly string[]).includes(candidate ?? '') ? (candidate as BlueCandidate) : DEFAULT_BLUE;
}

export function parseBtnParam(value: string | string[] | undefined): BtnTreatment {
  const candidate = firstValue(value)?.toLowerCase();
  return (BTN_TREATMENTS as readonly string[]).includes(candidate ?? '') ? (candidate as BtnTreatment) : DEFAULT_BTN;
}

/** '0588B6' -> '5, 136, 182' — the rgb triplet tokens.css's rgba() rules need alongside the hex value. */
export function hexToRgbTriplet(hex: string): string {
  const clean = hex.replace(/^#/, '');
  const r = parseInt(clean.slice(0, 2), 16);
  const g = parseInt(clean.slice(2, 4), 16);
  const b = parseInt(clean.slice(4, 6), 16);
  return `${r}, ${g}, ${b}`;
}

function hexToRgb(hex: string): [number, number, number] {
  const clean = hex.replace(/^#/, '');
  return [parseInt(clean.slice(0, 2), 16), parseInt(clean.slice(2, 4), 16), parseInt(clean.slice(4, 6), 16)];
}

function rgbToHsl(r: number, g: number, b: number): [number, number, number] {
  const rn = r / 255, gn = g / 255, bn = b / 255;
  const max = Math.max(rn, gn, bn), min = Math.min(rn, gn, bn);
  const l = (max + min) / 2;
  if (max === min) return [0, 0, l * 100];
  const d = max - min;
  const s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
  let h: number;
  switch (max) {
    case rn: h = (gn - bn) / d + (gn < bn ? 6 : 0); break;
    case gn: h = (bn - rn) / d + 2; break;
    default: h = (rn - gn) / d + 4;
  }
  return [h * 60, s * 100, l * 100];
}

function hslToHex(h: number, s: number, l: number): string {
  const sn = s / 100, ln = l / 100;
  const c = (1 - Math.abs(2 * ln - 1)) * sn;
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
  const m = ln - c / 2;
  let [r, g, b] = [0, 0, 0];
  if (h < 60) [r, g, b] = [c, x, 0];
  else if (h < 120) [r, g, b] = [x, c, 0];
  else if (h < 180) [r, g, b] = [0, c, x];
  else if (h < 240) [r, g, b] = [0, x, c];
  else if (h < 300) [r, g, b] = [x, 0, c];
  else [r, g, b] = [c, 0, x];
  const toHex = (v: number) => Math.round((v + m) * 255).toString(16).padStart(2, '0');
  return `${toHex(r)}${toHex(g)}${toHex(b)}`;
}

// The shipped --victron-deep (#046c90, tokens.css) is a fixed value derived
// once from the original #0089b6: ~6.7 points less HSL lightness and a
// slightly lower saturation (35.7%->29.0% L, 100%->94.6% S — verified by
// direct conversion, not eyeballed). That fixed hex is right for the one
// candidate it was computed from, but the /styleguide page exists to let
// Oscar compare candidates on real components — under the default `btn=deep`
// treatment, showing that same fixed #046c90 for every candidate makes the
// primary CTA button look identical no matter which ?blue= is selected,
// which defeats the page's purpose (confirmed: Oscar clicked through the
// three candidates and saw no button-color change at all). Reproducing the
// same relative lightness/saturation drop against whichever candidate is
// selected keeps every candidate's "deep" swatch meaningfully derived from
// its own base blue, the way §1.8 actually describes the token ("a derived
// --victron-deep"), rather than one candidate's fixed answer standing in for
// all three. tokens.css's own #046c90 is untouched — this only affects the
// exploratory swap on this page.
export function deriveDeepHex(baseHex: string): string {
  const [r, g, b] = hexToRgb(baseHex);
  const [h, s, l] = rgbToHsl(r, g, b);
  return hslToHex(h, Math.max(0, s - 5.5), Math.max(0, l - 6.7));
}
