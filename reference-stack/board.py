"""HTML views, rendered server-side and updated in place with htmx.

Every mutation returns the fragment it changed. Anything that also shifts the
headline numbers responds with an `HX-Trigger: dashboard-refresh` header, and
the dashboard block re-fetches itself -- see partials/_dashboard.html.
"""

from flask import Blueprint, Response, render_template, request
from sqlalchemy import func, select

from docops.db import get_session
from docops.events import last_reviewed_map, record
from docops.health import STATUS_NEVER, STATUS_OVERDUE, STATUS_UNASSIGNED
from docops.identity import current_person_name, is_proxy_authenticated, set_current_person
from docops.identity import current_person_id
from docops.models import (
    EVENT_CADENCE_CHANGED,
    EVENT_CAP_CHANGED,
    EVENT_ITEM_CREATED,
    EVENT_ITEM_DELETED,
    EVENT_OWNERSHIP_TYPE_CHANGED,
    EVENT_PERSON_ADDED,
    EVENT_PERSON_DEACTIVATED,
    EVENT_PERSON_REACTIVATED,
    EVENT_PERSON_REMOVED,
    EVENT_REVIEWED,
    KIND_DOC_ARTICLE,
    ROLE_BACKUP,
    ROLE_PRIMARY,
    SOURCE_LOCAL,
    DocArticle,
    Event,
    Item,
    Ownership,
    Person,
    Setting,
)
from docops.seed import CADENCE_DEFAULT
from docops.services import (
    default_caps,
    get_article,
    get_cadence,
    get_person_by_name,
    list_articles,
    owner_name_options,
    set_owner,
    team_balances,
)

bp = Blueprint("board", __name__)

STATUS_META = {
    "healthy": {"label": "Up to date", "color": "#3F9142", "bg": "#E8F3E8"},
    "duesoon": {"label": "Due soon", "color": "#C9822A", "bg": "#FBF0DF"},
    "overdue": {"label": "Overdue", "color": "#B84345", "bg": "#F8E6E6"},
    "never": {"label": "Never reviewed", "color": "#B84345", "bg": "#F8E6E6"},
    "unassigned": {"label": "Unassigned", "color": "#7A63A8", "bg": "#EFEAF7"},
}

EVENT_META = {
    "reviewed": {"icon": "✓", "color": "var(--green)"},
    "item_created": {"icon": "+", "color": "var(--teal)"},
    "item_deleted": {"icon": "✖", "color": "var(--red)"},
    "owner_assigned": {"icon": "⇄", "color": "var(--teal)"},
    "owner_cleared": {"icon": "∅", "color": "var(--violet)"},
    "ownership_type_changed": {"icon": "◆", "color": "var(--muted)"},
    "note_changed": {"icon": "✎", "color": "var(--muted)"},
    "cap_changed": {"icon": "⚖", "color": "var(--amber)"},
    "person_added": {"icon": "☺", "color": "var(--teal)"},
    "person_reactivated": {"icon": "☺", "color": "var(--teal)"},
    "person_deactivated": {"icon": "⊖", "color": "var(--amber)"},
    "person_removed": {"icon": "✖", "color": "var(--red)"},
    "cadence_changed": {"icon": "⚙", "color": "var(--amber)"},
    "board_reset": {"icon": "↻", "color": "var(--red)"},
}

ATTENTION_STATUSES = (STATUS_UNASSIGNED, STATUS_OVERDUE, STATUS_NEVER)

REFRESH = {"HX-Trigger": "dashboard-refresh"}


# ============================== CONTEXT ==============================
def board_context(session, q=None, highlight=None):
    """Everything the templates need. One place, so no view forgets a variable."""
    pairs, cadence = list_articles(session)
    articles = [a.to_dict(last_reviewed=r, cadence_days=cadence) for a, r in pairs]

    counts = {key: 0 for key in STATUS_META}
    for a in articles:
        counts[a["status"]] += 1
    total = len(articles)

    visible = articles
    if q:
        needle = q.strip().lower()
        visible = [
            a
            for a in articles
            if needle in a["name"].lower()
            or needle in (a["primary"] or "").lower()
            or needle in (a["backup"] or "").lower()
        ]

    return {
        "articles": visible,
        "all_articles": articles,
        "needs_attention": [a for a in articles if a["status"] in ATTENTION_STATUSES],
        "summary": {
            "total": total,
            "healthy": counts["healthy"],
            "unassigned": counts["unassigned"],
            "attention": counts["overdue"] + counts["never"] + counts["unassigned"],
            "healthy_pct": round(counts["healthy"] / total * 100) if total else 0,
        },
        "status_meta": STATUS_META,
        "cadence": cadence,
        "roster": owner_name_options(session),
        "current_person": current_person_name(),
        "proxy_authenticated": is_proxy_authenticated(),
        "q": q,
        "highlight": highlight,
    }


def dashboard_context(session):
    """The subset the dashboard block needs; it always shows every article."""
    ctx = board_context(session)
    ctx["articles"] = ctx["all_articles"]
    return ctx


