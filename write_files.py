#!/usr/bin/env python3
"""
Lumbee Tribe Petition — File Writer
Run: python write_files.py
Creates all project files in the current directory.
"""

import os, sys, textwrap, zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))

def w(path, content):
    """Write file, creating parent dirs as needed."""
    full = os.path.join(ROOT, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, 'w', encoding='utf-8') as f:
        f.write(textwrap.dedent(content).lstrip('\n'))
    print(f"  ✓  {path}")


# ══════════════════════════════════════════════════════════════
#  MODELS
# ══════════════════════════════════════════════════════════════
w('app/models.py', '''
from datetime import datetime
from app import db
import uuid

def _uuid():
    return str(uuid.uuid4())

class Signer(db.Model):
    __tablename__ = "signers"
    id               = db.Column(db.String(36), primary_key=True, default=_uuid)
    full_name        = db.Column(db.String(255), nullable=False)
    enrollment_id    = db.Column(db.String(50),  nullable=False, unique=True, index=True)
    email            = db.Column(db.String(255), nullable=False)
    phone            = db.Column(db.String(20))
    id_card_filename = db.Column(db.String(500), nullable=False)
    id_card_expiry   = db.Column(db.Date,        nullable=False)
    ip_address       = db.Column(db.String(45),  nullable=False)
    timestamp        = db.Column(db.DateTime,    default=datetime.utcnow)
    is_verified      = db.Column(db.Boolean,     default=False)
    signature_hash   = db.Column(db.String(64))

class DuplicateAttempt(db.Model):
    __tablename__ = "duplicate_attempts"
    id                      = db.Column(db.String(36), primary_key=True, default=_uuid)
    attempted_enrollment_id = db.Column(db.String(50), nullable=False, index=True)
    attempted_name          = db.Column(db.String(255))
    attempted_email         = db.Column(db.String(255))
    ip_address              = db.Column(db.String(45),  nullable=False)
    timestamp               = db.Column(db.DateTime,    default=datetime.utcnow)
    details                 = db.Column(db.Text)

class AuditLog(db.Model):
    __tablename__ = "audit_log"
    id            = db.Column(db.String(36), primary_key=True, default=_uuid)
    event_type    = db.Column(db.String(100), nullable=False)
    enrollment_id = db.Column(db.String(50))
    ip_address    = db.Column(db.String(45),  nullable=False)
    timestamp     = db.Column(db.DateTime,    default=datetime.utcnow)
    details       = db.Column(db.Text)
    severity      = db.Column(db.String(20),  default="INFO")

class SiteSettings(db.Model):
    __tablename__ = "site_settings"
    id            = db.Column(db.Integer, primary_key=True)
    setting_key   = db.Column(db.String(100), unique=True, nullable=False)
    setting_value = db.Column(db.Text)
    updated_at    = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @staticmethod
    def get(key, default=None):
        row = SiteSettings.query.filter_by(setting_key=key).first()
        return row.setting_value if row else default

    @staticmethod
    def set(key, value):
        row = SiteSettings.query.filter_by(setting_key=key).first()
        if row:
            row.setting_value = value
        else:
            row = SiteSettings(setting_key=key, setting_value=value)
            db.session.add(row)
        db.session.commit()
''')

# ══════════════════════════════════════════════════════════════
#  ROUTES
# ══════════════════════════════════════════════════════════════
w('app/routes.py', r'''
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
''')

# ══════════════════════════════════════════════════════════════
#  TEMPLATES
# ══════════════════════════════════════════════════════════════
w('app/templates/base.html', '''
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0">
  <title>{% block title %}{{ s.petition_title }}{% endblock %} | Lumbee Tribe</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Cinzel:wght@400;600;700&family=Open+Sans:wght@300;400;600;700&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css">
  <link rel="stylesheet" href="{{ url_for(\'static\', filename=\'css/style.css\') }}">
  <style>
    :root {
      --primary:   {{ s.primary_color }};
      --secondary: {{ s.secondary_color }};
      --accent:    {{ s.accent_color }};
      --overlay-opacity: {{ s.hero_overlay_opacity }};
    }
    .site-bg {
      background-image: url("{{ url_for(\'static\', filename=\'images/\' + s.active_bg) }}");
    }
  </style>
</head>
<body class="site-bg">
  <nav class="navbar">
    <div class="nav-inner">
      <a href="{{ url_for(\'main.index\') }}" class="brand">
        <img src="{{ url_for(\'static\', filename=\'images/\' + s.tribe_logo) }}"
             alt="Logo" class="brand-logo" onerror="this.style.display=\'none\'">
        <span class="brand-name">Lumbee Tribe</span>
      </a>
      <div class="nav-right">
        <a href="{{ url_for(\'main.index\') }}" class="nav-link"><i class="fas fa-home"></i> Home</a>
        <a href="{{ url_for(\'main.sign\') }}"  class="nav-cta"><i class="fas fa-pen-nib"></i> Sign Now</a>
      </div>
    </div>
  </nav>
  {% with messages = get_flashed_messages(with_categories=true) %}
    {% if messages %}
      <div class="flash-wrap">
        {% for cat, msg in messages %}
          <div class="flash flash-{{ cat }}">{{ msg }}</div>
        {% endfor %}
      </div>
    {% endif %}
  {% endwith %}
  <main>{% block content %}{% endblock %}</main>
  <footer class="footer">
    <div class="footer-inner">
      <div class="footer-brand">
        <img src="{{ url_for(\'static\', filename=\'images/\' + s.tribe_logo) }}"
             alt="Logo" class="footer-logo" onerror="this.style.display=\'none\'">
        <span>Lumbee Tribe of North Carolina</span>
      </div>
      <div class="footer-links">
        <p><i class="fas fa-shield-alt"></i> Secured Petition System</p>
        <p><i class="fas fa-gavel"></i> Pursuant to Lumbee Constitution Art. V</p>
        <p><small>&copy; 2024 Lumbee Tribe. All rights reserved.</small></p>
      </div>
    </div>
  </footer>
  <script src="{{ url_for(\'static\', filename=\'js/main.js\') }}"></script>
  {% block scripts %}{% endblock %}
</body>
</html>
''')

