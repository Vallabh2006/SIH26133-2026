import re
import csv
import io
import json
import secrets
import bcrypt
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, jsonify, Response
from utils.auth_helpers import role_required, get_current_user
from utils.db import query_db, execute_db
from utils.audit import log_audit
from utils.email_helper import send_staff_invite_email
from utils.id_generator import generate_staff_id, generate_facility_id
from utils.sanitize import validate_username
from app import limiter

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


ROLE_DISPLAY_MAP = {
    'doctor': 'Medical Officer / Doctor',
    'nurse': 'Staff Nurse / ANM',
    'pharmacist': 'Pharmacist / Dispensary In-Charge',
    'lab_technician': 'Lab Technician / Pathologist',
    'ambulance_op': '108 Ambulance Operator / Driver',
    'receptionist': 'Registration & Front Desk',
    'care_taker': 'Care Taker / ASHA Worker',
    'helper': 'Healthcare Helper / Multi-Purpose Worker',
    'therapist': 'Physiotherapist / Specialist Therapist',
    'region_admin': 'Facility / Regional Admin',
    'system_admin': 'Master System Administrator'
}


@admin_bp.route('/')
@admin_bp.route('/dashboard')
@admin_bp.route('/@<username>')
@role_required('system_admin', 'region_admin')
def dashboard(username=None):
    user = get_current_user()
    if username and username.strip().lstrip('@') != user.get('username') and user.get('role') != 'system_admin':
        abort(403)
        
    stats = {}
    
    u_count = query_db('SELECT COUNT(*) as count FROM users', one=True)
    stats['total_users'] = u_count['count'] if u_count else 0

    staff_count = query_db("SELECT COUNT(*) as count FROM users WHERE role != 'patient'", one=True)
    stats['total_staff'] = staff_count['count'] if staff_count else 0
    
    pat_count = query_db('SELECT COUNT(*) as count FROM patients', one=True)
    stats['total_patients'] = pat_count['count'] if pat_count else 0
    
    hr_count = query_db('SELECT COUNT(*) as count FROM patients WHERE is_high_risk = 1', one=True)
    stats['high_risk_patients'] = hr_count['count'] if hr_count else 0
    
    fac_count = query_db('SELECT COUNT(*) as count FROM centers', one=True)
    stats['total_facilities'] = fac_count['count'] if fac_count else 0
    
    rec_count = query_db('SELECT COUNT(*) as count FROM medical_records', one=True)
    stats['total_records'] = rec_count['count'] if rec_count else 0
    
    rx_count = query_db('SELECT COUNT(*) as count FROM prescriptions', one=True)
    stats['total_prescriptions'] = rx_count['count'] if rx_count else 0
    
    appt_count = query_db('SELECT COUNT(*) as count FROM appointments', one=True)
    stats['total_appointments'] = appt_count['count'] if appt_count else 0
    
    low_stock = query_db('SELECT COUNT(*) as count FROM inventory_items WHERE quantity <= reorder_level', one=True)
    stats['low_stock_alerts'] = low_stock['count'] if low_stock else 0
    
    total_inv = query_db('SELECT COUNT(*) as count FROM inventory_items', one=True)
    stats['total_inventory_items'] = total_inv['count'] if total_inv else 0
    
    staff_breakdown = query_db('SELECT role, COUNT(*) as count FROM users GROUP BY role') or []
    stats['staff_breakdown'] = {item['role']: item['count'] for item in staff_breakdown}
    
    recent_audits = query_db('''
        SELECT a.*, u.username, u.full_name, u.role as user_role 
        FROM audit_logs a 
        LEFT JOIN users u ON a.user_id = u.id 
        ORDER BY a.created_at DESC 
        LIMIT 6
    ''') or []
    
    facilities_summary = query_db('''
        SELECT c.*, 
               (SELECT COUNT(*) FROM users u WHERE u.center_id = c.id) as staff_count,
               (SELECT COUNT(*) FROM inventory_items i WHERE i.center_id = c.id) as inventory_count,
               (SELECT u.username FROM users u WHERE u.center_id = c.id AND u.role = 'region_admin' LIMIT 1) as admin_username
        FROM centers c
        ORDER BY c.name ASC
    ''') or []
    
    recent_patients = query_db('''
        SELECT p.*, c.name as facility_name 
        FROM patients p 
        LEFT JOIN centers c ON p.center_id = c.id 
        ORDER BY p.created_at DESC 
        LIMIT 5
    ''') or []

    return render_template('admin/dashboard.html', 
                           current_user=user, 
                           stats=stats, 
                           recent_audits=recent_audits, 
                           facilities_summary=facilities_summary,
                           recent_patients=recent_patients)


@admin_bp.route('/staff')
@role_required('system_admin', 'region_admin')
def staff():
    user = get_current_user()
    role_filter = request.args.get('role', '').strip()
    center_filter = request.args.get('center_id', '').strip()
    status_filter = request.args.get('status', '').strip()
    search_q = request.args.get('q', '').strip()

    query = '''
        SELECT u.*, c.name as facility_name, c.type as facility_type
        FROM users u
        LEFT JOIN centers c ON u.center_id = c.id
        WHERE u.role != 'patient'
    '''
    params = []

    if user.get('role') == 'region_admin' and user.get('center_id') and not center_filter:
        center_filter = user.get('center_id')

    if role_filter and role_filter != 'all':
        query += ' AND u.role = %s'
        params.append(role_filter)

    if center_filter and center_filter != 'all':
        query += ' AND u.center_id = %s'
        params.append(center_filter)

    if status_filter == 'active':
        query += ' AND u.is_active = 1 AND u.invite_status = "active"'
    elif status_filter == 'pending':
        query += ' AND u.invite_status = "pending"'
    elif status_filter == 'inactive':
        query += ' AND u.is_active = 0'

    if search_q:
        query += ' AND (u.full_name LIKE %s OR u.username LIKE %s OR u.email LIKE %s OR u.phone LIKE %s OR u.staff_id LIKE %s)'
        params.extend([f'%{search_q}%', f'%{search_q}%', f'%{search_q}%', f'%{search_q}%', f'%{search_q}%'])

    query += ' ORDER BY u.role ASC, u.full_name ASC'
    staff_list = query_db(query, tuple(params)) or []

    metrics = {
        'total_staff': 0,
        'doctors': 0,
        'nurses': 0,
        'pharma_lab': 0,
        'ambulance': 0,
        'pending_invites': 0
    }

    all_staff_counts = query_db('''
        SELECT role, invite_status, is_active, COUNT(*) as cnt 
        FROM users 
        WHERE role != 'patient' 
        GROUP BY role, invite_status, is_active
    ''') or []

    for row in all_staff_counts:
        cnt = row['cnt']
        metrics['total_staff'] += cnt
        if row['invite_status'] == 'pending':
            metrics['pending_invites'] += cnt
        
        role = row['role']
        if role == 'doctor':
            metrics['doctors'] += cnt
        elif role == 'nurse':
            metrics['nurses'] += cnt
        elif role in ('pharmacist', 'lab_technician'):
            metrics['pharma_lab'] += cnt
        elif role == 'ambulance_op':
            metrics['ambulance'] += cnt

    centers = query_db('SELECT id, name, type FROM centers ORDER BY name ASC') or []

    return render_template('admin/staff.html',
                           current_user=user,
                           staff_list=staff_list,
                           centers=centers,
                           metrics=metrics,
                           role_filter=role_filter,
                           center_filter=center_filter,
                           status_filter=status_filter,
                           search_q=search_q,
                           role_display_map=ROLE_DISPLAY_MAP)


