from flask import (
    Blueprint, render_template, request, redirect,
    url_for, flash, Response
)
from flask_login import login_required, current_user
from app.models import db, SiteSettings, DocumentHashLog, \
    PetitionCommitteeMember, Signer
from app.utils.hash_utils import (
    compute_sha256,
    log_document_hash,
    get_current_hash,
    get_hash_history,
    verify_chain_integrity,
    verify_content_matches_hash,
)
import datetime

# ── Define Blueprints ──────────────────────────────────────────
main_bp  = Blueprint('main_bp',  __name__)
admin_bp = Blueprint('admin_bp', __name__)


# ── Root Redirect ──────────────────────────────────────────────
@main_bp.route('/')
def index():
    return redirect(url_for('main_bp.petition'))


# ── Petition Public Page ───────────────────────────────────────
@main_bp.route('/petition')
def petition():
    settings          = SiteSettings.query.first()
    ordinance_text    = settings.ordinance_text if settings else ""
    committee_members = PetitionCommitteeMember.query.order_by(
        PetitionCommitteeMember.slot
    ).all()
    recent_signers    = Signer.query.order_by(Signer.signed_at.desc()).limit(10).all()
    total_signatures  = Signer.query.count()
    goal              = settings.target_signatures if settings else 1000
    current_hash      = compute_sha256(ordinance_text) if ordinance_text else "—"

    _latest    = get_current_hash(DocumentHashLog)
    hash_match = (
        verify_content_matches_hash(ordinance_text, _latest["sha256_hash"])
        if _latest and ordinance_text else False
    )

    start_date = (
        settings.petition_start_date.strftime('%B %d, %Y')
        if settings and settings.petition_start_date else "—"
    )

    return render_template(
        'petition.html',
        ordinance_text    = ordinance_text,
        committee_members = committee_members,
        recent_signers    = recent_signers,
        total_signatures  = total_signatures,
        goal              = goal,
        current_hash      = current_hash,
        hash_match        = hash_match,
        start_date        = start_date,
    )


# ── Print / PDF View ───────────────────────────────────────────
@main_bp.route('/ordinance/print')
def print_ordinance():
    settings          = SiteSettings.query.first()
    ordinance_text    = settings.ordinance_text if settings else ""
    committee_members = PetitionCommitteeMember.query.order_by(
        PetitionCommitteeMember.slot
    ).all()
    current_hash  = compute_sha256(ordinance_text) if ordinance_text else "—"
    latest_log    = DocumentHashLog.query.order_by(
        DocumentHashLog.timestamp.desc()
    ).first()
    hash_timestamp = (
        latest_log.timestamp.strftime('%B %d, %Y at %I:%M %p UTC')
        if latest_log else "—"
    )

    return render_template(
        'ordinance_print.html',
        ordinance_text    = ordinance_text,
        committee_members = committee_members,
        current_hash      = current_hash,
        hash_timestamp    = hash_timestamp,
    )


# ── PDF Download ───────────────────────────────────────────────
@main_bp.route('/ordinance/download-pdf')
def download_ordinance_pdf():
    try:
        from weasyprint import HTML
        import io

        settings          = SiteSettings.query.first()
        ordinance_text    = settings.ordinance_text if settings else ""
        committee_members = PetitionCommitteeMember.query.order_by(
            PetitionCommitteeMember.slot
        ).all()
        current_hash  = compute_sha256(ordinance_text) if ordinance_text else "—"
        latest_log    = DocumentHashLog.query.order_by(
            DocumentHashLog.timestamp.desc()
        ).first()
        hash_timestamp = (
            latest_log.timestamp.strftime('%B %d, %Y at %I:%M %p UTC')
            if latest_log else "—"
        )

        html_content = render_template(
            'ordinance_print.html',
            ordinance_text    = ordinance_text,
            committee_members = committee_members,
            current_hash      = current_hash,
            hash_timestamp    = hash_timestamp,
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
            mimetype = 'application/pdf',
            headers  = {'Content-Disposition': f'attachment; filename="{filename}"'}
        )

    except ImportError:
        flash("PDF generation requires WeasyPrint.", "warning")
        return redirect(url_for('main_bp.print_ordinance'))


# ── Save Ordinance + Auto-Hash ─────────────────────────────────
@admin_bp.route('/dashboard/save-ordinance', methods=['POST'])
@login_required
def save_ordinance():
    new_text    = request.form.get('ordinance_text', '').strip()
    change_note = request.form.get('change_note', 'Ordinance text updated')
    changed_by  = request.form.get('changed_by', 'Admin')

    if not new_text:
        flash("Ordinance text cannot be empty.", "danger")
        return redirect(url_for('admin_bp.dashboard'))

    settings = SiteSettings.query.first()
    if not settings:
        settings = SiteSettings()
        db.session.add(settings)

    settings.ordinance_text = new_text
    db.session.commit()

    entry = log_document_hash(
        db             = db,
        DocumentHashLog = DocumentHashLog,
        content        = new_text,
        changed_by     = changed_by,
        note           = change_note,
    )

    flash(
        f"✅ Ordinance saved and hash logged. SHA-256: {entry.sha256_hash[:16]}...",
        "success"
    )
    return redirect(url_for('admin_bp.dashboard'))


# ── Hash Chain Integrity Check ─────────────────────────────────
@admin_bp.route('/dashboard/verify-chain')
@login_required
def verify_chain():
    result = verify_chain_integrity(DocumentHashLog)
    if result['valid']:
        flash(
            f"✅ Hash chain verified. {result['checked']} entries — chain is unbroken.",
            "success"
        )
    else:
        flash(
            f"⚠️ Hash chain BROKEN at entry ID: {result['broken_at']}. "
            f"{result['errors'][0] if result['errors'] else ''}",
            "danger"
        )
    return redirect(url_for('admin_bp.dashboard'))


# ── Sign Petition ──────────────────────────────────────────────
@main_bp.route('/petition/sign', methods=['POST'])
def sign_petition():
    first_name    = request.form.get('first_name', '').strip()
    last_name     = request.form.get('last_name', '').strip()
    enrollment_id = request.form.get('enrollment_id', '').strip()
    city          = request.form.get('city', '').strip()
    email         = request.form.get('email', '').strip()
    phone         = request.form.get('phone', '').strip()
    affirm        = request.form.get('affirm')

    if not all([first_name, last_name, enrollment_id]):
        flash("Please fill in all required fields.", "danger")
        return redirect(url_for('main_bp.petition'))

    if not affirm:
        flash("You must check the affirmation box to sign.", "danger")
        return redirect(url_for('main_bp.petition'))

    existing = Signer.query.filter_by(enrollment_id=enrollment_id).first()
    if existing:
        flash("This enrollment ID has already signed the petition.", "warning")
        return redirect(url_for('main_bp.petition'))

    signer = Signer(
        first_name    = first_name,
        last_name     = last_name,
        enrollment_id = enrollment_id,
        city          = city,
        email         = email,
        phone         = phone,
        signed_at     = datetime.datetime.utcnow(),
    )
    db.session.add(signer)
    db.session.commit()

    flash(f"✅ Thank you, {first_name}! Your signature has been recorded.", "success")
    return redirect(url_for('main_bp.petition'))

