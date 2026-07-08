import os
from flask import Flask, render_template
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager

# ── These are initialized in models.py ────────────────────────
from app.models import db, User

def create_app():
    app = Flask(__name__, template_folder='templates')

    # ── Config ────────────────────────────────────────────────
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key')
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
        'DATABASE_URL', 'sqlite:///petition.db'
    )
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # ── Init Extensions ───────────────────────────────────────
    db.init_app(app)

    # ── Flask-Login ───────────────────────────────────────────
    login_manager = LoginManager()
    login_manager.login_view = 'admin_bp.login'
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # ── Register Blueprints ───────────────────────────────────
    from app.routes import main_bp, admin_bp
    app.register_blueprint(main_bp)
    app.register_blueprint(admin_bp)

    # ── Error Handlers ────────────────────────────────────────
    @app.errorhandler(404)
    def not_found(e):
        return render_template('404.html'), 404

    @app.errorhandler(500)
    def server_error(e):
        return render_template('500.html'), 500

    # ── Create Tables ─────────────────────────────────────────
    with app.app_context():
        db.create_all()

    return app

