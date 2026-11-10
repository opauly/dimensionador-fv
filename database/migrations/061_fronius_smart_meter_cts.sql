-- 061: Fronius Smart Meter WR 100-600 V-3 (meter with current transformers, "donas") for Grid Zero.
-- The meter is a normal monitoring option (device_kind 'gateway', picked in the Grid Zero Equipos step); its current
-- transformers are one per phase (split-phase 240 V: 2, three-phase: 3) and have their own price.
-- Values come from the Fronius Smart Meter WR and Smart Meter CT V datasheets. Additive and idempotent.
--
--   uses_cts      the meter needs external current transformers
--   ct_model      what the transformers are (sizes 100 A / 250 A / 400 A, all 333 mV)
--   ct_cost_usd   price of ONE transformer (the quote multiplies by the number of phases)

ALTER TABLE monitoring_devices ADD COLUMN IF NOT EXISTS uses_cts boolean NOT NULL DEFAULT false;
ALTER TABLE monitoring_devices ADD COLUMN IF NOT EXISTS ct_model text;
ALTER TABLE monitoring_devices ADD COLUMN IF NOT EXISTS ct_cost_usd numeric;

INSERT INTO monitoring_devices (brand, model, compatible_with, device_kind, uses_cts, ct_model, notes)
SELECT 'Fronius', 'Smart Meter WR 100-600 V-3',
       'Inversores Fronius; Modbus RTU (RS485)',
       'gateway', true,
       'Fronius Smart Meter CT V, 333 mV (100 A / 250 A / 400 A, split-core)',
       'Medidor con transformadores de corriente: 120-600 V, 3 x 6000 A máx. con TC, clase 0.5 (ANSI C12.20), IP40, -40 a +80 °C, '
       'conductores hasta 2.5 mm². Interior; en exterior dentro de un gabinete NEMA 3R/4 (IP 66). Un TC por fase (monofásico 2, trifásico 3). '
       'TC Fronius Smart Meter CT V: 100 A / 250 A / 400 A con salida de 333 mV, cable de 1 m, -40 a +65 °C.'
WHERE NOT EXISTS (SELECT 1 FROM monitoring_devices WHERE model = 'Smart Meter WR 100-600 V-3');
