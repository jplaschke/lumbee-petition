import os
from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, flash, current_app, jsonify, send_from_directory, request
from werkzeug.utils import secure_filename
from werkzeug.security import check_password_hash
from flask_login import login_user, logout_user, login_required, current_user
from flask_mail import Message
from app import db, mail
from app.models import SiteSettings, PetitionCommitteeMember, Signer, DocumentHashLog, DuplicateAttempt, AdminUser
from app.forms import SignatureForm, LoginForm, SettingsForm, OrdinanceUploadForm
from app.utils.hash_utils import compute_sha256, compute_sha256_from_file, get_current_hash, log_document_hash, EASTERN

# ── BLUEPRINT DECLARATIONS ───────────────────────────────────────────
main_bp = Blueprint('main_bp', __name__)
admin_bp = Blueprint('admin_bp', __name__)

# The official ordinance PDF that signers are certifying they've read.
ORDINANCE_PDF_FILENAME = 'Official_Lumbee_Gaming_Ordinance_Record.pdf'


def get_ordinance_pdf_path():
    """Absolute path to the official ordinance PDF on disk."""
    return os.path.join(current_app.root_path, 'static', 'documents', ORDINANCE_PDF_FILENAME)


def get_pdf_integrity():
    """
    Compute the live SHA-256 hash of the actual ordinance PDF file and check
    it against the most recently logged hash, so readers/signers can verify
    the PDF hasn't been swapped or altered since it was logged.
    Returns (current_hash, hash_match, hash_timestamp, file_size_kb).
    """
    pdf_path = get_ordinance_pdf_path()

    if os.path.exists(pdf_path):
        current_hash = compute_sha256_from_file(pdf_path)
        file_size_kb = round(os.path.getsize(pdf_path) / 1024, 1)
    else:
        current_hash = "—"
        file_size_kb = 0

    hash_match = False
    hash_timestamp = "Not yet logged"
    try:
        logged = get_current_hash(DocumentHashLog)
        if logged:
            hash_match = (logged.get('sha256_hash') == current_hash)
            hash_timestamp = logged.get('timestamp') or hash_timestamp
    except Exception:
        hash_match = False

    return current_hash, hash_match, hash_timestamp, file_size_kb


def send_signature_receipt(signer):
    """
    Email the signer a confirmation receipt. Failures here are logged but
    never block the signature itself from being recorded successfully.
    """
    try:
        settings = SiteSettings.query.first()
        title = settings.petition_title if settings else "Lumbee Gaming Ordinance Petition"

        msg = Message(
            subject="Your Signature Has Been Recorded — Lumbee Gaming Ordinance Petition",
            recipients=[signer.email],
        )
        msg.body = (
            f"Dear {signer.full_name},\n\n"
            f"This confirms your signature has been recorded for:\n"
            f"\"{title}\"\n\n"
            f"Enrollment ID on file: {signer.enrollment_id}\n"
            f"Signed: {signer.timestamp.strftime('%B %d, %Y at %I:%M %p')} ET\n\n"
            f"This is a proposed citizen initiative under Article V of the Lumbee "
            f"Constitution. It has not been enacted by the Tribal Council.\n\n"
            f"You can review the full ordinance text at any time here:\n"
            f"{request.host_url.rstrip('/')}{url_for('main_bp.view_ordinance')}\n\n"
            f"If you did not sign this petition, please contact us immediately.\n\n"
            f"— Lumbee Gaming Ordinance Petition Committee"
        )
        mail.send(msg)
        signer.receipt_sent = True
        db.session.commit()
    except Exception as e:
        current_app.logger.warning(f"Failed to send signature receipt to {signer.email}: {e}")


@main_bp.route('/', methods=['GET'])
def index():
    return redirect(url_for('main_bp.sign_petition'))