@admin_bp.route('/staff/register', methods=['POST'])
@role_required('system_admin', 'region_admin')
def staff_register():
    user = get_current_user()
    full_name = request.form.get('full_name', '').strip()
    email = request.form.get('email', '').strip()
    role = request.form.get('role', '').strip()
    
    if user.get('role') == 'region_admin':
        center_id = user.get('center_id')
    else:
        center_id = request.form.get('center_id', '').strip() or None
    phone = request.form.get('phone', '').strip() or None
    designation = request.form.get('designation', '').strip() or None
    custom_username = request.form.get('username', '').strip()
    custom_staff_id = request.form.get('staff_id', '').strip()

    if not full_name or not email or not role:
        flash('Full Name, Email Address, and Staff Role are mandatory.', 'error')
        return redirect(url_for('admin.staff'))

    if role not in ROLE_DISPLAY_MAP:
        flash('Invalid staff role selected.', 'error')
        return redirect(url_for('admin.staff'))

    existing_email = query_db('SELECT id FROM users WHERE email = %s', (email,), one=True)
    if existing_email:
        flash(f'An account with email {email} already exists.', 'error')
        return redirect(url_for('admin.staff'))

    if custom_username:
        username = custom_username.lower().replace(' ', '_')
        if not validate_username(username):
            flash('Username must be 3-30 characters long and can only contain lowercase letters, numbers, dots (.), and underscores (_).', 'error')
            return redirect(url_for('admin.staff'))
        if query_db('SELECT id FROM users WHERE username = %s', (username,), one=True):
            flash(f'Username @{username} is already taken. Please choose another.', 'error')
            return redirect(url_for('admin.staff'))
    else:
        base_username = full_name.lower().replace('dr.', '').replace('dr', '').strip().replace(' ', '_')
        base_username = ''.join(ch for ch in base_username if ch.isalnum() or ch == '_')[:15]
        username = base_username
        counter = 1
        while query_db('SELECT id FROM users WHERE username = %s', (username,), one=True):
            username = f'{base_username}{counter}'
            counter += 1

    if custom_staff_id:
        staff_id = custom_staff_id.strip()
        if query_db('SELECT id FROM users WHERE staff_id = %s', (staff_id,), one=True):
            flash(f'Staff ID {staff_id} is already in use.', 'error')
            return redirect(url_for('admin.staff'))
    else:
        staff_id = generate_staff_id(role)

    temp_password = secrets.token_urlsafe(8)
    hashed_password = bcrypt.hashpw(temp_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    invite_token = secrets.token_urlsafe(32)

    new_user_id = execute_db('''
        INSERT INTO users (staff_id, username, password_hash, full_name, role, center_id, phone, email, is_active, invite_status, invite_token, designation)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 1, 'pending', %s, %s)
    ''', (staff_id, username, hashed_password, full_name, role, center_id, phone, email, invite_token, designation))

    facility_row = query_db('SELECT name FROM centers WHERE id = %s', (center_id,), one=True) if center_id else None
    center_name = facility_row['name'] if facility_row else 'Regional Health Network'
    role_title = ROLE_DISPLAY_MAP.get(role, role.title())

    invite_url = request.host_url.rstrip('/') + url_for('auth.accept_invite', token=invite_token)
    email_sent = send_staff_invite_email(
        to_email=email,
        full_name=full_name,
        role_title=role_title,
        center_name=center_name,
        username=username,
        temp_password=temp_password,
        invite_url=invite_url
    )

    log_audit('staff_invite_created', 'user', new_user_id, f'Invited {role_title} @{username} to {center_name}')
    
    if email_sent:
        flash(f'Staff account for {full_name} (@{username}) created! Invitation email sent to {email}.', 'success')
    else:
        flash(f'Staff account created (@{username}). Email delivery could not be completed at this time.', 'info')

    return redirect(url_for('admin.staff'))


@admin_bp.route('/staff/resend-invite/<int:user_id>', methods=['POST'])
@role_required('system_admin', 'region_admin')
def staff_resend_invite(user_id):
    staff_member = query_db('''
        SELECT u.*, c.name as facility_name 
        FROM users u 
        LEFT JOIN centers c ON u.center_id = c.id 
        WHERE u.id = %s AND u.role != 'patient'
    ''', (user_id,), one=True)

    if not staff_member:
        flash('Staff member not found.', 'error')
        return redirect(url_for('admin.staff'))

    if not staff_member.get('email'):
        flash('Staff member has no registered email address.', 'error')
        return redirect(url_for('admin.staff'))

    invite_token = secrets.token_urlsafe(32)
    temp_password = secrets.token_urlsafe(8)
    hashed_password = bcrypt.hashpw(temp_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    execute_db('''
        UPDATE users 
        SET invite_token = %s, password_hash = %s, invite_status = 'pending' 
        WHERE id = %s
    ''', (invite_token, hashed_password, user_id))

    role_title = ROLE_DISPLAY_MAP.get(staff_member['role'], staff_member['role'].title())
    center_name = staff_member.get('facility_name') or 'Regional Health Network'
    invite_url = request.host_url.rstrip('/') + url_for('auth.accept_invite', token=invite_token)

    send_staff_invite_email(
        to_email=staff_member['email'],
        full_name=staff_member['full_name'],
        role_title=role_title,
        center_name=center_name,
        username=staff_member['username'],
        temp_password=temp_password,
        invite_url=invite_url
    )

    log_audit('staff_invite_resent', 'user', user_id)
    flash(f'Invitation resent to {staff_member["email"]} with a fresh activation link.', 'success')
    return redirect(url_for('admin.staff'))


@admin_bp.route('/staff/toggle-status/<int:user_id>', methods=['POST'])
@role_required('system_admin', 'region_admin')
def staff_toggle_status(user_id):
    staff_member = query_db("SELECT * FROM users WHERE id = %s AND role != 'patient'", (user_id,), one=True)
    if not staff_member:
        flash('Staff member not found.', 'error')
        return redirect(url_for('admin.staff'))

    new_status = 0 if staff_member['is_active'] else 1
    execute_db('UPDATE users SET is_active = %s WHERE id = %s', (new_status, user_id))

    status_label = 'activated' if new_status else 'deactivated'
    log_audit(f'staff_{status_label}', 'user', user_id)
    flash(f'Staff account for {staff_member["full_name"]} has been {status_label}.', 'info')
    return redirect(url_for('admin.staff'))


@admin_bp.route('/staff/edit/<int:user_id>', methods=['POST'])
@role_required('system_admin', 'region_admin')
def staff_edit(user_id):
    staff_member = query_db("SELECT * FROM users WHERE id = %s AND role != 'patient'", (user_id,), one=True)
    if not staff_member:
        flash('Staff member not found.', 'error')
        return redirect(url_for('admin.staff'))

    full_name = request.form.get('full_name', '').strip() or staff_member['full_name']
    phone = request.form.get('phone', '').strip() or None
    role = request.form.get('role', '').strip() or staff_member['role']
    center_id = request.form.get('center_id', '').strip() or None
    designation = request.form.get('designation', '').strip() or None

    execute_db('''
        UPDATE users 
        SET full_name = %s, phone = %s, role = %s, center_id = %s, designation = %s 
        WHERE id = %s
    ''', (full_name, phone, role, center_id, designation, user_id))

    log_audit('staff_updated', 'user', user_id)
    flash(f'Profile for {full_name} updated successfully.', 'success')
    return redirect(url_for('admin.staff'))


@admin_bp.route('/users')
@role_required('system_admin', 'region_admin')
def users():
    user = get_current_user()
    role_filter = request.args.get('role', '').strip()
    center_filter = request.args.get('center_id', '').strip()
    search_q = request.args.get('q', '').strip()
    
    query = '''
        SELECT u.*, c.name as facility_name, c.type as facility_type
        FROM users u
        LEFT JOIN centers c ON u.center_id = c.id
        WHERE 1=1
    '''
    params = []
    
    if role_filter and role_filter != 'all':
        query += ' AND u.role = %s'
        params.append(role_filter)
        
    if center_filter and center_filter != 'all':
        query += ' AND u.center_id = %s'
        params.append(center_filter)
        
    if search_q:
        query += ' AND (u.full_name LIKE %s OR u.username LIKE %s OR u.email LIKE %s OR u.phone LIKE %s)'
        params.extend([f'%{search_q}%', f'%{search_q}%', f'%{search_q}%', f'%{search_q}%'])
        
    query += ' ORDER BY u.role ASC, u.full_name ASC'
    users_list = query_db(query, tuple(params)) or []
    
    centers = query_db('SELECT id, name, type FROM centers ORDER BY name ASC') or []
    
    role_counts = query_db('SELECT role, COUNT(*) as count FROM users GROUP BY role') or []
    role_stats = {item['role']: item['count'] for item in role_counts}
    
    return render_template('admin/users.html', 
                           current_user=user, 
                           users=users_list, 
                           centers=centers, 
                           role_stats=role_stats,
                           role_filter=role_filter,
                           center_filter=center_filter,
                           search_q=search_q)


@admin_bp.route('/facilities')
@role_required('system_admin', 'region_admin')
def facilities():
    user = get_current_user()
    fac_type = request.args.get('type', '').strip()
    status_filter = request.args.get('status', '').strip()
    search_q = request.args.get('q', '').strip()
    
    query = '''
        SELECT c.*, 
               (SELECT COUNT(*) FROM users u WHERE u.center_id = c.id) as staff_count,
               (SELECT COUNT(*) FROM inventory_items i WHERE i.center_id = c.id) as inventory_count,
               (SELECT COUNT(*) FROM patients p WHERE p.center_id = c.id) as patient_count,
               (SELECT u.id FROM users u WHERE u.center_id = c.id AND u.role = 'region_admin' LIMIT 1) as admin_id,
               (SELECT u.username FROM users u WHERE u.center_id = c.id AND u.role = 'region_admin' LIMIT 1) as admin_username,
               (SELECT u.full_name FROM users u WHERE u.center_id = c.id AND u.role = 'region_admin' LIMIT 1) as admin_fullname,
               (SELECT u.email FROM users u WHERE u.center_id = c.id AND u.role = 'region_admin' LIMIT 1) as admin_email
        FROM centers c
        WHERE 1=1
    '''
    params = []
    
    if fac_type and fac_type != 'all':
        query += ' AND c.type = %s'
        params.append(fac_type)

    if status_filter == 'active':
        query += ' AND c.is_active = 1'
    elif status_filter == 'inactive':
        query += ' AND c.is_active = 0'
        
    if search_q:
        query += ' AND (c.name LIKE %s OR c.id LIKE %s OR c.region LIKE %s OR c.state LIKE %s)'
        params.extend([f'%{search_q}%', f'%{search_q}%', f'%{search_q}%', f'%{search_q}%'])
        
    query += ' ORDER BY c.name ASC'
    facilities_list = query_db(query, tuple(params)) or []

    all_staff = query_db("""
        SELECT id, staff_id, username, full_name, role, designation, phone, email, is_active, center_id
        FROM users
        WHERE center_id IS NOT NULL
        ORDER BY role ASC, full_name ASC
    """) or []

    for fac in facilities_list:
        try:
            fac['resources_parsed'] = json.loads(fac['resources']) if fac.get('resources') else {}
        except Exception:
            fac['resources_parsed'] = {}
        fac['staff_list'] = [s for s in all_staff if s.get('center_id') == fac['id']]
    
    type_counts = query_db('SELECT type, COUNT(*) as count FROM centers GROUP BY type') or []
    type_stats = {item['type']: item['count'] for item in type_counts}

    total_count_row = query_db('SELECT COUNT(*) as count FROM centers', one=True)
    total_count = total_count_row['count'] if total_count_row else 0
    active_count_row = query_db('SELECT COUNT(*) as count FROM centers WHERE is_active = 1', one=True)
    active_count = active_count_row['count'] if active_count_row else 0
    inactive_count = total_count - active_count
    
    available_admins = query_db("SELECT id, username, full_name, role, center_id FROM users WHERE role = 'region_admin' ORDER BY full_name ASC") or []

    return render_template('admin/facilities.html',
                           current_user=user,
                           facilities=facilities_list,
                           type_stats=type_stats,
                           fac_type=fac_type,
                           status_filter=status_filter,
                           search_q=search_q,
                           total_count=total_count,
                           active_count=active_count,
                           inactive_count=inactive_count,
                           available_admins=available_admins)


@admin_bp.route('/facilities/create', methods=['POST'])
@role_required('system_admin')
def create_facility():
    name = request.form.get('name', '').strip()
    fac_type = request.form.get('type', 'PHC').strip()
    region = request.form.get('region', 'Anand').strip()
    state = request.form.get('state', 'Gujarat').strip()
    address = request.form.get('address', '').strip()
    lat = request.form.get('lat', '').strip() or '22.5530000'
    lng = request.form.get('lng', '').strip() or '72.9300000'
    phone = request.form.get('phone', '').strip() or None
    
    beds = int(request.form.get('beds', 10) or 10)
    ambulance = int(request.form.get('ambulance', 1) or 1)
    oxygen = int(request.form.get('oxygen', 5) or 5)
    timings = request.form.get('timings', '24x7 Emergency / OPD 9AM - 5PM').strip()
    resources_json = json.dumps({
        'beds': beds,
        'ambulance': ambulance,
        'oxygen': oxygen,
        'timings': timings,
        'emergency_24x7': True if request.form.get('emergency_24x7') else False
    })

    if not name or not address:
        flash('Facility Name and Physical Address are mandatory.', 'error')
        return redirect(url_for('admin.facilities'))

    prefix = re.sub(r'(?i)(phc|sdh|dh|subcentre|dispensary|hospital|centre|center)', '', name.split()[0]).strip() or name[:4].upper()
    fac_id = generate_facility_id(prefix)

    execute_db('''
        INSERT INTO centers (id, name, type, region, state, address, lat, lng, phone, resources, is_active)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1)
    ''', (fac_id, name, fac_type, region, state, address, lat, lng, phone, resources_json))

    admin_mode = request.form.get('admin_mode', 'new')
    created_admin_pass = None
    if admin_mode == 'existing':
        existing_admin_id = request.form.get('assigned_admin_id')
        if existing_admin_id:
            execute_db('UPDATE users SET center_id = %s WHERE id = %s', (fac_id, existing_admin_id))
    else:
        admin_fullname = request.form.get('admin_fullname', '').strip() or f'{name} Admin'
        admin_username = request.form.get('admin_username', '').strip().lower()
        if admin_username and not validate_username(admin_username):
            flash('Facility admin username must be 3-30 characters long and can only contain lowercase letters, numbers, dots (.), and underscores (_).', 'error')
            return redirect(url_for('admin.facilities'))
        admin_email = request.form.get('admin_email', '').strip()
        admin_phone = request.form.get('admin_phone', '').strip() or phone
        admin_password = request.form.get('admin_password', '').strip()

        if not admin_password:
            admin_password = secrets.token_urlsafe(10) + '1!'
            created_admin_pass = admin_password

        if not admin_username:
            base_u = 'admin_' + ''.join(ch for ch in name.lower() if ch.isalnum())[:10]
            admin_username = base_u
            c = 1
            while query_db('SELECT id FROM users WHERE username = %s', (admin_username,), one=True):
                admin_username = f'{base_u}_{c}'
                c += 1

        if not admin_email:
            admin_email = f'{admin_username}@anvayavistara.in'

        pw_hash = bcrypt.hashpw(admin_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        staff_id = generate_staff_id('region_admin')

        execute_db('''
            INSERT INTO users (staff_id, username, password_hash, full_name, role, center_id, phone, email, is_active, invite_status, designation)
            VALUES (%s, %s, %s, %s, 'region_admin', %s, %s, %s, 1, 'active', 'Facility Administrator')
        ''', (staff_id, admin_username, pw_hash, admin_fullname, fac_id, admin_phone, admin_email))

    log_audit('facility_created', 'center', fac_id, f'Master Admin created facility {name} ({fac_id})')
    if created_admin_pass:
        flash(f'Health facility "{name}" ({fac_id}) successfully created! Assigned Admin: @{admin_username} | Temporary Password: {created_admin_pass}', 'success')
    else:
        flash(f'Health facility "{name}" ({fac_id}) successfully created and assigned to facility administrator!', 'success')
    return redirect(url_for('admin.facilities'))


@admin_bp.route('/facilities/update/<facility_id>', methods=['POST'])
@role_required('system_admin', 'region_admin')
def update_facility(facility_id):
    user = get_current_user()
    if user['role'] == 'region_admin' and user.get('center_id') != facility_id:
        flash('Unauthorized: You can only update your assigned health facility.', 'error')
        return redirect(url_for('admin.facilities'))

    facility = query_db('SELECT * FROM centers WHERE id = %s', (facility_id,), one=True)
    if not facility:
        flash('Facility not found.', 'error')
        return redirect(url_for('admin.facilities'))

    name = request.form.get('name', '').strip()
    fac_type = request.form.get('type', facility['type']).strip()
    region = request.form.get('region', facility['region'] or '').strip()
    state = request.form.get('state', facility['state'] or '').strip()
    address = request.form.get('address', facility['address'] or '').strip()
    lat = request.form.get('lat', str(facility['lat'] or '22.5530000')).strip()
    lng = request.form.get('lng', str(facility['lng'] or '72.9300000')).strip()
    phone = request.form.get('phone', facility['phone'] or '').strip() or None

    if not name or not address:
        flash('Facility Name and Physical Address are mandatory.', 'error')
        return redirect(url_for('admin.facilities'))

    beds = int(request.form.get('beds', 0) or 0)
    oxygen = int(request.form.get('oxygen', 0) or 0)
    ambulance = int(request.form.get('ambulance', 0) or 0)
    timings = request.form.get('timings', '24x7 Emergency / OPD 9AM - 5PM').strip()
    emergency_24x7 = True if (request.form.get('emergency_24x7') in ('1', 'on', 'true', True)) else False
    is_active = 1 if (request.form.get('is_active') in ('1', 'on', 'true', 1)) else 0

    curr_resources = {}
    if facility.get('resources'):
        try:
            curr_resources = json.loads(facility['resources'])
        except Exception:
            pass
    curr_resources.update({
        'beds': beds,
        'oxygen': oxygen,
        'ambulance': ambulance,
        'timings': timings,
        'emergency_24x7': emergency_24x7
    })
    resources_json = json.dumps(curr_resources)

    execute_db('''
        UPDATE centers
        SET name = %s, type = %s, region = %s, state = %s, address = %s,
            lat = %s, lng = %s, phone = %s, resources = %s, is_active = %s, updated_at = NOW()
        WHERE id = %s
    ''', (name, fac_type, region, state, address, lat, lng, phone, resources_json, is_active, facility_id))

    if user['role'] == 'system_admin' and 'assigned_admin_id' in request.form:
        assigned_admin_id = request.form.get('assigned_admin_id', '').strip()
        if assigned_admin_id == 'unassign':
            execute_db("UPDATE users SET center_id = NULL WHERE center_id = %s AND role = 'region_admin'", (facility_id,))
        elif assigned_admin_id.isdigit():
            execute_db("UPDATE users SET center_id = NULL WHERE center_id = %s AND role = 'region_admin'", (facility_id,))
            execute_db("UPDATE users SET center_id = %s WHERE id = %s", (facility_id, int(assigned_admin_id)))

    log_audit('facility_updated', 'center', facility_id, f'Admin @{user["username"]} updated facility {name} ({facility_id})')
    flash(f'Facility "{name}" ({facility_id}) details and resources successfully updated.', 'success')
    return redirect(url_for('admin.facilities'))


@admin_bp.route('/facilities/toggle-status/<facility_id>', methods=['POST'])
@role_required('system_admin')
def toggle_facility_status(facility_id):
    facility = query_db('SELECT * FROM centers WHERE id = %s', (facility_id,), one=True)
    if not facility:
        flash('Facility not found.', 'error')
        return redirect(url_for('admin.facilities'))

    new_status = 0 if facility.get('is_active') else 1
    execute_db('UPDATE centers SET is_active = %s, updated_at = NOW() WHERE id = %s', (new_status, facility_id))

    status_label = 'Activated' if new_status == 1 else 'Deactivated'
    log_audit('facility_status_toggled', 'center', facility_id, f'Master Admin {status_label.lower()} facility {facility["name"]} ({facility_id})')
    flash(f'Facility "{facility["name"]}" ({facility_id}) has been {status_label}.', 'success')
    return redirect(url_for('admin.facilities'))


@admin_bp.route('/facilities/reset-staff-password/<int:user_id>', methods=['POST'])
@role_required('system_admin', 'region_admin')
def reset_facility_staff_password(user_id):
    current_admin = get_current_user()
    target_user = query_db('SELECT * FROM users WHERE id = %s', (user_id,), one=True)
    if not target_user:
        flash('Staff member account not found.', 'error')
        return redirect(url_for('admin.facilities'))

    if current_admin['role'] == 'region_admin':
        if target_user.get('center_id') != current_admin.get('center_id'):
            flash('Unauthorized: You can only reset passwords for staff assigned to your facility.', 'error')
            return redirect(url_for('admin.facilities'))

    new_password = request.form.get('new_password', '').strip()
    was_auto_generated = False
    if not new_password:
        new_password = secrets.token_urlsafe(10) + '1!'
        was_auto_generated = True
    elif len(new_password) < 8:
        flash('Password must be at least 8 characters long.', 'error')
        return redirect(url_for('admin.facilities'))

    hashed = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    new_version = (target_user.get('session_version') or 1) + 1
    execute_db('UPDATE users SET password_hash = %s, session_version = %s, failed_login_count = 0, locked_until = NULL, updated_at = NOW() WHERE id = %s', 
               (hashed, new_version, user_id))

    admin_name = current_admin.get('username') if current_admin else 'admin'
    log_audit('password_reset_by_admin', 'user', user_id, f'Admin @{admin_name} reset password for @{target_user["username"]}')

    if was_auto_generated:
        flash(f'Password for @{target_user["username"]} ({target_user.get("full_name") or target_user["username"]}) reset to: {new_password}', 'success')
    else:
        flash(f'Password for @{target_user["username"]} has been successfully updated.', 'success')
    return redirect(url_for('admin.facilities'))


@admin_bp.route('/inventory')
@role_required('system_admin', 'region_admin')
def inventory():
    user = get_current_user()
    center_filter = request.args.get('center_id', '').strip()
    stock_status = request.args.get('status', '').strip()
    category_filter = request.args.get('category', '').strip()
    search_q = request.args.get('q', '').strip()
    
    if user.get('role') == 'region_admin' and user.get('center_id') and not center_filter:
        center_filter = user.get('center_id')

    query = '''
        SELECT i.*, c.name as facility_name, c.type as facility_type
        FROM inventory_items i
        JOIN centers c ON i.center_id = c.id
        WHERE 1=1
    '''
    params = []
    
    if center_filter and center_filter != 'all':
        query += ' AND i.center_id = %s'
        params.append(center_filter)
        
    if category_filter and category_filter != 'all':
        query += ' AND i.category = %s'
        params.append(category_filter)
        
    if stock_status == 'low':
        query += ' AND i.quantity <= i.reorder_level AND i.quantity > 0'
    elif stock_status == 'out':
        query += ' AND i.quantity = 0'
    elif stock_status == 'adequate':
        query += ' AND i.quantity > i.reorder_level'
        
    if search_q:
        query += ' AND (i.item_name LIKE %s OR i.category LIKE %s)'
        params.extend([f'%{search_q}%', f'%{search_q}%'])
        
    query += ' ORDER BY (i.quantity <= i.reorder_level) DESC, i.item_name ASC'
    items = query_db(query, tuple(params)) or []
    
    centers = query_db('SELECT id, name, type FROM centers ORDER BY name ASC') or []
    categories_raw = query_db("SELECT DISTINCT category FROM inventory_items WHERE category IS NOT NULL AND category != '' ORDER BY category ASC") or []
    categories = [c['category'] for c in categories_raw if c.get('category')]
    
    summary = {
        'total_items': len(items),
        'low_stock': sum(1 for item in items if item['quantity'] <= item['reorder_level'] and item['quantity'] > 0),
        'out_of_stock': sum(1 for item in items if item['quantity'] == 0),
        'total_quantity': sum(item['quantity'] for item in items)
    }
    
    return render_template('admin/inventory.html',
                           current_user=user,
                           items=items,
                           inventory=items,
                           centers=centers,
                           categories=categories,
                           summary=summary,
                           total_count=summary['total_items'],
                           low_stock_count=summary['low_stock'],
                           out_of_stock_count=summary['out_of_stock'],
                           selected_center_id=center_filter or 'all',
                           center_filter=center_filter or 'all',
                           status_filter=stock_status,
                           stock_status=stock_status,
                           category_filter=category_filter,
                           search_q=search_q)


@admin_bp.route('/inventory/export')
@role_required('system_admin', 'region_admin')
def export_inventory_csv():
    center_filter = request.args.get('center_id', '').strip()
    
    query = '''
        SELECT i.*, c.name as facility_name
        FROM inventory_items i
        JOIN centers c ON i.center_id = c.id
        WHERE 1=1
    '''
    params = []
    
    if center_filter and center_filter != 'all':
        query += ' AND i.center_id = %s'
        params.append(center_filter)
        
    query += ' ORDER BY c.name ASC, i.item_name ASC'
    items = query_db(query, tuple(params)) or []
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'Center ID', 
        'Center Name', 
        'Item Name', 
        'Category', 
        'Quantity', 
        'Unit', 
        'Reorder Level', 
        'Expiry Date', 
        'Stock Status'
    ])
    
    for item in items:
        status = 'Out of Stock' if item['quantity'] == 0 else ('Low Stock' if item['quantity'] <= item['reorder_level'] else 'Adequate')
        writer.writerow([
            item.get('center_id', ''),
            item.get('facility_name', ''),
            item.get('item_name', ''),
            item.get('category', ''),
            item.get('quantity', 0),
            item.get('unit', ''),
            item.get('reorder_level', 0),
            str(item.get('expiry_date') or ''),
            status
        ])
        
    output.seek(0)
    filename = f'inventory_export_{center_filter or "all_centers"}.csv'
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )


