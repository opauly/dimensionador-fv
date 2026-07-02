"""
Seed starter equipment catalog — panels, inverters, batteries, charge controllers,
and monitoring devices used by Pauly&Co. Update costs and add more via Admin → Equipment.

Run:  python -m database.seed.seed_equipment
"""
from database.supabase_client import get_client

PANELS = [
    {
        "brand": "JA Solar",
        "model": "JAM72S30-620/MR",
        "wp": 620,
        "voc": 49.6,
        "vmp": 42.0,
        "isc": 15.78,
        "imp": 14.77,
        "temp_coeff_pmax": -0.35,
        "width_m": 1.134,
        "height_m": 2.278,
        "weight_kg": 32.5,
        "warranty_product_yr": 12,
        "warranty_power_yr": 25,
        "cost_usd": None,
        "notes": "Mono PERC. Más común en instalaciones Pauly&Co.",
    },
    {
        "brand": "JA Solar",
        "model": "JAM72S30-570/MR",
        "wp": 570,
        "voc": 48.3,
        "vmp": 40.8,
        "isc": 14.89,
        "imp": 13.97,
        "temp_coeff_pmax": -0.35,
        "width_m": 1.134,
        "height_m": 2.278,
        "weight_kg": 32.0,
        "warranty_product_yr": 12,
        "warranty_power_yr": 25,
        "cost_usd": None,
        "notes": "Mono PERC.",
    },
    {
        "brand": "Jinko Solar",
        "model": "JKM580N-7RL3-TV",
        "wp": 580,
        "voc": 49.9,
        "vmp": 42.2,
        "isc": 14.68,
        "imp": 13.75,
        "temp_coeff_pmax": -0.30,
        "width_m": 1.134,
        "height_m": 2.278,
        "weight_kg": 31.8,
        "warranty_product_yr": 12,
        "warranty_power_yr": 30,
        "cost_usd": None,
        "notes": "Tiger Neo N-type.",
    },
    {
        "brand": "Canadian Solar",
        "model": "CS7N-620MS",
        "wp": 620,
        "voc": 50.2,
        "vmp": 42.4,
        "isc": 15.62,
        "imp": 14.62,
        "temp_coeff_pmax": -0.34,
        "width_m": 1.134,
        "height_m": 2.384,
        "weight_kg": 33.0,
        "warranty_product_yr": 12,
        "warranty_power_yr": 25,
        "cost_usd": None,
        "notes": "HiKu7 Mono PERC.",
    },
]

INVERTERS = [
    {
        "brand": "Fronius",
        "model": "Primo 10.0-1",
        "kw": 10.0,
        "type": "string_inverter",
        "vmax": 1000.0,
        "vmin_mppt": 200.0,
        "vmax_mppt": 800.0,
        "imax_mppt": 27.0,
        "mppt_channels": 2,
        "phase": "single",
        "output_v": 240.0,
        "warranty_yr": 5,
        "cost_usd": None,
        "notes": "Monofásico. Más común en Grid Zero residencial.",
    },
    {
        "brand": "Fronius",
        "model": "Primo 8.2-1",
        "kw": 8.2,
        "type": "string_inverter",
        "vmax": 1000.0,
        "vmin_mppt": 200.0,
        "vmax_mppt": 800.0,
        "imax_mppt": 27.0,
        "mppt_channels": 2,
        "phase": "single",
        "output_v": 240.0,
        "warranty_yr": 5,
        "cost_usd": None,
        "notes": "Monofásico.",
    },
    {
        "brand": "Fronius",
        "model": "Primo 6.0-1",
        "kw": 6.0,
        "type": "string_inverter",
        "vmax": 1000.0,
        "vmin_mppt": 150.0,
        "vmax_mppt": 800.0,
        "imax_mppt": 18.0,
        "mppt_channels": 2,
        "phase": "single",
        "output_v": 240.0,
        "warranty_yr": 5,
        "cost_usd": None,
        "notes": "Monofásico.",
    },
    {
        "brand": "Victron Energy",
        "model": "MultiPlus-II 48/5000/70-50",
        "kw": 5.0,
        "type": "hybrid",
        "vmax": None,
        "vmin_mppt": None,
        "vmax_mppt": None,
        "imax_mppt": None,
        "mppt_channels": None,
        "phase": "single",
        "output_v": 120.0,
        "warranty_yr": 5,
        "cost_usd": None,
        "notes": "Inversor/cargador híbrido 48V. Uso Off-Grid. Para 240V split-phase se requieren dos en paralelo.",
    },
    {
        "brand": "SolarEdge",
        "model": "SE10000H",
        "kw": 10.0,
        "type": "string_inverter",
        "vmax": 1000.0,
        "vmin_mppt": 200.0,
        "vmax_mppt": 800.0,
        "imax_mppt": 32.5,
        "mppt_channels": 1,
        "phase": "single",
        "output_v": 240.0,
        "warranty_yr": 12,
        "cost_usd": None,
        "notes": "Requiere optimizadores por panel.",
    },
]

BATTERIES = [
    {
        "brand": "Pylontech",
        "model": "US5000C",
        "chemistry": "LiFePO4",
        "capacity_kwh": 4.8,
        "capacity_ah": 100,
        "voltage_v": 48.0,
        "dod_pct": 80,
        "cycles": 6000,
        "warranty_yr": 10,
        "cost_usd": None,
        "notes": "Estándar Off-Grid Pauly&Co. Ref: Jorge Ramírez.",
    },
    {
        "brand": "Pylontech",
        "model": "US3000C",
        "chemistry": "LiFePO4",
        "capacity_kwh": 3.5,
        "capacity_ah": 74,
        "voltage_v": 48.0,
        "dod_pct": 80,
        "cycles": 6000,
        "warranty_yr": 10,
        "cost_usd": None,
        "notes": "",
    },
]

CHARGE_CONTROLLERS = [
    {
        "brand": "Victron Energy",
        "model": "SmartSolar MPPT 250/100",
        "type": "MPPT",
        "vin_max": 250.0,
        "vout": 48.0,
        "imax_in": 35.0,
        "imax_out": 100.0,
        "cost_usd": None,
        "notes": "Ref: Jorge Ramírez Off-Grid.",
    },
    {
        "brand": "Victron Energy",
        "model": "SmartSolar MPPT 150/70",
        "type": "MPPT",
        "vin_max": 150.0,
        "vout": 48.0,
        "imax_in": 25.0,
        "imax_out": 70.0,
        "cost_usd": None,
        "notes": "",
    },
]

MONITORING = [
    {
        "brand": "Fronius",
        "model": "Smart Meter 63A-3",
        "compatible_with": "Fronius string inverters",
        "cost_usd": None,
    },
    {
        "brand": "Victron Energy",
        "model": "Cerbo GX",
        "compatible_with": "Victron MultiPlus, SmartSolar MPPT",
        "cost_usd": None,
    },
]


def seed():
    db = get_client()

    for table, rows, label in [
        ("panels", PANELS, "paneles"),
        ("inverters", INVERTERS, "inversores"),
        ("batteries", BATTERIES, "baterías"),
        ("charge_controllers", CHARGE_CONTROLLERS, "controladores de carga"),
        ("monitoring_devices", MONITORING, "dispositivos de monitoreo"),
    ]:
        for row in rows:
            result = db.table(table).insert(row).execute()
            name = row.get("model", row.get("model", ""))
            print(f"  ✓ {row.get('brand','')} {name}")
        print(f"  → {len(rows)} {label} insertados")

    print("\nEquipment seed complete.")


if __name__ == "__main__":
    seed()