@main_bp.route('/petition', methods=['GET', 'POST'])
def sign_petition():
    form = SignatureForm()

    if form.validate_on_submit():
        read_confirmation = request.form.get('read_ordinance_check')

        if not read_confirmation:
            return jsonify({
                "status": "error",
                "message": "You must check the confirmation box stating you have read the Lumbee constitution and ordinances."
            }), 400

        full_name = form.full_name.data.strip()
        enrollment_id = form.enrollment_id.data.strip()
        email = form.email.data.strip()
        ip_address = request.headers.get('X-Forwarded-For', request.remote_addr)
        if ip_address and ',' in ip_address:
            ip_address = ip_address.split(',')[0].strip()

        # ── Duplicate check: log the rejected attempt for the admin report ──
        existing = Signer.query.filter_by(enrollment_id=enrollment_id).first()
        if existing:
            attempt = DuplicateAttempt(
                full_name=full_name,
                enrollment_id=enrollment_id,
                email=email,
                ip_address=ip_address
            )
            db.session.add(attempt)
            db.session.commit()
            return jsonify({"status": "error", "message": "This enrollment ID has already signed the petition."}), 400

        # ── Handle ID Upload File ──
        id_file = form.id_upload.data
        filename = secure_filename(id_file.filename)
        # Namespace by enrollment ID to avoid collisions between signers
        filename = f"{secure_filename(enrollment_id)}_{filename}"
        upload_folder = current_app.config.get('UPLOAD_FOLDER', os.path.join(current_app.root_path, 'uploads'))
        if not os.path.exists(upload_folder):
            os.makedirs(upload_folder)
        id_file.save(os.path.join(upload_folder, filename))

        signer = Signer(
            full_name=full_name,
            enrollment_id=enrollment_id,
            email=email,
            phone=form.phone.data.strip() if form.phone.data else None,
            id_upload_path=filename,
            ip_address=ip_address
        )

        try:
            db.session.add(signer)
            db.session.commit()
        except Exception:
            db.session.rollback()
            return jsonify({"status": "error", "message": "A database error occurred. Please try again."}), 500

        # Send the confirmation email receipt (non-blocking on failure)
        if signer.email:
            send_signature_receipt(signer)

        return jsonify({"status": "success", "message": "Thank you! Your signature has been recorded successfully. A confirmation email has been sent."})

    if form.is_submitted() and not form.validate():
        errors = [f"{field.label.text}: {', '.join(field.errors)}" for field in form if field.errors]
        return jsonify({"status": "error", "message": "Missing or invalid form fields.", "details": errors}), 400

    # ── GET RENDER ──
    settings = SiteSettings.query.first()
    ordinance_text = settings.ordinance_text if settings else ""
    committee_members = PetitionCommitteeMember.query.order_by(PetitionCommitteeMember.slot).all()
    recent_signers = Signer.query.order_by(Signer.timestamp.desc()).limit(10).all()
    total_signatures = Signer.query.count()
    goal = settings.target_signatures if settings else 1000

    # Document integrity now reflects the actual PDF, not the text field
    current_hash, hash_match, hash_timestamp, file_size_kb = get_pdf_integrity()

    start_date = (
        settings.petition_start_date.strftime('%B %d, %Y')
        if settings and settings.petition_start_date else "—"
    )

    external_links = {
        "vote_no": "https://votenodemandbetter.com",
        "lumbee_docs": "https://www.lumbeetribe.com/faqs-history",
        "ordinances": "https://www.lumbeetribe.com/tribal-proposed-ordinances"
    }

    home_summary = (
        "This petition acts as a direct community initiative to protect the integrity of our foundational documents. "
        "By verifying and logging structural changes via SHA-256 cryptographic hashes, we ensure transparency and member consent."
    )

    return render_template(
        'petition.html',
        form              = form,
        settings          = settings,
        ordinance_text    = ordinance_text,
        committee_members = committee_members,
        recent_signers    = recent_signers,
        total_signatures  = total_signatures,
        goal              = goal,
        current_hash      = current_hash,
        hash_match        = hash_match,
        hash_timestamp    = hash_timestamp,
        file_size_kb      = file_size_kb,
        start_date        = start_date,
        links             = external_links,
        home_summary      = home_summary
    )