def rows_response(session, q=None, highlight=None, refresh=True):
    ctx = board_context(session, q=q, highlight=highlight)
    html = render_template("partials/_article_rows.html", **ctx)
    return Response(html, headers=REFRESH if refresh else None)


def row_response(session, article, refresh=True):
    ctx = board_context(session)
    reviewed = last_reviewed_map(session, [article.item_id]).get(article.item_id)
    ctx["a"] = article.to_dict(last_reviewed=reviewed, cadence_days=ctx["cadence"])
    html = render_template("partials/_article_row.html", **ctx)
    return Response(html, headers=REFRESH if refresh else None)


def team_response(session):
    balances = []
    for row in team_balances(session):
        balances.append(
            {
                **row,
                "primaryPct": min(100, row["primaryCount"] / max(1, row["primaryCap"]) * 100),
                "backupPct": min(100, row["backupCount"] / max(1, row["backupCap"]) * 100),
                "primaryOver": row["primaryCount"] > row["primaryCap"],
                "backupOver": row["backupCount"] > row["backupCap"],
            }
        )
    return Response(
        render_template("partials/_team.html", balances=balances), headers=REFRESH
    )


# ============================== PAGES ==============================
@bp.get("/")
def index():
    session = get_session()
    tab = request.args.get("tab", "articles")
    highlight = request.args.get("highlight", type=int)
    ctx = board_context(session, highlight=highlight)
    ctx["tab"] = tab
    ctx["panel"] = _panel_html(session, tab)
    return render_template("board.html", **ctx)


def _panel_html(session, name):
    if name == "team":
        return team_response(session).get_data(as_text=True)
    if name == "activity":
        return _activity_html(session)
    ctx = board_context(session)
    return render_template("partials/_articles.html", **ctx)


@bp.get("/tab/<name>")
def panel(name):
    session = get_session()
    return _panel_html(session, name)


@bp.get("/dashboard")
def dashboard():
    session = get_session()
    return render_template("partials/_dashboard.html", **dashboard_context(session))


@bp.get("/headline")
def headline():
    """Just the up-to-date percentage in the header, which sits outside #dashboard."""
    session = get_session()
    return f"{board_context(session)['summary']['healthy_pct']}%"


@bp.get("/articles/rows")
def article_rows():
    session = get_session()
    return rows_response(session, q=request.args.get("q"), refresh=False)


# ============================== IDENTITY ==============================
@bp.post("/whoami")
def set_identity():
    set_current_person((request.form.get("name") or "").strip())
    session = get_session()
    return _panel_html(session, request.form.get("tab", "articles"))


# ============================== ARTICLES ==============================
@bp.post("/articles")
def add_article():
    session = get_session()
    name = (request.form.get("name") or "").strip()
    if name:
        item = Item(
            kind=KIND_DOC_ARTICLE,
            source_system=SOURCE_LOCAL,
            title=name,
            ownership_type="Flexible",
            active=1,
        )
        item.article = DocArticle(note="")
        session.add(item)
        session.flush()
        record(
            session,
            EVENT_ITEM_CREATED,
            f"Article added: “{name}”",
            item_id=item.id,
            actor_person_id=current_person_id(session),
        )
        session.commit()
    return rows_response(session)


@bp.put("/articles/<int:article_id>/owner/<role>")
def set_article_owner(article_id, role):
    if role not in (ROLE_PRIMARY, ROLE_BACKUP):
        return Response("bad role", status=400)
    session = get_session()
    article = get_article(session, article_id)
    if article is None:
        return Response("", status=404)
    set_owner(
        session,
        article.item,
        role,
        request.form.get("name", ""),
        actor_id=current_person_id(session),
    )
    session.commit()
    return row_response(session, article)


@bp.put("/articles/<int:article_id>/type")
def set_article_type(article_id):
    session = get_session()
    article = get_article(session, article_id)
    if article is None:
        return Response("", status=404)
    wanted = request.form.get("type", "Flexible")
    if wanted != article.item.ownership_type:
        previous = article.item.ownership_type
        article.item.ownership_type = wanted
        record(
            session,
            EVENT_OWNERSHIP_TYPE_CHANGED,
            f"“{article.item.title}” ownership type {previous} → {wanted}",
            item_id=article.item_id,
            actor_person_id=current_person_id(session),
            detail={"previous": previous, "current": wanted},
        )
        session.commit()
    return row_response(session, article, refresh=False)


@bp.post("/articles/<int:article_id>/review")
def mark_reviewed(article_id):
    session = get_session()
    article = get_article(session, article_id)
    if article is None:
        return Response("", status=404)
    owner = article.item.owner(ROLE_PRIMARY)
    record(
        session,
        EVENT_REVIEWED,
        f"Reviewed: “{article.item.title}”",
        item_id=article.item_id,
        subject_person_id=owner.person_id if owner is not None else None,
        actor_person_id=current_person_id(session),
    )
    session.commit()
    return row_response(session, article)


