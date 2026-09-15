
DROP SCHEMA IF EXISTS public CASCADE;
CREATE SCHEMA public;
GRANT ALL ON SCHEMA public TO PUBLIC;

CREATE TABLE centers (
    id VARCHAR(30) PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    type VARCHAR(50) NOT NULL,
    region VARCHAR(100) NOT NULL,
    state VARCHAR(100) NOT NULL,
    address TEXT NOT NULL,
    lat DECIMAL(10, 7),
    lng DECIMAL(10, 7),
    phone VARCHAR(20),
    resources TEXT,
    is_active SMALLINT NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    staff_id VARCHAR(30) UNIQUE,
    username VARCHAR(100) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    full_name VARCHAR(200) NOT NULL,
    role VARCHAR(50) NOT NULL,
    center_id VARCHAR(30) REFERENCES centers(id) ON DELETE SET NULL,
    phone VARCHAR(20),
    email VARCHAR(200),
    totp_secret VARCHAR(64),
    is_active SMALLINT NOT NULL DEFAULT 1,
    lang_pref VARCHAR(10) NOT NULL DEFAULT 'en',
    invite_status VARCHAR(30) NOT NULL DEFAULT 'active',
    invite_token VARCHAR(100),
    designation VARCHAR(100),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    failed_login_count INTEGER DEFAULT 0,
    locked_until TIMESTAMP,
    session_version INTEGER DEFAULT 1
);
CREATE INDEX idx_user_role ON users(role);
CREATE INDEX idx_user_center ON users(center_id);

