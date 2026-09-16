import flask.cli
flask.cli.show_server_banner = lambda *args, **kwargs: None
import time
import os
import json
import re
from flask import Flask, render_template, redirect, url_for, session, jsonify, request, flash, abort, g, send_from_directory
from flask_session import Session
from flask_wtf.csrf import CSRFProtect, CSRFError
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_cors import CORS

from config import config_map
from utils.db import init_db, query_db, execute_db
from utils.i18n import init_i18n
from utils.auth_helpers import get_current_user
from utils.defaults import get_user_center_id, get_center_or_404
from utils.constants import DEFAULT_ALLERGIES, DEFAULT_DISTRICT, DEFAULT_DEPARTMENT, DEFAULT_WALK_IN_REASON, DEFAULT_ONLINE_REASON
from utils.logger import setup_logging, get_logger

class CustomCSRFProtect(CSRFProtect):
    def protect(self):
        from flask import current_app
        if current_app.testing or current_app.config.get('TESTING') or not current_app.config.get('WTF_CSRF_ENABLED', True):
            return
        super().protect()

csrf = CustomCSRFProtect()
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["1000 per hour", "200 per minute"],
    storage_uri=os.getenv('RATELIMIT_STORAGE_URI', 'memory://'),
    strategy="fixed-window"
)


