from blueprints.auth import parse_flexible_dob
from utils.id_generator import generate_patient_id
from utils.notifications import create_notification, notify_patient
import json
from datetime import datetime, date, timedelta
from flask import Blueprint, render_template, redirect, url_for, abort, request, flash
from utils.auth_helpers import login_required, get_current_user
from utils.db import query_db, execute_db
from utils.defaults import get_user_center_id
from utils.constants import DEFAULT_ALLERGIES, DEFAULT_DISTRICT, DEFAULT_DEPARTMENT, DEFAULT_ONLINE_REASON
from utils.audit import log_audit

patient_bp = Blueprint('patient', __name__, url_prefix='/patient', template_folder='../../templates/patient')


def format_patient_meta(patient):
    if not patient:
        return patient
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
        
    conditions = patient.get('chronic_conditions')
    if isinstance(conditions, str):
        try:
            parsed = json.loads(conditions)
            patient['conditions_list'] = parsed if isinstance(parsed, list) else [str(parsed)]
        except Exception:
            patient['conditions_list'] = [conditions]
    elif isinstance(conditions, list):
        patient['conditions_list'] = conditions
    else:
        patient['conditions_list'] = []
    return patient


@patient_bp.route('/')
@patient_bp.route('/dashboard')
@patient_bp.route('/@<username>')
@login_required
def user_profile(username=None):
    user = get_current_user()
    
    if not username and user.get('role') != 'patient':
        search_q = request.args.get('q', '').strip()
        center_filter = request.args.get('center_id', 'all').strip()
        risk_filter = request.args.get('risk', 'all').strip()
        gender_filter = request.args.get('gender', 'all').strip()
        
        query = """
            SELECT p.*, c.name as facility_name, c.region as facility_region, u.username as linked_username 
            FROM patients p 
            LEFT JOIN centers c ON p.center_id = c.id 
            LEFT JOIN users u ON p.linked_user_id = u.id 
            WHERE 1=1
        """
        params = []
        if search_q:
            query += " AND (p.full_name LIKE %s OR p.id LIKE %s OR p.phone LIKE %s OR p.blood_group LIKE %s)"
            term = f"%{search_q}%"
            params.extend([term, term, term, term])
        if center_filter and center_filter != 'all':
            query += " AND p.center_id = %s"
            params.append(center_filter)
        if risk_filter and risk_filter != 'all':
            if risk_filter == 'high':
                query += " AND p.is_high_risk = 1"
            elif risk_filter == 'standard':
                query += " AND (p.is_high_risk = 0 OR p.is_high_risk IS NULL)"
        if gender_filter and gender_filter != 'all':
            query += " AND p.gender = %s"
            params.append(gender_filter)
            
        query += " ORDER BY p.created_at DESC, p.full_name ASC"
        
        patients_list = query_db(query, tuple(params)) or []
        for pat in patients_list:
            format_patient_meta(pat)
            
        all_patients = query_db("SELECT id, gender, is_high_risk, center_id FROM patients") or []
        centers = query_db("SELECT id, name, type FROM centers WHERE is_active = 1 ORDER BY name ASC") or []
        
        stats = {
            'total': len(all_patients),
            'high_risk': sum(1 for p in all_patients if p.get('is_high_risk')),
            'male': sum(1 for p in all_patients if p.get('gender') == 'M'),
            'female': sum(1 for p in all_patients if p.get('gender') == 'F'),
            'centers_count': len(centers)
        }
        
        return render_template(
            'patient/list.html', 
            current_user=user, 
            patients=patients_list,
            centers=centers,
            stats=stats,
            search_q=search_q,
            center_filter=center_filter,
            risk_filter=risk_filter,
            gender_filter=gender_filter
        )

    if not username:
        username = user.get('username')
        
    username = username.strip().lstrip('@')
    if user.get('role') == 'patient' and user.get('username') != username:
        flash('Access denied: You are only authorized to view your own patient portal.', 'error')
        return redirect(url_for('patient.user_profile', username=user.get('username')))
    target_user = query_db('SELECT * FROM users WHERE username = %s', (username,), one=True)
    
    patient = None
    facility = None
    records = []
    prescriptions = []
    appointments = []
    referrals = []
    upcoming_appointment = None
    latest_vitals = None
    
    if target_user:
        patient = query_db('SELECT * FROM patients WHERE linked_user_id = %s', (target_user['id'],), one=True)
        if patient:
            format_patient_meta(patient)
            
            if patient.get('center_id'):
                facility = query_db('SELECT * FROM centers WHERE id = %s', (patient['center_id'],), one=True)
                
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
            
            now = datetime.now()
            for a in appointments:
                if a.get('slot_time') and a.get('status') in ('scheduled', 'checked_in', 'in_progress'):
                    upcoming_appointment = a
                    break
                    
            if records:
                latest_vitals = records[0].get('data_parsed', {})

            referrals = query_db("""
                SELECT r.*, c_to.name as to_center_name, c_from.name as from_center_name, u.full_name as doctor_name
                FROM referrals r
                LEFT JOIN centers c_to ON r.to_center = c_to.id
                LEFT JOIN centers c_from ON r.from_center = c_from.id
                LEFT JOIN users u ON r.created_by = u.id
                WHERE r.patient_id = %s
                ORDER BY r.created_at DESC
            """, (patient['id'],)) or []

    return render_template('patient/my_records.html', current_user=user, profile_username=username, records=records, target_user=target_user, patient=patient, appointments=appointments, prescriptions=prescriptions, referrals=referrals, upcoming_appointment=upcoming_appointment, latest_vitals=latest_vitals, facility=facility)