@admin_bp.route('/inventory/import', methods=['POST'])
@limiter.limit("30 per hour")
@role_required('system_admin', 'region_admin')
def import_inventory_csv():
    if 'file' not in request.files:
        flash('No file uploaded.', 'error')
        return redirect(url_for('admin.inventory'))
        
    file = request.files['file']
    if not file.filename.endswith('.csv'):
        flash('Please upload a valid CSV file.', 'error')
        return redirect(url_for('admin.inventory'))

    if request.content_length and request.content_length > 5 * 1024 * 1024:
        flash('Uploaded file exceeds 5MB limit.', 'error')
        return redirect(url_for('admin.inventory'))
        
    center_id_default = request.form.get('center_id', '').strip()
    
    try:
        stream = io.StringIO(file.stream.read().decode('utf-8-sig'), newline=None)
        reader = csv.DictReader(stream)
        
        imported_count = 0
        updated_count = 0
        
        for row in reader:
            normalized_row = {k.strip().lower().replace(' ', '_'): v.strip() for k, v in row.items() if k}
            
            c_id = normalized_row.get('center_id') or center_id_default
            item_name = normalized_row.get('item_name') or normalized_row.get('name')
            category = normalized_row.get('category', 'General Supplies')
            quantity_val = int(normalized_row.get('quantity', 0) or 0)
            unit_val = normalized_row.get('unit', 'units')
            reorder_val = int(normalized_row.get('reorder_level', 10) or 10)
            expiry_val = normalized_row.get('expiry_date') or None
            
            if not c_id or not item_name:
                continue
                
            center_exists = query_db('SELECT id FROM centers WHERE id = %s', (c_id,), one=True)
            if not center_exists:
                continue
                
            existing_item = query_db('SELECT id, quantity FROM inventory_items WHERE center_id = %s AND item_name = %s', (c_id, item_name), one=True)
            
            if existing_item:
                new_qty = existing_item['quantity'] + quantity_val
                execute_db('''
                    UPDATE inventory_items 
                    SET quantity = %s, category = %s, unit = %s, reorder_level = %s, expiry_date = %s 
                    WHERE id = %s
                ''', (new_qty, category, unit_val, reorder_val, expiry_val, existing_item['id']))
                updated_count += 1
            else:
                execute_db('''
                    INSERT INTO inventory_items (center_id, item_name, category, quantity, unit, reorder_level, expiry_date)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                ''', (c_id, item_name, category, quantity_val, unit_val, reorder_val, expiry_val))
                imported_count += 1
                
        flash(f'Inventory CSV processed: {imported_count} new items added, {updated_count} existing items restocked/updated.', 'success')
        
    except Exception as e:
        flash(f'Error processing CSV file: {str(e)}', 'error')
        
    return redirect(url_for('admin.inventory', center_id=center_id_default if center_id_default else None))


