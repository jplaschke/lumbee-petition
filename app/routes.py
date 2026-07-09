import os
from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, flash, current_app, jsonify, send_from_directory, request
from werkzeug.utils import secure_filename
from app import db
from app.models import SiteSettings, PetitionCommitteeMember, Signer, DocumentHashLog
from app.forms import SignatureForm
from app.utils.hash_utils import compute_sha256, compute_sha256_from_file, get_current_hash, EASTERN

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

@main_bp.route('/', methods=['GET'])
def index():
    # This completely satisfies url_for('main_bp.index')
    return redirect(url_for('main_bp.sign_petition'))

# ── FIXED ROOT ROUTE ─────────────────────────────────────────────────
@main_bp.route('/petition', methods=['GET', 'POST'])
def sign_petition():
    form = SignatureForm()

    # Handle Form Submission via AJAX/Fetch inside Modal
    if form.validate_on_submit():
        read_confirmation = request.form.get('read_ordinance_check')
        
        if not read_confirmation:
            return jsonify({
                "status": "error", 
                "message": "You must check the confirmation box stating you have read the Lumbee constitution and ordinances."
            }), 400

        enrollment_id = form.enrollment_id.data.strip()
        
        existing = Signer.query.filter_by(enrollment_id=enrollment_id).first()
        if existing:
            return jsonify({"status": "error", "message": "This enrollment ID has already signed the petition."}), 400

        # Handle ID Upload File
        id_file = form.id_upload.data
        filename = secure_filename(id_file.filename)
        upload_folder = current_app.config.get('UPLOAD_FOLDER', 'uploads')
        if not os.path.exists(upload_folder):
            os.makedirs(upload_folder)
        id_file.save(os.path.join(upload_folder, filename))

        signer = Signer(
            full_name=form.full_name.data.strip(),
            enrollment_id=enrollment_id,
            email=form.email.data.strip(),
            phone=form.phone.data.strip() if form.phone.data else None,
            id_upload_path=filename
        )
        
        try:
            db.session.add(signer)
            db.session.commit()
            return jsonify({"status": "success", "message": "Thank you! Your signature has been recorded successfully."})
        except Exception as e:
            db.session.rollback()
            return jsonify({"status": "error", "message": "A database error occurred. Please try again."}), 500

    # Handle Validation Structural Errors 
    if form.is_submitted() and not form.validate():
        errors = [f"{field.label.text}: {', '.join(field.errors)}" for field in form if field.errors]
        return jsonify({"status": "error", "message": "Missing or invalid form fields.", "details": errors}), 400

    # GET RENDER BLOCKS
    settings = SiteSettings.query.first()
    ordinance_text = settings.ordinance_text if settings else ""
    committee_members = PetitionCommitteeMember.query.order_by(PetitionCommitteeMember.slot).all()
    recent_signers = Signer.query.order_by(Signer.signed_at.desc()).limit(10).all()
    total_signatures = Signer.query.count()
    goal = settings.target_signatures if settings else 1000
    
    # Generate current live text hash
    current_hash = compute_sha256(ordinance_text) if ordinance_text else "—"

    # FIRST-PRINCIPLES DEFENSIVE HASH MATCHING
    hash_match = False
    try:
        # Fetch the latest structural log entry safely directly from the DB model
        latest_log = DocumentHashLog.query.order_by(DocumentHashLog.id.desc()).first()
        if latest_log and ordinance_text:
            # Check for object attribute or dictionary key safely using fallbacks
            logged_hash = getattr(latest_log, 'sha256_hash', None) or latest_log.get('sha256_hash')
            hash_match = (current_hash == logged_hash)
    except Exception:
        # Fallback gracefully instead of throwing a 500 internal crash if log structures differ
        hash_match = False

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

# ── ADMIN PATHWAYS ───────────────────────────────────────────────────
@admin_bp.route('/admin/dashboard')
def dashboard():
    settings = SiteSettings.query.first()
    signers = Signer.query.order_by(Signer.signed_at.desc()).all()
    return render_template('admin/dashboard.html', settings=settings, signers=signers)a

