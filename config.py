BRAND_GREEN = "#4BAE6A"
BRAND_NAVY = "#1E2D54"
BRAND_GREEN_LIGHT = "#E8F5EE"

SYSTEM_TYPES = ["grid_zero", "off_grid", "hybrid"]
SYSTEM_TYPE_LABELS = {
    "grid_zero": "Grid Zero",
    "off_grid": "Off-Grid",
    "hybrid": "Híbrido",
}

PROPOSAL_STATUSES = ["draft", "active", "won", "lost", "cancelled"]
PROJECT_STATUSES = ["active", "completed", "paused", "cancelled"]

DEFAULT_IVA_RATE = 0.0
DEFAULT_TARIFF_ESCALATION = 0.05
DEFAULT_PROPOSAL_VALIDITY_DAYS = 15
DEFAULT_ONVO_COMMISSION = 0.024
IVA_EXEMPT_THRESHOLD_KWH = 280
BOMBEROS_RATE = 0.0175

PVGIS_API_BASE = "https://re.jrc.ec.europa.eu/api/v5_2"
EXCHANGE_RATE_API_BASE = "https://v6.exchangerate-api.com/v6"
EXCHANGE_RATE_CACHE_TTL = 3600  # seconds

WIZARD_STEPS_GRID_ZERO = 8
WIZARD_STEPS_OFF_GRID = 8
WIZARD_STEPS_HYBRID = 8

EXPENSE_CATEGORIES = ["banco", "equipo", "materiales", "mano_de_obra", "viaticos", "extras"]
INVOICE_CATEGORIES = ["equipos", "materiales", "servicios"]

DISTRIBUTORS = [
    "CNFL",
    "ICE",
    "JASEC",
    "ESPH",
    "COOPELESCA",
    "COOPEGUANACASTE",
    "COOPESANTOS",
    "COOPEALFARORUIZ",
]

DEFAULT_COMPANY = {
    "name": "Pauly & Co.",
    "license": "",
    "phone": "",
    "email": "",
    "website": "",
    "contact_name": "Oscar Pauly",
    "contact_title": "Ingeniero Solar",
    "bank_local": "",
    "bank_international": "",
}