@patient_bp.route('/records')
@patient_bp.route('/records/@<username>')
@login_required
def my_records(username=None):
    user = get_current_user()
    if not username:
        username = user.get('username')
    username = username.strip().lstrip('@')
    if user.get('role') == 'patient' and user.get('username') != username:
        flash('Access denied: You are only authorized to view your own medical records.', 'error')
        return redirect(url_for('patient.my_records', username=user.get('username')))
    target_user = query_db('SELECT * FROM users WHERE username = %s', (username,), one=True)
    patient = None
    records = []
    prescriptions = []
    appointments = []
    referrals = []
    
    if target_user:
        patient = query_db('SELECT * FROM patients WHERE linked_user_id = %s', (target_user['id'],), one=True)
        if patient:
            format_patient_meta(patient)
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
            referrals = query_db("""
                SELECT r.*, c_to.name as to_center_name, c_from.name as from_center_name, u.full_name as doctor_name
                FROM referrals r
                LEFT JOIN centers c_to ON r.to_center = c_to.id
                LEFT JOIN centers c_from ON r.from_center = c_from.id
                LEFT JOIN users u ON r.created_by = u.id
                WHERE r.patient_id = %s
                ORDER BY r.created_at DESC
            """, (patient['id'],)) or []
            
    return render_template('patient/my_records.html', current_user=user, profile_username=username, records=records, target_user=target_user, patient=patient, appointments=appointments, prescriptions=prescriptions, referrals=referrals)


@patient_bp.route('/map')
@patient_bp.route('/map/@<username>')
@login_required
def patient_map(username=None):
    user = get_current_user()
    if not username:
        username = user.get('username')
    username = username.strip().lstrip('@')
    selected_facility_id = request.args.get('facility', '').strip()
    facilities = query_db('SELECT * FROM centers ORDER BY name ASC') or []
    for fac in facilities:
        if not fac.get('district'):
            fac['district'] = fac.get('region') or fac.get('state') or DEFAULT_DISTRICT
    return render_template('map.html', profile_username=username, current_user=user, facilities=facilities, selected_facility_id=selected_facility_id)


@patient_bp.route('/facilities')
@patient_bp.route('/facilities/@<username>')
@login_required
def patient_facilities(username=None):
    user = get_current_user()
    if not username:
        username = user.get('username')
    username = username.strip().lstrip('@')
    facilities = query_db('SELECT * FROM centers ORDER BY name ASC') or []
    for fac in facilities:
        if not fac.get('district'):
            fac['district'] = fac.get('region') or fac.get('state') or 'Main Center'
    return render_template('facilities/list.html', profile_username=username, facilities=facilities, current_user=user)


@patient_bp.route('/notifications')
@patient_bp.route('/notifications/@<username>')
@login_required
def patient_notifications(username=None):
    user = get_current_user()
    if not username:
        username = user.get('username')
    username = username.strip().lstrip('@')
    notifs = []
    if user:
        notifs = query_db('SELECT * FROM notifications WHERE user_id = %s ORDER BY created_at DESC LIMIT 50', (user['id'],)) or []
        execute_db('UPDATE notifications SET is_read = 1 WHERE user_id = %s', (user['id'],))
    return render_template('notifications.html', profile_username=username, notifications=notifs, current_user=user)


