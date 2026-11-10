-- 059: energy meters (Victron VM-3P75CT) live in monitoring_devices, told apart from the GX gateways by device_kind.
-- The Equipos step shows them in their own selector; the materials list adds the meter and its current transformers.
-- Values come from Datasheets/Monitoreo/Datasheet-Energy-Meter-3P-EN.pdf. Additive and idempotent.
--
--   device_kind      'gateway' (Cerbo / Ekrano / Fronius meter, the old rows) or 'meter' (energy meter read by the GX)
--   rated_current_a  current the meter's own transformers are rated for (VM-3P75CT: 75 A)

ALTER TABLE monitoring_devices ADD COLUMN IF NOT EXISTS device_kind text NOT NULL DEFAULT 'gateway';
ALTER TABLE monitoring_devices ADD COLUMN IF NOT EXISTS rated_current_a numeric;

INSERT INTO monitoring_devices (brand, model, compatible_with, device_kind, rated_current_a, notes)
SELECT 'Victron Energy', 'VM-3P75CT',
       'Cerbo GX, Ekrano GX, VictronConnect y VRM; VE.Can (2 RJ45) o Ethernet (Modbus UDP)',
       'meter', 75,
       'Medidor de energía trifásico / split-phase, 75 A con transformadores de corriente de pinza (vienen 3 en la caja, cable de 640 mm). '
       'Mide red, salida de inversor FV, generador o cargas. Entrada de voltaje directa 85-265 V L-N, tornillos 1.0-2.5 mm² (22-12 AWG). '
       'Solo interior (IP20), -10 a +55 °C. Artículo REL200300100.'
WHERE NOT EXISTS (SELECT 1 FROM monitoring_devices WHERE model = 'VM-3P75CT');
