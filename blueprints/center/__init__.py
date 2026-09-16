from flask import Blueprint, render_template, abort
from utils.auth_helpers import login_required, get_current_user
from utils.db import query_db

center_bp = Blueprint('center', __name__, url_prefix='/center')

def verify_access(user, center_id):
    if user['role'] not in ('region_admin', 'system_admin') and user.get('center_id') != center_id:
        abort(403)

@center_bp.route('/<center_id>/dashboard')
@login_required
def dashboard(center_id):
    user = get_current_user()
    verify_access(user, center_id)
    center = query_db('SELECT * FROM centers WHERE id = %s', (center_id,), one=True)
    if not center:
        abort(404)
        
    queue = query_db("""
        SELECT a.*, p.full_name as patient_name, p.gender, p.blood_group
        FROM appointments a
        LEFT JOIN patients p ON a.patient_id = p.id
        WHERE a.center_id = %s
        ORDER BY a.urgency ASC, a.slot_time ASC LIMIT 8
    """, (center_id,)) or []
    
    staff_members = query_db('SELECT id, full_name, role, designation FROM users WHERE center_id = %s ORDER BY full_name ASC', (center_id,)) or []
    patient_count_row = query_db('SELECT COUNT(*) as c FROM patients WHERE center_id = %s', (center_id,), one=True)
    patient_count = patient_count_row['c'] if patient_count_row else 0
    
    inventory_items = query_db('SELECT * FROM inventory_items WHERE center_id = %s ORDER BY quantity ASC LIMIT 6', (center_id,)) or []

    stats = {
        'total_patients': patient_count,
        'queue_count': len(queue),
        'staff_count': len(staff_members),
        'inventory_count': len(inventory_items)
    }

    return render_template('center/dashboard.html', current_user=user, center=center, queue=queue, staff_members=staff_members, stats=stats, inventory_items=inventory_items)

@center_bp.route('/<center_id>/triage')
@login_required
def triage(center_id):
    user = get_current_user()
    verify_access(user, center_id)
    center = query_db('SELECT * FROM centers WHERE id = %s', (center_id,), one=True)
    if not center:
        abort(404)
        
    triage_queue = query_db("""
        SELECT a.*, p.full_name as patient_name, p.gender, p.blood_group, p.is_high_risk,
               u.full_name as doctor_name
        FROM appointments a
        LEFT JOIN patients p ON a.patient_id = p.id
        LEFT JOIN users u ON a.doctor_id = u.id
        WHERE a.center_id = %s AND a.status IN ('checked_in', 'in_progress', 'scheduled')
        ORDER BY a.urgency ASC, a.slot_time ASC
    """, (center_id,)) or []

    return render_template('center/triage.html', current_user=user, center=center, queue=triage_queue)

@center_bp.route('/<center_id>/referrals')
@login_required
def referrals(center_id):
    user = get_current_user()
    verify_access(user, center_id)
    center = query_db('SELECT * FROM centers WHERE id = %s', (center_id,), one=True)
    if not center:
        abort(404)
        
    referrals_list = query_db("""
        SELECT r.*, p.full_name as patient_name,
               c_to.name as to_center_name, c_from.name as from_center_name,
               u.full_name as doctor_name
        FROM referrals r
        LEFT JOIN patients p ON r.patient_id = p.id
        LEFT JOIN centers c_to ON r.to_center = c_to.id
        LEFT JOIN centers c_from ON r.from_center = c_from.id
        LEFT JOIN users u ON r.created_by = u.id
        WHERE r.from_center = %s OR r.to_center = %s
        ORDER BY r.created_at DESC
    """, (center_id, center_id)) or []

    return render_template('center/referrals.html', current_user=user, center=center, referrals=referrals_list)

@center_bp.route('/<center_id>/patients')
@login_required
def patients(center_id):
    user = get_current_user()
    verify_access(user, center_id)
    center = query_db('SELECT * FROM centers WHERE id = %s', (center_id,), one=True)
    if not center:
        abort(404)
        
    patients_list = query_db('SELECT * FROM patients WHERE center_id = %s ORDER BY full_name ASC', (center_id,)) or []
    return render_template('center/patients.html', current_user=user, center=center, patients=patients_list)
