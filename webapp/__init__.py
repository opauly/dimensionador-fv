from dotenv import load_dotenv
from flask import Flask

load_dotenv()


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["JSON_AS_ASCII"] = False

    from webapp.blueprints.dashboard import bp as dashboard_bp

    app.register_blueprint(dashboard_bp)

    @app.context_processor
    def inject_db_status():
        try:
            from database.supabase_client import ping

            return {"db_ok": ping()}
        except Exception:
            return {"db_ok": False}

    return app
