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
from app.forms import SignatureForm  # Adjust import based on your file structure
from app.models import Signer       # Assuming Signer is your database model
from app import db                  # Your database instance
import os
from werkzeug.utils import secure_filename


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
        settings          = settings,
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
        settings          = settings,
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
            settings          = settings,
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
    form = SignatureForm()

    # validate_on_submit handles the POST request and field validations automatically
    if form.validate_on_submit():
        enrollment_id = form.enrollment_id.data.strip()
        
        # 1. Database Check for existing signatures
        existing = Signer.query.filter_by(enrollment_id=enrollment_id).first()
        if existing:
            flash("This enrollment ID has already signed the petition.", "warning")
            return redirect(url_for('main_bp.petition'))

        # 2. Handle File Upload securely
        id_file = form.id_upload.data
        filename = secure_filename(id_file.filename)
        # Assuming you have an UPLOAD_FOLDER configured in your app config:
        # id_file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))

        # 3. Save to Database
        signer = Signer(
            full_name=form.full_name.data.strip(),
            enrollment_id=enrollment_id,
            email=form.email.data.strip(),
            phone=form.phone.data.strip() if form.phone.data else None,
            id_upload_path=filename  # Or save whatever path structure you use
        )
        
        db.session.add(signer)
        db.session.commit()

        flash("Thank you! Your signature has been recorded successfully.", "success")
        return redirect(url_for('main_bp.petition'))

    # If form validation fails (e.g. missing fields, bad email format, no ID uploaded)
    # We send the form back to the template so it can display the specific validation errors.
    flash("Please correct the errors in the form.", "danger")
    return render_template('petition.html', form=form)