def create_app(config_name=None):
    setup_logging()
    logger = get_logger("app")
    access_logger = get_logger("access")

    if config_name is None:
        config_name = os.getenv('FLASK_ENV', 'default')

    app = Flask(__name__)
    app.config.from_object(config_map.get(config_name, config_map['default']))
    if app.config.get('TESTING'):
        app.config['WTF_CSRF_ENABLED'] = False

    session_type = app.config.get('SESSION_TYPE')
    if session_type and session_type not in ('cookie', 'signed_cookie', 'null'):
        if session_type == 'filesystem':
            os.makedirs(app.config.get('SESSION_FILE_DIR', '/tmp/.flask_sessions'), exist_ok=True)
        Session(app)
    init_db(app)
    init_i18n(app)
    csrf.init_app(app)
    try:
        limiter.init_app(app)
        limiter.enabled = app.config.get('RATELIMIT_ENABLED', True)
    except RuntimeError:
        limiter.enabled = False
    cors_origins_env = os.getenv('CORS_ALLOWED_ORIGINS')
    if cors_origins_env:
        allowed_origins = [o.strip() for o in cors_origins_env.split(',') if o.strip()]
    else:
        allowed_origins = [r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"]
    CORS(app, resources={r"/api/*": {"origins": allowed_origins}}, supports_credentials=True)

    from utils.email_helper import mask_email

    @app.template_filter('mask_email')
    def mask_email_filter(email):
        return mask_email(email)

    @app.template_filter('age')
    def calculate_age(dob):
        if not dob:
            return 'N/A'
        try:
            from datetime import date, datetime
            if isinstance(dob, str):
                for fmt in ('%Y-%m-%d', '%d-%m-%Y', '%Y/%m/%d', '%d/%m/%Y'):
                    try:
                        dob_date = datetime.strptime(dob, fmt).date()
                        break
                    except ValueError:
                        continue
                else:
                    return str(dob)
            elif isinstance(dob, datetime):
                dob_date = dob.date()
            elif isinstance(dob, date):
                dob_date = dob
            else:
                return str(dob)
                
            today = date.today()
            age_years = today.year - dob_date.year - ((today.month, today.day) < (dob_date.month, dob_date.day))
            return f"{age_years} yrs"
        except Exception:
            return str(dob)

    @app.context_processor
    def inject_user():
        from utils.permissions import has_permission, can
        user = None
        if session and 'user_id' in session:
            try:
                user = get_current_user()
            except Exception:
                pass
        return dict(current_user=user, has_permission=has_permission, can=can)

    @app.before_request
    def check_testing_and_session():
        g.request_start_time = time.time()
        if app.config.get("TESTING"):
            app.config["WTF_CSRF_ENABLED"] = False
        validate_user_session_logic()

    def validate_user_session_logic():
        if session and 'user_id' in session and 'session_version' in session:
            try:
                row = query_db('SELECT session_version, is_active FROM users WHERE id = %s', (session['user_id'],), one=True)
                if not row or not row.get('is_active') or row.get('session_version', 1) != session.get('session_version'):
                    session.clear()
                    flash('Your session has expired or was invalidated. Please log in again.', 'warning')
                    return redirect(url_for('auth.login'))
            except Exception:
                pass

    @app.after_request
    def handle_after_request(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(self)"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://unpkg.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://unpkg.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: https://*.tile.openstreetmap.org; "
            "connect-src 'self'"
        )
        if not app.debug and (request.is_secure or request.headers.get('X-Forwarded-Proto') == 'https'):
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"

        if request.path.startswith("/static/"):
            response.headers["Cache-Control"] = "public, max-age=604800, immutable"
        elif response.status_code == 200 and not response.headers.get("Cache-Control"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"

        try:
            duration_ms = (time.time() - getattr(g, "request_start_time", time.time())) * 1000
            if not request.path.startswith("/static/"):
                access_logger.info("%s %s -> %s (%.1fms)", request.method, request.path, response.status_code, duration_ms)
        except Exception:
            pass

        return response

    from blueprints.auth import auth_bp
    from blueprints.phc import phc_bp
    from blueprints.region import region_bp
    from blueprints.admin import admin_bp
    from blueprints.patient import patient_bp
    from blueprints.center import center_bp
    from blueprints.api import api_bp
    from blueprints.dashboard import dashboard_bp

    csrf.exempt(api_bp)

    app.register_blueprint(auth_bp)
    app.register_blueprint(phc_bp)
    app.register_blueprint(region_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(patient_bp)
    app.register_blueprint(center_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(dashboard_bp)

    @app.route('/')
    def landing():
        if 'user_id' in session:
            return redirect(url_for('auth.app_redirect'))
        return render_template('landing.html')

    @app.route('/home')
    def landinghome():
        if 'user_id' in session:
            return redirect(url_for('auth.app_redirect'))
        return render_template('landing.html')

    @app.route('/facilities')
    @app.route('/facilities/@<username>')
    def facilities_view(username=None):
        user = get_current_user()
        facilities = query_db('SELECT * FROM centers ORDER BY name ASC') or []
        for fac in facilities:
            if not fac.get('district'):
                fac['district'] = fac.get('region') or fac.get('state') or 'Main Center'
        return render_template('facilities/list.html', facilities=facilities, current_user=user)

    @app.route('/facilities/<facility_id>')
    @app.route('/patient/facilities/<facility_id>')
    @app.route('/patient/facilities/<facility_id>/@<username>')
    def facility_detail(facility_id, username=None):
        user = get_current_user()
        facility = query_db('SELECT * FROM centers WHERE id = %s', (facility_id,), one=True)
        if not facility:
            abort(404)
        if not facility.get('district'):
            facility['district'] = facility.get('region') or facility.get('state') or 'Main Center'
            
        staff_members = query_db('SELECT id, full_name, role, phone, email FROM users WHERE center_id = %s ORDER BY full_name ASC', (facility_id,)) or []
        inventory_items = query_db('SELECT * FROM inventory_items WHERE center_id = %s ORDER BY quantity ASC', (facility_id,)) or []
        pat_count_row = query_db('SELECT COUNT(*) as cnt FROM patients WHERE center_id = %s', (facility_id,), one=True)
        patient_count = pat_count_row['cnt'] if pat_count_row else 0
        
        return render_template('facilities/detail.html', facility=facility, facility_id=facility_id, current_user=user, staff_members=staff_members, inventory_items=inventory_items, patient_count=patient_count)

    @app.route('/inventory')
    def inventory_redirect():
        user = get_current_user()
        if not user:
            return redirect(url_for('auth.login'))
        if user.get('role') == 'system_admin':
            return redirect(url_for('admin.inventory'))
        elif user.get('role') == 'patient':
            return redirect(f'/patient/@{user.get("username")}')
        return redirect(url_for('phc.inventory'))

    @app.route('/user')
    def user_redirect():
        user = get_current_user()
        if not user:
            return redirect(url_for('auth.login'))
        if user.get('role') == 'patient':
            return redirect(f'/patient/@{user.get("username")}')
        return redirect('/patient/')

    @app.route('/map')
    def map_view():
        user = get_current_user()
        selected_facility_id = request.args.get('facility', '').strip()
        facilities = query_db('SELECT * FROM centers ORDER BY name ASC') or []
        for fac in facilities:
            if not fac.get('district'):
                fac['district'] = fac.get('region') or fac.get('state') or DEFAULT_DISTRICT
        if user and user.get('username'):
            return redirect(f'/patient/map/@{user["username"]}?facility={selected_facility_id}' if selected_facility_id else f'/patient/map/@{user["username"]}') if user.get('role') == 'patient' else render_template('map.html', profile_username=user.get('username'), current_user=user, facilities=facilities, selected_facility_id=selected_facility_id)
        return render_template('map.html', profile_username=None, current_user=user, facilities=facilities, selected_facility_id=selected_facility_id)

    @app.route('/map/@<username>')
    def map_view_user(username):
        username = username.strip().lstrip('@')
        user = get_current_user()
        selected_facility_id = request.args.get('facility', '').strip()
        facilities = query_db('SELECT * FROM centers ORDER BY name ASC') or []
        for fac in facilities:
            if not fac.get('district'):
                fac['district'] = fac.get('region') or fac.get('state') or DEFAULT_DISTRICT
        return render_template('map.html', profile_username=username, current_user=user, facilities=facilities, selected_facility_id=selected_facility_id)

    @app.route('/emergency')
    def emergency_view():
        user = get_current_user()
        if user and user.get('username'):
            return redirect(f'/emergency/@{user["username"]}')
        return render_template('emergency.html', current_user=user)

    @app.route('/emergency/@<username>')
    @app.route('/emergency-contact/@<username>')
    def emergency_view_user(username):
        username = username.strip().lstrip('@')
        user = get_current_user()
        target_user = query_db('SELECT * FROM users WHERE username = %s', (username,), one=True)
        patient = None
        facility = None
        if target_user:
            patient = query_db('SELECT * FROM patients WHERE linked_user_id = %s', (target_user['id'],), one=True)
            if target_user.get('center_id'):
                facility = query_db('SELECT * FROM centers WHERE id = %s', (target_user['center_id'],), one=True)
        return render_template('emergency.html', profile_username=username, current_user=user, target_user=target_user, patient=patient, facility=facility)

    @app.route('/records/@<username>')
    def records_view(username):
        username = username.strip().lstrip('@')
        user = get_current_user()
        if not user:
            flash('Please log in to access medical records.', 'error')
            return redirect(url_for('auth.login'))
        if user.get('role') == 'patient' and user.get('username') != username:
            flash('Access denied: You are only authorized to view your own medical records.', 'error')
            return redirect(f'/records/@{user.get("username")}')
        target_user = query_db('SELECT * FROM users WHERE username = %s', (username,), one=True)
        records = []
        prescriptions = []
        patient = None
        appointments = []
        if target_user:
            patient = query_db('SELECT * FROM patients WHERE linked_user_id = %s', (target_user['id'],), one=True)
            if patient:
                allergies = patient.get('allergies')
                if isinstance(allergies, str):
                    try:
                        parsed = json.loads(allergies)
                        patient['allergies_list'] = parsed if isinstance(parsed, list) else [str(parsed)]
                    except Exception:
                        patient['allergies_list'] = [allergies]
                elif isinstance(allergies, list):
                    patient['allergies_list'] = allergies
                else:
                    patient['allergies_list'] = [DEFAULT_ALLERGIES]
                    
                raw_prescriptions = query_db("""
                    SELECT pr.*, u.full_name as doctor_name, c.name as center_name 
                    FROM prescriptions pr 
                    LEFT JOIN users u ON pr.prescribed_by = u.id 
                    LEFT JOIN centers c ON pr.center_id = c.id 
                    WHERE pr.patient_id = %s 
                    ORDER BY pr.created_at DESC
                """, (patient['id'],)) or []
                for p in raw_prescriptions:
                    if isinstance(p.get('medicines'), str):
                        try:
                            p['medicines_parsed'] = json.loads(p['medicines'])
                        except Exception:
                            p['medicines_parsed'] = []
                    else:
                        p['medicines_parsed'] = p.get('medicines', [])
                    prescriptions.append(p)

                raw_records = query_db("""
                    SELECT m.*, u.full_name as doctor_name, c.name as center_name 
                    FROM medical_records m 
                    LEFT JOIN users u ON m.created_by = u.id 
                    LEFT JOIN centers c ON m.center_id = c.id 
                    WHERE m.patient_id = %s 
                    ORDER BY m.created_at DESC
                """, (patient['id'],)) or []
                for r in raw_records:
                    if isinstance(r.get('data'), str):
                        try:
                            r['data_parsed'] = json.loads(r['data'])
                        except Exception:
                            r['data_parsed'] = {}
                    else:
                        r['data_parsed'] = r.get('data', {})
                    r['prescriptions'] = [p for p in prescriptions if p.get('record_id') == r['id']]
                    records.append(r)
                    
                appointments = query_db('SELECT * FROM appointments WHERE patient_id = %s ORDER BY slot_time DESC', (patient['id'],)) or []
        return render_template('patient/my_records.html', current_user=user, profile_username=username, records=records, target_user=target_user, patient=patient, appointments=appointments, prescriptions=prescriptions)

    @app.route('/notifications/@<username>')
    def notifications_user(username):
        username = username.strip().lstrip('@')
        user = get_current_user()
        notifs = []
        if user:
            notifs = query_db('SELECT * FROM notifications WHERE user_id = %s ORDER BY created_at DESC LIMIT 50', (user['id'],)) or []
            execute_db('UPDATE notifications SET is_read = 1 WHERE user_id = %s', (user['id'],))
        return render_template('notifications.html', profile_username=username, notifications=notifs, current_user=user)

    @app.route('/notifications')
    def notifications():
        user = get_current_user()
        if user and user.get('username'):
            return redirect(f'/notifications/@{user["username"]}')
        return redirect(url_for('auth.login'))

    @app.route('/settings', methods=['GET', 'POST'])
    @app.route('/settings/@<username>', methods=['GET', 'POST'])
    def settings_view(username=None):
        import secrets
        import time
        import bcrypt
        from utils.audit import log_audit
        from utils.email_helper import send_email_change_otp
        
        user = get_current_user()
        if not user:
            return redirect(url_for('auth.login'))

        current_db_user = query_db('SELECT * FROM users WHERE id = %s', (user['id'],), one=True)
        if not current_db_user:
            return redirect(url_for('auth.logout'))

        patient = None
        facility = None
        if current_db_user.get('center_id'):
            facility = query_db('SELECT * FROM centers WHERE id = %s', (current_db_user['center_id'],), one=True)

        if current_db_user['role'] == 'patient':
            patient = query_db('SELECT * FROM patients WHERE linked_user_id = %s', (current_db_user['id'],), one=True)
            if not patient:
                from utils.id_generator import generate_patient_id
                pat_id = generate_patient_id()
                cid = get_user_center_id(current_db_user)
                execute_db('INSERT INTO patients (id, linked_user_id, full_name, center_id, allergies) VALUES (%s, %s, %s, %s, %s)', 
                           (pat_id, current_db_user['id'], current_db_user['full_name'], cid, json.dumps([DEFAULT_ALLERGIES])))
                patient = query_db('SELECT * FROM patients WHERE linked_user_id = %s', (current_db_user['id'],), one=True)

        if request.method == 'POST':
            errors = []
            
            new_full_name = request.form.get('full_name', '').strip()
            new_username = request.form.get('username', '').strip()
            new_email = request.form.get('email', '').strip().lower()
            new_phone = request.form.get('phone', '').strip()
            new_lang = request.form.get('lang_pref', 'en').strip()
            new_designation = request.form.get('designation', '').strip()
            curr_pass = request.form.get('current_password', '')

            if not new_full_name:
                errors.append('Full Name / Display Name is required.')

            if not new_username:
                errors.append('Username is required.')
            elif not re.match(r'^[a-z0-9._]{3,30}$', new_username):
                errors.append('Username can only contain lowercase letters (a-z), numbers (0-9), dots (.), and underscores (_), and must be 3-30 characters long.')
            else:
                existing_user = query_db('SELECT id FROM users WHERE username = %s AND id != %s', (new_username, current_db_user['id']), one=True)
                if existing_user:
                    errors.append('Username is already taken by another user.')

            account_name_changed = (new_username != current_db_user['username']) or (new_full_name != current_db_user['full_name'])
            password_verified = False
            if curr_pass:
                if bcrypt.checkpw(curr_pass.encode('utf-8'), current_db_user['password_hash'].encode('utf-8')):
                    password_verified = True
                else:
                    errors.append('Current password entered is incorrect.')

            if account_name_changed and not password_verified and 'Current password entered is incorrect.' not in errors:
                errors.append('Your current password is required to change your username or display name.')

            email_changed = False
            curr_email = (current_db_user.get('email') or '').strip().lower()
            if new_email and new_email != curr_email:
                email_changed = True
                if not password_verified and 'Current password entered is incorrect.' not in errors:
                    errors.append('Your current password is required to update your email address.')

                if '@' not in new_email or '.' not in new_email:
                    errors.append('Please provide a valid email address.')
                else:
                    existing_email = query_db('SELECT id FROM users WHERE LOWER(email) = %s AND id != %s', (new_email, current_db_user['id']), one=True)
                    if existing_email:
                        errors.append('Email is already registered with another account.')

            new_pass = request.form.get('new_password', '')
            conf_pass = request.form.get('confirm_password', '')
            update_password = False

            if new_pass or conf_pass:
                if not password_verified and 'Current password entered is incorrect.' not in errors:
                    errors.append('Current password is required to set a new password.')
                elif not new_pass or len(new_pass) < 8:
                    errors.append('New password must be at least 8 characters long.')
                elif not re.search(r'[A-Z]', new_pass) or not re.search(r'[a-z]', new_pass) or not re.search(r'[0-9]', new_pass) or not re.search(r'[^A-Za-z0-9]', new_pass):
                    errors.append('New password must contain at least 1 uppercase letter, 1 lowercase letter, 1 digit, and 1 special character.')
                elif new_pass != conf_pass:
                    errors.append('New password and confirmation do not match.')
                elif password_verified:
                    update_password = True

            patient_address = request.form.get('address', '').strip()
            patient_dob = request.form.get('dob', '').strip() or None
            patient_gender = request.form.get('gender', 'Other')
            patient_blood_group = request.form.get('blood_group', '').strip()
            allergies_raw = request.form.get('allergies', '').strip()
            chronic_conditions_raw = request.form.get('chronic_conditions', '').strip()

            if errors:
                for err in errors:
                    flash(err, 'error')
            else:
                allergies_list = []
                if allergies_raw:
                    try:
                        if allergies_raw.startswith('[') and allergies_raw.endswith(']'):
                            parsed = json.loads(allergies_raw)
                            if isinstance(parsed, list):
                                allergies_list = [str(x).strip() for x in parsed if str(x).strip()]
                        else:
                            allergies_list = [x.strip() for x in allergies_raw.split(',') if x.strip()]
                    except Exception:
                        allergies_list = [x.strip() for x in allergies_raw.split(',') if x.strip()]
                
                if not allergies_list:
                    allergies_list = [DEFAULT_ALLERGIES]

                conditions_list = []
                if chronic_conditions_raw:
                    try:
                        if chronic_conditions_raw.startswith('[') and chronic_conditions_raw.endswith(']'):
                            parsed_c = json.loads(chronic_conditions_raw)
                            if isinstance(parsed_c, list):
                                conditions_list = [str(x).strip() for x in parsed_c if str(x).strip()]
                        else:
                            conditions_list = [x.strip() for x in chronic_conditions_raw.split(',') if x.strip()]
                    except Exception:
                        conditions_list = [x.strip() for x in chronic_conditions_raw.split(',') if x.strip()]

                chronic_conditions_val = json.dumps(conditions_list) if conditions_list else None

                email_to_save = curr_email if email_changed else (new_email or None)

                execute_db('UPDATE users SET full_name = %s, username = %s, email = %s, phone = %s, lang_pref = %s, designation = %s WHERE id = %s',
                           (new_full_name, new_username, email_to_save, new_phone or None, new_lang, new_designation or None, current_db_user['id']))

                if update_password:
                    hashed = bcrypt.hashpw(new_pass.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                    new_version = current_db_user.get('session_version', 1) + 1
                    execute_db('UPDATE users SET password_hash = %s, session_version = %s WHERE id = %s', (hashed, new_version, current_db_user['id']))
                    session['session_version'] = new_version
                    log_audit('password_changed_by_user', 'user', current_db_user['id'])

                if current_db_user['role'] == 'patient' and patient:
                    execute_db('UPDATE patients SET full_name = %s, phone = %s, address = %s, dob = %s, gender = %s, blood_group = %s, allergies = %s, chronic_conditions = %s WHERE id = %s',
                               (new_full_name, new_phone or None, patient_address or None, patient_dob, patient_gender, patient_blood_group or None,
                                json.dumps(allergies_list), chronic_conditions_val, patient['id']))

                session['username'] = new_username
                session['lang'] = new_lang

                log_audit('profile_updated', 'user', current_db_user['id'])

                if email_changed:
                    otp_code = str(secrets.randbelow(900000) + 100000)
                    session['pending_email_change'] = new_email
                    session['pending_email_otp'] = otp_code
                    session['pending_email_expires'] = time.time() + 600
                    send_email_change_otp(new_email, new_full_name, otp_code)
                    flash(f'Profile updated! A 6-digit verification code was sent to {new_email}. Please enter the code to finalize your new email address.', 'info')
                    return redirect('/settings/verify-email')

                flash('Your profile settings have been successfully updated!', 'success')
                return redirect(f'/settings/@{new_username}')

        if patient:
            raw_allergies = patient.get('allergies')
            if isinstance(raw_allergies, str):
                try:
                    parsed = json.loads(raw_allergies)
                    patient['allergies_list'] = parsed if isinstance(parsed, list) else [str(parsed)]
                except Exception:
                    patient['allergies_list'] = [raw_allergies] if raw_allergies else [DEFAULT_ALLERGIES]
            elif isinstance(raw_allergies, list):
                patient['allergies_list'] = raw_allergies
            else:
                patient['allergies_list'] = [DEFAULT_ALLERGIES]
                
            raw_conditions = patient.get('chronic_conditions')
            if isinstance(raw_conditions, str):
                try:
                    parsed = json.loads(raw_conditions)
                    patient['conditions_list'] = parsed if isinstance(parsed, list) else [str(parsed)]
                except Exception:
                    patient['conditions_list'] = [x.strip() for x in raw_conditions.split(',') if x.strip()]
            elif isinstance(raw_conditions, list):
                patient['conditions_list'] = raw_conditions
            else:
                patient['conditions_list'] = []

        pending_email = session.get('pending_email_change')
        return render_template('settings.html', current_user=current_db_user, profile_username=current_db_user['username'], patient=patient, facility=facility, pending_email=pending_email)

    @app.route('/settings/verify-email', methods=['GET', 'POST'])
    def settings_verify_email():
        import time
        from utils.audit import log_audit
        
        user = get_current_user()
        if not user:
            return redirect(url_for('auth.login'))

        pending_email = session.get('pending_email_change')
        if not pending_email:
            return redirect('/settings')

        if request.method == 'POST':
            entered_otp = request.form.get('otp', '').strip()
            expected_otp = session.get('pending_email_otp')
            expires_at = session.get('pending_email_expires', 0)

            if not expected_otp or time.time() > expires_at:
                flash('The verification code has expired. Please request a new code.', 'error')
                return render_template('verify_email_change.html', current_user=user, pending_email=pending_email)

            if entered_otp != expected_otp:
                flash('Incorrect 6-digit verification code. Please try again.', 'error')
                return render_template('verify_email_change.html', current_user=user, pending_email=pending_email)

            execute_db('UPDATE users SET email = %s WHERE id = %s', (pending_email, user['id']))
            session.pop('pending_email_change', None)
            session.pop('pending_email_otp', None)
            session.pop('pending_email_expires', None)

            log_audit('email_change_verified', 'user', user['id'])
            flash(f'Your email address has been successfully verified and updated to {pending_email}!', 'success')
            return redirect('/settings')

        return render_template('verify_email_change.html', current_user=user, pending_email=pending_email)

    @app.route('/settings/resend-email-otp', methods=['POST'])
    def settings_resend_email_otp():
        import secrets
        import time
        from utils.email_helper import send_email_change_otp

        user = get_current_user()
        if not user:
            return redirect(url_for('auth.login'))

        pending_email = session.get('pending_email_change')
        if not pending_email:
            flash('No pending email verification found.', 'error')
            return redirect('/settings')

        otp_code = str(secrets.randbelow(900000) + 100000)
        session['pending_email_otp'] = otp_code
        session['pending_email_expires'] = time.time() + 600

        send_email_change_otp(pending_email, user.get('full_name') or user.get('username'), otp_code)
        flash(f'A fresh 6-digit verification code has been dispatched to {pending_email}.', 'info')
        return redirect('/settings/verify-email')

    @app.route('/settings/cancel-email-change', methods=['POST'])
    def settings_cancel_email_change():
        session.pop('pending_email_change', None)
        session.pop('pending_email_otp', None)
        session.pop('pending_email_expires', None)
        flash('Email address update request has been cancelled.', 'info')
        return redirect('/settings')



    @app.errorhandler(429)
    def ratelimit_handler(e):
        from utils.audit import log_audit
        client_ip = request.remote_addr or "-"
        logger.warning("Rate limit triggered: ip=%s, path=%s, desc=%s", client_ip, request.path, str(e.description))
        log_audit("rate_limit_exceeded", "ip", client_ip, {"description": str(e.description)})
        if request.path.startswith("/api/") or request.is_json:
            return jsonify({"error": "Rate limit exceeded", "message": str(e.description)}), 429
        flash("Too many requests. Please slow down and try again in a moment.", "error")
        return render_template("errors/429.html"), 429

    @app.errorhandler(404)
    def not_found(e):
        if not request.path.startswith("/static/"):
            logger.info("Resource not found (404): %s %s", request.method, request.path)
        if request.path.startswith("/api/") or request.is_json:
            return jsonify({"error": "Not found"}), 404
        return render_template("errors/404.html"), 404

    @app.errorhandler(403)
    def forbidden(e):
        logger.warning("Access forbidden (403): %s %s", request.method, request.path)
        if request.path.startswith("/api/") or request.is_json:
            return jsonify({"error": "Forbidden"}), 403
        return render_template("errors/403.html"), 403



    @app.errorhandler(500)
    def server_error(e):
        logger.error("HTTP 500 Server Error: %s on %s %s", str(e), request.method, request.path, exc_info=True)
        if request.path.startswith("/api/") or request.is_json:
            return jsonify({"error": "INTERNAL_SERVER_ERROR", "message": "An unexpected server error occurred. Please try again later."}), 500
        return render_template("errors/500.html"), 500

    @app.errorhandler(Exception)
    def unhandled_exception_handler(e):
        from werkzeug.exceptions import HTTPException
        if isinstance(e, HTTPException):
            return e
        import sys, traceback
        traceback.print_exc(file=sys.stderr)
        sys.stderr.flush()
        logger.error("Unhandled Exception Caught: %s on %s %s", str(e), request.method, request.path)
        if request.path.startswith("/api/") or request.is_json:
            return jsonify({"error": "INTERNAL_SERVER_ERROR", "message": "An unexpected error occurred. Please try again later."}), 500
        return render_template("errors/500.html"), 500

    @app.errorhandler(CSRFError)
    def handle_csrf_error(e):
        flash('Session expired or security token invalid. Please try logging in again.', 'warning')
        return redirect(url_for('auth.login'))

    @app.route("/favicon.ico")
    def favicon():
        return send_from_directory(os.path.join(app.root_path, "static"), "anvaya.png", mimetype="image/png")

    return app


if __name__ == "__main__":
    import logging
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    port = int(os.getenv("PORT", 5000))
    app = create_app()
    debug_mode = os.getenv("FLASK_DEBUG", "false").lower() in ("true", "1", "t")

    mode_str = "Development" if debug_mode else "Production Ready"
    import socket
    local_ip = "127.0.0.1"
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        pass

    join_url = f"http://{local_ip}:{port}" if local_ip != "127.0.0.1" else f"http://127.0.0.1:{port}"

    print(chr(27) + "[36m" + "=" * 68 + chr(27) + "[0m")
    print(chr(27) + "[1;32m   ANVAYA VISTARA - Rural & Regional Healthcare Platform" + chr(27) + "[0m")
    print(chr(27) + "[36m" + "=" * 68 + chr(27) + "[0m")
    print(f"   - Local Server : " + chr(27) + f"[1;34mhttp://127.0.0.1:{port}" + chr(27) + "[0m")
    if local_ip and local_ip != "127.0.0.1":
        print(f"   - Network (LAN): " + chr(27) + f"[1;34m{join_url}" + chr(27) + "[0m")
    print(f"   - Environment  : " + chr(27) + f"[33m{mode_str}" + chr(27) + "[0m")
    print("   - Database     : " + chr(27) + "[32mPostgreSQL Active" + chr(27) + "[0m")
    print(chr(27) + "[36m" + "=" * 68 + chr(27) + "[0m")

    if False:
        try:
            import qrcode
            qr = qrcode.QRCode(box_size = 5, version=1,  border=2)
            qr.add_data(join_url)
            qr.make(fit=True)
            print(chr(10) + chr(27) + "[1;33m   [+] Scan QR Code with the Anvaya App to connect:" + chr(27) + "[0m" + chr(10))
            qr.print_ascii(invert=True)
        except Exception:
            pass
        print()

    app.run(debug=debug_mode, host="0.0.0.0", port=port)
