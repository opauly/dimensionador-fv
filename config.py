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

# ISO 3166-1 alpha-2 → Spanish display name. Used by the VRM report tool's
# País dropdown — the calculation for a site (CR blended ARESEP tariff vs.
# everywhere else's flat rate; see victron/savings.py) keys off this code, and
# reverse_geocode() (below, calculations/pvgis.py) resolves a code from
# coordinates that must land somewhere in this list to auto-fill the field.
#
# Deliberately near-exhaustive (essentially every UN member + common
# territories), not a curated subset limited to where Pauly & Co has
# customers today — a VRM installation really can be anywhere, and a missing
# entry here doesn't just look incomplete, it silently breaks the reverse-geocode
# autofill for that country (confirmed live: a Ukraine coordinate resolved a
# correct country_code that the form then had nowhere to put, because "UA"
# wasn't in an earlier, curated ~64-country version of this list).
COUNTRIES = {
    "AF": "Afganistán", "AL": "Albania", "DZ": "Argelia", "AD": "Andorra",
    "AO": "Angola", "AG": "Antigua y Barbuda", "AR": "Argentina",
    "AM": "Armenia", "AU": "Australia", "AT": "Austria", "AZ": "Azerbaiyán",
    "BS": "Bahamas", "BH": "Baréin", "BD": "Bangladés", "BB": "Barbados",
    "BY": "Bielorrusia", "BE": "Bélgica", "BZ": "Belice", "BJ": "Benín",
    "BT": "Bután", "BO": "Bolivia", "BA": "Bosnia y Herzegovina",
    "BW": "Botsuana", "BR": "Brasil", "BN": "Brunéi", "BG": "Bulgaria",
    "BF": "Burkina Faso", "BI": "Burundi", "CV": "Cabo Verde",
    "KH": "Camboya", "CM": "Camerún", "CA": "Canadá",
    "CF": "República Centroafricana", "TD": "Chad", "CL": "Chile",
    "CN": "China", "CO": "Colombia", "KM": "Comoras", "CG": "Congo",
    "CD": "República Democrática del Congo", "CR": "Costa Rica",
    "CI": "Costa de Marfil", "HR": "Croacia", "CU": "Cuba", "CY": "Chipre",
    "CZ": "Chequia", "DK": "Dinamarca", "DJ": "Yibuti", "DM": "Dominica",
    "DO": "República Dominicana", "EC": "Ecuador", "EG": "Egipto",
    "SV": "El Salvador", "GQ": "Guinea Ecuatorial", "ER": "Eritrea",
    "EE": "Estonia", "SZ": "Esuatini", "ET": "Etiopía", "FJ": "Fiyi",
    "FI": "Finlandia", "FR": "Francia", "GA": "Gabón", "GM": "Gambia",
    "GE": "Georgia", "DE": "Alemania", "GH": "Ghana", "GR": "Grecia",
    "GD": "Granada", "GT": "Guatemala", "GN": "Guinea",
    "GW": "Guinea-Bisáu", "GY": "Guyana", "HT": "Haití", "HN": "Honduras",
    "HK": "Hong Kong", "HU": "Hungría", "IS": "Islandia", "IN": "India",
    "ID": "Indonesia", "IR": "Irán", "IQ": "Irak", "IE": "Irlanda",
    "IL": "Israel", "IT": "Italia", "JM": "Jamaica", "JP": "Japón",
    "JO": "Jordania", "KZ": "Kazajistán", "KE": "Kenia", "KI": "Kiribati",
    "KP": "Corea del Norte", "KR": "Corea del Sur", "KW": "Kuwait",
    "KG": "Kirguistán", "LA": "Laos", "LV": "Letonia", "LB": "Líbano",
    "LS": "Lesoto", "LR": "Liberia", "LY": "Libia", "LI": "Liechtenstein",
    "LT": "Lituania", "LU": "Luxemburgo", "MO": "Macao",
    "MG": "Madagascar", "MW": "Malaui", "MY": "Malasia", "MV": "Maldivas",
    "ML": "Malí", "MT": "Malta", "MH": "Islas Marshall",
    "MR": "Mauritania", "MU": "Mauricio", "MX": "México",
    "FM": "Micronesia", "MD": "Moldavia", "MC": "Mónaco", "MN": "Mongolia",
    "ME": "Montenegro", "MA": "Marruecos", "MZ": "Mozambique",
    "MM": "Myanmar", "NA": "Namibia", "NR": "Nauru", "NP": "Nepal",
    "NL": "Países Bajos", "NZ": "Nueva Zelanda", "NI": "Nicaragua",
    "NE": "Níger", "NG": "Nigeria", "MK": "Macedonia del Norte",
    "NO": "Noruega", "OM": "Omán", "PK": "Pakistán", "PW": "Palaos",
    "PS": "Palestina", "PA": "Panamá", "PG": "Papúa Nueva Guinea",
    "PY": "Paraguay", "PE": "Perú", "PH": "Filipinas", "PL": "Polonia",
    "PT": "Portugal", "PR": "Puerto Rico", "QA": "Catar", "RO": "Rumania",
    "RU": "Rusia", "RW": "Ruanda", "KN": "San Cristóbal y Nieves",
    "LC": "Santa Lucía", "VC": "San Vicente y las Granadinas",
    "WS": "Samoa", "SM": "San Marino", "ST": "Santo Tomé y Príncipe",
    "SA": "Arabia Saudita", "SN": "Senegal", "RS": "Serbia",
    "SC": "Seychelles", "SL": "Sierra Leona", "SG": "Singapur",
    "SK": "Eslovaquia", "SI": "Eslovenia", "SB": "Islas Salomón",
    "SO": "Somalia", "ZA": "Sudáfrica", "SS": "Sudán del Sur",
    "ES": "España", "LK": "Sri Lanka", "SD": "Sudán", "SR": "Surinam",
    "SE": "Suecia", "CH": "Suiza", "SY": "Siria", "TW": "Taiwán",
    "TJ": "Tayikistán", "TZ": "Tanzania", "TH": "Tailandia",
    "TL": "Timor Oriental", "TG": "Togo", "TO": "Tonga",
    "TT": "Trinidad y Tobago", "TN": "Túnez", "TR": "Turquía",
    "TM": "Turkmenistán", "TV": "Tuvalu", "UG": "Uganda", "UA": "Ucrania",
    "AE": "Emiratos Árabes Unidos", "GB": "Reino Unido",
    "US": "Estados Unidos", "UY": "Uruguay", "UZ": "Uzbekistán",
    "VU": "Vanuatu", "VA": "Ciudad del Vaticano", "VE": "Venezuela",
    "VN": "Vietnam", "YE": "Yemen", "ZM": "Zambia", "ZW": "Zimbabue",
    "OT": "Otro",
}

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
