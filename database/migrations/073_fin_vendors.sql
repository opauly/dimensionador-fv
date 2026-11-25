-- Phase 25 — Proveedores (lista seleccionable en "Registrar movimiento").
-- Seeded from the QuickBooks supplier list (scripts/seed_fin_vendors.py);
-- typing a new name when saving a movement adds it. Safe to run more than once.

CREATE TABLE IF NOT EXISTS fin_vendors (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at  timestamptz NOT NULL DEFAULT now(),
    name        text NOT NULL,
    active      boolean NOT NULL DEFAULT true,
    source      text NOT NULL DEFAULT 'manual'      -- manual / quickbooks
);
CREATE UNIQUE INDEX IF NOT EXISTS fin_vendors_name_uq ON fin_vendors (lower(name));