@admin_bp.route('/inventory/template')
@role_required('system_admin', 'region_admin')
def download_inventory_template():
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['center_id', 'item_name', 'category', 'quantity', 'unit', 'reorder_level', 'expiry_date'])
    writer.writerow(['FAC-BAKROL-01', 'Paracetamol 500mg Tablets', 'Analgesic', '500', 'tablets', '100', '2027-12-31'])
    writer.writerow(['FAC-BAKROL-01', 'Amoxicillin 250mg Capsules', 'Antibiotic', '250', 'capsules', '50', '2027-06-30'])
    writer.writerow(['FAC-SKH-02', 'Normal Saline 0.9% IV 500ml', 'IV Fluids', '100', 'bottles', '30', '2027-10-31'])
    
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=inventory_import_template.csv'}
    )


@admin_bp.route('/audit-logs')
@role_required('system_admin', 'region_admin')
def audit_logs():
    user = get_current_user()
    action_filter = request.args.get('action', '').strip()
    user_filter = request.args.get('user_id', '').strip()
    search_q = request.args.get('q', '').strip()
    
    query = '''
        SELECT a.*, u.username, u.full_name, u.role as user_role
        FROM audit_logs a
        LEFT JOIN users u ON a.user_id = u.id
        WHERE 1=1
    '''
    params = []
    
    if action_filter and action_filter != 'all':
        query += ' AND a.action = %s'
        params.append(action_filter)
        
    if user_filter:
        query += ' AND a.user_id = %s'
        params.append(user_filter)
        
    if search_q:
        query += ' AND (a.action LIKE %s OR a.entity_type LIKE %s OR a.details LIKE %s OR u.username LIKE %s OR u.full_name LIKE %s)'
        params.extend([f'%{search_q}%', f'%{search_q}%', f'%{search_q}%', f'%{search_q}%', f'%{search_q}%'])
        
    query += ' ORDER BY a.created_at DESC LIMIT 200'
    logs = query_db(query, tuple(params)) or []
    
    actions = query_db('SELECT DISTINCT action FROM audit_logs ORDER BY action ASC') or []
    
    return render_template('admin/audit_logs.html',
                           current_user=user,
                           logs=logs,
                           actions=actions,
                           action_filter=action_filter,
                           user_filter=user_filter,
                           search_q=search_q)


