import hashlib
import hmac
from utils.notifications import create_notification, notify_patient
import json
import random
import secrets
import time
import re
from datetime import datetime, timedelta
import bcrypt
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify

from utils.db import query_db, execute_db
from utils.auth_helpers import get_current_user, login_required
from utils.audit import log_audit
from utils.email_helper import send_email, send_otp_email, send_password_reset_email, mask_email
from utils.id_generator import generate_patient_id
from utils.defaults import get_user_center_id
from utils.constants import DEFAULT_ALLERGIES
from utils.sanitize import validate_username, validate_email, validate_phone
from utils.security import check_ip_lockout, record_failed_ip_login, clear_ip_login_attempts, block_if_vpn, get_client_ip
from app import limiter

auth_bp = Blueprint('auth', __name__)


def hash_otp(code):
    return hashlib.sha256(str(code).encode('utf-8')).hexdigest()


def check_otp(entered_code, stored_val):
    if not entered_code or not stored_val:
        return False
    entered_hash = hashlib.sha256(str(entered_code).encode('utf-8')).hexdigest()
    if hmac.compare_digest(entered_hash, str(stored_val)):
        return True
    return hmac.compare_digest(str(entered_code), str(stored_val))



def parse_flexible_dob(dob_str):
    dob_str = (dob_str or '').strip()
    if not dob_str:
        return None
    from datetime import date
    parsed_date = None
    for fmt in ('%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y', '%Y/%m/%d', '%d.%m.%Y', '%m/%d/%Y'):
        try:
            parsed_date = datetime.strptime(dob_str, fmt).date()
            break
        except ValueError:
            pass
    if not parsed_date:
        return None
    today = date.today()
    if parsed_date > today or parsed_date < date(1900, 1, 1):
        return None
    return parsed_date.strftime('%Y-%m-%d')


def validate_password_complexity(password):
    if not password or len(password) < 8:
        return False, 'Password must be at least 8 characters long.'
    if not re.search(r'[A-Z]', password):
        return False, 'Password must contain at least one uppercase letter (A-Z).'
    if not re.search(r'[a-z]', password):
        return False, 'Password must contain at least one lowercase letter (a-z).'
    if not re.search(r'[0-9]', password):
        return False, 'Password must contain at least one number (0-9).'
    if not re.search(r'[^A-Za-z0-9]', password):
        return False, 'Password must contain at least one special character (!@#$%^&*...).'
    return True, None


