-- Migration 036: IOS (Impuesto Otros Servicios) on tariff_types
-- Run in Supabase SQL Editor
--
-- Migration 035 modeled IOS as derived (round(coa_monthly_crc * 0.13)),
-- based on it matching within 3 colones across three real Rainforest Lab
-- bills. A second, unrelated CNFL commercial customer (Choto Cruz Pacheco
-- Cayetano, NISE 27967117, Aug 2026 -- confirmed NOT enrolled in
-- Generacion Distribuida: no DER, no COA, no CVG line items at all) still
-- carries an IOS charge of 1,460 colones. That falsifies the derived
-- formula (COA=0 would predict IOS=0) and shows IOS is not
-- Generacion-Distribuida-specific -- it applies to plain commercial-tariff
-- customers too. No formula (percent of energy, alumbrado, or per-kWh
-- rate) fit the 4 real data points gathered so far.
--
-- So IOS moves from "derived inside include_gd_charges" to its own flat
-- monthly column, modeled like alumbrado_publico_rate_crc: always applied
-- when set (not gated behind include_gd_charges, since it isn't
-- solar-specific), defaulting to 0 ("unverified for this row," not
-- "genuinely zero") until confirmed per tariff row from a real invoice.
--
-- See calculations/tariff_calculator.py's docstring for the corrected
-- reasoning and estimate_bill_crc()'s updated formula.

ALTER TABLE tariff_types
    ADD COLUMN IF NOT EXISTS ios_monthly_crc numeric NOT NULL DEFAULT 0;