# ── ORDINANCE VIEW & PRINT PATHWAYS ──────────────────────────────────
@main_bp.route('/ordinance')
def view_ordinance():
    current_hash, hash_match, hash_timestamp, file_size_kb = get_pdf_integrity()
    return render_template(
        'ordinance.html',
        current_hash    = current_hash,
        hash_match      = hash_match,
        hash_timestamp  = hash_timestamp,
        file_size_kb    = file_size_kb
    )


@main_bp.route('/petition/print')
def print_ordinance():
    current_hash, hash_match, hash_timestamp, file_size_kb = get_pdf_integrity()
    committee_members = PetitionCommitteeMember.query.order_by(PetitionCommitteeMember.slot).all()
    now = datetime.now(EASTERN)

    return render_template(
        'ordinance_print.html',
        committee_members = committee_members,
        current_hash       = current_hash,
        hash_match         = hash_match,
        hash_timestamp     = hash_timestamp,
        file_size_kb       = file_size_kb,
        hash_version       = f"{DocumentHashLog.query.count() or 1}",
        generated_date     = now.strftime('%B %d, %Y'),
        generated_time     = now.strftime('%I:%M %p %Z'),
        site_url           = request.host_url.rstrip('/')
    )


@main_bp.route('/petition/download-pdf')
def download_ordinance_pdf():
    pdf_dir = os.path.join(current_app.root_path, 'static', 'documents')
    try:
        return send_from_directory(pdf_dir, ORDINANCE_PDF_FILENAME, as_attachment=True)
    except Exception:
        flash("The official document PDF version is currently being generated. Please print or review via web text view.", "warning")
        return redirect(url_for('main_bp.sign_petition'))


