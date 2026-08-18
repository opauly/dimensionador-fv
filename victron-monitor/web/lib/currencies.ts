// Flat-rate currency vocabulary — ported verbatim from
// `victron/savings.py:SUPPORTED_FLAT_CURRENCIES`. Only meaningful for sites
// with `country !== 'CR'` (migration 014): Costa Rica sites compute savings
// from the blended ARESEP tariff automatically and never read
// `savings_currency`.
export const SUPPORTED_FLAT_CURRENCIES = ['CRC', 'USD', 'EUR'] as const;

export type FlatCurrency = (typeof SUPPORTED_FLAT_CURRENCIES)[number];
