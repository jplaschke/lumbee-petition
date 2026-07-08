import os
from flask import Blueprint, render_template, redirect, url_for, flash, current_app, jsonify
from werkzeug.utils import secure_filename
from app import db
from app.models import SiteSettings, PetitionCommitteeMember, Signer, DocumentHashLog
from app.forms import SignatureForm
# 1. FIXED: Removed 'verify_content_matches_hash' from the import list
from app.utils import compute_sha256, get_current_hash

main_bp = Blueprint('main_bp', __name__)

@main_bp.route('/petition', methods=['GET', 'POST'])
def petition():
    form = SignatureForm()

    # Handle Form Submission via AJAX/Fetch inside Modal
    if form.validate_on_submit():
        from flask import request
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
    settings          = SiteSettings.query.first()
    ordinance_text    = settings.ordinance_text if settings else ""
    committee_members = PetitionCommitteeMember.query.order_by(PetitionCommitteeMember.slot).all()
    recent_signers    = Signer.query.order_by(Signer.signed_at.desc()).limit(10).all()
    total_signatures  = Signer.query.count()
    goal              = settings.target_signatures if settings else 1000
    current_hash      = compute_sha256(ordinance_text) if ordinance_text else "—"

    # 2. FIXED: Changed the verification logic to use a direct string comparison 
    # instead of calling the missing utility function.
    _latest    = get_current_hash(DocumentHashLog) if 'DocumentHashLog' in globals() else None
    
    hash_match = False
    if _latest and ordinance_text:
        # Direct string comparison between your calculated hash and the database log hash
        hash_match = (current_hash == _latest.get("sha256_hash"))

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