# ── ADMIN AUTH ────────────────────────────────────────────────────────
@admin_bp.route('/admin/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        admin = AdminUser.query.filter_by(username=form.username.data.strip()).first()
        if admin and check_password_hash(admin.password_hash, form.password.data):
            login_user(admin)
            return redirect(url_for('admin_bp.dashboard'))
        flash("Invalid username or password.", "danger")
    return render_template('admin/login.html', form=form)


@admin_bp.route('/admin/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('admin_bp.login'))


# ── ADMIN DASHBOARD ───────────────────────────────────────────────────
@admin_bp.route('/admin/dashboard')
@login_required
def dashboard():
    settings = SiteSettings.query.first()
    signers = Signer.query.order_by(Signer.timestamp.desc()).all()
    duplicate_attempts = DuplicateAttempt.query.order_by(DuplicateAttempt.timestamp.desc()).all()
    committee = PetitionCommitteeMember.query.order_by(PetitionCommitteeMember.slot).all()
    hash_log = DocumentHashLog.query.order_by(DocumentHashLog.timestamp.desc()).limit(20).all()
    current_hash_entry = (
        DocumentHashLog.query
        .filter_by(is_current=True)
        .order_by(DocumentHashLog.timestamp.desc())
        .first()
    )
    _, pdf_hash_match, _, file_size_kb = get_pdf_integrity()

    upload_form = OrdinanceUploadForm()

    return render_template(
        'admin/dashboard.html',
        settings           = settings,
        signers             = signers,
        count               = len(signers),
        duplicate_attempts  = duplicate_attempts,
        committee           = committee,
        hash_log            = hash_log,
        current_hash        = current_hash_entry,
        pdf_hash_match      = pdf_hash_match,
        file_size_kb        = file_size_kb,
        upload_form         = upload_form
    )


# ── ADMIN: ORDINANCE PDF UPLOAD + HASH GENERATION ─────────────────────
@admin_bp.route('/admin/ordinance/upload', methods=['POST'])
@login_required
def upload_ordinance_pdf():
    form = OrdinanceUploadForm()

    if not form.validate_on_submit():
        errors = [f"{field.label.text}: {', '.join(field.errors)}" for field in form if field.errors]
        flash("Upload failed: " + "; ".join(errors), "danger")
        return redirect(url_for('admin_bp.dashboard'))

    pdf_file = form.pdf_file.data
    pdf_dir = os.path.join(current_app.root_path, 'static', 'documents')
    if not os.path.exists(pdf_dir):
        os.makedirs(pdf_dir)

    # Overwrite the canonical ordinance PDF with the newly uploaded version
    pdf_path = os.path.join(pdf_dir, ORDINANCE_PDF_FILENAME)
    pdf_file.save(pdf_path)

    # Hash the actual bytes just written to disk
    with open(pdf_path, 'rb') as f:
        pdf_bytes = f.read()

    note = form.change_note.data.strip() if form.change_note.data else "Ordinance PDF replaced via admin upload"
    changed_by = getattr(current_user, 'username', 'admin')
    log_document_hash(db, DocumentHashLog, pdf_bytes, changed_by=changed_by, note=note)

    # Best-effort text extraction so petition.html has a readable preview.
    # If PyMuPDF isn't available or extraction fails, the PDF/hash upload
    # above has already succeeded — this is purely a bonus.
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        extracted_text = "\n\n".join(page.get_text() for page in doc)
        doc.close()

        settings = SiteSettings.query.first()
        if settings and extracted_text.strip():
            settings.ordinance_text = extracted_text.strip()
            db.session.commit()
    except Exception as e:
        current_app.logger.info(f"Ordinance PDF text extraction skipped: {e}")

    flash("Ordinance PDF uploaded and new hash generated successfully.", "success")
    return redirect(url_for('admin_bp.dashboard'))


# ── ADMIN: COMMITTEE MEMBER EDITING ────────────────────────────────────
@admin_bp.route('/admin/committee/<int:slot>', methods=['POST'])
@login_required
def update_committee_member(slot):
    member = PetitionCommitteeMember.query.filter_by(slot=slot).first()
    if not member:
        member = PetitionCommitteeMember(slot=slot)
        db.session.add(member)

    member.full_name     = request.form.get('full_name', '').strip() or None
    member.enrollment_id = request.form.get('enrollment_id', '').strip() or None
    member.address       = request.form.get('address', '').strip() or None
    member.phone         = request.form.get('phone', '').strip() or None
    member.email         = request.form.get('email', '').strip() or None
    member.is_filled     = bool(member.full_name)
    member.assigned_at   = datetime.utcnow() if member.full_name else None

    db.session.commit()
    flash(f"Committee Member {slot} updated.", "success")
    return redirect(url_for('admin_bp.dashboard') + '#committee')


# ── ADMIN: DEDICATED SIGNERS + DUPLICATE ATTEMPTS REPORT ──────────────
@admin_bp.route('/admin/signers')
@login_required
def signers_report():
    signers = Signer.query.order_by(Signer.timestamp.desc()).all()
    duplicate_attempts = DuplicateAttempt.query.order_by(DuplicateAttempt.timestamp.desc()).all()
    return render_template('admin/signers.html', signers=signers, duplicate_attempts=duplicate_attempts)


# ── ADMIN: SITE SETTINGS ──────────────────────────────────────────────
@admin_bp.route('/admin/settings', methods=['GET', 'POST'])
@login_required
def settings():
    site_settings = SiteSettings.query.first()
    if not site_settings:
        site_settings = SiteSettings()
        db.session.add(site_settings)
        db.session.commit()

    form = SettingsForm(obj=site_settings)

    if form.validate_on_submit():
        site_settings.petition_title = form.petition_title.data.strip()
        site_settings.petition_text = form.petition_text.data.strip()
        site_settings.target_signatures = form.target_signatures.data
        site_settings.background_color = form.background_color.data.strip() if form.background_color.data else site_settings.background_color

        upload_folder = os.path.join(current_app.root_path, 'static', 'uploads')
        if not os.path.exists(upload_folder):
            os.makedirs(upload_folder)

        if form.header_image.data:
            fname = secure_filename(form.header_image.data.filename)
            form.header_image.data.save(os.path.join(upload_folder, fname))
            site_settings.header_image = fname

        if form.background_image.data:
            fname = secure_filename(form.background_image.data.filename)
            form.background_image.data.save(os.path.join(upload_folder, fname))
            site_settings.background_image = fname

        db.session.commit()
        flash("Settings saved.", "success")
        return redirect(url_for('admin_bp.settings'))

    return render_template('admin/settings.html', form=form, settings=site_settings)

