from dotenv import load_dotenv
from flask import Flask, render_template

load_dotenv()


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["JSON_AS_ASCII"] = False
    # AI file uploads (bill PDFs, tablero images) take 5-40s and are held
    # synchronously — see PLAN_PHASE20_PROPOSALS_JINJA.md §1.7. This caps a
    # request body at 25 MB with a friendly 413 instead of the connection
    # just dying. No SECRET_KEY/flask.session here — the only planned use
    # (a pre-row Steps 1-2 carry) was removed when the proposal row moved to
    # Step 1's own POST (§0.3 Q3/Q6); nothing else in this phase needs it.
    app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024

    from webapp.blueprints.admin import bp as admin_bp
    from webapp.blueprints.dashboard import bp as dashboard_bp
    from webapp.blueprints.maintenance import bp as maintenance_bp
    from webapp.blueprints.proposals import bp as proposals_bp
    from webapp.blueprints.wizard import bp as wizard_bp

    app.register_blueprint(dashboard_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(proposals_bp)
    app.register_blueprint(wizard_bp)
    app.register_blueprint(maintenance_bp)

    @app.errorhandler(413)
    def too_large(_exc):
        return render_template("error_413.html"), 413

    @app.context_processor
    def inject_db_status():
        try:
            from database.supabase_client import ping

            return {"db_ok": ping()}
        except Exception:
            return {"db_ok": False}

    return app
