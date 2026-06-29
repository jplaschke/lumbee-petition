from app import db, login_manager
from flask_login import UserMixin
from datetime import datetime
import hashlib

class Signer(db.Model):
    __tablename__ = 'signers'
    id             = db.Column(db.Integer, primary_key=True)
    full_name      = db.Column(db.String(200), nullable=False)
    enrollment_id  = db.Column(db.String(100), unique=True, nullable=False)
    email          = db.Column(db.String(200), nullable=False)
    phone          = db.Column(db.String(50))
    ip_address     = db.Column(db.String(100))
    id_filename    = db.Column(db.String(300))
    signature_hash = db.Column(db.String(256))
    timestamp      = db.Column(db.DateTime, default=datetime.utcnow)
    verified       = db.Column(db.Boolean, default=True)

    # FIXED: Added missing crypto tracking blocks expected by routes.py
    digital_signature = db.Column(db.Text, nullable=True)
    public_key        = db.Column(db.Text, nullable=True)
    manifest_data     = db.Column(db.Text, nullable=True)

    def set_hash(self):
        raw = f"{self.full_name}{self.enrollment_id}{self.email}{self.timestamp}"
        self.signature_hash = hashlib.sha256(raw.encode()).hexdigest()

class AdminUser(db.Model, UserMixin):
    __tablename__ = 'admin_users'
    id       = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)

class SiteSettings(db.Model):
    __tablename__ = 'site_settings'
    id                = db.Column(db.Integer, primary_key=True)
    petition_title    = db.Column(db.String(300), default='Lumbee Tribe Federal Recognition Petition')
    petition_text     = db.Column(db.Text, default='We the undersigned call for full federal recognition.')
    target_signatures = db.Column(db.Integer, default=6400)
    background_color  = db.Column(db.String(20), default='#8B0000')
    header_image      = db.Column(db.String(300))
    background_image  = db.Column(db.String(300))

@login_manager.user_loader
def load_user(user_id):
    return AdminUser.query.get(int(user_id))

