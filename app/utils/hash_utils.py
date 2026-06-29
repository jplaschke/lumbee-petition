"""
hash_utils.py
─────────────────────────────────────────────────────────────────────────────
Cryptographic document integrity utilities for
Proposed Initiative Ordinance No. 2026-PI

Provides SHA-256 hashing, version chain logging, and integrity verification
for the Lumbee Tribe Gaming Initiative ordinance document.
─────────────────────────────────────────────────────────────────────────────
"""

import hashlib
import json
from datetime import datetime, timezone

import pytz

# ── Timezone ──────────────────────────────────────────────────────────────────
EASTERN = pytz.timezone("America/New_York")


# ─────────────────────────────────────────────────────────────────────────────
# 1. CORE HASH COMPUTATION
# ─────────────────────────────────────────────────────────────────────────────

def compute_sha256(content: str | bytes) -> str:
    """
    Compute a SHA-256 hex digest of the given content.

    Args:
        content: The document text (str) or raw bytes to hash.

    Returns:
        A lowercase 64-character hex string (SHA-256 digest).

    Example:
        >>> compute_sha256("Hello, Lumbee Nation!")
        'a3f1...'
    """
    if isinstance(content, str):
        content = content.encode("utf-8")

    return hashlib.sha256(content).hexdigest()


def compute_sha256_from_file(filepath: str) -> str:
    """
    Compute SHA-256 hash of a file on disk (e.g., uploaded PDF).

    Args:
        filepath: Absolute or relative path to the file.

    Returns:
        SHA-256 hex digest string.
    """
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
# 2. DATABASE HASH LOG OPERATIONS
# ─────────────────────────────────────────────────────────────────────────────

def log_document_hash(
    db,
    DocumentHashLog,
    content: str,
    changed_by: str = "system",
    note: str = "",
    filename: str = None,
) -> "DocumentHashLog":
    """
    Compute and persist a new hash log entry for the current ordinance content.

    Chains the new entry to the previous hash for tamper detection.

    Args:
        db:              SQLAlchemy db instance.
        DocumentHashLog: The ORM model class.
        content:         Full ordinance text content to hash.
        changed_by:      Username or identifier of who made the change.
        note:            Optional human-readable note about the change.
        filename:        Optional filename if content came from an upload.

    Returns:
        The newly created DocumentHashLog ORM instance (already committed).
    """
    new_hash = compute_sha256(content)
    text_length = len(content)

    # Retrieve the most recent hash to chain against
    previous_entry = (
        DocumentHashLog.query
        .order_by(DocumentHashLog.id.desc())
        .first()
    )
    previous_hash = previous_entry.hash_value if previous_entry else None

    now_utc = datetime.now(timezone.utc)
    now_eastern = now_utc.astimezone(EASTERN)

    entry = DocumentHashLog(
        hash_value=new_hash,
        previous_hash=previous_hash,
        changed_by=changed_by,
        text_length=text_length,
        note=note or f"Document updated by {changed_by}",
        filename=filename,
        created_at=now_utc,
    )

    db.session.add(entry)
    db.session.commit()

    return entry


# ─────────────────────────────────────────────────────────────────────────────
# 3. RETRIEVE HASHES
# ─────────────────────────────────────────────────────────────────────────────

def get_current_hash(DocumentHashLog) -> dict | None:
    """
    Retrieve the most recent hash log entry as a dictionary.

    Args:
        DocumentHashLog: The ORM model class.

    Returns:
        Dict with keys: hash_value, previous_hash, changed_by,
                        text_length, note, filename, created_at
        OR None if no entries exist.
    """
    entry = (
        DocumentHashLog.query
        .order_by(DocumentHashLog.id.desc())
        .first()
    )

    if not entry:
        return None

    return _entry_to_dict(entry)


def get_baseline_hash(DocumentHashLog) -> dict | None:
    """
    Retrieve the very first (baseline) hash log entry.

    Args:
        DocumentHashLog: The ORM model class.

    Returns:
        Dict for the first entry, or None if no entries exist.
    """
    entry = (
        DocumentHashLog.query
        .order_by(DocumentHashLog.id.asc())
        .first()
    )

    if not entry:
        return None

    return _entry_to_dict(entry)


