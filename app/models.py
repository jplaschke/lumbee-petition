import hashlib
import json
from datetime import datetime
from app import db

class Signer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(150), nullable=False)
    enrollment_id = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(150), nullable=True)
    phone = db.Column(db.String(30), nullable=True)
    ip_address = db.Column(db.String(50), nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    verified = db.Column(db.Boolean, default=False)

class SiteSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    petition_title = db.Column(db.String(300), nullable=False,
        default="Proposed Ordinance No. 2026- | Lumbee Gaming Governance, Transparency, and Economic Development Act")
    target_signatures = db.Column(db.Integer, default=500)
    ordinance_text = db.Column(db.Text, nullable=True)
    ordinance_hash = db.Column(db.String(64), nullable=True)  # SHA-256

class PetitionCommitteeMember(db.Model):
    """
    Article V — Initiative: Three members of the Petition Committee
    who are responsible for circulating and certifying the petition.
    """
    id = db.Column(db.Integer, primary_key=True)
    slot = db.Column(db.Integer, nullable=False, unique=True)  # 1, 2, or 3
    full_name = db.Column(db.String(150), nullable=True)
    enrollment_id = db.Column(db.String(100), nullable=True)
    address = db.Column(db.String(300), nullable=True)
    phone = db.Column(db.String(30), nullable=True)
    email = db.Column(db.String(150), nullable=True)
    assigned_at = db.Column(db.DateTime, nullable=True)
    is_filled = db.Column(db.Boolean, default=False)

class DocumentHashLog(db.Model):
    """
    Immutable log of SHA-256 hashes for change tracking.
    Every time the ordinance text is saved, a new hash record is created.
    """
    id = db.Column(db.Integer, primary_key=True)
    document_label = db.Column(db.String(200), nullable=False,
        default="Official_Lumbee_Gaming_Ordinance_Record")
    sha256_hash = db.Column(db.String(64), nullable=False)
    previous_hash = db.Column(db.String(64), nullable=True)  # chain link
    changed_by = db.Column(db.String(150), nullable=True)
    change_note = db.Column(db.String(500), nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    is_current = db.Column(db.Boolean, default=True)

    @staticmethod
    def compute_hash(text: str) -> str:
        """Compute SHA-256 hash of ordinance text."""
        return hashlib.sha256(text.encode('utf-8')).hexdigest()

    @staticmethod
    def log_change(text: str, changed_by: str = "admin", note: str = ""):
        """
        Call this whenever ordinance text is saved.
        Marks previous record as not current, creates new record.
        """
        new_hash = DocumentHashLog.compute_hash(text)

        # Get previous current hash
        previous = DocumentHashLog.query.filter_by(is_current=True)\
            .order_by(DocumentHashLog.timestamp.desc()).first()

        if previous:
            # No change — don't log duplicate
            if previous.sha256_hash == new_hash:
                return previous
            previous.is_current = False
            prev_hash_value = previous.sha256_hash
        else:
            prev_hash_value = None

        new_log = DocumentHashLog(
            sha256_hash=new_hash,
            previous_hash=prev_hash_value,
            changed_by=changed_by,
            change_note=note,
            is_current=True
        )
        db.session.add(new_log)
        db.session.commit()
        return new_log

class DocumentHashLog(db.Model):
    __tablename__ = 'document_hash_log'

    id            = db.Column(db.Integer, primary_key=True)
    hash_value    = db.Column(db.String(64), nullable=False)
    previous_hash = db.Column(db.String(64), nullable=True)
    change_note   = db.Column(db.String(500), nullable=True)
    changed_by    = db.Column(db.String(200), nullable=True)
    text_length   = db.Column(db.Integer, nullable=True)
    created_at    = db.Column(
        db.DateTime,
        default=datetime.datetime.utcnow,
        nullable=False
    )

    def __repr__(self):
        return (
            f"<HashLog id={self.id} "
            f"hash={self.hash_value[:12]}... "
            f"at={self.created_at}>"
        )

    @property
    def short_hash(self):
        return self.hash_value[:16] + "..."

    @property
    def chain_link(self):
        """Returns a visual chain link indicator."""
        return "🔗" if self.previous_hash else "🔑"

