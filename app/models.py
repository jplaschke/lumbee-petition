import hashlib
import datetime
from app import db
from flask_login import UserMixin
from app.utils.crypto_utils import EncryptedString


class AdminUser(db.Model, UserMixin):
    """Admin user seeded from ADMIN_USERNAME / ADMIN_PASSWORD env vars."""
    __tablename__ = 'admin_user'
    id            = db.Column(db.Integer, primary_key=True)
    username      = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)


class Signer(db.Model):
    __tablename__ = 'signer'
    id              = db.Column(db.Integer, primary_key=True)
    full_name       = db.Column(EncryptedString, nullable=False)
    enrollment_id   = db.Column(db.String(100), nullable=False, unique=True)  # kept plaintext - required for exact-match duplicate lookups
    email           = db.Column(EncryptedString, nullable=True)
    phone           = db.Column(EncryptedString, nullable=True)
    id_upload_path  = db.Column(db.String(300), nullable=True)
    ip_address      = db.Column(db.String(50),  nullable=True)
    timestamp       = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    verified        = db.Column(db.Boolean, default=False)
    receipt_sent    = db.Column(db.Boolean, default=False)
    signature       = db.Column(db.Text, nullable=True)  # base64 RSA signature - see app/utils/crypto_utils.py


class DuplicateAttempt(db.Model):
    """
    Logs rejected attempts to sign with an enrollment ID that has already
    signed, so the admin dashboard can report on possible double-voting.
    """
    __tablename__ = 'duplicate_attempt'
    id            = db.Column(db.Integer, primary_key=True)
    full_name     = db.Column(EncryptedString, nullable=True)
    enrollment_id = db.Column(db.String(100), nullable=False)
    email         = db.Column(EncryptedString, nullable=True)
    ip_address    = db.Column(db.String(50),  nullable=True)
    timestamp     = db.Column(db.DateTime, default=datetime.datetime.utcnow)


class SiteSettings(db.Model):
    __tablename__ = 'site_settings'
    id                  = db.Column(db.Integer, primary_key=True)
    petition_title      = db.Column(db.String(300), nullable=False, default=(
        "Proposed Ordinance No. 2026- | Lumbee Gaming Governance, "
        "Transparency, and Economic Development Act"
    ))
    target_signatures   = db.Column(db.Integer, default=500)
    petition_text       = db.Column(db.Text, nullable=True)
    petition_text_hash  = db.Column(db.String(64), nullable=True)
    ordinance_text      = db.Column(db.Text, nullable=True)
    ordinance_hash      = db.Column(db.String(64), nullable=True)
    email               = db.Column(db.String(255), nullable=True)
    background_color    = db.Column(db.String(50), nullable=True, default="#8B0000")
    header_image        = db.Column(db.String(300), nullable=True)
    background_image    = db.Column(db.String(300), nullable=True)
    petition_start_date = db.Column(db.DateTime, nullable=True)

    # ── Signature collection gating (Step 5 readiness) ──
    committee_finalized      = db.Column(db.Boolean, default=False)
    committee_finalized_at   = db.Column(db.DateTime, nullable=True)
    ordinance_finalized       = db.Column(db.Boolean, default=False)
    ordinance_finalized_hash  = db.Column(db.String(64), nullable=True)
    ordinance_finalized_at    = db.Column(db.DateTime, nullable=True)

    def __repr__(self):
        return f'<SiteSettings id={self.id}>'


class PetitionCommitteeMember(db.Model):
    """
    Article V — Initiative: Three members of the Petition Committee
    who are responsible for circulating and certifying the petition.
    """
    __tablename__ = 'petition_committee_member'
    id            = db.Column(db.Integer, primary_key=True)
    slot          = db.Column(db.Integer, nullable=False, unique=True)  # 1, 2, or 3
    full_name     = db.Column(db.String(150), nullable=True)
    enrollment_id = db.Column(db.String(100), nullable=True)
    address       = db.Column(db.String(300), nullable=True)
    phone         = db.Column(db.String(30),  nullable=True)
    email         = db.Column(db.String(150), nullable=True)
    assigned_at   = db.Column(db.DateTime, nullable=True)
    is_filled     = db.Column(db.Boolean, default=False)


class DocumentHashLog(db.Model):
    """
    Immutable log of SHA-256 hashes for change tracking.
    Every time the ordinance text is saved, a new hash record is created.
    """
    __tablename__ = 'document_hash_log'
    id             = db.Column(db.Integer, primary_key=True)
    document_label = db.Column(db.String(200), nullable=False,
                                default="Official_Lumbee_Gaming_Ordinance_Record")
    sha256_hash    = db.Column(db.String(64), nullable=False)
    previous_hash  = db.Column(db.String(64), nullable=True)
    changed_by     = db.Column(db.String(150), nullable=True)
    change_note    = db.Column(db.String(500), nullable=True)
    timestamp      = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    is_current     = db.Column(db.Boolean, default=True)

    @staticmethod
    def compute_hash(text: str) -> str:
        return hashlib.sha256(text.encode('utf-8')).hexdigest()

    @staticmethod
    def log_change(text: str, changed_by: str = "admin", note: str = ""):
        new_hash = DocumentHashLog.compute_hash(text)
        previous = (
            DocumentHashLog.query
            .filter_by(is_current=True)
            .order_by(DocumentHashLog.timestamp.desc())
            .first()
        )
        if previous:
            if previous.sha256_hash == new_hash:
                return previous
            previous.is_current = False
            prev_hash_value = previous.sha256_hash
        else:
            prev_hash_value = None

        new_log = DocumentHashLog(
            sha256_hash   = new_hash,
            previous_hash = prev_hash_value,
            changed_by    = changed_by,
            change_note   = note,
            is_current    = True,
        )
        db.session.add(new_log)
        db.session.commit()
        return new_log