CREATE TABLE patients (
    id VARCHAR(30) PRIMARY KEY,
    linked_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    full_name VARCHAR(200) NOT NULL,
    dob DATE,
    gender VARCHAR(20),
    phone VARCHAR(20),
    address TEXT,
    aadhaar_hash VARCHAR(64),
    blood_group VARCHAR(20),
    allergies TEXT,
    chronic_conditions TEXT,
    center_id VARCHAR(30) REFERENCES centers(id) ON DELETE CASCADE,
    is_high_risk SMALLINT NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_pat_center ON patients(center_id);
CREATE INDEX idx_pat_user ON patients(linked_user_id);

CREATE TABLE vehicles (
    id VARCHAR(30) PRIMARY KEY,
    type VARCHAR(50) NOT NULL DEFAULT 'ambulance',
    region VARCHAR(100) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'available',
    center_id VARCHAR(30) REFERENCES centers(id) ON DELETE SET NULL,
    driver_name VARCHAR(200),
    driver_phone VARCHAR(20),
    lat DECIMAL(10, 7),
    lng DECIMAL(10, 7),
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_veh_status ON vehicles(status);
CREATE INDEX idx_veh_region ON vehicles(region);

CREATE TABLE appointments (
    id SERIAL PRIMARY KEY,
    patient_id VARCHAR(30) NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    center_id VARCHAR(30) NOT NULL REFERENCES centers(id) ON DELETE CASCADE,
    doctor_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    token_number VARCHAR(30) NOT NULL,
    department VARCHAR(100) NOT NULL DEFAULT 'General Medicine',
    referral_id INTEGER,
    slot_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP,
    reason VARCHAR(500),
    urgency SMALLINT NOT NULL DEFAULT 3,
    status VARCHAR(50) NOT NULL DEFAULT 'scheduled',
    notes TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_appt_patient ON appointments(patient_id);
CREATE INDEX idx_appt_doctor ON appointments(doctor_id);
CREATE INDEX idx_appt_center_status ON appointments(center_id, status);

CREATE TABLE medical_records (
    id SERIAL PRIMARY KEY,
    patient_id VARCHAR(30) NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    record_type VARCHAR(50) DEFAULT 'consultation',
    title VARCHAR(200),
    data TEXT,
    center_id VARCHAR(30) NOT NULL REFERENCES centers(id) ON DELETE CASCADE,
    created_by INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_mr_patient ON medical_records(patient_id);
CREATE INDEX idx_mr_center ON medical_records(center_id);

CREATE TABLE prescriptions (
    id SERIAL PRIMARY KEY,
    record_id INTEGER REFERENCES medical_records(id) ON DELETE SET NULL,
    patient_id VARCHAR(30) NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    medicines TEXT NOT NULL,
    notes TEXT,
    prescribed_by INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    center_id VARCHAR(30) NOT NULL REFERENCES centers(id) ON DELETE CASCADE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_rx_record ON prescriptions(record_id);
CREATE INDEX idx_rx_patient ON prescriptions(patient_id);
CREATE INDEX idx_rx_center ON prescriptions(center_id);

CREATE TABLE lab_records (
    id SERIAL PRIMARY KEY,
    patient_id VARCHAR(30) NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    test_name VARCHAR(200) NOT NULL,
    test_category VARCHAR(100),
    result TEXT,
    result_data TEXT,
    status VARCHAR(50) NOT NULL DEFAULT 'ordered',
    center_id VARCHAR(30) NOT NULL REFERENCES centers(id) ON DELETE CASCADE,
    ordered_by INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    resulted_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_lab_patient ON lab_records(patient_id);
CREATE INDEX idx_lab_center ON lab_records(center_id);

CREATE TABLE teleconsult_sessions (
    id SERIAL PRIMARY KEY,
    patient_id VARCHAR(30) NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    doctor_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    center_id VARCHAR(30) NOT NULL REFERENCES centers(id) ON DELETE CASCADE,
    status VARCHAR(50) NOT NULL DEFAULT 'requested',
    summary TEXT,
    started_at TIMESTAMP,
    ended_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_tc_doctor ON teleconsult_sessions(doctor_id);
CREATE INDEX idx_tc_patient ON teleconsult_sessions(patient_id);
CREATE INDEX idx_tc_status ON teleconsult_sessions(status);

CREATE TABLE teleconsult_messages (
    id SERIAL PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES teleconsult_sessions(id) ON DELETE CASCADE,
    sender_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    body TEXT NOT NULL,
    sent_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_tcm_session ON teleconsult_messages(session_id, sent_at);

CREATE TABLE referrals (
    id SERIAL PRIMARY KEY,
    patient_id VARCHAR(30) NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    from_center VARCHAR(30) NOT NULL REFERENCES centers(id) ON DELETE CASCADE,
    to_center VARCHAR(30) NOT NULL REFERENCES centers(id) ON DELETE CASCADE,
    urgency VARCHAR(50) NOT NULL DEFAULT 'medium',
    status VARCHAR(50) NOT NULL DEFAULT 'initiated',
    reason TEXT,
    notes TEXT,
    created_by INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    accepted_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    completed_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_ref_patient ON referrals(patient_id);
CREATE INDEX idx_ref_from ON referrals(from_center);
CREATE INDEX idx_ref_to ON referrals(to_center);
CREATE INDEX idx_ref_status ON referrals(status);

CREATE TABLE follow_ups (
    id SERIAL PRIMARY KEY,
    patient_id VARCHAR(30) NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    category VARCHAR(50) DEFAULT 'general',
    due_date DATE NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    assigned_to INTEGER REFERENCES users(id) ON DELETE SET NULL,
    notes TEXT,
    completed_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_fu_patient ON follow_ups(patient_id);
CREATE INDEX idx_fu_due ON follow_ups(due_date);

CREATE TABLE triage_entries (
    id SERIAL PRIMARY KEY,
    patient_id VARCHAR(30) NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    center_id VARCHAR(30) NOT NULL REFERENCES centers(id) ON DELETE CASCADE,
    assessed_by INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    urgency_score SMALLINT NOT NULL,
    symptoms TEXT NOT NULL,
    vitals TEXT,
    recommendation TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_tri_patient ON triage_entries(patient_id);
CREATE INDEX idx_tri_center ON triage_entries(center_id);
CREATE INDEX idx_tri_urgency ON triage_entries(urgency_score);

CREATE TABLE inventory_items (
    id SERIAL PRIMARY KEY,
    center_id VARCHAR(30) NOT NULL REFERENCES centers(id) ON DELETE CASCADE,
    item_name VARCHAR(200) NOT NULL,
    category VARCHAR(100) NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 0,
    unit VARCHAR(30) NOT NULL,
    expiry_date DATE,
    reorder_level INTEGER NOT NULL DEFAULT 10,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_inv_center ON inventory_items(center_id);

CREATE TABLE notifications (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR(300) NOT NULL,
    body TEXT NOT NULL,
    link VARCHAR(500),
    is_read SMALLINT NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_notif_user ON notifications(user_id);
CREATE INDEX idx_notif_user_read ON notifications(user_id, is_read);

CREATE TABLE audit_logs (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER,
    action VARCHAR(100) NOT NULL,
    entity_type VARCHAR(50) NOT NULL,
    entity_id VARCHAR(50),
    detail TEXT,
    ip_address VARCHAR(45),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_audit_user ON audit_logs(user_id);
CREATE INDEX idx_audit_action ON audit_logs(action);

CREATE TABLE role_permissions (
    role VARCHAR(50) NOT NULL,
    action VARCHAR(100) NOT NULL,
    is_allowed SMALLINT NOT NULL DEFAULT 1,
    PRIMARY KEY (role, action)
);


INSERT INTO centers (id, name, type, region, state, address, lat, lng, phone, resources, is_active, created_at, updated_at) VALUES
    ('FAC-BAKROL-01', 'Primary Health Centre (PHC) Bakrol', 'PHC', 'Vallabh Vidyanagar', 'Gujarat', 'Near Bakrol Gate, Bakrol-Vadtal Road, Bakrol, Vallabh Vidyanagar 388315', '22.5488200', '72.9372100', '+91 2692 236104', '{"beds": 15, "ambulance": 2, "oxygen": 8, "opd_daily": 140, "timings": "24x7 Emergency", "emergency_24x7": true}', 1, '2026-09-05 22:21:01', '2026-09-14 21:47:42'),
    ('FAC-BVM-07', 'Bhaikaka Community Care SubCentre (BVM Campus)', 'SubCentre', 'Vallabh Vidyanagar', 'Gujarat', 'Opposite BVM Engineering College, AV Road, Vallabh Vidyanagar 388120', '22.5522400', '72.9288700', '+91 2692 230104', '{"first_aid": true, "teleconsult": true, "asha_workers": 4, "student_health": true}', 1, '2026-09-05 22:21:01', '2026-09-05 22:21:01'),
    ('FAC-CIVIL-08', 'Anand General Civil District Hospital', 'DH', 'Anand', 'Gujarat', 'Borsad Chokdi, Station Road, Anand 388001', '22.5645000', '72.9585000', '+91 2692 250100', '{"beds": 350, "blood_bank": true, "burn_unit": true, "dialysis": true, "emergency_24x7": true}', 1, '2026-09-05 22:21:01', '2026-09-05 22:21:01'),
    ('FAC-GAMDI-05', 'Urban Primary Health Centre (UPHC) Gamdi Gate', 'PHC', 'Anand', 'Gujarat', 'Near Gamdi Gate, Anand - Vidyanagar Highway, Anand 388001', '22.5582300', '72.9461200', '+91 2692 245220', '{"beds": 10, "ambulance": 1, "maternal_care": true, "immunization": true}', 1, '2026-09-05 22:21:01', '2026-09-05 22:21:01'),
    ('FAC-KARAMSAD-03', 'Community Health Centre (CHC) Karamsad', 'CHC', 'Karamsad', 'Gujarat', 'Karamsad Main Road, Near Sardar Patel Memorial, Karamsad 388325', '22.5495100', '72.9052300', '+91 2692 222108', '{"beds": 30, "ambulance": 2, "maternity_ward": true, "lab": true}', 1, '2026-09-05 22:21:01', '2026-09-05 22:21:01'),
    ('FAC-SKH-02', 'Shree Krishna Hospital & Bhaikaka Medical Centre', 'DH', 'Karamsad', 'Gujarat', 'Gokal Nagar, Karamsad - Vidyanagar Road, Anand 388325', '22.5471400', '72.8986500', '+91 2692 228411', '{"beds": 550, "icu_beds": 60, "ambulance": 6, "blood_bank": true, "specialities": ["Cardiology", "Trauma", "Pediatrics", "Oncology"]}', 1, '2026-09-05 22:21:01', '2026-09-05 22:21:01'),
    ('FAC-VVN-04', 'Vidyanagar Municipal Dispensary & Health Post', 'Dispensary', 'Vallabh Vidyanagar', 'Gujarat', 'Mota Bazaar, Near Shastri Maidan, Vallabh Vidyanagar 388120', '22.5530100', '72.9240300', '+91 2692 230457', '{"opd_rooms": 3, "pharmacy": true, "vaccination": true, "timings": "9:00 AM - 1:00 PM, 4:00 PM - 7:00 PM"}', 1, '2026-09-05 22:21:01', '2026-09-05 22:21:01'),
    ('FAC-ZYDUS-06', 'Zydus Healthcare Hospital & Trauma Centre', 'DH', 'Anand', 'Gujarat', 'Anand-Lambhvel Road, Near GIDC Phase 2, Anand 388001', '22.5760500', '72.9520400', '+91 2692 667000', '{"beds": 200, "icu_beds": 30, "emergency_24x7": true, "trauma_centre": true}', 1, '2026-09-05 22:21:01', '2026-09-05 22:21:01');

INSERT INTO users (id, staff_id, username, password_hash, full_name, role, center_id, phone, email, totp_secret, is_active, lang_pref, invite_status, invite_token, designation, created_at, updated_at, failed_login_count, locked_until, session_version) VALUES
    (1, 'ADM-2026-001', 'admin', '$2b$12$4o4lqHmY0MDN8wksSvpXPeEI4wZ8dPqqi2XMwA8A.fH78QTZJ7BNa', 'Master Health Administrator', 'system_admin', NULL, '+91 2692 230000', 'admin@anvayavistara.in', NULL, 1, 'en', 'active', NULL, 'Chief Health Officer / System Governor', '2026-09-05 22:21:01', '2026-09-14 14:35:24', 0, NULL, 2),
    (2, 'RAD-2026-001', 'admin_bakrol', '$2b$12$Yz5KF22ZtBhO5qyffLBDPepdSDw.6luqFgpZ.9mBEuvhdJqOiMrrC', 'Bakrol PHC Administrator', 'region_admin', 'FAC-BAKROL-01', '+91 2692 236105', 'bakrol.admin@anvayavistara.in', NULL, 1, 'en', 'active', NULL, 'Facility Health In-Charge', '2026-09-05 22:21:01', '2026-09-14 21:47:43', 0, NULL, 3),
    (3, 'RAD-2026-002', 'admin_skh', '$2b$12$4o4lqHmY0MDN8wksSvpXPeEI4wZ8dPqqi2XMwA8A.fH78QTZJ7BNa', 'Shree Krishna Hospital Admin', 'region_admin', 'FAC-SKH-02', '+91 2692 228412', 'skh.admin@anvayavistara.in', NULL, 1, 'en', 'active', NULL, 'Medical Superintendent Admin', '2026-09-05 22:21:01', '2026-09-06 12:33:51', 0, NULL, 2),
    (4, 'RAD-2026-003', 'admin_karamsad', '$2b$12$4o4lqHmY0MDN8wksSvpXPeEI4wZ8dPqqi2XMwA8A.fH78QTZJ7BNa', 'Karamsad CHC Administrator', 'region_admin', 'FAC-KARAMSAD-03', '+91 2692 222109', 'karamsad.admin@anvayavistara.in', NULL, 1, 'en', 'active', NULL, 'CHC Regional Supervisor', '2026-09-05 22:21:01', '2026-09-06 13:25:20', 0, NULL, 2),
    (5, 'RAD-2026-004', 'admin_vvn', '$2b$12$4o4lqHmY0MDN8wksSvpXPeEI4wZ8dPqqi2XMwA8A.fH78QTZJ7BNa', 'Vidyanagar Dispensary Admin', 'region_admin', 'FAC-VVN-04', '+91 2692 230457', 'vvn.admin@anvayavistara.in', NULL, 1, 'en', 'active', NULL, 'Municipal Health Supervisor', '2026-09-05 22:21:01', '2026-09-06 12:33:51', 0, NULL, 2),
    (6, 'RAD-2026-005', 'admin_gamdi', '$2b$12$4o4lqHmY0MDN8wksSvpXPeEI4wZ8dPqqi2XMwA8A.fH78QTZJ7BNa', 'Gamdi UPHC Administrator', 'region_admin', 'FAC-GAMDI-05', '+91 2692 245221', 'gamdi.admin@anvayavistara.in', NULL, 1, 'en', 'active', NULL, 'Urban Health Center Admin', '2026-09-05 22:21:01', '2026-09-06 12:33:51', 0, NULL, 2),
    (7, 'RAD-2026-006', 'admin_zydus', '$2b$12$4o4lqHmY0MDN8wksSvpXPeEI4wZ8dPqqi2XMwA8A.fH78QTZJ7BNa', 'Zydus Trauma Centre Admin', 'region_admin', 'FAC-ZYDUS-06', '+91 2692 667001', 'zydus.admin@anvayavistara.in', NULL, 1, 'en', 'active', NULL, 'Hospital Operations Admin', '2026-09-05 22:21:01', '2026-09-06 12:33:51', 0, NULL, 2),
    (8, 'RAD-2026-007', 'admin_bvm', '$2b$12$4o4lqHmY0MDN8wksSvpXPeEI4wZ8dPqqi2XMwA8A.fH78QTZJ7BNa', 'BVM SubCentre Administrator', 'region_admin', 'FAC-BVM-07', '+91 2692 230105', 'bvm.admin@anvayavistara.in', NULL, 1, 'en', 'active', NULL, 'SubCentre Field Coordinator', '2026-09-05 22:21:01', '2026-09-06 16:08:39', 0, NULL, 2),
    (9, 'RAD-2026-008', 'admin_anand', '$2b$12$4o4lqHmY0MDN8wksSvpXPeEI4wZ8dPqqi2XMwA8A.fH78QTZJ7BNa', 'District Civil Hospital Admin', 'region_admin', 'FAC-CIVIL-08', '+91 2692 250101', 'anand.admin@anvayavistara.in', NULL, 1, 'en', 'active', NULL, 'District Administrative Officer', '2026-09-05 22:21:01', '2026-09-06 12:34:55', 5, '2026-09-06 12:49:55', 2),
    (13, 'PHM-2026-001', 'drvallabh', '$2b$12$IzgZH65W1gVs8VAwZLbLNO8qY4eH5Nb8OTMLee5gw/UpOL3FW3pRG', 'Dr. Vallabh Mehrotra', 'doctor', 'FAC-BAKROL-01', '+91 98765 43210', 'vallabhmehrotra45@gmail.com', NULL, 1, 'en', 'active', NULL, 'Medical Officer / General Physician', '2026-09-05 22:21:01', '2026-09-07 08:16:52', 0, NULL, 3),
    
SELECT setval('users_id_seq', COALESCE((SELECT MAX(id) FROM users), 1));

INSERT INTO role_permissions (role, action, is_allowed) VALUES
    ('doctor', 'create_consultation', 1),
    ('doctor', 'manage_appointments', 1),
    ('doctor', 'manage_facilities', 0),
    ('doctor', 'manage_inventory', 0),
    ('doctor', 'manage_permissions', 0),
    ('doctor', 'manage_prescriptions', 1),
    ('doctor', 'manage_referrals', 1),
    ('doctor', 'manage_staff', 0),
    ('doctor', 'register_patient', 1),
    ('doctor', 'teleconsult', 1),
    ('doctor', 'view_analytics', 0),
    ('doctor', 'view_appointments', 1),
    ('doctor', 'view_audit_logs', 0),
    ('doctor', 'view_inventory', 1),
    ('doctor', 'view_records', 1),
    ('nurse', 'create_consultation', 0),
    ('nurse', 'manage_appointments', 1),
    ('nurse', 'manage_facilities', 0),
    ('nurse', 'manage_inventory', 0),
    ('nurse', 'manage_permissions', 0),
    ('nurse', 'manage_prescriptions', 0),
    ('nurse', 'manage_referrals', 0),
    ('nurse', 'manage_staff', 0),
    ('nurse', 'register_patient', 1),
    ('nurse', 'teleconsult', 0),
    ('nurse', 'view_analytics', 0),
    ('nurse', 'view_appointments', 1),
    ('nurse', 'view_audit_logs', 0),
    ('nurse', 'view_inventory', 1),
    ('nurse', 'view_records', 1),
    ('patient', 'create_consultation', 0),
    ('patient', 'manage_appointments', 0),
    ('patient', 'manage_facilities', 0),
    ('patient', 'manage_inventory', 0),
    ('patient', 'manage_permissions', 0),
    ('patient', 'manage_prescriptions', 0),
    ('patient', 'manage_referrals', 0),
    ('patient', 'manage_staff', 0),
    ('patient', 'register_patient', 0),
    ('patient', 'teleconsult', 1),
    ('patient', 'view_analytics', 0),
    ('patient', 'view_appointments', 1),
    ('patient', 'view_audit_logs', 0),
    ('patient', 'view_inventory', 0),
    ('patient', 'view_records', 1),
    ('pharmacist', 'create_consultation', 0),
    ('pharmacist', 'manage_appointments', 0),
    ('pharmacist', 'manage_facilities', 0),
    ('pharmacist', 'manage_inventory', 1),
    ('pharmacist', 'manage_permissions', 0),
    ('pharmacist', 'manage_prescriptions', 1),
    ('pharmacist', 'manage_referrals', 0),
    ('pharmacist', 'manage_staff', 0),
    ('pharmacist', 'register_patient', 0),
    ('pharmacist', 'teleconsult', 0),
    ('pharmacist', 'view_analytics', 0),
    ('pharmacist', 'view_appointments', 0),
    ('pharmacist', 'view_audit_logs', 0),
    ('pharmacist', 'view_inventory', 1),
    ('pharmacist', 'view_records', 1),
    ('receptionist', 'create_consultation', 0),
    ('receptionist', 'manage_appointments', 1),
    ('receptionist', 'manage_facilities', 0),
    ('receptionist', 'manage_inventory', 0),
    ('receptionist', 'manage_permissions', 0),
    ('receptionist', 'manage_prescriptions', 0),
    ('receptionist', 'manage_referrals', 0),
    ('receptionist', 'manage_staff', 0),
    ('receptionist', 'register_patient', 1),
    ('receptionist', 'teleconsult', 0),
    ('receptionist', 'view_analytics', 0),
    ('receptionist', 'view_appointments', 1),
    ('receptionist', 'view_audit_logs', 0),
    ('receptionist', 'view_inventory', 0),
    ('receptionist', 'view_records', 0),
    ('region_admin', 'create_consultation', 1),
    ('region_admin', 'manage_appointments', 1),
    ('region_admin', 'manage_facilities', 0),
    ('region_admin', 'manage_inventory', 1),
    ('region_admin', 'manage_permissions', 0),
    ('region_admin', 'manage_prescriptions', 1),
    ('region_admin', 'manage_referrals', 1),
    ('region_admin', 'manage_staff', 1),
    ('region_admin', 'register_patient', 1),
    ('region_admin', 'teleconsult', 1),
    ('region_admin', 'view_analytics', 1),
    ('region_admin', 'view_appointments', 1),
    ('region_admin', 'view_audit_logs', 1),
    ('region_admin', 'view_inventory', 1),
    ('region_admin', 'view_records', 1),
    ('system_admin', 'create_consultation', 1),
    ('system_admin', 'manage_appointments', 1),
    ('system_admin', 'manage_facilities', 1),
    ('system_admin', 'manage_inventory', 1),
    ('system_admin', 'manage_permissions', 1),
    ('system_admin', 'manage_prescriptions', 1),
    ('system_admin', 'manage_referrals', 1),
    ('system_admin', 'manage_staff', 1),
    ('system_admin', 'register_patient', 1),
    ('system_admin', 'teleconsult', 1),
    ('system_admin', 'view_analytics', 1),
    ('system_admin', 'view_appointments', 1),
    ('system_admin', 'view_audit_logs', 1),
    ('system_admin', 'view_inventory', 1),
    ('system_admin', 'view_records', 1);