@admin_bp.route('/audit-logs/export')
@role_required('system_admin', 'region_admin')
def export_audit_logs_csv():
    action_filter = request.args.get('action', '').strip()
    
    query = '''
        SELECT a.*, u.username, u.full_name, u.role as user_role
        FROM audit_logs a
        LEFT JOIN users u ON a.user_id = u.id
        WHERE 1=1
    '''
    params = []
    if action_filter and action_filter != 'all':
        query += ' AND a.action = %s'
        params.append(action_filter)
        
    query += ' ORDER BY a.created_at DESC LIMIT 1000'
    logs = query_db(query, tuple(params)) or []
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Timestamp', 'User ID', 'Username', 'Full Name', 'Role', 'Action', 'Entity Type', 'Entity ID', 'Details', 'IP Address'])
    
    for log in logs:
        writer.writerow([
            str(log.get('created_at', '')),
            log.get('user_id', ''),
            log.get('username', ''),
            log.get('full_name', ''),
            log.get('user_role', ''),
            log.get('action', ''),
            log.get('entity_type', ''),
            log.get('entity_id', ''),
            log.get('details', ''),
            log.get('ip_address', '')
        ])
        
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=audit_logs_export.csv'}
    )


@admin_bp.route('/analytics')
@admin_bp.route('/surveillance')
@role_required('system_admin', 'region_admin')
def analytics():
    user = get_current_user()
    
    total_patients = (query_db('SELECT COUNT(*) as cnt FROM patients', one=True) or {}).get('cnt', 0)
    high_risk_count = (query_db('SELECT COUNT(*) as cnt FROM patients WHERE is_high_risk = 1', one=True) or {}).get('cnt', 0)
    
    gender_rows = query_db('SELECT gender, COUNT(*) as cnt FROM patients WHERE gender IS NOT NULL GROUP BY gender') or []
    gender_tally = {r['gender']: r['cnt'] for r in gender_rows}
    
    blood_rows = query_db("SELECT blood_group, COUNT(*) as cnt FROM patients WHERE blood_group IS NOT NULL AND blood_group != '' GROUP BY blood_group") or []
    blood_tally = {r['blood_group']: r['cnt'] for r in blood_rows}
    if not blood_tally:
        blood_tally = {'A+': 0, 'B+': 0, 'O+': 0, 'AB+': 0, 'A-': 0, 'B-': 0, 'O-': 0, 'AB-': 0}
        
    conditions_rows = query_db("SELECT chronic_conditions FROM patients WHERE chronic_conditions IS NOT NULL AND chronic_conditions != ''") or []
    conditions_tally = {}
    for r in conditions_rows:
        conds = [c.strip() for c in r['chronic_conditions'].split(',') if c.strip()]
        for c in conds:
            conditions_tally[c] = conditions_tally.get(c, 0) + 1
            
    top_meds_tally = {}
    rx_rows = query_db("SELECT medicines FROM prescriptions WHERE medicines IS NOT NULL AND medicines != ''") or []
    import json
    for r in rx_rows:
        try:
            med_data = json.loads(r['medicines'])
            if isinstance(med_data, list):
                for m in med_data:
                    m_name = (m.get('name') or m.get('item_name') or m.get('medicine')) if isinstance(m, dict) else str(m)
                    if m_name:
                        top_meds_tally[m_name] = top_meds_tally.get(m_name, 0) + 1
        except Exception:
            for m in r['medicines'].split(','):
                m_clean = m.strip()
                if m_clean:
                    top_meds_tally[m_clean] = top_meds_tally.get(m_clean, 0) + 1
    
    if top_meds_tally:
        top_meds = sorted(top_meds_tally.items(), key=lambda x: x[1], reverse=True)[:8]
    else:
        inv_items = query_db('SELECT item_name, quantity FROM inventory_items ORDER BY quantity DESC LIMIT 8') or []
        top_meds = [(i['item_name'], i['quantity']) for i in inv_items]
    
    patient_stats = {
        'total': total_patients,
        'high_risk': high_risk_count,
        'active_last_30_days': (query_db("SELECT COUNT(DISTINCT patient_id) as cnt FROM medical_records WHERE created_at >= NOW() - INTERVAL '30 days'", one=True) or {}).get('cnt', 0)
    }
    
    facility_activity = query_db('''
        SELECT c.id, c.name, c.type,
               COUNT(DISTINCT m.id) as records_count,
               COUNT(DISTINCT p.id) as prescriptions_count,
               COUNT(DISTINCT a.id) as appointments_count
        FROM centers c
        LEFT JOIN medical_records m ON m.center_id = c.id
        LEFT JOIN prescriptions p ON p.center_id = c.id
        LEFT JOIN appointments a ON a.center_id = c.id
        GROUP BY c.id, c.name, c.type
        ORDER BY records_count DESC
    ''') or []
    
    disease_surveillance = query_db('''
        SELECT m.record_type as category, COUNT(*) as case_count 
        FROM medical_records m 
        WHERE m.record_type IS NOT NULL 
        GROUP BY m.record_type 
        ORDER BY case_count DESC 
        LIMIT 10
    ''') or []
    
    appointment_stats = {
        'total': (query_db('SELECT COUNT(*) as cnt FROM appointments', one=True) or {}).get('cnt', 0),
        'scheduled': (query_db("SELECT COUNT(*) as cnt FROM appointments WHERE status = 'scheduled'", one=True) or {}).get('cnt', 0),
        'completed': (query_db("SELECT COUNT(*) as cnt FROM appointments WHERE status = 'completed'", one=True) or {}).get('cnt', 0),
        'cancelled': (query_db("SELECT COUNT(*) as cnt FROM appointments WHERE status = 'cancelled'", one=True) or {}).get('cnt', 0)
    }
    
    return render_template('admin/analytics.html',
                           current_user=user,
                           total_patients=total_patients,
                           high_risk_count=high_risk_count,
                           gender_tally=gender_tally,
                           blood_tally=blood_tally,
                           conditions_tally=conditions_tally,
                           top_meds=top_meds,
                           patient_stats=patient_stats,
                           facility_activity=facility_activity,
                           disease_surveillance=disease_surveillance,
                           appointment_stats=appointment_stats)