@patient_bp.route('/emergency')
@patient_bp.route('/emergency/@<username>')
@patient_bp.route('/emergency-contact')
@patient_bp.route('/emergency-contact/@<username>')
@login_required
def patient_emergency(username=None):
    user = get_current_user()
    if not username:
        username = user.get('username')
    username = username.strip().lstrip('@')
    if user.get('role') == 'patient' and user.get('username') != username:
        flash('Access denied: You are only authorized to view your own teleconsultations.', 'error')
        return redirect(url_for('patient.patient_teleconsult', username=user.get('username')))
    target_user = query_db('SELECT * FROM users WHERE username = %s', (username,), one=True)
    patient = None
    facility = None
    if target_user:
        patient = query_db('SELECT * FROM patients WHERE linked_user_id = %s', (target_user['id'],), one=True)
        if target_user.get('center_id'):
            facility = query_db('SELECT * FROM centers WHERE id = %s', (target_user['center_id'],), one=True)
    return render_template('emergency.html', profile_username=username, patient=patient, facility=facility, current_user=user, target_user=target_user)


@patient_bp.route('/me')
@login_required
def my_records_redirect():
    user = get_current_user()
    return redirect(url_for('patient.user_profile', username=user['username']))


@patient_bp.route('/<patient_id>')
@patient_bp.route('/<patient_id>/@<username>')
@login_required
def patient_detail(patient_id, username=None):
    patient_id = patient_id.strip()
    if patient_id.startswith('@'):
        return redirect(url_for('patient.user_profile', username=patient_id.lstrip('@')))
        
    user = get_current_user()
    patient = query_db('SELECT * FROM patients WHERE id = %s', (patient_id,), one=True)
    if not patient:
        abort(404)
        
    if user.get('role') == 'patient' and patient.get('linked_user_id') != user.get('id'):
        abort(403)
        
    format_patient_meta(patient)
    center = query_db('SELECT * FROM centers WHERE id = %s', (patient.get('center_id'),), one=True) or {'name': patient.get('center_id') or 'Primary Health Centre'}
    
    raw_prescriptions = query_db("""
        SELECT pr.*, u.full_name as doctor_name, c.name as center_name 
        FROM prescriptions pr 
        LEFT JOIN users u ON pr.prescribed_by = u.id 
        LEFT JOIN centers c ON pr.center_id = c.id 
        WHERE pr.patient_id = %s 
        ORDER BY pr.created_at DESC
    """, (patient['id'],)) or []
    
    prescriptions = []
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
    
    records = []
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
        
    latest_vitals = records[0].get('data_parsed', {}) if records else {}
    appointments = query_db('SELECT * FROM appointments WHERE patient_id = %s ORDER BY slot_time DESC', (patient['id'],)) or []
    
    return render_template('patient/detail.html', current_user=user, patient=patient, patient_id=patient_id, center=center, records=records, prescriptions=prescriptions, appointments=appointments, latest_vitals=latest_vitals)


@patient_bp.route('/teleconsult')
@patient_bp.route('/teleconsult/@<username>')
@login_required
def patient_teleconsult(username=None):
    user = get_current_user()
    if not username:
        username = user.get('username')
    username = username.strip().lstrip('@')
    target_user = query_db('SELECT * FROM users WHERE username = %s', (username,), one=True)
    patient = None
    sessions = []
    facilities = query_db("SELECT * FROM centers ORDER BY name ASC") or []

    if target_user:
        patient = query_db('SELECT * FROM patients WHERE linked_user_id = %s', (target_user['id'],), one=True)
        if patient:
            sessions = query_db("""
                SELECT t.*, u.full_name as doctor_name, u.designation as doctor_designation, c.name as center_name
                FROM teleconsult_sessions t
                LEFT JOIN users u ON t.doctor_id = u.id
                LEFT JOIN centers c ON t.center_id = c.id
                WHERE t.patient_id = %s
                ORDER BY t.created_at DESC
            """, (patient['id'],)) or []
    return render_template('patient/teleconsult.html', current_user=user, profile_username=username, patient=patient, sessions=sessions, facilities=facilities)


