-- 051: track the commercial discount (or premium) between the quote and the
-- final agreed price.
--
-- The quote lines and versions are never touched when a customer negotiates;
-- the final price is `projects.contract_usd` (already what payments and profit
-- use). These columns record what was quoted and why the price moved:
--   quoted_usd              snapshot of the quote total the project was promoted from
--                           (or the baseline the customer was first offered)
--   price_adjustment_reason free text ("-$300 en materiales eléctricos")
--   price_adjusted_at       when the baseline/reason was last set
-- The discount itself (quoted_usd - contract_usd, and its %) is always derived.
--
-- Additive and idempotent.

ALTER TABLE projects
    ADD COLUMN IF NOT EXISTS quoted_usd numeric(10,2),
    ADD COLUMN IF NOT EXISTS price_adjustment_reason text,
    ADD COLUMN IF NOT EXISTS price_adjusted_at timestamptz;
