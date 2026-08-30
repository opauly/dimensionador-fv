from __future__ import annotations
"""
Tiered report branding (PLAN_PHASE17.md §4, §8 Step 4).

`vrm.customers.branding` has existed since migration 012 and was completely
dead until this module: nothing read it, nothing wrote it. This is the ONLY
reader. `victron/weekly_report.py` receives this module's OUTPUT (or
`None`) — it never receives `customer_row['branding']` directly. That is
the whole enforcement: a tier gate that only exists in the UI is not a tier
gate (PLAN_PHASE16.md §6.4 control 3 is the exact same shape of rule for
ONVO ids — "no id is ever accepted from a request body, every id is looked
up" — this module's version is "no branding is ever handed to the renderer
unresolved").

`resolve_branding(customer_row) -> dict` never raises and never returns
`None` — it always returns a complete, render-ready dict (every key
present, `logo_b64` already base64-encoded if there is one), so
`victron/weekly_report.py` never has to special-case a partial or missing
value. On any of the three "don't apply the customer's branding" cases
(not white-labeled, not entitled, or an individual field failing
validation at read time), the affected value falls back to the Pauly & Co
default INDIVIDUALLY — a Growth customer who set only a logo still gets
their logo with our contact block, not an all-or-nothing swap.
"""
import logging
import re

from vrm_api import storage
from vrm_api.billing import NOT_ENTITLED_BILLING_STATUSES

logger = logging.getLogger("vrm_api.branding")

# The shared entitlement denylist (`vrm_api.billing.
# NOT_ENTITLED_BILLING_STATUSES` — that constant's own docstring has the
# full reasoning, including PLAN_PHASE17.md §3.6's "denylist on purpose so
# billing_status='none' isn't excluded" point). Previously a private
# restatement here, along with two others in report_modules.py and
# routers/reports.py — consolidated 2026-08-29 after adding 'trial_expired'
# meant editing three separate copies and the first pass only caught two.
# Branding doesn't need routers/reports.py's additional site-level check
# (vrm.sites.active) — only the customer-level entitlement question applies
# here.

# §4.4: strict hex, no shorthand, no alpha — this string is interpolated
# directly into SVG/CSS.
_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

# §4.4: reject a colour whose relative luminance is too high to read as
# text on the report's white/near-white backgrounds — otherwise a customer
# picks #FFFFFF and ships an invisible header, then emails Oscar about it.
_MAX_LUMINANCE = 0.75

# §4.1/§4.4 — generous but bounded; these are short display strings, not
# free text fields.
_TEXT_FIELD_MAX_LEN = {
    "company_name": 80,
    "contact_name": 80,
    "contact_phone": 40,
    "website": 200,
}
_EMAIL_MAX_LEN = 254

_LOGO_MAX_BYTES = 1_000_000  # ~1MB, §4.4
_LOGO_MAX_DIMENSION_PX = 1000  # long edge, §4.4
_ALLOWED_LOGO_FORMATS = {"PNG", "JPEG"}  # Pillow's own format names; SVG rejected on purpose (§4.4)

DEFAULTS: dict = {
    "company_name": "Pauly & Co.",
    "contact_email": "proyectos@paulyco.com",
    "primary_color": "#1FAE6E",
    "logo_b64": None,  # None -> render_html() falls back to get_logo_b64() (the local Pauly & Co asset)
}


