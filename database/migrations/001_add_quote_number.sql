-- Migration 001: Add quote_number to proposals
-- Run in Supabase SQL Editor (Project → SQL Editor → New query)

ALTER TABLE proposals ADD COLUMN IF NOT EXISTS quote_number int;

-- Back-fill existing rows with sequential numbers within each year
UPDATE proposals
SET quote_number = subq.rn
FROM (
    SELECT id,
           ROW_NUMBER() OVER (
               PARTITION BY EXTRACT(YEAR FROM created_at)
               ORDER BY created_at
           ) AS rn
    FROM proposals
    WHERE quote_number IS NULL
) subq
WHERE proposals.id = subq.id;
