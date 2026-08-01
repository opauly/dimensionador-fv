-- Migration 014: flat electricity rate for non-CR `vrm` sites
--
-- Estimated savings in the weekly report has two paths, chosen by
-- `sites.country` (already exists, default 'CR', both schemas) — never a
-- distributor/company picker:
--
--   country = 'CR'  → real ARESEP tiered bill formula
--                      (calculations/tariff_calculator.py), blended across
--                      every seeded distributor's T-RE tariff into one
--                      effective rate. No new columns needed — reads the
--                      existing public.distributors/tariff_types/tariff_tiers
--                      tables that already exist for the proposal tool.
--   country != 'CR' → whatever flat rate + currency the operator entered at
--                      upload. These are the two columns this migration adds.
--
-- Only `vrm.sites` needs them. `monitoring.sites` is Pauly & Co's own fleet —
-- every real site today is Costa Rica — so the CR path alone covers it; this
-- can be revisited if that ever stops being true.

ALTER TABLE vrm.sites
  ADD COLUMN IF NOT EXISTS savings_rate     numeric,
  ADD COLUMN IF NOT EXISTS savings_currency text;

COMMENT ON COLUMN vrm.sites.savings_rate IS
  'Flat electricity rate per kWh, used for savings estimation when country != CR. Ignored for CR sites, which use the blended ARESEP calculation instead.';
COMMENT ON COLUMN vrm.sites.savings_currency IS
  'Currency code for savings_rate (e.g. USD, EUR, CRC). Display label only — no FX conversion performed.';