@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("20 per minute; 60 per hour", methods=["POST"])
def login():
    if 'user_id' in session:
        return redirect(url_for('auth.app_redirect'))

    vpn_blocked = block_if_vpn()
    if vpn_blocked:
        return vpn_blocked

    active_tab = request.args.get('tab', 'username')
    form_data = {}

    if request.method == 'POST':
        client_ip = get_client_ip()
        is_ip_locked, remaining_secs, remaining_attempts = check_ip_lockout(client_ip)
        if is_ip_locked:
            remaining_mins = int(remaining_secs / 60) + 1
            log_audit('ip_lockout_blocked_attempt', 'ip', None, {'ip': client_ip, 'remaining_minutes': remaining_mins})
            flash(f'Too many failed login attempts from your IP address ({client_ip}). Access is temporarily suspended. Please try again in {remaining_mins} minute(s).', 'error')
            return render_template('auth/login.html', active_tab=active_tab, form_data=form_data)

        login_type = request.form.get('login_type', 'username')
        form_data = request.form
        
        if login_type == 'email':
            active_tab = 'email'
            email = request.form.get('email', '').strip().lower()
            if not email:
                flash('Please enter your registered email address.', 'error')
                return render_template('auth/login.html', active_tab='email', form_data=form_data)
                
            user = query_db('SELECT * FROM users WHERE LOWER(email) = %s AND is_active = 1', (email,), one=True)
            if not user:
                is_locked_now, rem_secs, rem_attempts = record_failed_ip_login(client_ip)
                log_audit('login_failed_email_not_found', 'auth', None, {'email': email, 'ip': client_ip})
                if is_locked_now:
                    rem_mins = int(rem_secs / 60) + 1
                    flash(f'Too many failed attempts. Your IP address ({client_ip}) has been temporarily suspended for {rem_mins} minutes.', 'error')
                else:
                    flash(f'No active account found with this email address. {rem_attempts} attempt(s) remaining for your IP.', 'error')
                return render_template('auth/login.html', active_tab='email', form_data=form_data)

            otp_code = str(secrets.randbelow(900000) + 100000)
            session['pending_otp'] = hash_otp(otp_code)
            session['pending_otp_expires'] = time.time() + 600
            session['pending_user_id'] = user['id']
            session['pending_email'] = user['email']
            session['pending_fullname'] = user['full_name'] or user['username']
            session['otp_attempts'] = 0
            session['otp_flow'] = 'login'
            
            send_otp_email(user['email'], user['full_name'] or user['username'], otp_code)
            log_audit('login_otp_initiated', 'user', user['id'], {'ip': client_ip})
            flash(f'Verification code sent to {mask_email(user["email"])}. Please enter the 6-digit OTP to complete login.', 'info')
            return redirect(url_for('auth.verify_otp'))

        else:
            identifier = request.form.get('username', '').strip().lower()
            password = request.form.get('password', '')

            if not identifier:
                flash('Please enter your username or registered email.', 'error')
                return render_template('auth/login.html', active_tab='username', form_data=form_data)

            if '@' in identifier:
                user = query_db('SELECT * FROM users WHERE LOWER(email) = %s AND is_active = 1', (identifier.lower(),), one=True)
                if not user:
                    is_locked_now, rem_secs, rem_attempts = record_failed_ip_login(client_ip)
                    log_audit('login_failed', 'auth', None, {'identifier': identifier, 'ip': client_ip})
                    if is_locked_now:
                        rem_mins = int(rem_secs / 60) + 1
                        flash(f'Too many failed attempts. Your IP address ({client_ip}) has been temporarily suspended for {rem_mins} minutes.', 'error')
                    else:
                        flash(f'No active account found with this email address. {rem_attempts} attempt(s) remaining for your IP.', 'error')
                    return render_template('auth/login.html', active_tab='email', form_data=form_data)

                otp_code = str(secrets.randbelow(900000) + 100000)
                session['pending_otp'] = hash_otp(otp_code)
                session['pending_otp_expires'] = time.time() + 600
                session['pending_user_id'] = user['id']
                session['pending_email'] = user['email']
                session['pending_fullname'] = user['full_name'] or user['username']
                session['otp_attempts'] = 0
                session['otp_flow'] = 'login'

                send_otp_email(user['email'], user['full_name'] or user['username'], otp_code)
                log_audit('login_otp_initiated', 'user', user['id'], {'ip': client_ip})
                flash(f'Logging in with email requires OTP verification. A 6-digit code was sent to {mask_email(user["email"])}.', 'info')
                return redirect(url_for('auth.verify_otp'))

            if not password:
                flash('Please enter your password.', 'error')
                return render_template('auth/login.html', active_tab='username', form_data=form_data)

            user = query_db('SELECT * FROM users WHERE LOWER(username) = %s AND is_active = 1', (identifier,), one=True)
            
            if user:
                if bcrypt.checkpw(password.encode('utf-8'), user['password_hash'].encode('utf-8')):
                    clear_ip_login_attempts(client_ip)
                    execute_db('UPDATE users SET failed_login_count = 0, locked_until = NULL WHERE id = %s', (user['id'],))
                    session.clear()
                    session['user_id'] = user['id']
                    session['username'] = user['username']
                    session['role'] = user['role']
                    session['session_version'] = user.get('session_version', 1)
                    session['lang'] = user.get('lang_pref') or session.get('lang', 'en')
                    log_audit('login_success', 'user', user['id'], {'ip': client_ip})
                    create_notification(
                        user['id'],
                        'Security Alert: Successful Login',
                        f'You successfully signed into your account on {datetime.now().strftime("%b %d, %Y at %I:%M %p")} from IP {client_ip}.',
                        f'/patient/@{user.get("username")}' if user.get('role') == 'patient' else '/notifications'
                    )
                    
                    next_url = request.args.get('next')
                    if next_url:
                        return redirect(next_url)
                        
                    flash(f'Welcome back, {user.get("full_name") or user.get("username")}!', 'success')
                    return redirect(url_for('auth.app_redirect'))
                else:
                    is_locked_now, rem_secs, rem_attempts = record_failed_ip_login(client_ip)
                    log_audit('login_failed_bad_password', 'user', user['id'], {'ip': client_ip})
                    create_notification(
                        user['id'],
                        'Security Alert: Failed Login Attempt',
                        f'An unsuccessful login attempt with an incorrect password was recorded on {datetime.now().strftime("%b %d, %Y at %I:%M %p")} from IP {client_ip}.',
                        '/auth/forgot-password'
                    )
                    if is_locked_now:
                        rem_mins = int(rem_secs / 60) + 1
                        flash(f'Too many failed attempts. Your IP address ({client_ip}) has been temporarily suspended for {rem_mins} minutes.', 'error')
                    else:
                        flash(f'Invalid username or password. {rem_attempts} attempt(s) remaining for your IP address before temporary suspension.', 'error')
                    return render_template('auth/login.html', active_tab='username', form_data=form_data)
            else:
                is_locked_now, rem_secs, rem_attempts = record_failed_ip_login(client_ip)
                log_audit('login_failed_user_not_found', 'auth', None, {'identifier': identifier, 'ip': client_ip})
                if is_locked_now:
                    rem_mins = int(rem_secs / 60) + 1
                    flash(f'Too many failed attempts. Your IP address ({client_ip}) has been temporarily suspended for {rem_mins} minutes.', 'error')
                else:
                    flash(f'Invalid username or password. {rem_attempts} attempt(s) remaining for your IP address before temporary suspension.', 'error')
                return render_template('auth/login.html', active_tab='username', form_data=form_data)

    return render_template('auth/login.html', active_tab=active_tab, form_data=form_data)


