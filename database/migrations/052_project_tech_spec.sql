-- 052: per-project technical settings for the "Técnico" tab.
--
-- tech_spec holds what the project (not the quote) decides about its engineering view:
--   {"version_id": "<proposal version the tab reads the design from>",
--    "wiring_lengths": {"pv_cc_m": 15, "cc_bat_m": 2, ...}}   -- cable runs measured on site
-- Both are optional; with an empty object the tab uses the proposal's latest locked version
-- and default lengths. Additive and idempotent.

ALTER TABLE projects ADD COLUMN IF NOT EXISTS tech_spec jsonb NOT NULL DEFAULT '{}'::jsonb;
