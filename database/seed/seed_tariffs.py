"""
Seed 2026 ARESEP residential tariffs (T-RE) for all 8 Costa Rican distributors.
Values are approximations based on official ARESEP publications effective 2026-01-01.
Verify and update via Admin → Tariff Manager before going live with real proposals.

Run:  python -m database.seed.seed_tariffs
"""
from database.supabase_client import get_client

# Approximate 2026 T-RE tariff data
# Structure: (abbreviation, name, coverage, access_crc, tiers)
# Tiers: list of (from_kwh, to_kwh|None, rate_crc, sort_order)
DISTRIBUTORS = [
    {
        "abbreviation": "CNFL",
        "name": "Compañía Nacional de Fuerza y Luz",
        "coverage_area": "Gran Área Metropolitana (GAM)",
        "tariffs": [
            {
                "code": "T-RE",
                "name": "Tarifa Residencial",
                "sector": "residential",
                "access_charge_crc": 3100.00,
                "tiers": [
                    (0,   200, 79.28,  1),
                    (201, 500, 112.45, 2),
                    (501, None,148.20, 3),
                ],
            }
        ],
    },
    {
        "abbreviation": "ICE",
        "name": "Instituto Costarricense de Electricidad",
        "coverage_area": "Nacional (zonas no servidas por otras distribuidoras)",
        "tariffs": [
            {
                "code": "T-RE",
                "name": "Tarifa Residencial",
                "sector": "residential",
                "access_charge_crc": 2800.00,
                "tiers": [
                    (0,   200, 76.50,  1),
                    (201, 500, 108.30, 2),
                    (501, None,142.80, 3),
                ],
            }
        ],
    },
    {
        "abbreviation": "JASEC",
        "name": "Junta Administrativa del Servicio Eléctrico Municipal de Cartago",
        "coverage_area": "Cartago",
        "tariffs": [
            {
                "code": "T-RE",
                "name": "Tarifa Residencial",
                "sector": "residential",
                "access_charge_crc": 3250.00,
                "tiers": [
                    (0,   200, 81.20,  1),
                    (201, 500, 115.60, 2),
                    (501, None,152.40, 3),
                ],
            }
        ],
    },
    {
        "abbreviation": "ESPH",
        "name": "Empresa de Servicios Públicos de Heredia",
        "coverage_area": "Heredia",
        "tariffs": [
            {
                "code": "T-RE",
                "name": "Tarifa Residencial",
                "sector": "residential",
                "access_charge_crc": 3050.00,
                "tiers": [
                    (0,   200, 78.90,  1),
                    (201, 500, 111.80, 2),
                    (501, None,147.60, 3),
                ],
            }
        ],
    },
    {
        "abbreviation": "COOPELESCA",
        "name": "Cooperativa de Electrificación Rural de San Carlos",
        "coverage_area": "San Carlos, Sarapiquí, zona norte",
        "tariffs": [
            {
                "code": "T-RE",
                "name": "Tarifa Residencial",
                "sector": "residential",
                "access_charge_crc": 2900.00,
                "tiers": [
                    (0,   200, 77.80,  1),
                    (201, 500, 110.20, 2),
                    (501, None,145.30, 3),
                ],
            }
        ],
    },
    {
        "abbreviation": "COOPEGUANACASTE",
        "name": "Cooperativa de Electrificación Rural de Guanacaste",
        "coverage_area": "Guanacaste",
        "tariffs": [
            {
                "code": "T-RE",
                "name": "Tarifa Residencial",
                "sector": "residential",
                "access_charge_crc": 2750.00,
                "tiers": [
                    (0,   200, 75.90,  1),
                    (201, 500, 107.50, 2),
                    (501, None,141.60, 3),
                ],
            }
        ],
    },
    {
        "abbreviation": "COOPESANTOS",
        "name": "Cooperativa de Electrificación Rural de los Santos",
        "coverage_area": "Tarrazú, León Cortés, Dota",
        "tariffs": [
            {
                "code": "T-RE",
                "name": "Tarifa Residencial",
                "sector": "residential",
                "access_charge_crc": 2650.00,
                "tiers": [
                    (0,   200, 74.30,  1),
                    (201, 500, 105.20, 2),
                    (501, None,138.80, 3),
                ],
            }
        ],
    },
    {
        "abbreviation": "COOPEALFARORUIZ",
        "name": "Cooperativa de Electrificación Rural de Alfaro Ruiz",
        "coverage_area": "Zarcero, Valverde Vega, Naranjo",
        "tariffs": [
            {
                "code": "T-RE",
                "name": "Tarifa Residencial",
                "sector": "residential",
                "access_charge_crc": 2700.00,
                "tiers": [
                    (0,   200, 75.10,  1),
                    (201, 500, 106.40, 2),
                    (501, None,140.20, 3),
                ],
            }
        ],
    },
]


def seed():
    db = get_client()
    created = 0

    for dist in DISTRIBUTORS:
        # Upsert distributor
        result = (
            db.table("distributors")
            .upsert(
                {
                    "abbreviation": dist["abbreviation"],
                    "name": dist["name"],
                    "coverage_area": dist["coverage_area"],
                },
                on_conflict="name",
            )
            .execute()
        )
        dist_id = result.data[0]["id"]

        for tariff in dist["tariffs"]:
            # Check if tariff type already exists, insert if not
            existing = (
                db.table("tariff_types")
                .select("id")
                .eq("distributor_id", dist_id)
                .eq("code", tariff["code"])
                .execute()
            )
            if existing.data:
                tt_id = existing.data[0]["id"]
                db.table("tariff_types").update(
                    {
                        "access_charge_crc": tariff["access_charge_crc"],
                        "bomberos_pct": 0.0175,
                        "iva_threshold_kwh": 280,
                    }
                ).eq("id", tt_id).execute()
            else:
                tt_result = (
                    db.table("tariff_types")
                    .insert(
                        {
                            "distributor_id": dist_id,
                            "code": tariff["code"],
                            "name": tariff["name"],
                            "sector": tariff["sector"],
                            "access_charge_crc": tariff["access_charge_crc"],
                            "bomberos_pct": 0.0175,
                            "iva_threshold_kwh": 280,
                        }
                    )
                    .execute()
                )
                tt_id = tt_result.data[0]["id"]

            # Delete existing tiers and re-insert (clean replace)
            db.table("tariff_tiers").delete().eq("tariff_type_id", tt_id).execute()

            tier_rows = [
                {
                    "tariff_type_id": tt_id,
                    "from_kwh": t[0],
                    "to_kwh": t[1],
                    "rate_crc": t[2],
                    "is_fixed": False,
                    "sort_order": t[3],
                }
                for t in tariff["tiers"]
            ]
            db.table("tariff_tiers").insert(tier_rows).execute()
            created += 1
            print(f"  ✓ {dist['abbreviation']} {tariff['code']}")

    print(f"\nSeeded {len(DISTRIBUTORS)} distributors, {created} tariff types.")


if __name__ == "__main__":
    seed()
