-- Migration 046: bundled visits + manual due-date overrides (Phase 10 follow-up)
--
-- Two real workflow gaps found after migration 045 shipped: Oscar bills one trip that
-- covers several sites for the same customer as one charge, not N separate charges —
-- and a customer sometimes asks to move their visit to a different month, which the
-- computed last-visit + interval schedule can't express on its own.
--
-- next_due_override: NULL = use the computed date (unchanged for every existing
-- property). Set = use this date instead, until the next real visit is logged for
-- that property, which clears it automatically (see database/site_properties_db.py).
--
-- maintenance_visit_groups: one row per bundled trip. Its amount_usd is the ONLY place
-- a bundled visit's charge lives — decided with Oscar (2026-09-07): splitting it across
-- N properties would fabricate a per-site number that was never actually charged.
-- maintenance_visits.visit_group_id links each covered property's own visit row back
-- to it; those rows get amount_usd = NULL (the real number is on the group).
--
-- Idempotent: ADD COLUMN IF NOT EXISTS / CREATE TABLE IF NOT EXISTS — safe to run twice.

ALTER TABLE public.site_properties
  ADD COLUMN IF NOT EXISTS next_due_override date;

CREATE TABLE IF NOT EXISTS public.maintenance_visit_groups (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  client_id     uuid REFERENCES public.clients(id),
  visit_date    date NOT NULL,
  amount_usd    numeric(10,2),
  technician    text,
  notes         text,
  created_at    timestamptz DEFAULT now()
);

ALTER TABLE public.maintenance_visits
  ADD COLUMN IF NOT EXISTS visit_group_id uuid REFERENCES public.maintenance_visit_groups(id);

-- Mirrors calculations/maintenance.py:compute_status()'s new override_date parameter —
-- checked first, before falling back to the last-visit/commissioned_at computation.
CREATE OR REPLACE FUNCTION public.get_property_maintenance_status(p_property_id uuid)
RETURNS TABLE (next_due_date date, status text) AS $$
DECLARE
  v_last_visit date;
  v_interval   int;
  v_override   date;
  v_fallback   date;
  v_base       date;
BEGIN
  SELECT maintenance_interval_days, next_due_override INTO v_interval, v_override
  FROM public.site_properties WHERE id = p_property_id;

  IF v_interval IS NULL THEN
    RETURN;
  END IF;

  IF v_override IS NOT NULL THEN
    next_due_date := v_override;
    status := CASE
      WHEN next_due_date < CURRENT_DATE THEN 'overdue'
      WHEN next_due_date < CURRENT_DATE + 30 THEN 'due_soon'
      ELSE 'up_to_date'
    END;
    RETURN NEXT;
    RETURN;
  END IF;

  SELECT MAX(mv.visit_date) INTO v_last_visit
  FROM public.maintenance_visits mv
  WHERE mv.property_id = p_property_id;

  IF v_last_visit IS NULL THEN
    SELECT MIN(commissioned_at) INTO v_fallback
    FROM monitoring.sites WHERE property_id = p_property_id;

    IF v_fallback IS NULL THEN
      SELECT MIN(commissioned_at) INTO v_fallback
      FROM vrm.sites WHERE property_id = p_property_id;
    END IF;
  END IF;

  v_base := COALESCE(v_last_visit, v_fallback);
  IF v_base IS NULL THEN
    RETURN;
  END IF;

  next_due_date := v_base + (v_interval || ' days')::interval;
  status := CASE
    WHEN next_due_date < CURRENT_DATE THEN 'overdue'
    WHEN next_due_date < CURRENT_DATE + 30 THEN 'due_soon'
    ELSE 'up_to_date'
  END;
  RETURN NEXT;
END;
$$ LANGUAGE plpgsql STABLE;