@auth_bp.route('/signup', methods=['GET', 'POST'])
@limiter.limit("10 per minute; 30 per hour", methods=["POST"])
def signup():
    if 'user_id' in session:
        return redirect(url_for('auth.app_redirect'))

    vpn_blocked = block_if_vpn()
    if vpn_blocked:
        return vpn_blocked

    if request.method == 'POST':
        username = request.form.get('username', '').strip().lower()
        full_name = request.form.get('full_name', '').strip()
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')
        role = 'patient'
        phone = request.form.get('phone', '').strip()
        email = request.form.get('email', '').strip().lower()
        raw_dob = request.form.get('dob', '').strip()
        dob = parse_flexible_dob(raw_dob)
        gender = request.form.get('gender', 'Other').strip()
        blood_group = request.form.get('blood_group', '').strip()
        address = request.form.get('address', '').strip()

        errors = []
        if not username or not full_name or not password:
            errors.append('Please fill in all mandatory fields.')
        elif not validate_username(username):
            errors.append('Username must be 3-30 characters long and can only contain lowercase letters, numbers, dots (.), and underscores (_).')
        
        if not email or not validate_email(email):
            errors.append('A valid email address is required.')
        if not dob:
            errors.append('Please provide a valid date of birth between 1900 and today.')
        if not blood_group:
            errors.append('Blood group is required.')
        if password != confirm:
            errors.append('Passwords do not match.')
            
        valid_pass, pass_err = validate_password_complexity(password)
        if not valid_pass:
            errors.append(pass_err)

        existing_user = query_db('SELECT id FROM users WHERE username = %s', (username,), one=True)
        if existing_user:
            errors.append('Username is already taken.')

        existing_email = query_db('SELECT id FROM users WHERE email = %s', (email,), one=True)
        if existing_email:
            errors.append('An account with this email address already exists.')

        if errors:
            for e in errors:
                flash(e, 'error')
            return render_template('auth/signup.html', form_data=request.form)

        hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

        user_id = execute_db(
            'INSERT INTO users (username, password_hash, full_name, role, phone, email, is_active, invite_status) VALUES (%s, %s, %s, %s, %s, %s, 1, %s)',
            (username, hashed, full_name, role, phone or None, email, 'active')
        )

        user = query_db('SELECT * FROM users WHERE id = %s', (user_id,), one=True)
        
        pat_id = generate_patient_id()
        center_id = get_user_center_id(user)

        execute_db(
            'INSERT INTO patients (id, linked_user_id, full_name, dob, gender, phone, address, blood_group, center_id, allergies) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)',
            (pat_id, user['id'], full_name, dob, gender, phone or None, address or None, blood_group, center_id, json.dumps([DEFAULT_ALLERGIES]))
        )

        otp_code = str(secrets.randbelow(900000) + 100000)
        session['pending_otp'] = hash_otp(otp_code)
        session['pending_otp_expires'] = time.time() + 600
        session['pending_user_id'] = user['id']
        session['pending_email'] = email
        session['pending_fullname'] = full_name
        session['otp_attempts'] = 0
        
        send_otp_email(email, full_name, otp_code)
        log_audit('signup_initiated', 'user', user['id'])
        flash('Account created! Please enter the 6-digit verification code sent to your email.', 'info')
        return redirect(url_for('auth.verify_otp'))

    return render_template('auth/signup.html', form_data={})


