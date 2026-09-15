from functools import wraps
from flask import session, redirect, url_for, flash, request, jsonify, abort
from utils.db import query_db, execute_db
from utils.auth_helpers import get_current_user

SYSTEM_ACTIONS = [
    {
        'key': 'view_records',
        'name': 'View Medical Records',
        'category': 'Clinical Operations',
        'description': 'View patient electronic health records and clinical consultation history'
    },
    {
        'key': 'create_consultation',
        'name': 'Conduct Consultations',
        'category': 'Clinical Operations',
        'description': 'Conduct outpatient examinations, record symptoms, diagnoses and sign clinical notes'
    },
    {
        'key': 'manage_prescriptions',
        'name': 'Prescriptions & Dispensing',
        'category': 'Clinical Operations',
        'description': 'Issue prescriptions, dispense pharmaceuticals, and review medication history'
    },
    {
        'key': 'view_inventory',
        'name': 'View Inventory Stock',
        'category': 'Supply & Pharmacy',
        'description': 'View health facility medicines, stock levels, and supply availability'
    },
    {
        'key': 'manage_inventory',
        'name': 'Manage Inventory & Supplies',
        'category': 'Supply & Pharmacy',
        'description': 'Add new stock items, perform CSV import/export, and modify reorder thresholds'
    },
    {
        'key': 'view_appointments',
        'name': 'View Appointment Queues',
        'category': 'Patient Flow',
        'description': 'Access clinic waiting queues, booked appointments, and visit rosters'
    },
    {
        'key': 'manage_appointments',
        'name': 'Manage Appointments & Triage',
        'category': 'Patient Flow',
        'description': 'Book, reschedule, triage, and update status of patient encounters'
    },
    {
        'key': 'teleconsult',
        'name': 'Remote Teleconsultation',
        'category': 'Clinical Operations',
        'description': 'Conduct live teleconsultation calls and remote patient clinical advisory'
    },
    {
        'key': 'manage_referrals',
        'name': 'Inter-Facility Referrals',
        'category': 'Patient Flow',
        'description': 'Create and manage referrals to higher-tier hospitals or specialists'
    },
    {
        'key': 'register_patient',
        'name': 'Register Patients',
        'category': 'Patient Flow',
        'description': 'Register and onboard new patients into the digital health registry'
    },
    {
        'key': 'manage_staff',
        'name': 'Staff Onboarding & Mgmt',
        'category': 'Administration',
        'description': 'Add new healthcare staff, send invitation emails, activate/deactivate accounts'
    },
    {
        'key': 'manage_facilities',
        'name': 'Provision Health Centers',
        'category': 'Administration',
        'description': 'Create new health centers and assign facility administrators'
    },
    {
        'key': 'view_audit_logs',
        'name': 'View System Audit Logs',
        'category': 'Governance',
        'description': 'Access security trails, clinical audit events, and user activity logs'
    },
    {
        'key': 'view_analytics',
        'name': 'Analytics & Surveillance',
        'category': 'Governance',
        'description': 'Access disease surveillance, workload distribution, and epidemiology reports'
    },
    {
        'key': 'manage_permissions',
        'name': 'Permission Matrix Governance',
        'category': 'Governance',
        'description': 'Configure action grants and role privileges across the entire platform'
    }
]

ALL_ROLES = [
    ('doctor', 'Medical Officer / Doctor', '#0284c7'),
    ('nurse', 'Staff Nurse / ANM', '#16a34a'),
    ('pharmacist', 'Pharmacist / Dispensary In-Charge', '#7c3aed'),
    ('lab_technician', 'Lab Technician / Pathologist', '#0891b2'),
    ('ambulance_op', '108 Ambulance Operator / Driver', '#ea580c'),
    ('receptionist', 'Registration & Front Desk', '#475569'),
    ('care_taker', 'Care Taker / ASHA Worker', '#059669'),
    ('helper', 'Healthcare Helper / Multi-Purpose Worker', '#0d9488'),
    ('therapist', 'Physiotherapist / Specialist Therapist', '#4f46e5'),
    ('region_admin', 'Facility / Regional Admin', '#b45309'),
    ('system_admin', 'Master System Administrator', '#dc2626')
]

