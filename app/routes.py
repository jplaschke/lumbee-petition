from flask import (
    render_template, request, redirect,
    url_for, flash, Response
)
from models import db, SiteSettings, DocumentHashLog, \
                   PetitionCommitteeMember, Signer
from utils.hash_utils import (
    compute_hash, log_hash, get_current_hash,
    get_baseline_hash, hash_matches_latest_log,
    verify_chain_integrity, get_hash_log
)
import datetime


# ── Petition Public Page ───────────────────────────────────────
@app.route('/petition')
def petition():
    settings         = SiteSettings.query.first()
    ordinance_text   = settings.ordinance_text if settings else ""
    committee_members = PetitionCommitteeMember.query.order_by(
        PetitionCommitteeMember.slot_number
    ).all()
    recent_signers   = Signer.query.order_by(
        Signer.signed_at.desc()
    ).limit(10).all()
    total_signatures = Signer.query.count()
    goal             = settings.signature_goal if settings else 1000
    current_hash     = compute_hash(ordinance_text) if ordinance_text else "—"
    hash_match       = hash_matches_latest_log()
    start_date       = settings.petition_start_date.strftime('%B %d, %Y') \
                       if settings and settings.petition_start_date else "—"

    return render_template(
        'petition.html',
        ordinance_text    = ordinance_text,
        committee_members = committee_members,
        recent_signers    = recent_signers,
        total_signatures  = total_signatures,
        goal              = goal,
        current_hash      = current_hash,
        hash_match        = hash_match,
        start_date        = start_date
    )


# ── Print / PDF View ───────────────────────────────────────────
@app.route('/ordinance/print')
def print_ordinance():
    settings          = SiteSettings.query.first()
    ordinance_text    = settings.ordinance_text if settings else ""
    committee_members = PetitionCommitteeMember.query.order_by(
        PetitionCommitteeMember.slot_number
    ).all()
    current_hash      = compute_hash(ordinance_text) if ordinance_text else "—"
    latest_log        = DocumentHashLog.query.order_by(
        DocumentHashLog.created_at.desc()
    ).first()
    hash_timestamp    = latest_log.created_at.strftime(
        '%B %d, %Y at %I:%M %p UTC'
    ) if latest_log else "—"

    return render_template(
        'ordinance_print.html',
        ordinance_text    = ordinance_text,
        committee_members = committee_members,
        current_hash      = current_hash,
        hash_timestamp    = hash_timestamp
    )


# ── PDF Download ───────────────────────────────────────────────
@app.route('/ordinance/download-pdf')
def download_ordinance_pdf():
    """
    Generates a PDF using WeasyPrint and streams it as a download.
    Requires: pip install weasyprint
    """
    try:
        from weasyprint import HTML, CSS
        from flask import current_app
        import io

        settings          = SiteSettings.query.first()
        ordinance_text    = settings.ordinance_text if settings else ""
        committee_members = PetitionCommitteeMember.query.order_by(
            PetitionCommitteeMember.slot_number
        ).all()
        current_hash      = compute_hash(ordinance_text) if ordinance_text else "—"
        latest_log        = DocumentHashLog.query.order_by(
            DocumentHashLog.created_at.desc()
        ).first()
        hash_timestamp    = latest_log.created_at.strftime(
            '%B %d, %Y at %I:%M %p UTC'
        ) if latest_log else "—"

        html_content = render_template(
            'ordinance_print.html',
            ordinance_text    = ordinance_text,
            committee_members = committee_members,
            current_hash      = current_hash,
            hash_timestamp    = hash_timestamp
        )

        pdf_bytes = HTML(
            string   = html_content,
            base_url = request.host_url
        ).write_pdf()

        filename = (
            f"Proposed_Initiative_Ordinance_2026-PI_"
            f"{datetime.date.today().strftime('%Y%m%d')}.pdf"
        )

        return Response(
            pdf_bytes,
            mimetype    = 'application/pdf',
            headers     = {
                'Content-Disposition':
                    f'attachment; filename="{filename}"'
            }
        )

    except ImportError:
        flash(
            "PDF generation requires WeasyPrint. "
            "Install it with: pip install weasyprint",
            "warning"
        )
        return redirect(url_for('print_ordinance'))


# ── Save Ordinance + Auto-Hash ─────────────────────────────────
@app.route('/dashboard/save-ordinance', methods=['POST'])
def save_ordinance():
    new_text    = request.form.get('ordinance_text', '').strip()
    change_note = request.form.get('change_note', 'Ordinance text updated')
    changed_by  = request.form.get('changed_by', 'Admin')

    if not new_text:
        flash("Ordinance text cannot be empty.", "danger")
        return redirect(url_for('dashboard'))

    settings = SiteSettings.query.first()
    if not settings:
        settings = SiteSettings()
        db.session.add(settings)

    settings.ordinance_text = new_text
    db.session.commit()

    # Auto-log hash
    entry = log_hash(new_text, change_note, changed_by)

    flash(
        f"✅ Ordinance saved and hash logged. "
        f"SHA-256: {entry.hash_value[:16]}...",
        "success"
    )
    return redirect(url_for('dashboard'))


# ── Hash Chain Integrity Check ─────────────────────────────────
@app.route('/dashboard/verify-chain')
def verify_chain():
    result = verify_chain_integrity()
    if result['valid']:
        flash(
            f"✅ Hash chain integrity verified. "
            f"{result['total']} entries — chain is unbroken.",
            "success"
        )
    else:
        flash(
            f"⚠️ Hash chain integrity BROKEN at entry IDs: "
            f"{result['broken_at']}. Possible document tampering.",
            "danger"
        )
    return redirect(url_for('dashboard'))


# ── Sign Petition ──────────────────────────────────────────────
@app.route('/petition/sign', methods=['POST'])
def sign_petition():
    first_name    = request.form.get('first_name', '').strip()
    last_name     = request.form.get('last_name', '').strip()
    enrollment_id = request.form.get('enrollment_id', '').strip()
    city          = request.form.get('city', '').strip()
    email         = request.form.get('email', '').strip()
    phone         = request.form.get('phone', '').strip()
    affirm        = request.form.get('affirm')

    # Validations
    if not all([first_name, last_name, enrollment_id]):
        flash("Please fill in all required fields.", "danger")
        return redirect(url_for('petition'))

    if not affirm:
        flash("You must check the affirmation box to sign.", "danger")
        return redirect(url_for('petition'))

    # Duplicate check by enrollment ID
    existing = Signer.query.filter_by(
        enrollment_id=enrollment_id
    ).first()
    if existing:
        flash(
            "This enrollment ID has already signed the petition.",
            "warning"
        )
        return redirect(url_for('petition'))

    signer = Signer(
        first_name    = first_name,
        last_name     = last_name,
        enrollment_id = enrollment_id,
        city          = city,
        email         = email,
        phone         = phone,
        signed_at     = datetime.datetime.utcnow()
    )
    db.session.add(signer)
    db.session.commit()

    flash(
        f"✅ Thank you, {first_name}! Your signature has been recorded.",
        "success"
    )
    return redirect(url_for('petition'))

