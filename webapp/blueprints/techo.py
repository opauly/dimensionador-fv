from __future__ import annotations
"""Plano de techo — an aerial photo of the roof, scaled module blocks (the strings of the design) the user moves and rotates, and a PDF sheet.

One page for a quote version (`/techo/c/<version id>`) and one for a project (`/techo/p/<project id>`). The plan lives in the same two homes as the
other design answers: `scratch.roof_plan` of the version's draft and `projects.tech_spec["roof_plan"]` (a project starts from its quote's plan).
The photo goes to the Supabase storage bucket `solar-tool` under `roof/`. See `techo/service.py` for the saved shape and `static/techo.js` for the editor.
"""
import io
import uuid
from datetime import date

from flask import Blueprint, Response, abort, jsonify, render_template, request, url_for

from techo import service as S
from utils.pdf_sheet import title_fields

bp = Blueprint("techo", __name__, url_prefix="/techo")

_BUCKET = "solar-tool"
_MAX_BYTES = 15 * 1024 * 1024
_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


def _ctx(kind: str, oid: str) -> dict:
    """{kind, id, project (name/client), d (design), plan_raw, back, label} — 404 for an unknown owner."""
    from webapp.blueprints import projects_design

    if kind == "c":
        from webapp.blueprints.documentos import _load, _vquote

        version, proposal, project, d = _load(oid)
        raw = ((d.get("blob") or {}).get("scratch") or {}).get(S.SCRATCH_KEY)
        return {"kind": kind, "id": oid, "project": project, "d": d, "plan_raw": raw, "label": f"Cotización {_vquote(version, proposal)}",
                "back": url_for("proposals.index")}
    if kind == "p":
        from database.projects_db import get_project

        project = get_project(oid)
        if not project:
            abort(404)
        d = projects_design.load(project)
        raw = (project.get("tech_spec") or {}).get(S.SCRATCH_KEY) or ((d.get("blob") or {}).get("scratch") or {}).get(S.SCRATCH_KEY)
        return {"kind": kind, "id": oid, "project": project, "d": d, "plan_raw": raw, "label": "Proyecto", "back": url_for("projects.detalle", pid=oid)}
    abort(404)


def _save_plan(ctx: dict, plan: dict) -> None:
    if ctx["kind"] == "c":
        from wizard import draft

        blob = draft.load(ctx["id"])
        blob.setdefault("scratch", {})[S.SCRATCH_KEY] = plan
        draft.save(ctx["id"], blob)
    else:
        from database.projects_db import get_project, update_tech_spec

        spec = dict((get_project(ctx["id"]) or {}).get("tech_spec") or {})
        spec[S.SCRATCH_KEY] = plan
        update_tech_spec(ctx["id"], spec)


def _signed_url(path: str | None) -> str | None:
    if not path:
        return None
    try:
        from database.supabase_client import get_client

        return get_client().storage.from_(_BUCKET).create_signed_url(path, 3600).get("signedURL")
    except Exception:                                   # noqa: BLE001
        return None


def _safe(name: str | None) -> str:
    return "".join(ch for ch in (name or "Proyecto").replace(" ", "_") if ch.isalnum() or ch == "_") or "Proyecto"


@bp.route("/<kind>/<oid>")
def page(kind, oid):
    ctx = _ctx(kind, oid)
    d, project = ctx["d"], ctx["project"]
    if d["empty"]:
        return render_template("techo/page.html", empty=d["empty"], ctx=ctx, client=project.get("client_name") or "")
    info = S.design_info(d)
    plan = S.clean(ctx["plan_raw"], info)
    photo_url = _signed_url((plan["photo"] or {}).get("path"))
    data = {"info": info, "plan": plan, "photoUrl": photo_url, "colors": list(S.COLORS), "saveUrl": url_for("techo.guardar", kind=kind, oid=oid),
            "photoPostUrl": url_for("techo.foto", kind=kind, oid=oid)}
    return render_template("techo/page.html", empty=None, ctx=ctx, client=project.get("client_name") or "", data=data,
                           pdf_url=url_for("techo.pdf", kind=kind, oid=oid), panel=info["panel"], design_count=info["panel_count"])