DEFAULT_ROLE_PERMISSIONS = {
    'system_admin': {a['key']: 1 for a in SYSTEM_ACTIONS},
    'region_admin': {
        'view_records': 1,
        'create_consultation': 1,
        'manage_prescriptions': 1,
        'view_inventory': 1,
        'manage_inventory': 1,
        'view_appointments': 1,
        'manage_appointments': 1,
        'teleconsult': 1,
        'manage_referrals': 1,
        'register_patient': 1,
        'manage_staff': 1,
        'manage_facilities': 0,
        'view_audit_logs': 1,
        'view_analytics': 1,
        'manage_permissions': 0
    },
    'doctor': {
        'view_records': 1,
        'create_consultation': 1,
        'manage_prescriptions': 1,
        'view_inventory': 1,
        'manage_inventory': 0,
        'view_appointments': 1,
        'manage_appointments': 1,
        'teleconsult': 1,
        'manage_referrals': 1,
        'register_patient': 1,
        'manage_staff': 0,
        'manage_facilities': 0,
        'view_audit_logs': 0,
        'view_analytics': 0,
        'manage_permissions': 0
    },
    'nurse': {
        'view_records': 1,
        'create_consultation': 0,
        'manage_prescriptions': 0,
        'view_inventory': 1,
        'manage_inventory': 0,
        'view_appointments': 1,
        'manage_appointments': 1,
        'teleconsult': 0,
        'manage_referrals': 0,
        'register_patient': 1,
        'manage_staff': 0,
        'manage_facilities': 0,
        'view_audit_logs': 0,
        'view_analytics': 0,
        'manage_permissions': 0
    },
    'pharmacist': {
        'view_records': 1,
        'create_consultation': 0,
        'manage_prescriptions': 1,
        'view_inventory': 1,
        'manage_inventory': 1,
        'view_appointments': 0,
        'manage_appointments': 0,
        'teleconsult': 0,
        'manage_referrals': 0,
        'register_patient': 0,
        'manage_staff': 0,
        'manage_facilities': 0,
        'view_audit_logs': 0,
        'view_analytics': 0,
        'manage_permissions': 0
    },
    'lab_technician': {
        'view_records': 1,
        'create_consultation': 0,
        'manage_prescriptions': 0,
        'view_inventory': 1,
        'manage_inventory': 0,
        'view_appointments': 0,
        'manage_appointments': 0,
        'teleconsult': 0,
        'manage_referrals': 0,
        'register_patient': 0,
        'manage_staff': 0,
        'manage_facilities': 0,
        'view_audit_logs': 0,
        'view_analytics': 0,
        'manage_permissions': 0
    },
    'ambulance_op': {
        'view_records': 1,
        'create_consultation': 0,
        'manage_prescriptions': 0,
        'view_inventory': 0,
        'manage_inventory': 0,
        'view_appointments': 1,
        'manage_appointments': 0,
        'teleconsult': 0,
        'manage_referrals': 1,
        'register_patient': 0,
        'manage_staff': 0,
        'manage_facilities': 0,
        'view_audit_logs': 0,
        'view_analytics': 0,
        'manage_permissions': 0
    },
    'receptionist': {
        'view_records': 0,
        'create_consultation': 0,
        'manage_prescriptions': 0,
        'view_inventory': 0,
        'manage_inventory': 0,
        'view_appointments': 1,
        'manage_appointments': 1,
        'teleconsult': 0,
        'manage_referrals': 0,
        'register_patient': 1,
        'manage_staff': 0,
        'manage_facilities': 0,
        'view_audit_logs': 0,
        'view_analytics': 0,
        'manage_permissions': 0
    },
    'care_taker': {
        'view_records': 1,
        'create_consultation': 0,
        'manage_prescriptions': 0,
        'view_inventory': 0,
        'manage_inventory': 0,
        'view_appointments': 1,
        'manage_appointments': 0,
        'teleconsult': 0,
        'manage_referrals': 0,
        'register_patient': 1,
        'manage_staff': 0,
        'manage_facilities': 0,
        'view_audit_logs': 0,
        'view_analytics': 0,
        'manage_permissions': 0
    },
    'helper': {
        'view_records': 1,
        'create_consultation': 0,
        'manage_prescriptions': 0,
        'view_inventory': 1,
        'manage_inventory': 0,
        'view_appointments': 1,
        'manage_appointments': 0,
        'teleconsult': 0,
        'manage_referrals': 0,
        'register_patient': 1,
        'manage_staff': 0,
        'manage_facilities': 0,
        'view_audit_logs': 0,
        'view_analytics': 0,
        'manage_permissions': 0
    },
    'therapist': {
        'view_records': 1,
        'create_consultation': 1,
        'manage_prescriptions': 0,
        'view_inventory': 1,
        'manage_inventory': 0,
        'view_appointments': 1,
        'manage_appointments': 1,
        'teleconsult': 1,
        'manage_referrals': 1,
        'register_patient': 0,
        'manage_staff': 0,
        'manage_facilities': 0,
        'view_audit_logs': 0,
        'view_analytics': 0,
        'manage_permissions': 0
    },
    'patient': {
        'view_records': 1,
        'create_consultation': 0,
        'manage_prescriptions': 0,
        'view_inventory': 0,
        'manage_inventory': 0,
        'view_appointments': 1,
        'manage_appointments': 0,
        'teleconsult': 1,
        'manage_referrals': 0,
        'register_patient': 0,
        'manage_staff': 0,
        'manage_facilities': 0,
        'view_audit_logs': 0,
        'view_analytics': 0,
        'manage_permissions': 0
    }
}