@bp.put("/articles/<int:article_id>/backdate")
def backdate_review(article_id):
    """Record a review that happened in the past.

    Appends rather than overwrites, so the earlier dates stay in the log.
    """
    session = get_session()
    article = get_article(session, article_id)
    if article is None:
        return Response("", status=404)
    stamp = (request.form.get("lastReviewed") or "")[:10]
    if stamp:
        record(
            session,
            EVENT_REVIEWED,
            f"Reviewed: “{article.item.title}” (backdated to {stamp})",
            item_id=article.item_id,
            actor_person_id=current_person_id(session),
            occurred_at=f"{stamp}T00:00:00",
            detail={"backdated": True},
        )
        session.commit()
    return row_response(session, article)


@bp.delete("/articles/<int:article_id>")
def delete_article(article_id):
    session = get_session()
    item = session.get(Item, article_id)
    if item is not None:
        title = item.title
        session.delete(item)
        record(
            session,
            EVENT_ITEM_DELETED,
            f"Article deleted: “{title}”",
            item_id=article_id,
            actor_person_id=current_person_id(session),
            detail={"title": title},
        )
        session.commit()
    # Empty body with an outerHTML swap removes the row.
    return Response("", headers=REFRESH)


@bp.put("/settings/cadence")
def set_cadence():
    session = get_session()
    days = max(30, int(request.form.get("cadenceDays") or CADENCE_DEFAULT))
    setting = session.get(Setting, "cadence_days")
    previous = setting.value if setting is not None else None
    if setting is None:
        session.add(Setting(key="cadence_days", value=str(days)))
    else:
        setting.value = str(days)
    if str(days) != str(previous):
        record(
            session,
            EVENT_CADENCE_CHANGED,
            f"Review cadence changed from {previous or CADENCE_DEFAULT} to {days} days",
            actor_person_id=current_person_id(session),
            detail={"previous": previous, "current": days},
        )
    session.commit()
    return rows_response(session)


# ============================== PEOPLE ==============================
@bp.post("/people")
def add_person():
    session = get_session()
    name = (request.form.get("name") or "").strip()
    if name:
        actor = current_person_id(session)
        person = get_person_by_name(session, name)
        if person is None:
            person = Person(name=name, active=1)
            person.caps = default_caps()
            session.add(person)
            session.flush()
            record(
                session,
                EVENT_PERSON_ADDED,
                f"{name} added to the roster",
                subject_person_id=person.id,
                actor_person_id=actor,
            )
        elif not person.active:
            person.active = 1
            record(
                session,
                EVENT_PERSON_REACTIVATED,
                f"{name} reactivated",
                subject_person_id=person.id,
                actor_person_id=actor,
            )
        session.commit()
    return team_response(session)


@bp.put("/people/<path:name>/cap/<role>")
def set_person_cap(name, role):
    if role not in (ROLE_PRIMARY, ROLE_BACKUP):
        return Response("bad role", status=400)
    session = get_session()
    person = get_person_by_name(session, name)
    if person is None:
        return Response("", status=404)
    field = "primaryCap" if role == ROLE_PRIMARY else "backupCap"
    wanted = max(0, int(request.form.get(field) or 0))
    previous = person.cap(KIND_DOC_ARTICLE, role)
    if previous != wanted:
        person.set_cap(KIND_DOC_ARTICLE, role, wanted)
        record(
            session,
            EVENT_CAP_CHANGED,
            f"{name} {role} cap {previous} → {wanted} (articles)",
            subject_person_id=person.id,
            actor_person_id=current_person_id(session),
            detail={"kind": KIND_DOC_ARTICLE, "role": role, "previous": previous, "current": wanted},
        )
        session.commit()
    return team_response(session)


@bp.delete("/people/<path:name>")
def delete_person(name):
    session = get_session()
    person = get_person_by_name(session, name)
    if person is None:
        return team_response(session)
    actor = current_person_id(session)
    owning = session.scalar(
        select(func.count()).select_from(Ownership).where(Ownership.person_id == person.id)
    )
    if owning > 0:
        if person.active:
            record(
                session,
                EVENT_PERSON_DEACTIVATED,
                f"{name} deactivated (still owns {owning} item{'s' if owning != 1 else ''})",
                subject_person_id=person.id,
                actor_person_id=actor,
                detail={"owning": owning},
            )
        person.active = 0
    else:
        record(
            session,
            EVENT_PERSON_REMOVED,
            f"{name} removed from the roster",
            subject_person_id=person.id,
            actor_person_id=actor,
        )
        session.delete(person)
    session.commit()
    return team_response(session)


# ============================== ACTIVITY ==============================
def _activity_html(session):
    rows = session.scalars(
        select(Event).order_by(Event.occurred_at.desc(), Event.id.desc()).limit(200)
    ).all()
    total = session.scalar(select(func.count()).select_from(Event))
    names = dict(session.execute(select(Person.id, Person.name)).all())
    events = []
    for e in rows:
        events.append(
            {
                "summary": e.summary,
                "source": e.source,
                "occurredAt": e.occurred_at,
                "actor": names.get(e.actor_person_id),
                "meta": EVENT_META.get(e.type, {"icon": "•", "color": "var(--muted)"}),
            }
        )
    return render_template(
        "partials/_activity.html",
        events=events,
        total=total,
        any_actor=any(e["actor"] for e in events),
    )
