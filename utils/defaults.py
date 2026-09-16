from utils.db import query_db
from flask import abort

def get_user_center_id(user):
    if user and isinstance(user, dict) and user.get('center_id'):
        return user['center_id']
    try:
        default_center = query_db('SELECT id FROM centers ORDER BY id ASC LIMIT 1', one=True)
        return default_center['id'] if default_center else None
    except Exception:
        return None

def get_center_or_404(center_id):
    if not center_id:
        abort(400, description='No healthcare facility assigned to your account.')
    center = query_db('SELECT * FROM centers WHERE id = %s', (center_id,), one=True)
    if not center:
        abort(404, description='Healthcare facility not found.')
    return center