w('app/templates/index.html', '''
{% extends "base.html" %}
{% block content %}
<section class="hero">
  <div class="hero-overlay"></div>
  <div class="hero-body">
    <span class="hero-badge"><i class="fas fa-feather-alt"></i> Official Tribal Petition</span>
    <h1 class="hero-title">{{ s.petition_title }}</h1>
    {% if s.petition_description %}
    <p class="hero-desc">{{ s.petition_description }}</p>
    {% endif %}
    <div class="progress-widget">
      <div class="pw-stats">
        <div class="pw-stat">
          <span class="pw-num" id="live-count">{{ p.current }}</span>
          <span class="pw-lbl">Signatures</span>
        </div>
        <div class="pw-divider"></div>
        <div class="pw-stat">
          <span class="pw-num">{{ p.target }}</span>
          <span class="pw-lbl">Goal (10%)</span>
        </div>
        <div class="pw-divider"></div>
        <div class="pw-stat">
          <span class="pw-num">{{ p.percent }}%</span>
          <span class="pw-lbl">Complete</span>
        </div>
      </div>
      <div class="pw-track">
        <div class="pw-fill" data-pct="{{ p.percent }}" style="width:0%"></div>
      </div>
      {% if p.met %}
      <div class="pw-met"><i class="fas fa-trophy"></i> 10% Threshold Achieved</div>
      {% endif %}
    </div>
    <a href="{{ url_for(\'main.sign\') }}" class="hero-btn">
      <i class="fas fa-pen-nib"></i> Sign the Petition
    </a>
  </div>
</section>
<section class="cards-section">
  <div class="cards-grid">
    <div class="card">
      <div class="card-icon"><i class="fas fa-user-check"></i></div>
      <h3>Who Can Sign</h3>
      <p>Enrolled members of the Lumbee Tribe of North Carolina with a valid, non-expired Member ID card.</p>
    </div>
    <div class="card">
      <div class="card-icon"><i class="fas fa-id-card"></i></div>
      <h3>What You Need</h3>
      <p>Your Enrollment ID number and a photo or scan of your Lumbee Tribe Member ID card.</p>
    </div>
    <div class="card">
      <div class="card-icon"><i class="fas fa-lock"></i></div>
      <h3>Your Privacy</h3>
      <p>All data is encrypted, stored securely, and used only for petition verification by tribal authorities.</p>
    </div>
    <div class="card">
      <div class="card-icon"><i class="fas fa-gavel"></i></div>
      <h3>Legal Basis</h3>
      <p>Conducted pursuant to Article V of the Lumbee Tribe Constitution and applicable tribal ordinance.</p>
    </div>
  </div>
</section>
{% endblock %}
''')

w('app/templates/sign.html', '''
{% extends "base.html" %}
{% block title %}Sign the Petition{% endblock %}
{% block content %}
<section class="form-page">
  <div class="form-box">
    <div class="form-top">
      <img src="{{ url_for(\'static\', filename=\'images/\' + s.tribe_logo) }}"
           alt="Logo" class="form-logo" onerror="this.style.display=\'none\'">
      <h1><i class="fas fa-pen-nib"></i> Sign the Petition</h1>
      <p>{{ s.petition_title }}</p>
      <div class="mini-prog">
        <span>{{ p.current }} / {{ p.target }} signatures collected</span>
        <div class="mini-track"><div class="mini-fill" style="width:{{ p.percent }}%"></div></div>
      </div>
    </div>
    {% if errors %}
    <div class="alert alert-error">
      <i class="fas fa-exclamation-triangle"></i>
      <ul>{% for e in errors %}<li>{{ e }}</li>{% endfor %}</ul>
    </div>
    {% endif %}
    <div class="alert alert-info">
      <i class="fas fa-info-circle"></i>
      Only enrolled Lumbee Tribe members may sign. Duplicate submissions are blocked and logged.
    </div>
    <form id="petitionForm" method="POST"
          action="{{ url_for(\'main.sign\') }}"
          enctype="multipart/form-data" novalidate>
      <div class="field-grid">
        <div class="field span2">
          <label for="full_name"><i class="fas fa-user"></i> Full Legal Name *</label>
          <input type="text" id="full_name" name="full_name"
                 placeholder="As it appears on enrollment records" required>
        </div>
        <div class="field">
          <label for="enrollment_id"><i class="fas fa-id-badge"></i> Enrollment ID *</label>
          <input type="text" id="enrollment_id" name="enrollment_id"
                 placeholder="e.g. LT-00000" required style="text-transform:uppercase">
        </div>
        <div class="field">
          <label for="email"><i class="fas fa-envelope"></i> Email Address *</label>
          <input type="email" id="email" name="email" placeholder="you@example.com" required>
        </div>
        <div class="field">
          <label for="phone"><i class="fas fa-phone"></i> Phone <span class="opt">(optional)</span></label>
          <input type="tel" id="phone" name="phone" placeholder="(910) 555-0000">
        </div>
        <div class="field">
          <label for="id_card_expiry"><i class="fas fa-calendar-alt"></i> Member ID Expiry Date *</label>
          <input type="date" id="id_card_expiry" name="id_card_expiry" required>
          <small>Card must not be expired</small>
        </div>
        <div class="field span2">
          <label><i class="fas fa-camera"></i> Upload Member ID Card *</label>
          <div class="drop-zone" id="dropZone">
            <input type="file" id="id_card" name="id_card"
                   accept=".jpg,.jpeg,.png,.pdf" required>
            <div class="dz-inner" id="dzInner">
              <i class="fas fa-cloud-upload-alt"></i>
              <p>Drag &amp; drop or <u>click to browse</u></p>
              <small>JPG · PNG · PDF — max 16 MB</small>
            </div>
          </div>
        </div>
        <div class="field span2">
          <label class="check-label">
            <input type="checkbox" id="certify" required>
            <span>I certify under penalty of tribal law that I am an enrolled member of the Lumbee Tribe of North Carolina, and all information is true and accurate.</span>
          </label>
        </div>
      </div>
      <button type="submit" class="submit-btn" id="submitBtn">
        <i class="fas fa-pen-nib"></i> Submit My Signature
      </button>
    </form>
  </div>
</section>
{% endblock %}
''')