@admin_bp.route('/reports')
@role_required('system_admin', 'region_admin')
def reports():
    user = get_current_user()
    return render_template('admin/reports.html', current_user=user)


PERMISSION_CAPABILITIES = {
    'system_admin': {
        'title': 'Master System Administrator',
        'badge_color': '#dc2626',
        'scope': 'Universal / Entire Health Network',
        'capabilities': [
            'System Security & Global Audit Governance',
            'Permission Management & Role Reassignment',
            'Provision New Health Centers & Assign Admins',
            'Centralized Multi-Facility Inventory Oversight',
            'Network-wide Epidemiological Surveillance & Reports'
        ]
    },
    'region_admin': {
        'title': 'Facility / Center Administrator',
        'badge_color': '#b45309',
        'scope': 'Designated Primary Health Centre / Hospital',
        'capabilities': [
            'Center Staff Onboarding & Account Management',
            'Local Pharmacy Inventory & Supply Audits',
            'Outpatient Appointment Queues & Triage',
            'Inter-Facility Patient Referrals Routing',
            'Facility Operations & Log Monitoring'
        ]
    },
    'doctor': {
        'title': 'Medical Officer / Physician',
        'badge_color': '#0284c7',
        'scope': 'Clinical Consultations & EHR',
        'capabilities': [
            'Conduct Outpatient Clinical Consultations',
            'Author & Sign Electronic Health Records (EHR)',
            'Prescribe Medications & Diagnostic Orders',
            'Conduct Remote Teleconsultations',
            'Initiate Emergency & Higher-Tier Referrals'
        ]
    },
    'nurse': {
        'title': 'Staff Nurse / Nursing Officer',
        'badge_color': '#16a34a',
        'scope': 'Clinical Care & Vitals',
        'capabilities': [
            'Patient Intake & Physiological Vitals Recording',
            'Manage Outpatient Clinic Queues',
            'Assist Medical Consultations & Care Follow-ups',
            'Record Nursing Notes & Clinical Observations',
            'Monitor High-Risk Patient Registries'
        ]
    },
    'pharmacist': {
        'title': 'Pharmacist / Dispensary Specialist',
        'badge_color': '#7c3aed',
        'scope': 'Pharmacy & Supply Chain',
        'capabilities': [
            'Dispense Doctor Prescriptions to Patients',
            'Maintain Medicine Stock & Expiry Tracking',
            'Bulk CSV Inventory Import & Export',
            'Trigger Low-Stock Alerts & Reorder Points',
            'Review Pharmaceutical Utilization'
        ]
    },
    'lab_technician': {
        'title': 'Laboratory Specialist / Pathologist',
        'badge_color': '#0891b2',
        'scope': 'Diagnostics & Lab Reports',
        'capabilities': [
            'Process Diagnostic Lab & Specimen Orders',
            'Publish Test Results & Pathology Records',
            'Maintain Clinical Laboratory Logbooks',
            'Upload Diagnostic Imagery & Reports'
        ]
    },
    'ambulance_op': {
        'title': '108 Emergency Ambulance Operator',
        'badge_color': '#ea580c',
        'scope': 'Emergency Care & Fleet',
        'capabilities': [
            'Receive 108 Emergency SOS Dispatches',
            'Real-Time GPS Location Broadcasting',
            'Emergency En-Route Patient Triage',
            'Coordinate Rapid Hospital Emergency Admissions'
        ]
    },
    'receptionist': {
        'title': 'Registration & Front Desk Officer',
        'badge_color': '#475569',
        'scope': 'Front Desk & Patient Intake',
        'capabilities': [
            'Register In-Person Walk-In Patients',
            'Schedule & Check-In Outpatient Appointments',
            'Route Patients to Clinical Triage & Queues',
            'Issue Digital Health IDs & QR Cards'
        ]
    },
    'care_taker': {
        'title': 'Care Taker / ASHA Worker',
        'badge_color': '#059669',
        'scope': 'Community Health & Maternal Care',
        'capabilities': [
            'Community Healthcare Outreach',
            'Maternal & Child Health Monitoring',
            'Immunization Drive Coordination',
            'Primary Health Centre Liaison'
        ]
    },
    'patient': {
        'title': 'Registered Patient',
        'badge_color': '#2563eb',
        'scope': 'Self-Service Health Portal',
        'capabilities': [
            'View Lifetime Personal Electronic Health Records',
            'Request Appointments & Teleconsultations',
            'Access Interactive Health Network Map',
            'Trigger 108 Emergency SOS & Ambulance Help'
        ]
    }
}


