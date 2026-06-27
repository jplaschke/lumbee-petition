from flask import (Blueprint, render_template, request, jsonify,
                   redirect, url_for, flash, current_app, session)
from werkzeug.utils import secure_filename
from datetime import datetime, date
from app import db
from app.models import Signer, DuplicateAttempt, AuditLog, SiteSettings
import os, hashlib, json

main = Blueprint("main", __name__)

def allowed_file(filename):
    return ("." in filename and
            filename.rsplit(".", 1)[1].lower()
            in current_app.config["ALLOWED_EXTENSIONS"])

def get_ip():
    xff = request.headers.get("X-Forwarded-For")
    return xff.split(",")[0].strip() if xff else request.remote_addr

def audit(event, enrollment_id, ip, details, severity="INFO"):
    log = AuditLog(event_type=event, enrollment_id=enrollment_id,
                   ip_address=ip, details=json.dumps(details), severity=severity)
    db.session.add(log)
    db.session.commit()

def site():
    return {
        "active_bg":            SiteSettings.get("active_bg",            "bg_default.jpg"),
        "tribe_logo":           SiteSettings.get("tribe_logo",           "logo.png"),
        "petition_title":       SiteSettings.get("petition_title",       "Lumbee Tribe Petition"),
        "petition_description": SiteSettings.get("petition_description", ""),
        "primary_color":        SiteSettings.get("primary_color",        "#1a237e"),
        "secondary_color":      SiteSettings.get("secondary_color",      "#b71c1c"),
        "accent_color":         SiteSettings.get("accent_color",         "#f9a825"),
        "hero_overlay_opacity": SiteSettings.get("hero_overlay_opacity", "0.65"),
    }

def progress():
    count  = Signer.query.count()
    target = current_app.config["TARGET_SIGNATURES"]
    pct    = round((count / target) * 100, 1) if target else 0
    return {"current": count, "target": target,
            "percent": min(pct, 100), "met": count >= target}

@main.route("/")
def index():
    return render_template("index.html", s=site(), p=progress())

@main.route("/sign", methods=["GET", "POST"])
def sign():
    s = site(); p = progress()
    if request.method == "GET":
        return render_template("sign.html", s=s, p=p, errors=[])
    ip     = get_ip()
    name   = request.form.get("full_name",      "").strip()
    eid    = request.form.get("enrollment_id",  "").strip().upper()
    email  = request.form.get("email",          "").strip().lower()
    phone  = request.form.get("phone",          "").strip()
    expiry = request.form.get("id_card_expiry", "").strip()
    f      = request.files.get("id_card")
    errors = []
    if not all([name, eid, email, expiry, f and f.filename]):
        errors.append("All required fields must be filled in.")
    try:
        exp_date = datetime.strptime(expiry, "%Y-%m-%d").date()
        if exp_date < date.today():
            errors.append("Your Member ID card is expired.")
    except ValueError:
        errors.append("Invalid expiry date.")
        exp_date = None
    if f and not allowed_file(f.filename):
        errors.append("Invalid file type. Use JPG, PNG, or PDF.")
    if errors:
        return render_template("sign.html", s=s, p=p, errors=errors)
    if Signer.query.filter_by(enrollment_id=eid).first():
        dup = DuplicateAttempt(
            attempted_enrollment_id=eid, attempted_name=name,
            attempted_email=email, ip_address=ip,
            details=json.dumps({"ts": datetime.utcnow().isoformat()}))
        db.session.add(dup); db.session.commit()
        audit("DUPLICATE_ATTEMPT", eid, ip, {"name": name}, "WARNING")
        errors.append("This Enrollment ID has already signed this petition.")
        return render_template("sign.html", s=s, p=p, errors=errors)
    filename = secure_filename(f"{eid}_{f.filename}")
    f.save(os.path.join(current_app.config["UPLOAD_FOLDER"], filename))
    sig_hash = hashlib.sha256(
        f"{name}{eid}{datetime.utcnow().isoformat()}".encode()).hexdigest()
    signer = Signer(full_name=name, enrollment_id=eid, email=email, phone=phone,
                    id_card_filename=filename, id_card_expiry=exp_date,
                    ip_address=ip, signature_hash=sig_hash)
    db.session.add(signer); db.session.commit()
    audit("SIGNATURE", eid, ip, {"name": name, "hash": sig_hash})
    p2 = progress()
    if p2["met"]:
        audit("THRESHOLD_REACHED", eid, ip, {"total": p2["current"]})
    return redirect(url_for("main.success", name=name.split()[0]))

@main.route("/success")
def success():
    return render_template("success.html", s=site(), p=progress(),
                           name=request.args.get("name", "Member"))

@main.route("/api/progress")
def api_progress():
    return jsonify(progress())

def admin_only(f):
    from functools import wraps
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("main.login"))
        return f(*args, **kwargs)
    return wrapper

@main.route("/admin/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u  = request.form.get("username", "")
        pw = request.form.get("password", "")
        if (u == current_app.config["ADMIN_USERNAME"] and
                pw == current_app.config["ADMIN_PASSWORD"]):
            session["admin"] = True
            return redirect(url_for("main.admin"))
        flash("Invalid credentials.", "error")
    return render_template("admin_login.html", s=site())

@main.route("/admin/logout")
def logout():
    session.pop("admin", None)
    return redirect(url_for("main.index"))

@main.route("/admin")
@admin_only
def admin():
    s       = site(); p = progress()
    signers = Signer.query.order_by(Signer.timestamp.desc()).limit(100).all()
    dups    = DuplicateAttempt.query.order_by(
                  DuplicateAttempt.timestamp.desc()).limit(50).all()
    logs    = AuditLog.query.order_by(AuditLog.timestamp.desc()).limit(100).all()
    return render_template("admin.html", s=s, p=p,
                           signers=signers, dups=dups, logs=logs)

@main.route("/admin/settings", methods=["POST"])
@admin_only
def save_settings():
    for key in ["petition_title","petition_description","primary_color",
                "secondary_color","accent_color","hero_overlay_opacity","active_bg"]:
        val = request.form.get(key)
        if val is not None:
            SiteSettings.set(key, val)
    img_dir = "app/static/images"
    os.makedirs(img_dir, exist_ok=True)
    for field, setting in [("tribe_logo","tribe_logo"),("new_bg","active_bg")]:
        uploaded = request.files.get(field)
        if uploaded and uploaded.filename and allowed_file(uploaded.filename):
            fname = secure_filename(uploaded.filename)
            uploaded.save(os.path.join(img_dir, fname))
            if field == "tribe_logo":
                SiteSettings.set("tribe_logo", fname)
            else:
                SiteSettings.set("active_bg", fname)
    flash("Settings saved!", "success")
    return redirect(url_for("main.admin"))