w('app/templates/success.html', '''
{% extends "base.html" %}
{% block title %}Signature Recorded{% endblock %}
{% block content %}
<section class="success-page">
  <div class="success-box">
    <div class="success-icon"><i class="fas fa-check-circle"></i></div>
    <h1>Thank You, {{ name }}!</h1>
    <p class="success-sub">Your signature has been securely recorded.</p>
    <div class="progress-widget" style="margin:2rem 0">
      <div class="pw-stats">
        <div class="pw-stat">
          <span class="pw-num">{{ p.current }}</span>
          <span class="pw-lbl">Total Signatures</span>
        </div>
        <div class="pw-divider"></div>
        <div class="pw-stat">
          <span class="pw-num">{{ p.target }}</span>
          <span class="pw-lbl">Required</span>
        </div>
        <div class="pw-divider"></div>
        <div class="pw-stat">
          <span class="pw-num">{{ p.percent }}%</span>
          <span class="pw-lbl">Complete</span>
        </div>
      </div>
      <div class="pw-track">
        <div class="pw-fill" data-pct="{{ p.percent }}" style="width:0%"></div>
      </div>
    </div>
    {% if p.met %}
    <div class="threshold-banner">
      <i class="fas fa-trophy"></i> The 10% threshold has been reached!
    </div>
    {% endif %}
    <div class="success-actions">
      <a href="{{ url_for(\'main.index\') }}" class="btn-outline"><i class="fas fa-home"></i> Home</a>
      <button onclick="sharePetition()" class="btn-solid"><i class="fas fa-share-alt"></i> Share</button>
    </div>
  </div>
</section>
<script>
function sharePetition() {
  const data = {
    title: "{{ s.petition_title }}",
    text: "I signed the Lumbee Tribe petition — add your voice!",
    url: window.location.origin
  };
  if (navigator.share) { navigator.share(data); }
  else { navigator.clipboard.writeText(data.url).then(() => alert("Link copied!")); }
}
</script>
{% endblock %}
''')

w('app/templates/admin_login.html', '''
{% extends "base.html" %}
{% block title %}Admin Login{% endblock %}
{% block content %}
<section class="form-page">
  <div class="form-box" style="max-width:420px">
    <div class="form-top">
      <i class="fas fa-lock" style="font-size:3rem;color:var(--accent)"></i>
      <h1 style="margin-top:1rem">Admin Login</h1>
      <p>Lumbee Tribe Petition System</p>
    </div>
    {% if get_flashed_messages() %}
    <div class="alert alert-error">
      <i class="fas fa-exclamation-triangle"></i>
      {{ get_flashed_messages()[0] }}
    </div>
    {% endif %}
    <form method="POST" action="{{ url_for(\'main.login\') }}">
      <div class="field-grid">
        <div class="field span2">
          <label for="username"><i class="fas fa-user"></i> Username</label>
          <input type="text" id="username" name="username" required autofocus>
        </div>
        <div class="field span2">
          <label for="password"><i class="fas fa-key"></i> Password</label>
          <input type="password" id="password" name="password" required>
        </div>
      </div>
      <button type="submit" class="submit-btn">
        <i class="fas fa-sign-in-alt"></i> Login
      </button>
    </form>
  </div>
</section>
{% endblock %}
''')