@admin_bp.route('/permissions')
@role_required('system_admin')
def permissions():
    user = get_current_user()
    role_filter = request.args.get('role', '').strip()
    center_filter = request.args.get('center_id', '').strip()
    search_q = request.args.get('q', '').strip()

    query = '''
        SELECT u.*, c.name as facility_name, c.type as facility_type
        FROM users u
        LEFT JOIN centers c ON u.center_id = c.id
        WHERE 1=1
    '''
    params = []

    if role_filter and role_filter != 'all':
        query += ' AND u.role = %s'
        params.append(role_filter)

    if center_filter and center_filter != 'all':
        query += ' AND u.center_id = %s'
        params.append(center_filter)

    if search_q:
        query += ' AND (u.full_name LIKE %s OR u.username LIKE %s OR u.email LIKE %s OR u.phone LIKE %s)'
        params.extend([f'%{search_q}%', f'%{search_q}%', f'%{search_q}%', f'%{search_q}%'])

    role_order = """
        CASE u.role
            WHEN 'system_admin' THEN 1
            WHEN 'region_admin' THEN 2
            WHEN 'doctor' THEN 3
            WHEN 'nurse' THEN 4
            WHEN 'pharmacist' THEN 5
            WHEN 'lab_technician' THEN 6
            WHEN 'ambulance_op' THEN 7
            WHEN 'receptionist' THEN 8
            WHEN 'care_taker' THEN 9
            WHEN 'helper' THEN 10
            WHEN 'therapist' THEN 11
            ELSE 12
        END
    """
    query += f' ORDER BY {role_order}, u.full_name ASC'
    users_list = query_db(query, tuple(params)) or []

    centers = query_db('SELECT id, name, type FROM centers ORDER BY name ASC') or []
    
    role_counts_raw = query_db('SELECT role, COUNT(*) as cnt FROM users GROUP BY role') or []
    role_counts = {r['role']: r['cnt'] for r in role_counts_raw}

    from utils.permissions import SYSTEM_ACTIONS, ALL_ROLES, get_permissions_matrix
    permissions_matrix = get_permissions_matrix()
    
    return render_template('admin/permissions.html',
                           current_user=user,
                           users=users_list,
                           centers=centers,
                           role_filter=role_filter,
                           center_filter=center_filter,
                           search_q=search_q,
                           role_counts=role_counts,
                           role_matrix=PERMISSION_CAPABILITIES,
                           system_actions=SYSTEM_ACTIONS,
                           all_roles=ALL_ROLES,
                           permissions_matrix=permissions_matrix)


