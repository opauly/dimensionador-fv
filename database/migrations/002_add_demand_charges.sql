-- Migration 002: Add demand charge columns to tariff_types for commercial tariffs (T-CO)
-- Run in Supabase SQL Editor

ALTER TABLE tariff_types
    ADD COLUMN IF NOT EXISTS demand_rate_crc     numeric NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS demand_threshold_kw int     NOT NULL DEFAULT 0;
