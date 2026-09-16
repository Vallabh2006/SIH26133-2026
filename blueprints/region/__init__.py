from flask import Blueprint, render_template, request, redirect, url_for, flash
from utils.auth_helpers import role_required, get_current_user
from utils.db import query_db, execute_db

region_bp = Blueprint('region', __name__, url_prefix='/region')


@region_bp.route('/')
@region_bp.route('/dashboard')
@role_required('region_admin', 'system_admin')
def dashboard():
    user = get_current_user()
    facilities = query_db('SELECT * FROM centers ORDER BY name ASC') or []
    total_patients_row = query_db('SELECT COUNT(*) as c FROM patients', one=True)
    total_patients = total_patients_row['c'] if total_patients_row else 0
    
    total_staff_row = query_db("SELECT COUNT(*) as c FROM users WHERE role NOT IN ('patient', 'system_admin')", one=True)
    total_staff = total_staff_row['c'] if total_staff_row else 0
    
    active_refs = query_db("SELECT COUNT(*) as c FROM referrals WHERE status IN ('initiated', 'accepted', 'in_transit')", one=True)
    active_referrals = active_refs['c'] if active_refs else 0

    recent_referrals = query_db("""
        SELECT r.*, p.full_name as patient_name, c_to.name as to_center_name, c_from.name as from_center_name
        FROM referrals r
        LEFT JOIN patients p ON r.patient_id = p.id
        LEFT JOIN centers c_to ON r.to_center = c_to.id
        LEFT JOIN centers c_from ON r.from_center = c_from.id
        ORDER BY r.created_at DESC LIMIT 6
    """) or []

    low_inventory = query_db("""
        SELECT i.*, c.name as center_name 
        FROM inventory_items i
        LEFT JOIN centers c ON i.center_id = c.id
        WHERE i.quantity <= i.reorder_level
        ORDER BY i.quantity ASC LIMIT 6
    """) or []

    stats = {
        'total_facilities': len(facilities),
        'total_patients': total_patients,
        'total_staff': total_staff,
        'active_referrals': active_referrals
    }

    return render_template('region/dashboard.html', current_user=user, facilities=facilities, stats=stats, recent_referrals=recent_referrals, low_inventory=low_inventory)


@region_bp.route('/referrals')
@role_required('region_admin', 'system_admin')
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

    query += " ORDER BY r.created_at DESC"
    all_referrals = query_db(query, tuple(params)) or []

    stats = {
        'total': len(all_referrals),
        'active': len([r for r in all_referrals if r['status'] in ('initiated', 'accepted', 'in_transit')]),
        'critical': len([r for r in all_referrals if r.get('urgency') == 'critical']),
        'completed': len([r for r in all_referrals if r['status'] in ('completed', 'counter_referred')])
    }

    return render_template('region/referrals.html', current_user=user, referrals=all_referrals, stats=stats, status_filter=status_filter, urgency_filter=urgency_filter)


@region_bp.route('/admissions')
@role_required('region_admin', 'system_admin')
def admissions():
    user = get_current_user()
    facility_filter = request.args.get('facility', '').strip()
    
    query = """
        SELECT a.*, p.full_name as patient_name, p.gender, p.dob, p.blood_group, p.is_high_risk,
               c.name as center_name, c.type as center_type,
               u.full_name as doctor_name
        FROM appointments a
        LEFT JOIN patients p ON a.patient_id = p.id
        LEFT JOIN centers c ON a.center_id = c.id
        LEFT JOIN users u ON a.doctor_id = u.id
        WHERE a.status IN ('checked_in', 'in_progress')
    """
    params = []
    if facility_filter:
        query += " AND a.center_id = %s"
        params.append(facility_filter)
        
    query += " ORDER BY a.urgency ASC, a.slot_time ASC"
    admitted_patients = query_db(query, tuple(params)) or []
    facilities = query_db('SELECT id, name, type FROM centers ORDER BY name ASC') or []

    return render_template('region/admissions.html', current_user=user, patients=admitted_patients, facilities=facilities, facility_filter=facility_filter)


@region_bp.route('/discharges')
@role_required('region_admin', 'system_admin')
def discharges():
    user = get_current_user()
    discharged_cases = query_db("""
        SELECT a.*, p.full_name as patient_name, p.gender, p.blood_group,
               c.name as center_name, u.full_name as doctor_name
        FROM appointments a
        LEFT JOIN patients p ON a.patient_id = p.id
        LEFT JOIN centers c ON a.center_id = c.id
        LEFT JOIN users u ON a.doctor_id = u.id
        WHERE a.status = 'completed'
        ORDER BY a.updated_at DESC LIMIT 50
    """) or []

    return render_template('region/discharges.html', current_user=user, discharges=discharged_cases)


@region_bp.route('/counter-referrals')
@role_required('region_admin', 'system_admin')
def counter_referrals():
    user = get_current_user()
    counter_refs = query_db("""
        SELECT r.*, p.full_name as patient_name, p.gender, p.dob,
               c_to.name as specialist_center_name, c_from.name as phc_center_name,
               u.full_name as doctor_name
        FROM referrals r
        LEFT JOIN patients p ON r.patient_id = p.id
        LEFT JOIN centers c_to ON r.to_center = c_to.id
        LEFT JOIN centers c_from ON r.from_center = c_from.id
        LEFT JOIN users u ON r.accepted_by = u.id
        WHERE r.status = 'counter_referred' OR r.notes LIKE '%%Counter-Referral%%'
        ORDER BY r.completed_at DESC, r.created_at DESC
    """) or []

    return render_template('region/counter_referrals.html', current_user=user, counter_referrals=counter_refs)
