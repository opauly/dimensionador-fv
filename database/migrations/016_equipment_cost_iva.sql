-- Migration 016: per-equipment-item IVA rate
--
-- Admin equipment forms are gaining a cost sub-block (cost_usd + IVA rate +
-- computed total) so the engineer can see what an item actually costs
-- including tax while cataloguing it, without doing the math by hand.
-- Fraction, not percent (0.13 = 13%), matching the convention already used
-- for cost-line IVA elsewhere in the app (proposal cost items, tariff
-- tiers). Defaults to 0 — most catalog items today have no IVA recorded,
-- and 0% (exempt) is the common case for renewable-energy equipment in
-- Costa Rica.

ALTER TABLE panels              ADD COLUMN IF NOT EXISTS cost_iva_rate numeric NOT NULL DEFAULT 0;
ALTER TABLE inverters           ADD COLUMN IF NOT EXISTS cost_iva_rate numeric NOT NULL DEFAULT 0;
ALTER TABLE batteries           ADD COLUMN IF NOT EXISTS cost_iva_rate numeric NOT NULL DEFAULT 0;
ALTER TABLE charge_controllers  ADD COLUMN IF NOT EXISTS cost_iva_rate numeric NOT NULL DEFAULT 0;
ALTER TABLE monitoring_devices  ADD COLUMN IF NOT EXISTS cost_iva_rate numeric NOT NULL DEFAULT 0;

-- monitoring_devices never had a notes column (unlike every other equipment
-- table) — added now for parity, while building its admin CRUD section for
-- the first time (e.g. distinguishing "Cerbo GX" from "Cerbo GX Touch").
ALTER TABLE monitoring_devices  ADD COLUMN IF NOT EXISTS notes text;
