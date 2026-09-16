from flask import Blueprint, render_template, redirect, url_for
from utils.auth_helpers import role_required, get_current_user
from utils.db import query_db
from utils.defaults import get_user_center_id
from utils.cache import get_cached, set_cached

dashboard_bp = Blueprint('dashboard', __name__, url_prefix='/dashboard')

@dashboard_bp.route('/patient')
@role_required('patient')
def patient_dashboard():
    user = get_current_user()
    if user and user.get('username'):
        return redirect(f'/patient/@{user["username"]}')
    return render_template('dashboard/patient.html', current_user=user)

@dashboard_bp.route('/doctor')
@role_required('doctor')
def doctor_dashboard():
    user = get_current_user()
    center_id = get_user_center_id(user)
    cache_key = f"dashboard:doctor:{user['id']}:{center_id}"

    cached = get_cached(cache_key, center_id=center_id)
    if cached:
        return render_template('dashboard/doctor.html', current_user=user, queue=cached['queue'], teleconsults=cached['teleconsults'])

    today_queue = query_db("""
        SELECT a.*, p.full_name as patient_name, p.gender, p.dob, p.blood_group
        FROM appointments a
        LEFT JOIN patients p ON a.patient_id = p.id
        WHERE a.center_id = %s AND a.status IN ('scheduled', 'checked_in', 'in_progress')
        ORDER BY a.urgency ASC, a.slot_time ASC LIMIT 10
    """, (center_id,)) or []

    my_teleconsults = query_db("""
        SELECT t.*, p.full_name as patient_name
        FROM teleconsult_sessions t
        LEFT JOIN patients p ON t.patient_id = p.id
        WHERE t.doctor_id = %s AND t.status IN ('requested', 'active')
        ORDER BY t.created_at DESC
    """, (user['id'],)) or []

    set_cached(cache_key, {'queue': today_queue, 'teleconsults': my_teleconsults}, center_id=center_id)
    return render_template('dashboard/doctor.html', current_user=user, queue=today_queue, teleconsults=my_teleconsults)

@dashboard_bp.route('/staff')
@role_required('nurse', 'helper', 'ambulance_op', 'care_taker', 'therapist', 'pharmacist', 'lab_technician', 'receptionist')
def staff_dashboard():
    user = get_current_user()
    center_id = get_user_center_id(user)
    cache_key = f"dashboard:staff:{user['id']}:{center_id}"

    cached = get_cached(cache_key, center_id=center_id)
    if cached:
        return render_template('dashboard/staff.html', current_user=user, queue=cached['queue'], low_stock=cached['low_stock'])

    today_queue = query_db("""
        SELECT a.*, p.full_name as patient_name
        FROM appointments a
        LEFT JOIN patients p ON a.patient_id = p.id
        WHERE a.center_id = %s AND a.status IN ('scheduled', 'checked_in')
        ORDER BY a.urgency ASC, a.slot_time ASC LIMIT 10
    """, (center_id,)) or []

    low_stock = query_db("""
        SELECT * FROM inventory_items
        WHERE center_id = %s AND quantity <= reorder_level
        ORDER BY quantity ASC LIMIT 5
    """, (center_id,)) or []

    set_cached(cache_key, {'queue': today_queue, 'low_stock': low_stock}, center_id=center_id)
    return render_template('dashboard/staff.html', current_user=user, queue=today_queue, low_stock=low_stock)

@dashboard_bp.route('/phc')
def phc_dashboard():
    user = get_current_user()
    if user and user.get('username'):
        return redirect(f'/phc/@{user["username"]}')
    return redirect(url_for('phc.dashboard'))
