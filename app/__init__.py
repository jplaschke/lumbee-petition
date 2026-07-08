from flask import Flask, abort, request
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_mail import Mail
from pathlib import Path
import os

db = SQLAlchemy()
login_manager = LoginManager()
mail = Mail()


def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'change-me')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # ── Email Configuration ────────────────────────────────────────────
    app.config['MAIL_SERVER'] = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
    app.config['MAIL_PORT'] = int(os.environ.get('MAIL_PORT', 587))
    app.config['MAIL_USE_TLS'] = True
    app.config['MAIL_USE_SSL'] = False
    app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')
    app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')
    app.config['MAIL_DEFAULT_SENDER'] = os.environ.get(
        'MAIL_DEFAULT_SENDER',
        'noreply@lumbeepetition.org'
    )

    # ── Database Configuration ─────────────────────────────────────────
    app.config['SQLALCHEMY_DATABASE_URI'] = (
        'sqlite:////app/app/static/uploads/petition.db'
    )

    # ── Block DB Files from Web Access ─────────────────────────────────
    @app.before_request
    def block_sensitive_files():
        blocked = ['.db', '.sqlite', '.sqlite3']
        if any(request.path.endswith(ext) for ext in blocked):
            abort(403)

    def maybe_reset_db(app):
        reset = os.environ.get("RESET_DB_ON_START", "").lower() in ("1", "true", "yes")
        if not reset:
            return
        db_uri = app.config["SQLALCHEMY_DATABASE_URI"]
        if not db_uri.startswith("sqlite:///") and not db_uri.startswith("sqlite:////"):
            return
        db_path = db_uri.replace("sqlite:////", "/").replace("sqlite:///", "/")
        path = Path(db_path)
        if path.exists():
            path.unlink()

    # ── Initialize Extensions ──────────────────────────────────────────
    maybe_reset_db(app)
    db.init_app(app)
    login_manager.init_app(app)
    mail.init_app(app)
    login_manager.login_view = 'main.login'

    # ── Register Blueprints ────────────────────────────────────────────
    from app.routes import main
    app.register_blueprint(main)

    # ── Create Tables & Seed Defaults ─────────────────────────────────
    with app.app_context():
        db.create_all()
        from app.models import SiteSettings
        if not SiteSettings.query.first():
            default_settings = SiteSettings(
                petition_title='Petition for Gaming Ordinance',
                petition_text=(
                    'Under Title V of the Lumbee Constitution, we call on the Tribal Council '
                    'to adopt a Gaming Ordinance. Voted yes, voted no — this is better.'
                ),
                target_signatures=6400,
                background_color='#8B0000',
                email=app.config['MAIL_DEFAULT_SENDER'],
            )
            db.session.add(default_settings)
            db.session.commit()

    return app