@admin_bp.route('/permissions/save-matrix', methods=['POST'])
@role_required('system_admin')
def save_permission_matrix():
    from utils.permissions import SYSTEM_ACTIONS, ALL_ROLES
    for r_tuple in ALL_ROLES:
        r_key = r_tuple[0]
        for a_obj in SYSTEM_ACTIONS:
            a_key = a_obj['key']
            field_name = f'perm_{r_key}_{a_key}'
            is_allowed = 1 if request.form.get(field_name) else 0
            
            if r_key == 'system_admin':
                is_allowed = 1
                
            execute_db('''
                INSERT INTO role_permissions (role, action, is_allowed) VALUES (%s, %s, %s) ON CONFLICT (role, action) DO UPDATE SET is_allowed = EXCLUDED.is_allowed
            ''', (r_key, a_key, is_allowed))
            
    log_audit('permission_matrix_updated', 'system', 0, 'Action permission matrix updated by Master Admin')
    flash('Role Action Permission Matrix successfully updated and deployed across the platform.', 'success')
    return redirect(url_for('admin.permissions'))


@admin_bp.route('/permissions/update-role/<int:user_id>', methods=['POST'])
@role_required('system_admin')
def update_user_permission(user_id):
    target_user = query_db('SELECT * FROM users WHERE id = %s', (user_id,), one=True)
    if not target_user:
        flash('User account not found.', 'error')
        return redirect(url_for('admin.permissions'))

    new_role = request.form.get('role', '').strip()
    new_center_id = request.form.get('center_id', '').strip() or None
    new_designation = request.form.get('designation', '').strip() or None

    if target_user['username'] == 'admin' and new_role != 'system_admin':
        flash('The primary master administrator account cannot be demoted.', 'error')
        return redirect(url_for('admin.permissions'))

    if new_role not in PERMISSION_CAPABILITIES:
        flash('Invalid role specification.', 'error')
        return redirect(url_for('admin.permissions'))

    execute_db('''
        UPDATE users 
        SET role = %s, center_id = %s, designation = %s, updated_at = NOW()
        WHERE id = %s
    ''', (new_role, new_center_id, new_designation, user_id))

    log_audit('permission_role_updated', 'user', user_id, f'Role changed from {target_user["role"]} to {new_role} by Master Admin')
    flash(f'Permissions and role for @{target_user["username"]} updated to {new_role}.', 'success')
    return redirect(url_for('admin.permissions'))


@admin_bp.route('/permissions/toggle-status/<int:user_id>', methods=['POST'])
@role_required('system_admin')
def toggle_user_permission_status(user_id):
    target_user = query_db('SELECT * FROM users WHERE id = %s', (user_id,), one=True)
    if not target_user:
        flash('User account not found.', 'error')
        return redirect(url_for('admin.permissions'))

    if target_user['username'] == 'admin':
        flash('The primary master administrator account cannot be suspended.', 'error')
        return redirect(url_for('admin.permissions'))

    new_status = 0 if target_user['is_active'] else 1
    execute_db('UPDATE users SET is_active = %s, updated_at = NOW() WHERE id = %s', (new_status, user_id))

    status_str = 'Activated' if new_status == 1 else 'Suspended'
    log_audit('permission_status_toggled', 'user', user_id, f'Account status set to {status_str}')
    flash(f'Account @{target_user["username"]} has been {status_str}.', 'success')
    return redirect(url_for('admin.permissions'))


@admin_bp.route('/permissions/reset-password/<int:user_id>', methods=['POST'])
@role_required('system_admin')
def reset_user_password(user_id):
    target_user = query_db('SELECT * FROM users WHERE id = %s', (user_id,), one=True)
    if not target_user:
        flash('User account not found.', 'error')
        return redirect(url_for('admin.permissions'))

    new_password = request.form.get('new_password', '').strip()
    if not new_password or len(new_password) < 8:
        flash('Password must be at least 8 characters long.', 'error')
        return redirect(url_for('admin.permissions'))

    hashed = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    new_version = (target_user.get('session_version') or 1) + 1
    execute_db('UPDATE users SET password_hash = %s, session_version = %s, failed_login_count = 0, locked_until = NULL, updated_at = NOW() WHERE id = %s', (hashed, new_version, user_id))

    current_admin = get_current_user()
    admin_name = current_admin.get('username') if current_admin else 'admin'
    log_audit('password_reset_by_master_admin', 'user', user_id, f'Admin @{admin_name} reset password for @{target_user["username"]}')
    flash(f'Password for @{target_user["username"]} has been successfully reset.', 'success')
    return redirect(url_for('admin.permissions'))


@admin_bp.route('/referrals')
@role_required('system_admin', 'region_admin')
def referrals():
    user = get_current_user()
    status_filter = request.args.get('status', '').strip()
    urgency_filter = request.args.get('urgency', '').strip()

    query = """
        SELECT r.*, p.full_name as patient_name, p.gender, p.dob, p.blood_group,
               c_to.name as to_center_name, c_to.type as to_center_type,
               c_from.name as from_center_name, c_from.type as from_center_type,
               u.full_name as created_by_name, acc.full_name as accepted_by_name
        FROM referrals r
        LEFT JOIN patients p ON r.patient_id = p.id
        LEFT JOIN centers c_to ON r.to_center = c_to.id
        LEFT JOIN centers c_from ON r.from_center = c_from.id
        LEFT JOIN users u ON r.created_by = u.id
        LEFT JOIN users acc ON r.accepted_by = acc.id
        WHERE 1=1
    """
    params = []
    if status_filter:
        query += " AND r.status = %s"
        params.append(status_filter)
    if urgency_filter:
        query += " AND r.urgency = %s"
        params.append(urgency_filter)

    query += " ORDER BY CASE r.urgency WHEN 'critical' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 ELSE 4 END, r.created_at DESC"

    referrals_list = query_db(query, tuple(params)) or []

    all_refs = query_db("SELECT status, urgency FROM referrals") or []
    stats = {
        'total': len(all_refs),
        'active_transfers': len([r for r in all_refs if r['status'] in ('initiated', 'accepted', 'in_transit')]),
        'critical': len([r for r in all_refs if r['urgency'] == 'critical']),
        'in_transit': len([r for r in all_refs if r['status'] == 'in_transit']),
        'completed': len([r for r in all_refs if r['status'] in ('completed', 'counter_referred')])
    }

    centers_list = query_db('SELECT id, name, type FROM centers ORDER BY name ASC') or []
    ambulances = query_db("SELECT id, driver_name, driver_phone, status, center_id FROM vehicles WHERE type = 'ambulance'") or []

    return render_template('admin/referrals.html', current_user=user, referrals=referrals_list,
                           centers_list=centers_list, ambulances=ambulances, stats=stats)
