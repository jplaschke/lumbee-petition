from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify, current_app
from flask_login import login_user, logout_user, login_required
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from app import db
from app.models import Signer, AdminUser, SiteSettings
from app.forms import SignatureForm, LoginForm, SettingsForm
from datetime import datetime
import os
from sqlalchemy import func
import base64
import logging
# Assuming SignatureForm is imported from your forms module

# Cryptography primitives
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import hashes, serialization

# Configure logging to output to Render console
logger = logging.getLogger(__name__)

# The static, formal text of the petition the board evaluates
PETITION_MANIFESTO = "Official Petition to the Lumbee Election Board regarding..."

main_bp  = Blueprint('main_bp',  __name__)
admin_bp = Blueprint('admin_bp', __name__)

def get_settings():
    s = SiteSettings.query.first()
    if not s:
        s = SiteSettings()
        db.session.add(s)
        db.session.commit()
    return s

def save_file(file_obj, folder='uploads'):
    upload_dir = os.path.join(current_app.root_path, 'static', folder)
    os.makedirs(upload_dir, exist_ok=True)
    filename = secure_filename(file_obj.filename)
    file_obj.save(os.path.join(upload_dir, filename))
    return filename

@main_bp.route('/')
def index():
    settings = get_settings()

    count = Signer.query.filter_by(verified=True).count()

    target = settings.target_signatures or 1
    percent = min(int((count / target) * 100), 100)

    return render_template('index.html', settings=settings, count=count, percent=percent)

@main_bp.route('/sign', methods=['GET', 'POST'])
def sign():
    settings = get_settings()
    form = SignatureForm()
    
    if form.validate_on_submit():
        # Check for duplicate signatures
        if Signer.query.filter_by(enrollment_id=form.enrollment_id.data.strip()).first():
            flash('This Enrollment ID has already signed.', 'danger')
            return redirect(url_for('main_bp.sign'))
            
        # Handle the mandatory file upload (Guaranteed to exist thanks to FileRequired!)
        id_filename = None
        if form.id_upload.data and form.id_upload.data.filename:
            id_filename = save_file(form.id_upload.data)
        
        # 1. Extract clean string inputs
        from datetime import datetime, timezone, timedelta
        
        full_name = form.full_name.data.strip()
        enrollment_id = form.enrollment_id.data.strip()
        email = form.email.data.strip() if form.email.data else None
        phone = form.phone.data.strip() if form.phone.data else None
        
        # FORCED EASTERN TIME OFFSET:
        # Calculates explicit Eastern Time (UTC-5/UTC-4 depending on seasonality) 
        # By querying the system shift dynamically:
        local_now = datetime.now()
        
        # Check if we are currently in Daylight Saving Time (March - November)
        # 0 = Monday, 6 = Sunday. This dynamically checks for standard North American changes.
        is_dst = False
        if 3 < local_now.month < 11:
            is_dst = True
        elif local_now.month == 3:
            # Starts second Sunday of March
            dst_start = datetime(local_now.year, 3, 8)
            dst_start += timedelta(days=(6 - dst_start.weekday()))
            if local_now >= dst_start:
                is_dst = True
        elif local_now.month == 11:
            # Ends first Sunday of November
            dst_end = datetime(local_now.year, 11, 1)
            dst_end += timedelta(days=(6 - dst_end.weekday()))
            if local_now < dst_end:
                is_dst = True

        offset_hours = -4 if is_dst else -5
        eastern_tz = timezone(timedelta(hours=offset_hours))
        
        # Locks both the real Eastern clock time and the explicit timezone indicator string
        timestamp = datetime.now(eastern_tz)

        # 2. Extract proxy-safe Client IP on Render
        if request.headers.getlist("X-Forwarded-For"):
            ip_address = request.headers.getlist("X-Forwarded-For")[0].split(',')[0].strip()
        else:
            ip_address = request.remote_addr or "Unknown"

        # 3. Log data to the live terminal console for auditing and tracking
        logger.info("=== NEW PETITION SIGNATURE ATTEMPT ===")
        logger.info(f"Name: {full_name} | ID: {enrollment_id}")
        logger.info(f"Attached ID File: {id_filename}")
        logger.info(f"Verified Client IP: {ip_address}")
        logger.info(f"Timestamp: {timestamp.isoformat()}")

        try:
            # 4. Generate unique RSA keys for asymmetric validation
            private_key = rsa.generate_private_key(
                public_exponent=65537,
                key_size=2048
            )
            public_key = private_key.public_key()
            
            # Serialize Public Key to PEM format text for DB storage
            pem_public_key = public_key.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo
            ).decode('utf-8')

            # 5. Build the immutable legal manifest statement (Explicitly binding the ID file!)
            signature_manifest = (
                f"Petition Manifest: {PETITION_MANIFESTO}\n"
                f"Signer Legal Name: {full_name}\n"
                f"Enrollment ID: {enrollment_id}\n"
                f"Verified ID Attachment: {id_filename}\n"
                f"Timestamp ISO: {timestamp.isoformat()}\n"
                f"Network IP Origin: {ip_address}"
            )
            
            # 6. Cryptographically seal the manifest block using standard PKCS1v15 padding
            message_bytes = signature_manifest.encode('utf-8')
            raw_signature = private_key.sign(
                message_bytes,
                padding.PKCS1v15(),  # Switched to standard PKCS1v15 to fix version mismatches
                hashes.SHA256()
            )
            # Encode binary data to clean, web-safe Base64 text
            b64_signature = base64.b64encode(raw_signature).decode('utf-8')
            
            # 7. Build and populate the database record
            signer = Signer(
                full_name=full_name,
                enrollment_id=enrollment_id,
                email=email,
                phone=phone,
                ip_address=ip_address,
                id_filename=id_filename,
                timestamp=timestamp,
                # New cryptographic audit columns
                digital_signature=b64_signature,
                public_key=pem_public_key,
                manifest_data=signature_manifest
            )
            
            signer.set_hash()  # Runs your existing application specific hashing
            db.session.add(signer)
            db.session.commit()
            
            logger.info(f"=== SECURE AUDIT SIGNATURE RECODED FOR ID: {enrollment_id} ===")
            flash('Thank you for signing! Your legal digital signature has been sealed.', 'success')
            return redirect(url_for('main_bp.thank_you'))
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"CRITICAL CRYPTO ERROR: {str(e)}")
            flash('An error occurred cryptographically sealing your signature. Please try again.', 'danger')
            return redirect(url_for('main_bp.sign'))
            
    return render_template('sign.html', form=form, settings=settings)