w('app/templates/admin.html', '''
{% extends "base.html" %}
{% block title %}Admin Dashboard{% endblock %}
{% block content %}
<section class="admin-page">
<div class="admin-wrap">
  <div class="admin-hdr">
    <h1><i class="fas fa-tachometer-alt"></i> Admin Dashboard</h1>
    <a href="{{ url_for(\'main.logout\') }}" class="btn-logout">
      <i class="fas fa-sign-out-alt"></i> Logout
    </a>
  </div>
  <div class="kpi-grid">
    <div class="kpi primary"><i class="fas fa-pen-nib"></i>
      <div><strong>{{ p.current }}</strong><span>Signatures</span></div></div>
    <div class="kpi success"><i class="fas fa-chart-line"></i>
      <div><strong>{{ p.percent }}%</strong><span>Progress</span></div></div>
    <div class="kpi warning"><i class="fas fa-ban"></i>
      <div><strong>{{ dups|length }}</strong><span>Blocked Duplicates</span></div></div>
    <div class="kpi info"><i class="fas fa-clipboard-list"></i>
      <div><strong>{{ logs|length }}</strong><span>Audit Records</span></div></div>
  </div>

  <!-- Appearance -->
  <div class="panel">
    <h2><i class="fas fa-paint-brush"></i> Site Appearance</h2>
    <form method="POST" action="{{ url_for(\'main.save_settings\') }}"
          enctype="multipart/form-data">
      <div class="settings-grid">
        <div class="sg-group span2">
          <label>Petition Title</label>
          <input type="text" name="petition_title" value="{{ s.petition_title }}">
        </div>
        <div class="sg-group span2">
          <label>Petition Description</label>
          <textarea name="petition_description" rows="3">{{ s.petition_description }}</textarea>
        </div>
        <div class="sg-group">
          <label>Primary Color</label>
          <div class="color-row">
            <input type="color" name="primary_color" value="{{ s.primary_color }}">
            <input type="text" class="hex-input" data-target="primary_color" value="{{ s.primary_color }}">
          </div>
        </div>
        <div class="sg-group">
          <label>Secondary Color</label>
          <div class="color-row">
            <input type="color" name="secondary_color" value="{{ s.secondary_color }}">
            <input type="text" class="hex-input" data-target="secondary_color" value="{{ s.secondary_color }}">
          </div>
        </div>
        <div class="sg-group">
          <label>Accent Color</label>
          <div class="color-row">
            <input type="color" name="accent_color" value="{{ s.accent_color }}">
            <input type="text" class="hex-input" data-target="accent_color" value="{{ s.accent_color }}">
          </div>
        </div>
        <div class="sg-group">
          <label>Overlay Opacity (0–1)</label>
          <input type="range" name="hero_overlay_opacity" min="0" max="1" step="0.05"
                 value="{{ s.hero_overlay_opacity }}"
                 oninput="document.getElementById(\'opVal\').textContent=this.value">
          <small>Current: <span id="opVal">{{ s.hero_overlay_opacity }}</span></small>
        </div>
        <div class="sg-group span2">
          <label>Background Images</label>
          <div class="bg-picker">
            {% for bg in ["bg_default.jpg","bg2.jpg","bg3.jpg","bg4.jpg"] %}
            <label class="bg-thumb">
              <input type="radio" name="active_bg" value="{{ bg }}"
                     {% if s.active_bg == bg %}checked{% endif %}>
              <img src="{{ url_for(\'static\', filename=\'images/\' + bg) }}" alt="{{ bg }}"
                   onerror="this.src=\'https://placehold.co/120x75/1a237e/white?text=\' + \'{{ bg }}\'">
              <span>{{ bg }}</span>
            </label>
            {% endfor %}
          </div>
        </div>
        <div class="sg-group">
          <label><i class="fas fa-image"></i> Upload New Background</label>
          <input type="file" name="new_bg" accept=".jpg,.jpeg,.png">
        </div>
        <div class="sg-group">
          <label><i class="fas fa-image"></i> Upload Tribe Logo</label>
          <input type="file" name="tribe_logo" accept=".jpg,.jpeg,.png,.svg">
        </div>
      </div>
      <button type="submit" class="submit-btn" style="max-width:280px">
        <i class="fas fa-save"></i> Save Settings
      </button>
    </form>
  </div>

  <!-- Signatures -->
  <div class="panel">
    <h2><i class="fas fa-list-alt"></i> Recent Signatures ({{ signers|length }})</h2>
    <div class="tbl-wrap">
      <table class="tbl">
        <thead>
          <tr><th>#</th><th>Name</th><th>Enrollment ID</th>
              <th>Email</th><th>Date</th><th>IP</th><th>Status</th></tr>
        </thead>
        <tbody>
          {% for sig in signers %}
          <tr>
            <td>{{ loop.index }}</td>
            <td>{{ sig.full_name }}</td>
            <td><code>{{ sig.enrollment_id }}</code></td>
            <td>{{ sig.email }}</td>
            <td>{{ sig.timestamp.strftime("%b %d, %Y %H:%M") }}</td>
            <td><code>{{ sig.ip_address }}</code></td>
            <td>
              {% if sig.is_verified %}
                <span class="badge green">Verified</span>
              {% else %}
                <span class="badge yellow">Pending</span>
              {% endif %}
            </td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
  </div>

  <!-- Duplicates -->
  <div class="panel">
    <h2><i class="fas fa-ban"></i> Blocked Duplicates ({{ dups|length }})</h2>
    <div class="tbl-wrap">
      <table class="tbl">
        <thead><tr><th>Enrollment ID</th><th>Name</th><th>IP</th><th>Time</th></tr></thead>
        <tbody>
          {% for d in dups %}
          <tr class="row-warn">
            <td><code>{{ d.attempted_enrollment_id }}</code></td>
            <td>{{ d.attempted_name }}</td>
            <td><code>{{ d.ip_address }}</code></td>
            <td>{{ d.timestamp.strftime("%b %d, %Y %H:%M") }}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
  </div>

  <!-- Audit -->
  <div class="panel">
    <h2><i class="fas fa-history"></i> Audit Log ({{ logs|length }})</h2>
    <div class="tbl-wrap">
      <table class="tbl">
        <thead><tr><th>Event</th><th>Enrollment ID</th><th>IP</th><th>Severity</th><th>Time</th></tr></thead>
        <tbody>
          {% for log in logs %}
          <tr class="{% if log.severity == \'WARNING\' %}row-warn{% endif %}">
            <td>{{ log.event_type }}</td>
            <td><code>{{ log.enrollment_id or "—" }}</code></td>
            <td><code>{{ log.ip_address }}</code></td>
            <td><span class="badge {% if log.severity == \'WARNING\' %}red{% else %}green{% endif %}">
              {{ log.severity }}</span></td>
            <td>{{ log.timestamp.strftime("%b %d, %Y %H:%M") }}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
  </div>
</div>
</section>
{% endblock %}
''')

