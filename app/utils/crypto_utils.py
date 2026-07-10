"""
crypto_utils.py
─────────────────────────────────────────────────────────────────────────────
Two independent cryptographic concerns, kept separate on purpose:

1. FIELD ENCRYPTION (symmetric, Fernet)
   Encrypts sensitive PII columns (name, email, phone) at rest, so that if
   the raw database file is ever copied or leaked, those fields are not
   readable without FIELD_ENCRYPTION_KEY. This is transparent to the rest
   of the app via the EncryptedString SQLAlchemy type below.

2. SIGNATURE SIGNING (asymmetric, RSA)
   Each recorded signature gets signed by the SERVER's private key at the
   moment it's created. This proves the record hasn't been altered since
   creation and that it originated from this system - it is NOT the signer
   personally holding or using their own private key (they don't have one).
   Think of it as a stronger, per-record version of the ordinance SHA-256
   hash you already use, not a personal digital ID.

Both keys are read from environment variables. Neither is ever stored in
the database itself.
─────────────────────────────────────────────────────────────────────────────
"""

import os
import base64
import logging

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from sqlalchemy.types import TypeDecorator, Text

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────
# 1. FIELD ENCRYPTION
# ─────────────────────────────────────────────────────────────────────────

def _get_fernet():
    """
    Load the Fernet symmetric key from FIELD_ENCRYPTION_KEY.
    Generate one locally with:
        python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    and set it as an environment variable on Render. Losing this key means
    losing access to every encrypted field permanently - back it up somewhere safe.
    """
    key = os.environ.get('FIELD_ENCRYPTION_KEY')
    if not key:
        raise RuntimeError(
            "FIELD_ENCRYPTION_KEY is not set. Generate one with "
            "`python3 -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"` "
            "and set it as an environment variable."
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


class EncryptedString(TypeDecorator):
    """
    A SQLAlchemy column type that transparently encrypts values on write
    and decrypts them on read. Usage is identical to db.String - the
    encryption is invisible to the rest of the application.

    NOTE: because Fernet ciphertext is non-deterministic (different output
    each time for the same input), encrypted columns CANNOT be used in
    equality lookups (e.g. `Signer.query.filter_by(email=...)`). Only use
    this for fields you never need to query directly by exact value.
    """
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        f = _get_fernet()
        return f.encrypt(value.encode('utf-8')).decode('utf-8')

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        f = _get_fernet()
        try:
            return f.decrypt(value.encode('utf-8')).decode('utf-8')
        except InvalidToken:
            # Value was stored before encryption was enabled, or the key
            # rotated - surface plainly rather than silently corrupting data.
            logger.warning("Failed to decrypt an EncryptedString field - returning raw stored value.")
            return value


# ─────────────────────────────────────────────────────────────────────────
# 2. RSA SIGNATURE SIGNING (per-signature integrity, not personal identity)
# ─────────────────────────────────────────────────────────────────────────

def _load_private_key():
    """
    Load the RSA private key from RSA_PRIVATE_KEY_B64 (base64-encoded PEM,
    kept single-line so it fits cleanly in a Render environment variable).

    Generate a keypair locally with:
        openssl genrsa -out private.pem 2048
        openssl rsa -in private.pem -pubout -out public.pem
        base64 -w 0 private.pem   # -> set this as RSA_PRIVATE_KEY_B64
    Keep private.pem somewhere safe outside the repo. Publish public.pem
    (or use get_public_key_pem() below) so the Tribal Council or anyone
    else can independently verify signatures without needing your private key.
    """
    key_b64 = os.environ.get('RSA_PRIVATE_KEY_B64')
    if not key_b64:
        raise RuntimeError(
            "RSA_PRIVATE_KEY_B64 is not set. See crypto_utils.py docstring "
            "for how to generate and set it."
        )
    pem_bytes = base64.b64decode(key_b64)
    return serialization.load_pem_private_key(pem_bytes, password=None)


def get_public_key_pem() -> str:
    """Return the PEM-encoded public key, safe to publish/display."""
    private_key = _load_private_key()
    public_key = private_key.public_key()
    pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return pem.decode('utf-8')


def sign_payload(payload: str) -> str:
    """
    Sign a canonical string payload with the server's RSA private key
    (RSA-PSS + SHA-256). Returns a base64-encoded signature suitable for
    storing in the database or including in an email receipt.
    """
    private_key = _load_private_key()
    signature = private_key.sign(
        payload.encode('utf-8'),
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.MAX_LENGTH
        ),
        hashes.SHA256()
    )
    return base64.b64encode(signature).decode('utf-8')


def verify_signature(payload: str, signature_b64: str) -> bool:
    """
    Verify a payload against a base64 signature using the public key
    derived from the same private key. Returns True/False rather than
    raising, so callers can display a simple pass/fail without try/except.
    """
    try:
        private_key = _load_private_key()
        public_key = private_key.public_key()
        signature = base64.b64decode(signature_b64)
        public_key.verify(
            signature,
            payload.encode('utf-8'),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH
            ),
            hashes.SHA256()
        )
        return True
    except Exception:
        return False


def build_signer_payload(signer) -> str:
    """
    Canonical, order-fixed string representation of a signer record used
    for both signing and verifying. Keep this format stable - changing it
    would invalidate every previously-issued signature.
    """
    return (
        f"id={signer.id}|"
        f"full_name={signer.full_name}|"
        f"enrollment_id={signer.enrollment_id}|"
        f"email={signer.email}|"
        f"timestamp={signer.timestamp.isoformat() if signer.timestamp else ''}"
    )