@main_bp.route('/thank-you')
def thank_you():
    settings = get_settings()
    count    = Signer.query.filter_by(verified=True).count()
    return render_template('thank_you.html', settings=settings, count=count)

@main_bp.route('/progress')
def progress():
    settings = get_settings()
    count    = Signer.query.filter_by(verified=True).count()
    percent  = min(int((count / settings.target_signatures) * 100), 100)
    return jsonify({'count': count, 'target': settings.target_signatures, 'percent': percent})

@main_bp.route('/ordinance')
def view_ordinance():
    """Render the styled ordinance viewer page"""
    return render_template('ordinance.html')

@admin_bp.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()

    if request.method == 'POST':
        form.process(request.form)
        username = form.username.data or request.form.get('username')
        password = form.password.data or request.form.get('password')

        # 🔍 THE ULTIMATE TRUTH LOG
        print("--- DISCOVERING ACTUAL DB CONTENT ---", flush=True)
        any_user = AdminUser.query.first()
        if any_user:
            print(f"The actual username stored in your DB is: '{any_user.username}'", flush=True)
        else:
            print("The AdminUser table is completely EMPTY!", flush=True)
        print("-------------------------------------", flush=True)

        user = AdminUser.query.filter(func.lower(AdminUser.username) == func.lower(username)).first()
        
        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('admin_bp.dashboard'))

        flash('Invalid credentials.', 'danger')
        return redirect(request.referrer or url_for('main.index'))

    return render_template('admin/login.html', form=form)


@admin_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('admin_bp.login'))

@admin_bp.route('/dashboard')
@login_required
def dashboard():
    settings = get_settings()
    count    = Signer.query.filter_by(verified=True).count()
    signers  = Signer.query.order_by(Signer.timestamp.desc()).limit(50).all()
    return render_template('admin/dashboard.html', settings=settings, count=count, signers=signers)

@admin_bp.route('/settings', methods=['GET','POST'])
@login_required
def settings():
    s    = get_settings()
    form = SettingsForm(obj=s)
    if form.validate_on_submit():
        s.petition_title    = form.petition_title.data
        s.petition_text     = form.petition_text.data
        s.target_signatures = form.target_signatures.data
        s.background_color  = form.background_color.data
        if form.header_image.data and form.header_image.data.filename:
            s.header_image = save_file(form.header_image.data)
        if form.background_image.data and form.background_image.data.filename:
            s.background_image = save_file(form.background_image.data)
        db.session.commit()
        flash('Settings saved!', 'success')
        return redirect(url_for('admin_bp.settings'))
    return render_template('admin/settings.html', form=form, settings=s)

@admin_bp.route('/signers')
@login_required
def signers():
    all_signers = Signer.query.order_by(Signer.timestamp.desc()).all()
    return render_template('admin/signers.html', signers=all_signers)

@admin_bp.route('/setup')
def setup():
    username = os.environ.get('ADMIN_USERNAME', 'admin')
    password = os.environ.get('ADMIN_PASSWORD', 'changeme123')
    if not AdminUser.query.filter_by(username=username).first():
        user = AdminUser(username=username, password=generate_password_hash(password))
        db.session.add(user)
        db.session.commit()
        return f'Admin {username} created!'
    return 'Admin already exists.'