@patient_bp.route('/teleconsult/request', methods=['POST'])
@login_required
def patient_request_teleconsult():
    user = get_current_user()
    patient = query_db('SELECT * FROM patients WHERE linked_user_id = %s', (user['id'],), one=True)
    if not patient:
        flash('No patient profile is linked to your account.', 'error')
        return redirect(url_for('patient.user_profile', username=user['username']))

    center_id = (request.form.get('center_id') or get_user_center_id(user) or '').strip()
    reason = request.form.get('reason', 'Remote General Teleconsultation Request').strip()
    notes = request.form.get('notes', '').strip()

    doctor = query_db("SELECT id FROM users WHERE role = 'doctor' AND (center_id = %s OR center_id IS NULL) AND is_active = 1 LIMIT 1", (center_id,), one=True)
    doctor_id = doctor['id'] if doctor else None

    session_id = execute_db("""
        INSERT INTO teleconsult_sessions (patient_id, doctor_id, center_id, status, session_type, chief_complaint, clinical_notes)
        VALUES (%s, %s, %s, 'requested', 'video', %s, %s)
    """, (patient['id'], doctor_id, center_id, reason, notes))

    log_audit('patient_requested_teleconsult', 'teleconsult_session', session_id)
    fac = query_db('SELECT name FROM centers WHERE id = %s', (center_id,), one=True)
    fac_name = fac['name'] if fac else (center_id or 'Healthcare Center')
    create_notification(
        user['id'],
        'Teleconsultation Request Submitted',
        f'Your teleconsultation request has been submitted to clinical staff at {fac_name}. Chief complaint: {reason}.',
        url_for('patient.patient_teleconsult', username=user['username'])
    )
    flash('Your teleconsultation request has been submitted to clinical staff.', 'success')
    return redirect(url_for('patient.patient_teleconsult', username=user['username']))


@patient_bp.route('/appointments')
@patient_bp.route('/appointments/@<username>')
@login_required
def patient_appointments(username=None):
    user = get_current_user()
    if not username:
        username = user.get('username')
    username = username.strip().lstrip('@')
    if user.get('role') == 'patient' and user.get('username') != username:
        flash('Access denied: You are only authorized to view your own appointments.', 'error')
        return redirect(url_for('patient.patient_appointments', username=user.get('username')))
    target_user = query_db('SELECT * FROM users WHERE username = %s', (username,), one=True)
    patient = None
    appointments = []
    active_token = None
    referrals = []
    now = datetime.now()

    if target_user:
        patient = query_db('SELECT * FROM patients WHERE linked_user_id = %s', (target_user['id'],), one=True)
        if patient:
            raw_appts = query_db("""
                SELECT a.*, c.name as center_name, c.phone as center_phone, u.full_name as doctor_name
                FROM appointments a
                LEFT JOIN centers c ON a.center_id = c.id
                LEFT JOIN users u ON a.doctor_id = u.id
                WHERE a.patient_id = %s
                ORDER BY a.slot_time DESC
            """, (patient['id'],)) or []

            appointments = raw_appts

            for a in raw_appts:
                is_active_status = a.get('status') in ('checked_in', 'in_progress')
                is_upcoming_today = (a.get('status') == 'scheduled' and a.get('slot_time') and a['slot_time'] >= now - timedelta(hours=4))
                if is_active_status or is_upcoming_today:
                    active_token = dict(a)
                    ahead_res = query_db("""
                        SELECT COUNT(*) as c FROM appointments
                        WHERE center_id = %s AND status IN ('checked_in', 'scheduled')
                          AND (urgency < %s OR (urgency = %s AND slot_time < %s))
                    """, (a['center_id'], a['urgency'], a['urgency'], a['slot_time']), one=True)
                    active_token['patients_ahead'] = ahead_res['c'] if ahead_res else 0
                    active_token['est_wait_min'] = max(5, (active_token['patients_ahead'] + (0 if a.get('status') == 'in_progress' else 1)) * 12)
                    break

            referrals = query_db("""
                SELECT r.*, c_to.name as to_center_name, c_to.type as to_center_type,
                       c_from.name as from_center_name, u.full_name as doctor_name
                FROM referrals r
                LEFT JOIN centers c_to ON r.to_center = c_to.id
                LEFT JOIN centers c_from ON r.from_center = c_from.id
                LEFT JOIN users u ON r.created_by = u.id
                WHERE r.patient_id = %s
                ORDER BY r.created_at DESC
            """, (patient['id'],)) or []
        else:
            if user.get('role') == 'patient':
                flash('No patient profile linked to this account.', 'error')

    facilities = query_db("SELECT * FROM centers ORDER BY name ASC") or []
    server_time_iso = now.strftime('%Y-%m-%dT%H:%M')

    return render_template('patient/appointments.html', current_user=user, profile_username=username,
                           patient=patient, appointments=appointments, active_token=active_token,
                           referrals=referrals, facilities=facilities, server_time_iso=server_time_iso)