@auth_bp.route('/verify-otp', methods=['GET', 'POST'])
@limiter.limit("10 per minute", methods=["POST"])
def verify_otp():
    vpn_blocked = block_if_vpn()
    if vpn_blocked:
        return vpn_blocked
    user_id = session.get('pending_user_id')
    email = session.get('pending_email')
    
    if not user_id:
        return redirect(url_for('auth.login'))

    user = query_db('SELECT * FROM users WHERE id = %s', (user_id,), one=True)
    if not user:
        session.pop('pending_user_id', None)
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        otp_entered = request.form.get('otp', '').strip()
        expected_otp = session.get('pending_otp')
        expires_at = session.get('pending_otp_expires', 0)
        attempts = session.get('otp_attempts', 0) + 1
        session['otp_attempts'] = attempts

        if not expected_otp or time.time() > expires_at:
            flash('Verification code has expired. Please request a new code.', 'error')
            return render_template('auth/verify_otp.html', email=email, user=user)

        if attempts > 5:
            session.pop('pending_otp', None)
            flash('Too many incorrect verification attempts. The code has been invalidated. Please request a new code.', 'error')
            return render_template('auth/verify_otp.html', email=email, user=user)

        if check_otp(otp_entered, expected_otp):
            execute_db('UPDATE users SET is_active = 1, failed_login_count = 0, locked_until = NULL WHERE id = %s', (user['id'],))
            flow = session.pop('otp_flow', 'signup')
            session.pop('pending_otp', None)
            session.pop('pending_otp_expires', None)
            session.pop('pending_user_id', None)
            session.pop('pending_email', None)
            session.pop('pending_fullname', None)
            session.pop('otp_attempts', None)
            
            session.clear()
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            session['session_version'] = user.get('session_version', 1)
            session['lang'] = user.get('lang_pref') or session.get('lang', 'en')
            log_audit('login_verified' if flow == 'login' else 'signup_verified', 'user', user['id'])
            create_notification(
                user['id'],
                'Security Alert: Verification Successful',
                f'You successfully verified and signed into your account on {datetime.now().strftime("%b %d, %Y at %I:%M %p")}.',
                f'/patient/@{user.get("username")}' if user.get('role') == 'patient' else '/notifications'
            )
            flash(f'Verification successful! Welcome, {user.get("full_name") or user.get("username")}.', 'success')
            return redirect(url_for('auth.app_redirect'))
        else:
            remaining = 5 - attempts
            create_notification(
                user['id'],
                'Security Alert: Failed OTP Verification',
                f'An invalid verification code attempt was made on {datetime.now().strftime("%b %d, %Y at %I:%M %p")} (Attempt {attempts}/5).',
                '/auth/login'
            )
            if remaining > 0:
                flash(f'Incorrect 6-digit verification code. {remaining} attempt(s) remaining.', 'error')
            else:
                flash('Incorrect verification code. Maximum attempts reached.', 'error')

    return render_template('auth/verify_otp.html', email=email, user=user)


@auth_bp.route('/resend-otp', methods=['POST'])
@limiter.limit("5 per minute", methods=["POST"])
def resend_otp():
    user_id = session.get('pending_user_id')
    email = session.get('pending_email')
    full_name = session.get('pending_fullname')

    if not user_id or not email:
        flash('Session expired. Please sign in or register again.', 'error')
        return redirect(url_for('auth.login'))

    otp_code = str(secrets.randbelow(900000) + 100000)
    session['pending_otp'] = hash_otp(otp_code)
    session['pending_otp_expires'] = time.time() + 600
    session['otp_attempts'] = 0

    send_otp_email(email, full_name, otp_code)
    flash(f'A fresh 6-digit verification code has been dispatched to {mask_email(email)}.', 'info')
    return redirect(url_for('auth.verify_otp'))


