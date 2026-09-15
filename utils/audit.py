import json
from flask import session, request
from utils.db import execute_db, query_db
from utils.logger import get_logger

logger = get_logger('audit')


def log_audit(action, entity_type=None, entity_id=None, detail=None):
    user_id = session.get('user_id') if session else None
    ip = request.remote_addr if request else None
    detail_json = json.dumps(detail) if detail else None

    if user_id:
        try:
            user_exists = query_db('SELECT id FROM users WHERE id = %s', (user_id,), one=True)
            if not user_exists:
                user_id = None
        except Exception:
            user_id = None

    try:
        execute_db(
            'INSERT INTO audit_logs (user_id, action, entity_type, entity_id, detail, ip_address) VALUES (%s, %s, %s, %s, %s, %s)',
            (user_id, action, entity_type, str(entity_id) if entity_id else None, detail_json, ip)
        )
        logger.debug('Audit log recorded: action=%s, entity_type=%s, entity_id=%s', action, entity_type, entity_id)
    except Exception as e:
        logger.error('Failed to record audit log: %s | Action: %s', e, action)