@patient_bp.route('/appointments/book', methods=['POST'])
@login_required
def patient_book_appointment():
    user = get_current_user()
    patient = query_db('SELECT * FROM patients WHERE linked_user_id = %s', (user['id'],), one=True)

    if not patient:
        flash('No patient profile is linked to your account. Please contact the administrator.', 'error')
        return redirect(url_for('patient.user_profile', username=user['username']))

    center_id = (request.form.get('center_id') or get_user_center_id(user) or '').strip()
    department = (request.form.get('department') or DEFAULT_DEPARTMENT).strip()
    reason = (request.form.get('reason') or DEFAULT_ONLINE_REASON).strip()
    slot_time_str = request.form.get('slot_time')

    now = datetime.now()
    if slot_time_str:
        try:
            slot_time = datetime.strptime(slot_time_str, '%Y-%m-%dT%H:%M')
        except Exception:
            slot_time = now
    else:
        slot_time = now

    if slot_time < now - timedelta(minutes=5):
        flash('Appointment slot cannot be set in the past. Please select an upcoming date and time.', 'error')
        return redirect(url_for('patient.patient_appointments', username=user['username']))

    count_res = query_db("""
        SELECT COUNT(*) as c FROM appointments 
        WHERE center_id = %s AND DATE(created_at) = CURDATE()
    """, (center_id,), one=True)
    next_idx = (count_res['c'] if count_res else 0) + 1
    token_number = f"OPD-{next_idx:03d}"

    appt_id = execute_db("""
        INSERT INTO appointments (patient_id, center_id, token_number, department, slot_time, reason, urgency, status, notes)
        VALUES (%s, %s, %s, %s, %s, %s, 3, 'scheduled', 'Booked via Patient Portal Online Scheduler')
    """, (patient['id'], center_id, token_number, department, slot_time, reason))

    log_audit('patient_booked_appointment', 'appointment', appt_id)
    fac = query_db('SELECT name FROM centers WHERE id = %s', (center_id,), one=True)
    fac_name = fac['name'] if fac else (center_id or 'Healthcare Center')
    create_notification(
        user['id'],
        f'Appointment Confirmed (Token #{token_number})',
        f'Your OPD appointment at {fac_name} is scheduled for {slot_time.strftime("%b %d, %Y at %I:%M %p")}. Department: {department}. Token #{token_number}.',
        url_for('patient.patient_appointments', username=user['username'])
    )
    flash(f"Appointment successfully scheduled! Your OPD Token is #{token_number}.", 'success')
    return redirect(url_for('patient.patient_appointments', username=user['username']))

@patient_bp.route('/add', methods=['POST'])
@login_required
def add_patient():
    user = get_current_user()
    if user.get('role') not in ('doctor', 'nurse', 'receptionist', 'care_taker', 'helper', 'region_admin', 'system_admin'):
        flash('Unauthorized to register patients.', 'error')
        return redirect(url_for('patient.user_profile'))
        
    full_name = request.form.get('full_name', '').strip()
    dob = request.form.get('dob', '').strip()
    gender = request.form.get('gender', 'M').strip()
    phone = request.form.get('phone', '').strip()
    blood_group = request.form.get('blood_group', 'O+').strip()
    center_id = request.form.get('center_id', '').strip() or get_user_center_id(user)
    address = request.form.get('address', '').strip()
    allergies = request.form.get('allergies', '').strip()
    chronic_conditions = request.form.get('chronic_conditions', '').strip()
    is_high_risk = 1 if request.form.get('is_high_risk') in ('1', 'on', 'true', True) else 0
    
    parsed_dob = parse_flexible_dob(dob)
    if not full_name or not parsed_dob or not phone:
        flash('Full name, a valid date of birth (between 1900 and today), and phone number are required.', 'error')
        return redirect(url_for('patient.user_profile'))
    dob = parsed_dob
        
    allergies_json = json.dumps([a.strip() for a in allergies.split(',') if a.strip()]) if allergies else json.dumps([DEFAULT_ALLERGIES])
    conditions_json = json.dumps([c.strip() for c in chronic_conditions.split(',') if c.strip()]) if chronic_conditions else json.dumps([])
    
    pat_id = generate_patient_id()
    
    execute_db("""
        INSERT INTO patients (id, full_name, dob, gender, phone, address, blood_group, center_id, allergies, chronic_conditions, is_high_risk)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (pat_id, full_name, dob, gender, phone, address, blood_group, center_id, allergies_json, conditions_json, is_high_risk))
    
    log_audit(user.get('id'), 'REGISTER_PATIENT', f"Registered patient {pat_id} ({full_name})", request.remote_addr)
    flash(f"Patient {full_name} ({pat_id}) successfully registered in registry.", "success")
    return redirect(url_for('patient.patient_detail', patient_id=pat_id))
