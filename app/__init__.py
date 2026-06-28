from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
import os

db = SQLAlchemy()
login_manager = LoginManager()

def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'change-me')
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///petition.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'admin_bp.login'

    from app.routes import main_bp, admin_bp
    app.register_blueprint(main_bp)
    app.register_blueprint(admin_bp, url_prefix='/admin')

    with app.app_context():
        db.create_all()

        # Seed default settings if table is empty
        from app.models import SiteSettings
        if not SiteSettings.query.first():
            default_settings = SiteSettings(
                petition_title='Petition for Gaming Ordinance',
                petition_text='Under Title V of the Lumbee Constitution, we call on the Tribal Council to adopt a Gaming Ordinance. Voted yes, voted no — this is better.',
                target_signatures=6400,
                background_color='#8B0000'
            )
            db.session.add(default_settings)
            db.session.commit()

    return app