@auth_bp.route('/accept-invite/<token>', methods=['GET', 'POST'])
def accept_invite(token):
    if 'user_id' in session:
        session.clear()

    user = query_db('''
        SELECT u.*, c.name as facility_name 
        FROM users u 
        LEFT JOIN centers c ON u.center_id = c.id 
        WHERE u.invite_token = %s
    ''', (token,), one=True)

    if not user:
        flash('Invalid or expired staff invitation link. Please contact system admin.', 'error')
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')
        phone = request.form.get('phone', '').strip()

        valid_pass, pass_err = validate_password_complexity(password)
        if not valid_pass:
            flash(pass_err, 'error')
            return render_template('auth/accept_invite.html', user=user, token=token)

        if password != confirm:
            flash('Passwords do not match.', 'error')
            return render_template('auth/accept_invite.html', user=user, token=token)

        hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        execute_db('''
            UPDATE users 
            SET password_hash = %s, phone = COALESCE(NULLIF(%s, ''), phone), invite_status = 'active', is_active = 1, invite_token = NULL 
            WHERE id = %s
        ''', (hashed, phone, user['id']))

        session['user_id'] = user['id']
        session['role'] = user['role']
        session['session_version'] = user.get('session_version', 1)
        log_audit('staff_invite_accepted', 'user', user['id'])
        flash('Staff account successfully activated! Welcome to your clinical dashboard.', 'success')
        return redirect(url_for('auth.app_redirect'))

    return render_template('auth/accept_invite.html', user=user, token=token)


@auth_bp.route('/logout', methods=['GET', 'POST'])
def logout():
    user_id = session.get('user_id')
    if user_id:
        log_audit('logout', 'user', user_id)
        create_notification(
            user_id,
            'Security Alert: Logged Out',
            f'Your account was logged out on {datetime.now().strftime("%b %d, %Y at %I:%M %p")}.',
            '/auth/login'
        )
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.login'))


@auth_bp.route('/app')
def app_redirect():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
        
    user = get_current_user()
    if not user:
        return redirect(url_for('auth.logout'))
        
    role = user.get('role')
    
    if role == 'patient':
        return redirect(f'/patient/@{user.get("username")}')
    elif role in ('doctor', 'nurse', 'pharmacist', 'lab_technician', 'ambulance_op', 'receptionist', 'care_taker', 'helper', 'therapist'):
        return redirect(f'/phc/@{user.get("username")}')
    elif role == 'region_admin':
        return redirect('/admin/dashboard')
    elif role == 'system_admin':
        return redirect(f'/admin/@{user.get("username")}')
    else:
        return redirect(f'/phc/@{user.get("username")}')


@auth_bp.route('/admin-login', methods=['GET', 'POST'])
def admin_login():
    return login()


@auth_bp.route('/phc-login', methods=['GET', 'POST'])
def phc_login():
    return login()


@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
@limiter.limit("10 per minute; 30 per hour", methods=["POST"])
def forgot_password():
    if 'user_id' in session:
        return redirect(url_for('auth.app_redirect'))

    vpn_blocked = block_if_vpn()
    if vpn_blocked:
        return vpn_blocked

    if request.method == 'POST':
        identifier = request.form.get('identifier', '').strip()
        if not identifier:
            flash('Please enter your registered email address or username.', 'error')
            return render_template('auth/forgot_password.html', identifier=identifier)

        if '@' in identifier:
            user = query_db('SELECT * FROM users WHERE LOWER(email) = %s AND is_active = 1', (identifier.lower(),), one=True)
        else:
            user = query_db('SELECT * FROM users WHERE LOWER(username) = %s AND is_active = 1', (identifier,), one=True)

        if not user:
            log_audit('password_reset_user_not_found', 'auth', None, {'identifier': identifier})
            flash('No active account found matching the provided details.', 'error')
            return render_template('auth/forgot_password.html', identifier=identifier)

        if not user.get('email'):
            flash('This account does not have a registered email address. Please contact your system administrator.', 'error')
            return render_template('auth/forgot_password.html', identifier=identifier)

        otp_code = str(secrets.randbelow(900000) + 100000)
        session['reset_otp'] = hash_otp(otp_code)
        session['reset_otp_expires'] = time.time() + 600
        session['reset_user_id'] = user['id']
        session['reset_email'] = user['email']
        session['reset_fullname'] = user['full_name'] or user['username']
        session['reset_otp_verified'] = False
        session['reset_attempts'] = 0

        send_password_reset_email(user['email'], user['full_name'] or user['username'], otp_code)
        log_audit('password_reset_initiated', 'user', user['id'])
        flash(f'A 6-digit password reset verification code has been dispatched to {mask_email(user["email"])}.', 'info')
        return redirect(url_for('auth.reset_password'))

    return render_template('auth/forgot_password.html', identifier='')


