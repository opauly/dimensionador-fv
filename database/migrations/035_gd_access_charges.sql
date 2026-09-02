-- Migration 035: Generacion Distribuida access charges (COA, CVG) on tariff_types
-- Run in Supabase SQL Editor
--
-- Confirmed from three real CNFL invoices (Rainforest Lab / Casa Garleo
-- S.A., NISE 28487956, Jan/Apr/Aug 2026) that a customer enrolled in
-- Generacion Distribuida (i.e. anyone with grid-tied solar under net
-- metering) is billed two charges beyond the plain tariff: COA (Costo de
-- Acceso Generacion Distribuida) and, intermittently, CVG (Costo Variable
-- Generacion). Both vary independently of kWh delivered -- two bills for
-- the identical 410 kWh had COA of 9,085 and 14,020 colones -- so they are
-- modeled here as flat monthly averages, not a rate applied to consumption.
--
-- A third charge, IOS (Impuesto Otros Servicios), is NOT a stored column:
-- across all three real bills IOS = round(COA x 0.13) held within 3 colones
-- (a 13% tax specifically on COA, distinct from the main IVA line, which is
-- 13% of the energy charge only) -- see calculations/tariff_calculator.py,
-- which derives it instead of storing it.
--
-- A fourth charge, DER (Recursos Energeticos Distribuidos), is deliberately
-- NOT added here at Oscar's explicit direction (2026-09-02): Grid Zero and
-- Hybrid proposal projections should match the real invoice as closely as
-- practical EXCLUDING DER specifically.
--
-- DEFAULT 0 for the same reason as migration 034's alumbrado_publico_rate_crc:
-- these are confirmed real charges for ONE CNFL account on a tariff whose
-- exact code is still unresolved (the invoice prints "TARIFA COMERCIAL" but
-- its own tariff desglose is labeled "TARIFA RESIDENCIAL (T RE)" with a flat,
-- untiered rate that matches neither of CNFL's two currently-seeded tariff
-- rows -- T-RE's tiers or T-CO's demand-charge structure). Do not copy these
-- values onto other tariff_types rows without a real invoice for that
-- specific row's code.

ALTER TABLE tariff_types
    ADD COLUMN IF NOT EXISTS coa_monthly_crc numeric NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS cvg_monthly_crc numeric NOT NULL DEFAULT 0;