@bp.route("/<kind>/<oid>/guardar", methods=["POST"])
def guardar(kind, oid):
    ctx = _ctx(kind, oid)
    if ctx["d"]["empty"]:
        return jsonify(ok=False, error=ctx["d"]["empty"]), 409
    info = S.design_info(ctx["d"])
    plan = S.clean(request.get_json(silent=True) or {}, info)
    _save_plan(ctx, plan)
    sm = S.summary(plan, info)
    return jsonify(ok=True, summary={k: sm[k] for k in ("placed", "designed", "kwp", "area_m2", "ok")})


@bp.route("/<kind>/<oid>/foto", methods=["POST"])
def foto(kind, oid):
    ctx = _ctx(kind, oid)
    f = request.files.get("foto")
    if not f or not f.filename:
        return jsonify(ok=False, error="Elige una imagen."), 400
    data = f.read()
    ext = _TYPES.get((f.mimetype or "").lower())
    if not ext or not data:
        return jsonify(ok=False, error="La foto debe ser JPG, PNG o WebP."), 400
    if len(data) > _MAX_BYTES:
        return jsonify(ok=False, error="La foto pesa más de 15 MB."), 400
    try:
        from PIL import Image

        w, h = Image.open(io.BytesIO(data)).size
    except Exception:                                   # noqa: BLE001
        return jsonify(ok=False, error="No se pudo leer la imagen."), 400
    path = f"roof/{kind}/{oid}/{uuid.uuid4().hex[:10]}.{ext}"
    try:
        from database.supabase_client import get_client

        get_client().storage.from_(_BUCKET).upload(path=path, file=data, file_options={"content-type": f.mimetype, "upsert": "true"})
    except Exception as exc:                            # noqa: BLE001
        return jsonify(ok=False, error=f"No se pudo guardar la foto: {exc}"), 500
    info = S.design_info(ctx["d"]) if not ctx["d"]["empty"] else {"counts": [], "panel_count": 0}
    plan = S.clean(ctx["plan_raw"], info)
    plan = {**plan, "photo": {"path": path, "w": w, "h": h}, "scale": None, "roof": [], "strings": S.default_strings(info, {"w": w, "h": h})}
    _save_plan(ctx, plan)
    return jsonify(ok=True, plan=plan, photoUrl=_signed_url(path))


@bp.route("/<kind>/<oid>/pdf")
def pdf(kind, oid):
    from database.supabase_client import get_client
    from techo import pdf as P

    ctx = _ctx(kind, oid)
    if ctx["d"]["empty"]:
        return Response(ctx["d"]["empty"], status=409)
    info = S.design_info(ctx["d"])
    plan = S.clean(ctx["plan_raw"], info)
    if not plan["photo"]:
        return Response("Sube primero la foto aérea del techo.", status=409)
    try:
        photo_bytes = get_client().storage.from_(_BUCKET).download(plan["photo"]["path"])
    except Exception as exc:                            # noqa: BLE001
        return Response(f"No se pudo leer la foto: {exc}", status=500)
    site = (ctx["d"].get("blob") or {}).get("site") or {}
    place = ", ".join(x for x in (site.get("city"), site.get("province")) if x)
    client = ctx["project"].get("client_name") or "Cliente"
    out = io.BytesIO()
    P.build({"project": {"name": f"Proyecto {client}" + (f" en {place}" if place else ""), "client": client,
                         "location": (place + ", Costa Rica") if place else "Costa Rica", "date": date.today().isoformat(),
                         "revision": "A (borrador)", "draft": True, "responsible": "Ing. Oscar Pauly Calvo · IE-30111",
                         **title_fields(ctx["project"], ctx["d"].get("blob"), "techo")},
             "plan": plan, "info": info, "photo_bytes": photo_bytes}, out)
    return Response(out.getvalue(), mimetype="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{_safe(client)}_Plano_de_techo.pdf"'})