@auth_bp.route('/reset-password', methods=['GET', 'POST'])
@limiter.limit("10 per minute", methods=["POST"])
def reset_password():
    vpn_blocked = block_if_vpn()
    if vpn_blocked:
        return vpn_blocked
    reset_user_id = session.get('reset_user_id')
    reset_email = session.get('reset_email')
    is_verified = session.get('reset_otp_verified', False)

    if not reset_user_id:
        flash('Password reset session expired or not started. Please initiate a reset request.', 'error')
        return redirect(url_for('auth.forgot_password'))

    user = query_db('SELECT * FROM users WHERE id = %s', (reset_user_id,), one=True)
    if not user:
        session.pop('reset_user_id', None)
        session.pop('reset_otp_verified', None)
        return redirect(url_for('auth.forgot_password'))

    if request.method == 'POST':
        if not is_verified:
            otp_entered = request.form.get('otp', '').strip()
            expected_otp = session.get('reset_otp')
            expires_at = session.get('reset_otp_expires', 0)
            attempts = session.get('reset_attempts', 0) + 1
            session['reset_attempts'] = attempts

            if not expected_otp or time.time() > expires_at:
                flash('The verification code has expired. Please request a new reset code.', 'error')
                return render_template('auth/reset_password.html', email=mask_email(reset_email), user=user, is_verified=False)

            if attempts > 5:
                session.pop('reset_otp', None)
                flash('Too many incorrect verification attempts. The reset code has been invalidated. Please request a new code.', 'error')
                return render_template('auth/reset_password.html', email=mask_email(reset_email), user=user, is_verified=False)

            if not check_otp(otp_entered, expected_otp):
                remaining = 5 - attempts
                flash(f'Incorrect 6-digit verification code. {remaining} attempt(s) remaining.', 'error')
                return render_template('auth/reset_password.html', email=mask_email(reset_email), user=user, is_verified=False)

            session['reset_otp_verified'] = True
            flash('Verification code confirmed! You can now create your new password.', 'success')
            return redirect(url_for('auth.reset_password'))

        else:
            new_password = request.form.get('new_password', '')
            confirm_password = request.form.get('confirm_password', '')

            valid_pass, pass_err = validate_password_complexity(new_password)
            if not valid_pass:
                flash(pass_err, 'error')
                return render_template('auth/reset_password.html', email=mask_email(reset_email), user=user, is_verified=True)

            if new_password != confirm_password:
                flash('New password and confirmation password do not match.', 'error')
                return render_template('auth/reset_password.html', email=mask_email(reset_email), user=user, is_verified=True)

            hashed = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            new_version = (user.get('session_version') or 1) + 1
            execute_db('UPDATE users SET password_hash = %s, session_version = %s, failed_login_count = 0, locked_until = NULL WHERE id = %s', 
                       (hashed, new_version, user['id']))

            session.pop('reset_otp', None)
            session.pop('reset_otp_expires', None)
            session.pop('reset_user_id', None)
            session.pop('reset_email', None)
            session.pop('reset_fullname', None)
            session.pop('reset_otp_verified', None)
            session.pop('reset_attempts', None)

            log_audit('password_reset_completed', 'user', user['id'])
            flash('Password successfully reset! You can now sign in with your new password.', 'success')
            return redirect(url_for('auth.login'))

    return render_template('auth/reset_password.html', email=mask_email(reset_email), user=user, is_verified=is_verified)


@auth_bp.route('/resend-reset-otp', methods=['POST'])
@limiter.limit("5 per minute", methods=["POST"])
def resend_reset_otp():
    reset_user_id = session.get('reset_user_id')
    reset_email = session.get('reset_email')
    reset_fullname = session.get('reset_fullname')

    if not reset_user_id or not reset_email:
        flash('Password reset session expired. Please try again.', 'error')
        return redirect(url_for('auth.forgot_password'))

    otp_code = str(secrets.randbelow(900000) + 100000)
    session['reset_otp'] = hash_otp(otp_code)
    session['reset_otp_expires'] = time.time() + 600
    session['reset_otp_verified'] = False
    session['reset_attempts'] = 0

    send_password_reset_email(reset_email, reset_fullname, otp_code)
    flash(f'A fresh 6-digit reset code has been sent to {mask_email(reset_email)}.', 'info')
    return redirect(url_for('auth.reset_password'))