def init_permissions_db():
    try:
        execute_db('''
            CREATE TABLE IF NOT EXISTS role_permissions (
                role VARCHAR(50) NOT NULL,
                action VARCHAR(100) NOT NULL,
                is_allowed SMALLINT NOT NULL DEFAULT 1,
                PRIMARY KEY (role, action)
            )
        ''')
        existing = query_db('SELECT COUNT(*) as cnt FROM role_permissions', one=True)
        if not existing or existing.get('cnt', 0) == 0:
            for r_key, actions in DEFAULT_ROLE_PERMISSIONS.items():
                for a_key, allowed in actions.items():
                    execute_db('INSERT INTO role_permissions (role, action, is_allowed) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING', (r_key, a_key, allowed))
    except Exception:
        pass


def get_permissions_matrix():
    init_permissions_db()
    rows = query_db('SELECT role, action, is_allowed FROM role_permissions') or []
    matrix = {}
    for r in rows:
        matrix.setdefault(r['role'], {})[r['action']] = bool(r['is_allowed'])
    
    for r_key, actions in DEFAULT_ROLE_PERMISSIONS.items():
        if r_key not in matrix:
            matrix[r_key] = {}
        for a_key, val in actions.items():
            if a_key not in matrix[r_key]:
                matrix[r_key][a_key] = bool(val)
    return matrix


def has_permission(action, user=None):
    if user is None:
        user = get_current_user()
    if not user:
        return False
    if isinstance(user, str):
        role = user
    else:
        role = user.get('role')
    if role == 'system_admin':
        return True
    
    matrix = get_permissions_matrix()
    return matrix.get(role, {}).get(action, False)


def can(action, user=None):
    return has_permission(action, user)


def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                if request.path.startswith('/admin'):
                    return redirect(url_for('auth.admin_login', next=request.url))
                if request.path.startswith('/dashboard/phc') or request.path.startswith('/phc'):
                    return redirect(url_for('auth.phc_login', next=request.url))
                return redirect(url_for('auth.login', next=request.url))
            
            user = get_current_user()
            if not user or user['role'] not in roles:
                session.clear()
                flash("Access Denied: Please log in with an account that has the correct permissions.", "error")
                return redirect(url_for('auth.login'))
                
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def permission_required(action):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                return redirect(url_for('auth.login', next=request.url))
            
            user = get_current_user()
            if not user or not has_permission(action, user):
                flash(f"Permission Denied: Your account role does not have authorization to perform this action ({action}).", "error")
                if request.is_json:
                    return jsonify({'error': 'Permission denied', 'action': action}), 403
                return redirect(url_for('auth.app_redirect'))
                
            return f(*args, **kwargs)
        return decorated_function
    return decorator
