from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify, current_app
from flask_login import login_user, logout_user, login_required
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from app import db
from app.models import Signer, AdminUser, SiteSettings
from app.forms import SignatureForm, LoginForm, SettingsForm
from datetime import datetime
import os

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
    count    = Signer.query.filter_by(verified=True).count()
    percent  = min(int((count / settings.target_signatures) * 100), 100)
    return render_template('index.html', settings=settings, count=count, percent=percent)

@main_bp.route('/sign', methods=['GET','POST'])
def sign():
    settings = get_settings()
    form     = SignatureForm()
    if form.validate_on_submit():
        if Signer.query.filter_by(enrollment_id=form.enrollment_id.data.strip()).first():
            flash('This Enrollment ID has already signed.', 'danger')
            return redirect(url_for('main_bp.sign'))
        id_filename = None
        if form.id_upload.data and form.id_upload.data.filename:
            id_filename = save_file(form.id_upload.data)
        signer = Signer(
            full_name=form.full_name.data.strip(),
            enrollment_id=form.enrollment_id.data.strip(),
            email=form.email.data.strip(),
            phone=form.phone.data.strip() if form.phone.data else None,
            ip_address=request.remote_addr,
            id_filename=id_filename,
            timestamp=datetime.utcnow(),
        )
        signer.set_hash()
        db.session.add(signer)
        db.session.commit()
        flash('Thank you for signing!', 'success')
        return redirect(url_for('main_bp.thank_you'))
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

@admin_bp.route('/login', methods=['GET','POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        user = AdminUser.query.filter_by(username=form.username.data).first()
        if user and check_password_hash(user.password, form.password.data):
            login_user(user)
            return redirect(url_for('admin_bp.dashboard'))
        flash('Invalid credentials.', 'danger')
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