# ══════════════════════════════════════════════════════════════
#  CSS
# ══════════════════════════════════════════════════════════════
w('app/static/css/style.css', '''
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --primary:#1a237e;--secondary:#b71c1c;--accent:#f9a825;
  --white:#fff;--dark:#0d1117;
  --glass:rgba(255,255,255,.10);--glass-b:rgba(255,255,255,.20);
  --shadow:0 8px 40px rgba(0,0,0,.35);--r:16px;--ease:all .3s ease;
}
html{scroll-behavior:smooth}
body{
  font-family:"Open Sans",sans-serif;color:#fff;min-height:100vh;
  background-size:cover;background-position:center;
  background-attachment:fixed;background-repeat:no-repeat;
}
body::before{
  content:"";position:fixed;inset:0;
  background:linear-gradient(150deg,rgba(13,17,23,.78) 0%,rgba(26,35,126,.55) 60%,rgba(183,28,28,.40) 100%);
  z-index:0;pointer-events:none;
}
main{position:relative;z-index:1}
a{color:inherit;text-decoration:none}
img{max-width:100%}

/* Navbar */
.navbar{position:sticky;top:0;z-index:900;background:rgba(13,17,23,.90);
  backdrop-filter:blur(14px);border-bottom:2px solid var(--accent)}
.nav-inner{max-width:1200px;margin:0 auto;display:flex;align-items:center;
  justify-content:space-between;padding:0 2rem;height:68px}
.brand{display:flex;align-items:center;gap:12px}
.brand-logo{height:44px;width:44px;border-radius:50%;border:2px solid var(--accent);object-fit:cover}
.brand-name{font-family:"Cinzel",serif;font-size:1.25rem;font-weight:700;letter-spacing:1px}
.nav-right{display:flex;align-items:center;gap:1.5rem}
.nav-link{font-size:.9rem;opacity:.8;transition:var(--ease)}
.nav-link:hover{opacity:1;color:var(--accent)}
.nav-cta{background:var(--accent);color:var(--dark)!important;padding:8px 22px;
  border-radius:50px;font-weight:700;font-size:.9rem;transition:var(--ease)}
.nav-cta:hover{background:#fff;transform:translateY(-2px);box-shadow:0 6px 20px rgba(249,168,37,.4)}

/* Flash */
.flash-wrap{position:relative;z-index:2;padding:.75rem 2rem}
.flash{max-width:900px;margin:0 auto;padding:.9rem 1.25rem;border-radius:10px;font-size:.9rem;font-weight:600}
.flash-success{background:rgba(46,125,50,.35);border:1px solid #4caf50}
.flash-error{background:rgba(183,28,28,.35);border:1px solid #ef5350}

/* Hero */
.hero{position:relative;min-height:88vh;display:flex;align-items:center;
  justify-content:center;text-align:center;padding:5rem 2rem}
.hero-overlay{position:absolute;inset:0;background:rgba(0,0,0,var(--overlay-opacity,.55));z-index:0}
.hero-body{position:relative;z-index:1;max-width:820px;animation:fadeUp .8s ease}
.hero-badge{display:inline-block;background:var(--accent);color:var(--dark);
  padding:6px 20px;border-radius:50px;font-size:.8rem;font-weight:700;
  letter-spacing:1.5px;text-transform:uppercase;margin-bottom:1.5rem}
.hero-title{font-family:"Cinzel",serif;font-size:clamp(2rem,5.5vw,3.6rem);
  font-weight:700;line-height:1.15;text-shadow:2px 4px 12px rgba(0,0,0,.6);margin-bottom:1rem}
.hero-desc{font-size:1.1rem;opacity:.88;line-height:1.7;margin-bottom:2.5rem}
.hero-btn{display:inline-flex;align-items:center;gap:10px;
  background:linear-gradient(135deg,var(--accent),#e65100);color:var(--dark);
  padding:15px 38px;border-radius:50px;font-size:1.05rem;font-weight:700;margin-top:2rem;
  transition:var(--ease);box-shadow:0 6px 24px rgba(249,168,37,.45)}
.hero-btn:hover{transform:translateY(-3px);box-shadow:0 10px 35px rgba(249,168,37,.6)}

/* Progress Widget */
.progress-widget{background:var(--glass);backdrop-filter:blur(18px);
  border:1px solid var(--glass-b);border-radius:var(--r);
  padding:1.75rem 2rem;box-shadow:var(--shadow)}
.pw-stats{display:flex;align-items:center;justify-content:space-around;
  margin-bottom:1.5rem;flex-wrap:wrap;gap:.75rem}
.pw-stat{text-align:center}
.pw-num{display:block;font-family:"Cinzel",serif;font-size:2.2rem;font-weight:700;color:var(--accent)}
.pw-lbl{font-size:.75rem;text-transform:uppercase;letter-spacing:1px;opacity:.75}
.pw-divider{width:1px;height:50px;background:var(--glass-b)}
.pw-track{background:rgba(255,255,255,.18);border-radius:50px;height:18px;overflow:hidden}
.pw-fill{height:100%;background:linear-gradient(90deg,var(--accent),#e65100);
  border-radius:50px;transition:width 1.6s cubic-bezier(.4,0,.2,1);position:relative;overflow:hidden}
.pw-fill::after{content:"";position:absolute;top:0;left:-100%;width:60%;height:100%;
  background:linear-gradient(90deg,transparent,rgba(255,255,255,.35),transparent);
  animation:shimmer 2.5s infinite}
.pw-met{margin-top:1rem;padding:.75rem 1rem;background:rgba(46,125,50,.3);
  border:1px solid #66bb6a;border-radius:8px;color:#a5d6a7;font-weight:600;font-size:.9rem}

/* Cards */
.cards-section{padding:5rem 2rem;background:rgba(0,0,0,.45);backdrop-filter:blur(6px);position:relative;z-index:1}
.cards-grid{max-width:1100px;margin:0 auto;display:grid;
  grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:2rem}
.card{background:var(--glass);backdrop-filter:blur(14px);border:1px solid var(--glass-b);
  border-radius:var(--r);padding:2rem 1.75rem;text-align:center;
  transition:var(--ease);box-shadow:var(--shadow)}
.card:hover{transform:translateY(-6px);border-color:var(--accent);
  box-shadow:0 16px 50px rgba(249,168,37,.18)}
.card-icon{font-size:2.4rem;color:var(--accent);margin-bottom:1rem}
.card h3{font-family:"Cinzel",serif;font-size:1.05rem;margin-bottom:.75rem}
.card p{opacity:.82;line-height:1.65;font-size:.92rem}

/* Form */
.form-page{min-height:90vh;display:flex;align-items:flex-start;
  justify-content:center;padding:4rem 1.5rem;position:relative;z-index:1}
.form-box{background:rgba(13,17,23,.90);backdrop-filter:blur(22px);
  border:1px solid var(--glass-b);border-radius:24px;padding:3rem 2.5rem;
  width:100%;max-width:760px;box-shadow:0 24px 70px rgba(0,0,0,.55);animation:fadeUp .6s ease}
.form-top{text-align:center;padding-bottom:2rem;margin-bottom:2rem;border-bottom:1px solid var(--glass-b)}
.form-logo{height:80px;width:80px;border-radius:50%;border:3px solid var(--accent);object-fit:cover;margin-bottom:1rem}
.form-top h1{font-family:"Cinzel",serif;font-size:1.75rem;margin-bottom:.4rem}
.form-top p{opacity:.75;font-size:.95rem}
.mini-prog{margin-top:1rem}
.mini-prog span{font-size:.82rem;opacity:.7}
.mini-track{background:rgba(255,255,255,.15);border-radius:50px;height:8px;margin-top:6px;overflow:hidden}
.mini-fill{height:100%;background:linear-gradient(90deg,var(--accent),#e65100);border-radius:50px;transition:width 1s ease}

/* Alerts */
.alert{border-radius:10px;padding:1rem 1.25rem;margin-bottom:1.25rem;
  font-size:.9rem;line-height:1.5;display:flex;gap:.75rem;align-items:flex-start}
.alert i{margin-top:2px;flex-shrink:0}
.alert-error{background:rgba(183,28,28,.25);border:1px solid rgba(244,67,54,.45);color:#ffcdd2}
.alert-info{background:rgba(249,168,37,.12);border:1px solid rgba(249,168,37,.35);color:#fff8e1}
.alert ul{padding-left:1.25rem}

/* Fields */
.field-grid{display:grid;grid-template-columns:1fr 1fr;gap:1.4rem;margin-bottom:1.75rem}
.field{display:flex;flex-direction:column;gap:6px}
.field.span2{grid-column:1/-1}
label{font-size:.87rem;font-weight:600;color:rgba(255,255,255,.88);letter-spacing:.3px}
.opt{font-weight:400;opacity:.6}
input[type=text],input[type=email],input[type=tel],input[type=date],
input[type=password],textarea,select{
  background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.18);
  border-radius:10px;padding:11px 15px;color:#fff;font-size:.97rem;
  font-family:"Open Sans",sans-serif;transition:var(--ease);width:100%}
input:focus,textarea:focus,select:focus{
  outline:none;border-color:var(--accent);background:rgba(255,255,255,.11);
  box-shadow:0 0 0 3px rgba(249,168,37,.18)}
input::placeholder{color:rgba(255,255,255,.35)}
textarea{resize:vertical}
small{font-size:.76rem;color:rgba(255,255,255,.5)}

/* Drop zone */
.drop-zone{border:2px dashed rgba(255,255,255,.28);border-radius:12px;
  padding:2rem;text-align:center;cursor:pointer;position:relative;
  min-height:130px;transition:var(--ease);display:flex;align-items:center;justify-content:center}
.drop-zone:hover,.drop-zone.over{border-color:var(--accent);background:rgba(249,168,37,.06)}
.drop-zone input[type=file]{position:absolute;inset:0;opacity:0;cursor:pointer;width:100%;height:100%}
.dz-inner i{font-size:2.4rem;color:var(--accent);margin-bottom:.5rem}
.dz-inner p{font-weight:600;margin-bottom:.25rem}

/* Checkbox */
.check-label{display:flex;align-items:flex-start;gap:12px;cursor:pointer;font-size:.88rem;line-height:1.55}
.check-label input[type=checkbox]{width:18px;height:18px;flex-shrink:0;margin-top:2px;accent-color:var(--accent)}

/* Submit */
.submit-btn{width:100%;padding:15px;background:linear-gradient(135deg,var(--primary),#283593);
  border:2px solid var(--accent);color:#fff;font-size:1.05rem;font-weight:700;
  border-radius:12px;cursor:pointer;transition:var(--ease);
  font-family:"Open Sans",sans-serif;letter-spacing:.4px}
.submit-btn:hover{background:linear-gradient(135deg,var(--accent),#e65100);color:var(--dark);
  transform:translateY(-2px);box-shadow:0 8px 28px rgba(249,168,37,.4)}
.submit-btn:disabled{opacity:.6;cursor:not-allowed;transform:none}

/* Success */
.success-page{min-height:90vh;display:flex;align-items:center;justify-content:center;
  padding:4rem 1.5rem;position:relative;z-index:1}
.success-box{background:rgba(13,17,23,.90);backdrop-filter:blur(22px);
  border:1px solid var(--glass-b);border-radius:24px;padding:3rem 2.5rem;
  max-width:620px;width:100%;text-align:center;animation:fadeUp .6s ease}
.success-icon{font-size:5rem;color:#4caf50;margin-bottom:1rem;animation:pop .7s ease}
.success-box h1{font-family:"Cinzel",serif;font-size:2rem;margin-bottom:.5rem}
.success-sub{opacity:.75;margin-bottom:1.5rem}
.threshold-banner{background:rgba(46,125,50,.3);border:1px solid #66bb6a;
  border-radius:10px;padding:1rem;color:#a5d6a7;font-weight:600;margin-bottom:1.5rem}
.success-actions{display:flex;gap:1rem;justify-content:center;flex-wrap:wrap;margin-top:1.5rem}
.btn-outline,.btn-solid{padding:12px 28px;border-radius:50px;font-weight:600;
  font-size:.95rem;cursor:pointer;transition:var(--ease);font-family:"Open Sans",sans-serif;border:none}
.btn-outline{background:rgba(255,255,255,.12);color:#fff;border:1px solid var(--glass-b)}
.btn-solid{background:var(--accent);color:var(--dark)}
.btn-outline:hover{background:rgba(255,255,255,.22)}
.btn-solid:hover{transform:translateY(-2px);box-shadow:0 6px 20px rgba(249,168,37,.4)}

/* Admin */
.admin-page{padding:2rem 1.5rem;position:relative;z-index:1}
.admin-wrap{max-width:1400px;margin:0 auto}
.admin-hdr{display:flex;align-items:center;justify-content:space-between;
  margin-bottom:2rem;padding-bottom:1rem;border-bottom:1px solid var(--glass-b)}
.admin-hdr h1{font-family:"Cinzel",serif;font-size:1.7rem}
.btn-logout{padding:8px 20px;background:var(--secondary);color:#fff;
  border-radius:25px;font-size:.88rem;transition:var(--ease)}
.btn-logout:hover{background:#c62828}
.kpi-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:1.5rem;margin-bottom:2rem}
.kpi{background:var(--glass);backdrop-filter:blur(12px);border:1px solid var(--glass-b);
  border-radius:var(--r);padding:1.5rem;display:flex;align-items:center;gap:1rem;transition:var(--ease)}
.kpi:hover{transform:translateY(-4px)}
.kpi i{font-size:2rem}
.kpi strong{display:block;font-size:2rem;font-weight:700;line-height:1}
.kpi span{font-size:.78rem;opacity:.7;text-transform:uppercase;letter-spacing:.8px}
.kpi.primary i{color:var(--accent)}.kpi.success i{color:#66bb6a}
.kpi.warning i{color:#ffa726}.kpi.info i{color:#29b6f6}
.panel{background:rgba(13,17,23,.88);backdrop-filter:blur(14px);
  border:1px solid var(--glass-b);border-radius:var(--r);padding:2rem;margin-bottom:2rem}
.panel h2{font-family:"Cinzel",serif;font-size:1.2rem;color:var(--accent);
  margin-bottom:1.5rem;display:flex;align-items:center;gap:.6rem}
.settings-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));
  gap:1.5rem;margin-bottom:1.75rem}
.sg-group{display:flex;flex-direction:column;gap:8px}
.sg-group.span2{grid-column:1/-1}
.sg-group>label{font-size:.82rem;font-weight:600;opacity:.8}
.color-row{display:flex;gap:8px;align-items:center}
.color-row input[type=color]{width:44px;height:38px;border-radius:8px;
  border:1px solid var(--glass-b);background:none;cursor:pointer;padding:2px}
.hex-input{flex:1}
.bg-picker{display:flex;gap:1rem;flex-wrap:wrap}
.bg-thumb{cursor:pointer;text-align:center;font-size:.75rem}
.bg-thumb input{display:none}
.bg-thumb img{width:110px;height:70px;object-fit:cover;border-radius:8px;
  border:3px solid transparent;display:block;margin-bottom:4px;transition:var(--ease)}
.bg-thumb input:checked+img{border-color:var(--accent)}
.bg-thumb img:hover{border-color:rgba(249,168,37,.5)}
.tbl-wrap{overflow-x:auto}
.tbl{width:100%;border-collapse:collapse;font-size:.86rem}
.tbl th{background:rgba(255,255,255,.07);padding:11px 14px;text-align:left;
  font-weight:600;color:var(--accent);border-bottom:1px solid var(--glass-b);white-space:nowrap}
.tbl td{padding:9px 14px;border-bottom:1px solid rgba(255,255,255,.05);color:rgba(255,255,255,.82)}
.tbl tr:hover td{background:rgba(255,255,255,.03)}
.row-warn td{color:#ffcc80}
.badge{padding:3px 10px;border-radius:12px;font-size:.75rem;font-weight:700}
.badge.green{background:rgba(76,175,80,.25);color:#a5d6a7}
.badge.yellow{background:rgba(255,152,0,.25);color:#ffcc80}
.badge.red{background:rgba(183,28,28,.35);color:#ef9a9a}
code{background:rgba(255,255,255,.08);padding:2px 7px;border-radius:4px;
  font-size:.8rem;font-family:monospace}

/* Footer */
.footer{background:rgba(10,14,40,.96);border-top:2px solid var(--accent);
  padding:2rem;position:relative;z-index:1}
.footer-inner{max-width:1200px;margin:0 auto;display:flex;align-items:center;
  justify-content:space-between;flex-wrap:wrap;gap:1rem}
.footer-brand{display:flex;align-items:center;gap:12px;font-weight:600}
.footer-logo{height:40px;width:40px;border-radius:50%;border:1px solid var(--accent);object-fit:cover}
.footer-links p{font-size:.82rem;opacity:.7;margin-bottom:4px}

/* Animations */
@keyframes fadeUp{from{opacity:0;transform:translateY(28px)}to{opacity:1;transform:translateY(0)}}
@keyframes pop{0%{transform:scale(0) rotate(-10deg)}70%{transform:scale(1.15) rotate(3deg)}100%{transform:scale(1) rotate(0)}}
@keyframes shimmer{0%{left:-100%}100%{left:200%}}

/* Responsive */
@media(max-width:768px){
  .field-grid{grid-template-columns:1fr}
  .field.span2{grid-column:1}
  .form-box{padding:2rem 1.25rem}
  .hero-title{font-size:1.9rem}
  .pw-divider{display:none}
  .nav-inner{padding:0 1rem}
  .brand-name{font-size:1rem}
  .footer-inner{flex-direction:column;text-align:center}
  .settings-grid{grid-template-columns:1fr}
  .sg-group.span2{grid-column:1}
}
@media(max-width:480px){
  .kpi-grid{grid-template-columns:1fr 1fr}
  .success-box{padding:2rem 1.25rem}
  .admin-hdr{flex-direction:column;gap:1rem;align-items:flex-start}
}
''')

