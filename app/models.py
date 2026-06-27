from datetime import datetime
from app import db
import uuid

def _uuid():
    return str(uuid.uuid4())

class Signer(db.Model):
    __tablename__ = "signers"
    id               = db.Column(db.String(36), primary_key=True, default=_uuid)
    full_name        = db.Column(db.String(255), nullable=False)
    enrollment_id    = db.Column(db.String(50),  nullable=False, unique=True, index=True)
    email            = db.Column(db.String(255), nullable=False)
    phone            = db.Column(db.String(20))
    id_card_filename = db.Column(db.String(500), nullable=False)
    id_card_expiry   = db.Column(db.Date,        nullable=False)
    ip_address       = db.Column(db.String(45),  nullable=False)
    timestamp        = db.Column(db.DateTime,    default=datetime.utcnow)
    is_verified      = db.Column(db.Boolean,     default=False)
    signature_hash   = db.Column(db.String(64))

class DuplicateAttempt(db.Model):
    __tablename__ = "duplicate_attempts"
    id                      = db.Column(db.String(36), primary_key=True, default=_uuid)
    attempted_enrollment_id = db.Column(db.String(50), nullable=False, index=True)
    attempted_name          = db.Column(db.String(255))
    attempted_email         = db.Column(db.String(255))
    ip_address              = db.Column(db.String(45),  nullable=False)
    timestamp               = db.Column(db.DateTime,    default=datetime.utcnow)
    details                 = db.Column(db.Text)

class AuditLog(db.Model):
    __tablename__ = "audit_log"
    id            = db.Column(db.String(36), primary_key=True, default=_uuid)
    event_type    = db.Column(db.String(100), nullable=False)
    enrollment_id = db.Column(db.String(50))
    ip_address    = db.Column(db.String(45),  nullable=False)
    timestamp     = db.Column(db.DateTime,    default=datetime.utcnow)
    details       = db.Column(db.Text)
    severity      = db.Column(db.String(20),  default="INFO")

class SiteSettings(db.Model):
    __tablename__ = "site_settings"
    id            = db.Column(db.Integer, primary_key=True)
    setting_key   = db.Column(db.String(100), unique=True, nullable=False)
    setting_value = db.Column(db.Text)
    updated_at    = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @staticmethod
    def get(key, default=None):
        row = SiteSettings.query.filter_by(setting_key=key).first()
        return row.setting_value if row else default

    @staticmethod
    def set(key, value):
        row = SiteSettings.query.filter_by(setting_key=key).first()
        if row:
            row.setting_value = value
        else:
            row = SiteSettings(setting_key=key, setting_value=value)
            db.session.add(row)
        db.session.commit()
