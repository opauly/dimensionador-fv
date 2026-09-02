-- Migration 034: Add alumbrado publico (public lighting) rate to tariff_types
-- Run in Supabase SQL Editor
--
-- Confirmed from real CNFL invoices (Rainforest Lab / Casa Garleo S.A.,
-- NISE 28487956, commercial tariff, Curridabat) that every bill carries a
-- separate "ALUMBRADO PUBLICO" line item, billed at a flat rate per kWh
-- consumed and printed directly on the invoice ("COSTO POR kWh DE
-- ALUMBRADO PUBLICO: ¢3.02") -- distinct from the tiered energy charge and
-- from the bomberos levy, and previously not modeled anywhere in this
-- project's bill estimate (calculations/tariff_calculator.py had no field
-- for it at all).
--
-- DEFAULT 0, not a guessed nonzero value: alumbrado publico is set per
-- canton/municipality in Costa Rica, so the one confirmed rate (Curridabat,
-- commercial tariff) should not be assumed to apply to every distributor or
-- even every canton within CNFL's own territory. Existing rows stay at 0
-- (today's under-count, same as before this migration) until each one is
-- verified against a real invoice for that specific area -- see
-- calculations/tariff_calculator.py's docstring.

ALTER TABLE tariff_types
    ADD COLUMN IF NOT EXISTS alumbrado_publico_rate_crc numeric NOT NULL DEFAULT 0;
