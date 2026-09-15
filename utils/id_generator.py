import datetime
import re
from utils.db import query_db


def generate_patient_id():
    year = datetime.datetime.now().year
    row = query_db("SELECT id FROM patients WHERE id LIKE %s ORDER BY id DESC LIMIT 1", (f"PAT-{year}-%",), one=True)
    if row and row.get('id'):
        try:
            last_seq = int(row['id'].split('-')[-1])
            next_seq = last_seq + 1
        except Exception:
            next_seq = 1
    else:
        count_row = query_db("SELECT COUNT(*) as cnt FROM patients", one=True)
        next_seq = (count_row['cnt'] if count_row else 0) + 1

    pat_id = f"PAT-{year}-{next_seq:04d}"
    while query_db("SELECT id FROM patients WHERE id = %s", (pat_id,), one=True):
        next_seq += 1
        pat_id = f"PAT-{year}-{next_seq:04d}"
    return pat_id


def generate_staff_id(role):
    prefix_map = {
        'doctor': 'DOC',
        'nurse': 'NRS',
        'pharmacist': 'PHM',
        'lab_technician': 'LAB',
        'ambulance_op': 'AMB',
        'receptionist': 'REC',
        'care_taker': 'ASH',
        'helper': 'HLP',
        'therapist': 'THR',
        'region_admin': 'RAD',
        'system_admin': 'ADM'
    }
    pfx = prefix_map.get(role, 'STF')
    year = datetime.datetime.now().year
    
    row = query_db("SELECT staff_id FROM users WHERE staff_id LIKE %s ORDER BY staff_id DESC LIMIT 1", (f"{pfx}-{year}-%",), one=True)
    if row and row.get('staff_id'):
        try:
            last_seq = int(row['staff_id'].split('-')[-1])
            next_seq = last_seq + 1
        except Exception:
            next_seq = 1
    else:
        count_row = query_db("SELECT COUNT(*) as cnt FROM users WHERE role = %s", (role,), one=True)
        next_seq = (count_row['cnt'] if count_row else 0) + 1

    staff_id = f"{pfx}-{year}-{next_seq:03d}"
    while query_db("SELECT id FROM users WHERE staff_id = %s", (staff_id,), one=True):
        next_seq += 1
        staff_id = f"{pfx}-{year}-{next_seq:03d}"
    return staff_id


def generate_facility_id(name_or_region):
    words = [w for w in re.split(r'[\s\-_(),]+', name_or_region or '') if w.upper() not in ('PRIMARY', 'HEALTH', 'CENTRE', 'CENTER', 'COMMUNITY', 'HOSPITAL', 'DISPENSARY', 'SUBCENTRE', 'PHC', 'DH', 'UPHC', 'THE', 'AND')]
    if words:
        keyword = words[0].upper()
    else:
        keyword = ''.join(ch for ch in (name_or_region or 'FAC').upper() if ch.isalnum())[:6]
    
    keyword = re.sub(r'[^A-Z0-9]', '', keyword)[:8] or 'CTR'

    cnt = (query_db("SELECT COUNT(*) as cnt FROM centers", one=True) or {}).get('cnt', 0) + 1
    fac_id = f"FAC-{keyword}-{cnt:02d}"
    while query_db("SELECT id FROM centers WHERE id = %s", (fac_id,), one=True):
        cnt += 1
        fac_id = f"FAC-{keyword}-{cnt:02d}"
    return fac_id
