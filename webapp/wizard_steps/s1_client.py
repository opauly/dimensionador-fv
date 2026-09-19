"""Step 1 — Cliente. Port of wizard/common.py:step2_client() (Streamlit's
*display* step 1 — see webapp/wizard_steps/common.py's docstring on the
legacy name inversion this port drops).

Per PLAN_PHASE20_PROPOSALS_JINJA.md §1.3, this module exposes exactly one
`build_context(blob) -> dict`, used by the full-page GET and by the
search/select fragment routes alike — with one necessary wrinkle: `GET
/cotizaciones/asistente/nueva` has no proposal row yet, so there is no real
persisted blob to read. `build_context(None)` (and the ephemeral,
not-yet-saved `{"client": {...}}` shape passed by the search/select
fragments before a row exists) both mean "here is the client data to
display", not "here is the version's durable blob" — see the module-level
note below for exactly which callers persist and which don't.
"""
from __future__ import annotations


def parse_form(form) -> dict:
    """`request.form` -> the six client fields (+ client_id, if a search
    result was actively selected), matching wizard/common.py:step2_client()'s
    own field set and its NISE "N/A" default exactly."""
    return {
        "name": (form.get("name") or "").strip(),
        "empresa": (form.get("empresa") or "").strip(),
        "phone": (form.get("phone") or "").strip(),
        "email": (form.get("email") or "").strip(),
        "location": (form.get("location") or "").strip(),
        "nise": (form.get("nise") or "").strip() or "N/A",
        "client_id": (form.get("client_id") or "").strip() or None,
    }


def resolve_client(result: dict) -> dict:
    """Verbatim port of pages/02_new_proposal.py L141-166's prospect-vs-client
    rule: a result carrying `client_id` (i.e. an existing client was actively
    selected via search) only gets its BLANK fields filled in via
    upsert_client(); anything else — a typed name with no selected match —
    becomes a new prospect, not a client yet (promotion only happens when a
    proposal for them is later marked "won", via promote_prospect()). Both
    branches are wrapped in the same silent try/except as the original."""
    try:
        if result.get("client_id"):
            from database.clients_db import upsert_client

            upsert_client(
                name=result["name"], empresa=result.get("empresa", ""),
                phone=result.get("phone", ""), email=result.get("email", ""),
            )
        else:
            from database.prospects_db import create_prospect

            prospect = create_prospect(
                name=result["name"], empresa=result.get("empresa", ""),
                phone=result.get("phone", ""), email=result.get("email", ""),
            )
            result = {**result, "prospect_id": prospect["id"]}
    except Exception:
        pass
    return result


def search_matches(query: str) -> list[dict]:
    """Live client search fragment data — port of step2_client()'s
    `search_clients(search_query)` call (same 2-char minimum)."""
    from database.clients_db import search_clients

    if not query or len(query) < 2:
        return []
    matches = search_clients(query)
    return [
        {
            "id": m["id"],
            "name": m["name"],
            "sub": f"{m.get('phone') or ''} {m.get('email') or ''}".strip(),
        }
        for m in matches
    ]


def client_fields_by_id(client_id: str) -> dict:
    """Fields to fill in when a search result is clicked — port of
    step2_client()'s `_on_client_select()`. `location`/`nise` are NOT columns
    on the `clients` table (search_clients() never selects them either), so
    they land blank/"N/A" here exactly as they do in the Streamlit callback —
    a faithful port of that quirk, not a bug introduced here."""
    from database.clients_db import get_client_by_id

    c = get_client_by_id(client_id) or {}
    return {
        "client_id": c.get("id"),
        "name": c.get("name") or "",
        "empresa": c.get("empresa") or "",
        "phone": c.get("phone") or "",
        "email": c.get("email") or "",
        "location": "",
        "nise": "N/A",
    }


def prev_options(client_id: str | None, name: str | None) -> list[dict]:
    """Previous-proposals selector data — port of step2_client()'s
    `list_proposals_by_client()` block, including its label format and the
    [Enviada]/[Bloqueada] suffixes."""
    if not client_id and not name:
        return []
    from database.proposals_db import format_quote_number, list_proposals_by_client

    prev = list_proposals_by_client(client_id=client_id or "", client_name=name or "")
    options = []
    for p in prev:
        for v in sorted(p.get("proposal_versions") or [], key=lambda x: x["version_number"]):
            qn = format_quote_number(p.get("quote_number"), p.get("created_at", ""), v["version_number"])
            icons = (
                (" [Enviada]" if v.get("sent_to_client") else "")
                + (" [Bloqueada]" if v.get("locked") else "")
            )
            label = f"{qn} — {p.get('system_type') or ''} — ${v.get('total_usd') or 0:,.0f}{icons}"
            options.append({"label": label, "version_id": v["id"]})
    return options


def build_context(blob: dict | None) -> dict:
    """The step's one build_context(): everything s1_client.html /
    _s1_fields.html need. `blob` is either a real persisted version blob
    (GET on an existing /<vid>/paso/1) or an ephemeral `{"client": {...}}`
    shape standing in for one when there is no row yet (GET /nueva, or a
    search/select fragment for either case) — see module docstring."""
    client = (blob or {}).get("client") or {}
    name = client.get("name") or ""
    client_id = client.get("client_id")
    return {
        "client": {
            "client_id": client_id,
            "name": name,
            "empresa": client.get("empresa") or "",
            "phone": client.get("phone") or "",
            "email": client.get("email") or "",
            "location": client.get("location") or "",
            "nise": client.get("nise") or "N/A",
        },
        "prev_options": prev_options(client_id, name),
    }
