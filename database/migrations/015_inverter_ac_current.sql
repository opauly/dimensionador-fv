-- Migration 015: inverter AC output/passthrough current fields
--
-- Off-Grid/Hybrid Step 6 (Equipos) is gaining a "carga y protecciones"
-- section that suggests AC Out and AC In (hybrid passthrough) breaker
-- sizes. Both need the inverter's own rated continuous AC current, not an
-- approximation from kw/output_v (real inverters aren't 100% efficient,
-- and passthrough/charger current is a separate hard spec on hybrid
-- datasheets, unrelated to output power). Sourced from the datasheet
-- parser (calculations/datasheet_parser.py); falls back to a computed,
-- explicitly-flagged estimate in the wizard when null.

ALTER TABLE inverters
  ADD COLUMN IF NOT EXISTS ac_output_current_a    numeric;
ALTER TABLE inverters
  ADD COLUMN IF NOT EXISTS ac_input_current_max_a  numeric;