def _relative_luminance(hex_color: str) -> float:
    """WCAG relative luminance, sRGB — good enough for a "is this legible
    as dark text on white" gate, not a colour-management-grade calculation.
    """
    r, g, b = (int(hex_color[i:i + 2], 16) / 255.0 for i in (1, 3, 5))

    def _channel(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = _channel(r), _channel(g), _channel(b)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _validate_color(value) -> str | None:
    """Returns a safe hex colour, or `None` if `value` isn't a legible one
    — the caller falls back to the default individually, it never raises."""
    if not isinstance(value, str) or not _HEX_COLOR_RE.match(value):
        return None
    if _relative_luminance(value) > _MAX_LUMINANCE:
        logger.info("branding: rejected primary_color=%r — too light to read as text (luminance > %.2f)",
                    value, _MAX_LUMINANCE)
        return None
    return value


def _validate_text(value, max_len: int) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped or len(stripped) > max_len:
        return None
    # Jinja2's autoescape (on for .html in render_html(), confirmed still
    # on) HTML-escapes this at render time — no escaping needed here. This
    # function only bounds length/shape, it does not sanitize markup.
    return stripped


def _validate_email(value) -> str | None:
    text = _validate_text(value, _EMAIL_MAX_LEN)
    # Deliberately loose (contains '@', at least one '.' after it) — this
    # is a display string in a footer, not an auth boundary; RFC-perfect
    # validation isn't worth the false-negative risk of rejecting a real
    # customer's real address.
    if text and "@" in text and "." in text.split("@", 1)[1]:
        return text
    return None


def _resolve_logo_b64(logo_storage_path) -> str | None:
    """Fetches and base64-encodes a customer's uploaded logo (§4.4). Any
    failure — missing object, corrupt bytes, wrong format, too large —
    is logged and returns `None` (the caller falls back to the Pauly & Co
    logo); this function never raises into the report-rendering path.
    Format is verified with Pillow against the ACTUAL bytes, never trusted
    from the file extension."""
    if not isinstance(logo_storage_path, str) or not logo_storage_path:
        return None

    try:
        raw = storage.download_object_bytes(logo_storage_path)
    except Exception as exc:  # noqa: BLE001 — missing/unreadable object is expected, not exceptional
        logger.warning("branding: could not download logo at %r — falling back to default logo: %s",
                        logo_storage_path, exc)
        return None

    if len(raw) > _LOGO_MAX_BYTES:
        logger.warning("branding: logo at %r is %d bytes (max %d) — falling back to default logo",
                        logo_storage_path, len(raw), _LOGO_MAX_BYTES)
        return None

    try:
        from io import BytesIO

        from PIL import Image
        img = Image.open(BytesIO(raw))
        img.verify()  # raises if the bytes aren't a real, undamaged image
        # verify() invalidates the image object for further use — reopen.
        img = Image.open(BytesIO(raw))
        fmt = img.format
        width, height = img.size
    except Exception as exc:  # noqa: BLE001 — not a valid image, by content, not by extension
        logger.warning("branding: logo at %r failed image validation — falling back to default logo: %s",
                        logo_storage_path, exc)
        return None

    if fmt not in _ALLOWED_LOGO_FORMATS:
        logger.warning("branding: logo at %r has format=%r (allowed: %s) — falling back to default logo",
                        logo_storage_path, fmt, sorted(_ALLOWED_LOGO_FORMATS))
        return None
    if max(width, height) > _LOGO_MAX_DIMENSION_PX:
        logger.warning("branding: logo at %r is %dx%d (max long edge %dpx) — falling back to default logo",
                        logo_storage_path, width, height, _LOGO_MAX_DIMENSION_PX)
        return None

    import base64
    mime = "image/png" if fmt == "PNG" else "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(raw).decode()}"


def _is_entitled(customer_row: dict) -> bool:
    if not customer_row.get("active"):
        return False
    if customer_row.get("provisioning_state") != "active":
        return False
    if customer_row.get("billing_status") in NOT_ENTITLED_BILLING_STATUSES:
        return False
    return True


def _white_label_allowed(plan: str | None) -> bool:
    # Imported here, not at module load, to avoid a hard import-order
    # dependency between report_limits.py and branding.py for what is
    # otherwise two independent modules — both are cheap, side-effect-free
    # imports either way.
    from vrm_api.report_limits import resolve_limits
    return bool(resolve_limits(plan).get("white_label"))


def resolve_branding(customer_row: dict) -> dict:
    """The one gate (PLAN_PHASE17.md §4.2). Always returns a complete,
    render-ready dict — `company_name`, `contact_email`, `primary_color`,
    `logo_b64` (already base64, or `None`) — never a partial one and never
    `None` itself; call sites that want "no branding" pass `None` to
    `victron/weekly_report.py` themselves rather than expecting this
    function to.

    Rule 0 (account-type gate, added 2026-08-21 from live testing — not in
    the original plan), rule 1 (tier gate), and rule 2 (entitlement gate)
    all return the PURE Pauly & Co defaults and IGNORE
    `customer_row['branding']` entirely — not "merge with defaults." Only a
    white-labeled, entitled INSTALLER customer's jsonb is ever read at all.

    Rule 0's reasoning: an `account_type='owner'` customer is monitoring
    their own single system — there is no third party for their report to
    be "branded" AT, so the feature doesn't apply regardless of tier. An
    `account_type='installer'` customer sends reports to their own clients,
    which is the actual use case white-label branding exists for.
    """
    plan = customer_row.get("plan")

    if customer_row.get("account_type") != "installer":
        return dict(DEFAULTS)
    if not _white_label_allowed(plan):
        return dict(DEFAULTS)
    if not _is_entitled(customer_row):
        return dict(DEFAULTS)

    # migration 026's COMMENT ON COLUMN documents seven possible keys
    # (company_name, logo_storage_path, primary_color, contact_name,
    # contact_email, contact_phone, website) — only the four the renderer
    # actually consumes today (company_name, logo, colour, contact_email)
    # are resolved/validated here. contact_name/contact_phone/website are
    # real, storable fields (Step 5's settings page can write them today),
    # simply not yet read by victron/weekly_report.py's template — they get
    # their own resolve+validate treatment in whichever future step first
    # threads them into a rendered report, rather than validating fields
    # nothing consumes yet.
    raw = customer_row.get("branding") or {}
    if not isinstance(raw, dict):
        logger.error("branding: vrm.customers.branding for customer_id=%s is not a dict (%r) — using defaults",
                      customer_row.get("id"), type(raw))
        raw = {}

    resolved = dict(DEFAULTS)

    company_name = _validate_text(raw.get("company_name"), _TEXT_FIELD_MAX_LEN["company_name"])
    if company_name:
        resolved["company_name"] = company_name

    contact_email = _validate_email(raw.get("contact_email"))
    if contact_email:
        resolved["contact_email"] = contact_email

    primary_color = _validate_color(raw.get("primary_color"))
    if primary_color:
        resolved["primary_color"] = primary_color

    resolved["logo_b64"] = _resolve_logo_b64(raw.get("logo_storage_path"))

    return resolved
