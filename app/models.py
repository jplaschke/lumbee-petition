from app import db, login_manager
from flask_login import UserMixin
from datetime import datetime, timezone
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
    # Updated: Ensures the database explicitly knows the timezone structure
    timestamp = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    verified       = db.Column(db.Boolean, default=True)

    # FIXED: Added missing crypto tracking blocks expected by routes.py
    digital_signature = db.Column(db.Text, nullable=True)
    public_key        = db.Column(db.Text, nullable=True)
    manifest_data     = db.Column(db.Text, nullable=True)

    def set_hash(self):
        # Ensure timestamp string conversion handles explicit formatting cleanly
        ts_str = self.timestamp.isoformat() if self.timestamp else datetime.now(timezone.utc).isoformat()
        raw = f"{self.full_name}{self.enrollment_id}{self.email}{ts_str}"
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

class DuplicateAttempt(db.Model):
    __tablename__ = 'duplicate_attempts'
    
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    enrollment_id = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(120), nullable=True)
    ip_address = db.Column(db.String(50), nullable=True)
    timestamp = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    def __init__(self, full_name, enrollment_id, email, ip_address, timestamp=None):
        self.full_name = full_name
        self.enrollment_id = enrollment_id
        self.email = email
        self.ip_address = ip_address
        if timestamp:
            self.timestamp = timestamp

