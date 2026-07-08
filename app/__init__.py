from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
import os

db = SQLAlchemy()
login_manager = LoginManager()

def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'change-me')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    if os.environ.get('RENDER'):
        app.config['SQLALCHEMY_DATABASE_URI'] = \
            'sqlite:////app/app/static/uploads/petition.db'
    else:
        app.config['SQLALCHEMY_DATABASE_URI'] = \
            os.environ.get('DATABASE_URL', 'sqlite:///petition.db')

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'admin_bp.login'

    from app.routes import main_bp, admin_bp
    app.register_blueprint(main_bp)
    app.register_blueprint(admin_bp, url_prefix='/admin')

    with app.app_context():
        db.create_all()

        from app.models import SiteSettings
        if not SiteSettings.query.first():
            default_settings = SiteSettings(
                petition_title='Petition for Gaming Ordinance',
                petition_text='Under Title V of the Lumbee Constitution...',
                target_signatures=6400,
                background_color='#8B0000'
            )
            db.session.add(default_settings)
            db.session.commit()

    return app