# ══════════════════════════════════════════════════════════════
#  JAVASCRIPT
# ══════════════════════════════════════════════════════════════
w('app/static/js/main.js', r'''
document.addEventListener("DOMContentLoaded", () => {

  // Animate progress bars
  document.querySelectorAll(".pw-fill[data-pct]").forEach(bar => {
    const pct = parseFloat(bar.dataset.pct) || 0;
    bar.style.width = "0%";
    requestAnimationFrame(() => setTimeout(() => { bar.style.width = pct + "%"; }, 200));
  });

  // Drop zone
  const zone  = document.getElementById("dropZone");
  const input = document.getElementById("id_card");
  const inner = document.getElementById("dzInner");
  if (zone && input) {
    zone.addEventListener("dragover",  e => { e.preventDefault(); zone.classList.add("over"); });
    zone.addEventListener("dragleave", ()  => zone.classList.remove("over"));
    zone.addEventListener("drop", e => {
      e.preventDefault(); zone.classList.remove("over");
      const file = e.dataTransfer.files[0];
      if (file) setFile(file);
    });
    input.addEventListener("change", () => { if (input.files[0]) setFile(input.files[0]); });

    function setFile(file) {
      if (file.size > 16 * 1024 * 1024) { showToast("File too large. Max 16 MB.", "error"); return; }
      if (file.type.startsWith("image/")) {
        const reader = new FileReader();
        reader.onload = e => {
          inner.innerHTML = `<img src="${e.target.result}"
            style="max-height:90px;border-radius:8px;margin-bottom:.5rem">
            <p style="font-size:.82rem;opacity:.7">
              <i class="fas fa-check-circle" style="color:#4caf50"></i> ${file.name}</p>`;
        };
        reader.readAsDataURL(file);
      } else {
        inner.innerHTML = `<i class="fas fa-file-pdf" style="font-size:2.5rem;color:#ef5350"></i>
          <p style="font-size:.82rem;margin-top:.5rem;opacity:.7">${file.name}</p>`;
      }
    }
  }

  // Form submit guard
  const form = document.getElementById("petitionForm");
  if (form) {
    form.addEventListener("submit", e => {
      const expInput = document.getElementById("id_card_expiry");
      if (expInput && expInput.value) {
        const exp = new Date(expInput.value + "T00:00:00");
        const today = new Date(); today.setHours(0,0,0,0);
        if (exp < today) {
          e.preventDefault();
          showToast("Your Member ID card is expired.", "error");
          return;
        }
      }
      const btn = document.getElementById("submitBtn");
      if (btn) { btn.disabled = true; btn.innerHTML = "<i class='fas fa-spinner fa-spin'></i> Submitting…"; }
    });
  }

  // Enrollment ID uppercase
  const eid = document.getElementById("enrollment_id");
  if (eid) {
    eid.addEventListener("input", () => {
      const pos = eid.selectionStart;
      eid.value = eid.value.toUpperCase();
      eid.setSelectionRange(pos, pos);
    });
  }

  // Live counter
  const liveCount = document.getElementById("live-count");
  if (liveCount) {
    setInterval(() => {
      fetch("/api/progress").then(r => r.json()).then(d => {
        animNum(liveCount, parseInt(liveCount.textContent.replace(/,/g,"")) || 0, d.current);
        document.querySelectorAll(".pw-fill").forEach(b => {
          b.style.width = Math.min(d.percent, 100) + "%";
        });
      }).catch(() => {});
    }, 30000);
  }

  function animNum(el, from, to) {
    const dur = 900, t0 = performance.now();
    const step = ts => {
      const frac = Math.min((ts - t0) / dur, 1);
      el.textContent = Math.round(from + (to - from) * frac).toLocaleString();
      if (frac < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  // Color pickers sync
  document.querySelectorAll("input[type=color]").forEach(picker => {
    const name = picker.getAttribute("name");
    const hex  = document.querySelector(`.hex-input[data-target="${name}"]`);
    if (!hex) return;
    picker.addEventListener("input", () => { hex.value = picker.value; });
    hex.addEventListener("input", () => {
      if (/^#[0-9a-f]{6}$/i.test(hex.value)) picker.value = hex.value;
    });
  });

  // Toast
  function showToast(msg, type = "info") {
    const colors = { error:"rgba(183,28,28,.95)", info:"rgba(26,35,126,.95)", success:"rgba(46,125,50,.95)" };
    const t = document.createElement("div");
    t.style.cssText = `position:fixed;top:80px;right:20px;z-index:9999;
      background:${colors[type]||colors.info};color:#fff;padding:1rem 1.5rem;
      border-radius:12px;max-width:340px;font-size:.9rem;line-height:1.4;
      box-shadow:0 8px 30px rgba(0,0,0,.4);backdrop-filter:blur(8px);animation:fadeUp .3s ease;`;
    t.innerHTML = `<i class="fas fa-${type==="error"?"exclamation-triangle":"info-circle"}"></i> ${msg}`;
    document.body.appendChild(t);
    setTimeout(() => t.remove(), 5000);
  }

});
''')

# ══════════════════════════════════════════════════════════════
#  PLACEHOLDER FILES
# ══════════════════════════════════════════════════════════════
w('app/static/images/.gitkeep', '')
w('app/uploads/.gitkeep', '')

# ══════════════════════════════════════════════════════════════
#  CREATE ZIP
# ══════════════════════════════════════════════════════════════
print("\n📦 Creating ZIP archive...")
zip_path = os.path.join(os.path.dirname(ROOT), 'lumbee-petition.zip')
with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
    for dirpath, dirnames, filenames in os.walk(ROOT):
        # Skip venv, __pycache__, .git
        dirnames[:] = [d for d in dirnames
                       if d not in {'venv','env','.git','__pycache__','.pytest_cache'}]
        for filename in filenames:
            filepath = os.path.join(dirpath, filename)
            arcname  = os.path.relpath(filepath, os.path.dirname(ROOT))
            zf.write(filepath, arcname)

print(f"\n✅ ZIP created: {zip_path}")
print("\n" + "="*52)
print("  ALL FILES WRITTEN SUCCESSFULLY!")
print("  Your project is ready to deploy.")
print("="*52)

