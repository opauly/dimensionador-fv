"""Customer-facing copy for the VRM Monitor portal, in English and Spanish.

Every literal a customer might see must go through `t(lang, key)` rather than
being written inline in a view (§3 "Repo conventions" in PLAN_PHASE13.md) —
this is what makes the per-customer `vrm.customers.ui_language` column
(migration 021) actually do anything. `lang` is always `"en"` or `"es"`.

Admin views are Spanish and are ported near-verbatim from
`pages/06_vrm_monitor.py`'s own copy instead of going through this file
(PLAN_PHASE13.md §0.3 Q2, §3) — admin literals stay inline in `views/admin_*.py`.
"""
from __future__ import annotations

STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "login_title": "VRM Monitor",
        "login_subtitle": "Sign in to your account",
        "login_email": "Email",
        "login_password": "Password",
        "login_submit": "Log in",
        "login_missing_fields": "Enter your email and password.",
        "login_error": "Incorrect email or password.",
        "login_forgot_password": "Forgot your password?",
        "login_forgot_password_inert": (
            "Password reset isn't available yet — contact "
            "proyectos@paulyco.com."
        ),
        "not_linked_error": (
            "This account isn't linked to a VRM Monitor customer yet. "
            "Contact proyectos@paulyco.com."
        ),
        "please_log_in": "Please log in to continue.",
        "not_authorized": "You're not authorized to view this page.",
        "signed_in_as": "Signed in as {email}",
        "log_out": "Log out",
        "nav_reports": "Reports",
        "nav_upload": "Upload CSV",
        "nav_my_sites": "My Sites",
        "nav_profile": "Profile",
    },
    "es": {
        "login_title": "VRM Monitor",
        "login_subtitle": "Iniciá sesión en tu cuenta",
        "login_email": "Correo electrónico",
        "login_password": "Contraseña",
        "login_submit": "Iniciar sesión",
        "login_missing_fields": "Ingresá tu correo y contraseña.",
        "login_error": "Correo o contraseña incorrectos.",
        "login_forgot_password": "¿Olvidaste tu contraseña?",
        "login_forgot_password_inert": (
            "El restablecimiento de contraseña todavía no está disponible "
            "— contactá a proyectos@paulyco.com."
        ),
        "not_linked_error": (
            "Esta cuenta todavía no está vinculada a un cliente de VRM "
            "Monitor. Contactá a proyectos@paulyco.com."
        ),
        "please_log_in": "Iniciá sesión para continuar.",
        "not_authorized": "No tenés autorización para ver esta página.",
        "signed_in_as": "Sesión iniciada como {email}",
        "log_out": "Cerrar sesión",
        "nav_reports": "Reportes",
        "nav_upload": "Cargar CSV",
        "nav_my_sites": "Mis sitios",
        "nav_profile": "Perfil",
    },
}


def t(lang: str, key: str) -> str:
    """Looks up `key` in `lang`, falling back to English and then to the raw
    key itself — a visibly-wrong string beats a KeyError crash if a key is
    ever mistyped or a language is missing an entry."""
    table = STRINGS.get(lang, STRINGS["en"])
    return table.get(key, STRINGS["en"].get(key, key))