def get_hash_history(DocumentHashLog, limit: int = 50) -> list[dict]:
    """
    Retrieve recent hash log entries in reverse chronological order.

    Args:
        DocumentHashLog: The ORM model class.
        limit:           Max number of entries to return (default 50).

    Returns:
        List of dicts, newest first.
    """
    entries = (
        DocumentHashLog.query
        .order_by(DocumentHashLog.id.desc())
        .limit(limit)
        .all()
    )

    return [_entry_to_dict(e) for e in entries]


# ─────────────────────────────────────────────────────────────────────────────
# 4. CHAIN INTEGRITY VERIFICATION
# ─────────────────────────────────────────────────────────────────────────────

def verify_chain_integrity(DocumentHashLog) -> dict:
    """
    Walk the entire hash chain and verify each link is unbroken.

    For each entry (except the first), confirms that its `previous_hash`
    matches the `hash_value` of the entry before it.

    Args:
        DocumentHashLog: The ORM model class.

    Returns:
        {
            "valid":   bool,        # True if entire chain is intact
            "checked": int,         # Number of entries checked
            "broken_at": int|None,  # ID of first broken entry, or None
            "errors":  list[str],   # Human-readable error messages
        }
    """
    entries = (
        DocumentHashLog.query
        .order_by(DocumentHashLog.id.asc())
        .all()
    )

    if not entries:
        return {
            "valid": True,
            "checked": 0,
            "broken_at": None,
            "errors": [],
        }

    errors = []
    broken_at = None

    for i in range(1, len(entries)):
        current = entries[i]
        previous = entries[i - 1]

        if current.previous_hash != previous.hash_value:
            broken_at = current.id
            errors.append(
                f"Chain broken at entry ID {current.id}: "
                f"expected previous_hash='{previous.hash_value[:16]}…' "
                f"but got '{str(current.previous_hash)[:16]}…'"
            )
            break  # Stop at first break — chain is compromised

    return {
        "valid": len(errors) == 0,
        "checked": len(entries),
        "broken_at": broken_at,
        "errors": errors,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 5. CONTENT RE-VERIFICATION
# ─────────────────────────────────────────────────────────────────────────────

def verify_content_matches_hash(content: str, expected_hash: str) -> bool:
    """
    Verify that a given document content matches an expected SHA-256 hash.

    Useful for confirming that the live ordinance text has not drifted
    from the recorded hash.

    Args:
        content:       The document text to verify.
        expected_hash: The SHA-256 hex digest to compare against.

    Returns:
        True if content hashes to expected_hash, False otherwise.
    """
    return compute_sha256(content) == expected_hash.lower().strip()


# ─────────────────────────────────────────────────────────────────────────────
# 6. EXPORT UTILITIES
# ─────────────────────────────────────────────────────────────────────────────

def export_hash_log_json(DocumentHashLog) -> str:
    """
    Export the full hash log as a JSON string (for audit downloads).

    Args:
        DocumentHashLog: The ORM model class.

    Returns:
        Pretty-printed JSON string of all hash log entries.
    """
    entries = (
        DocumentHashLog.query
        .order_by(DocumentHashLog.id.asc())
        .all()
    )

    data = {
        "document": "Proposed Initiative Ordinance No. 2026-PI",
        "tribe": "Lumbee Tribe of North Carolina",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "total_entries": len(entries),
        "chain": [_entry_to_dict(e) for e in entries],
    }

    return json.dumps(data, indent=2, default=str)


# ─────────────────────────────────────────────────────────────────────────────
# PRIVATE HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _entry_to_dict(entry) -> dict:
    """Convert a DocumentHashLog ORM instance to a plain dictionary."""
    return {
        "id":            entry.id,
        "hash_value":    entry.hash_value,
        "previous_hash": entry.previous_hash,
        "changed_by":    entry.changed_by,
        "text_length":   entry.text_length,
        "note":          entry.note,
        "filename":      getattr(entry, "filename", None),
        "created_at":    entry.created_at.isoformat() if entry.created_at else None,
    }
    
