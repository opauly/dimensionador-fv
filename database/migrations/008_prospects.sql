-- Migration 008: prospects vs. clients
--
-- Business rule: a "client" is someone who has actually bought a project.
-- Someone who's only been quoted is a "prospect" until a proposal is
-- marked Won, at which point they're promoted (moved, not copied) into
-- clients. This keeps the clients list from filling up with people who
-- were quoted once and never converted.
--
-- Also fixes a pre-existing bug: database/clients_db.py has always
-- referenced a clients.empresa column that never existed in the schema —
-- the wizard's "Empresa" field has been silently failing to save.

-- ────────────────────────────────────────────────────────────
-- 1. Add empresa to clients (bug fix — column was always expected,
--    never existed)
-- ────────────────────────────────────────────────────────────
ALTER TABLE clients ADD COLUMN IF NOT EXISTS empresa text;

-- ────────────────────────────────────────────────────────────
-- 2. prospects — same shape as clients
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS prospects (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name        text NOT NULL,
    empresa     text,
    phone       text,
    email       text,
    notes       text,
    created_at  timestamptz DEFAULT now()
);

-- ────────────────────────────────────────────────────────────
-- 3. proposals gets a nullable prospect_id, alongside the existing
--    nullable client_id. A proposal references exactly one of them
--    (or neither, if the client field was typed freeform with no
--    match and no explicit "new" save) — never both.
-- ────────────────────────────────────────────────────────────
ALTER TABLE proposals ADD COLUMN IF NOT EXISTS prospect_id uuid REFERENCES prospects(id);

ALTER TABLE proposals DROP CONSTRAINT IF EXISTS proposals_client_xor_prospect;
ALTER TABLE proposals ADD CONSTRAINT proposals_client_xor_prospect
    CHECK (NOT (client_id IS NOT NULL AND prospect_id IS NOT NULL));

-- ────────────────────────────────────────────────────────────
-- 4. promote_prospect_to_client — atomic move. Copies the prospect into
--    clients, repoints every proposal that referenced this prospect_id
--    to the new client_id, deletes the prospect row. Called when a
--    proposal is marked "won" (pages/01_proposals.py).
-- ────────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION promote_prospect_to_client(p_prospect_id uuid)
RETURNS uuid
LANGUAGE plpgsql
AS $$
DECLARE
  v_client_id uuid;
BEGIN
  INSERT INTO clients (name, empresa, phone, email, notes)
  SELECT name, empresa, phone, email, notes
  FROM prospects
  WHERE id = p_prospect_id
  RETURNING id INTO v_client_id;

  IF v_client_id IS NULL THEN
    RAISE EXCEPTION 'No prospect found with id %', p_prospect_id;
  END IF;

  UPDATE proposals
  SET client_id = v_client_id, prospect_id = NULL
  WHERE prospect_id = p_prospect_id;

  DELETE FROM prospects WHERE id = p_prospect_id;

  RETURN v_client_id;
END;
$$;
