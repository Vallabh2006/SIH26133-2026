import json
from flask import session, request
from utils.db import execute_db
from utils.logger import get_logger

logger = get_logger('audit')


def log_audit(action, entity_type=None, entity_id=None, detail=None):
    user_id = session.get('user_id') if session else None
    
    ip = None
    if request:
        try:
            from utils.security import get_client_ip
            ip = get_client_ip()
        except Exception:
            ip = request.remote_addr
            
    detail_json = json.dumps(detail) if detail else None

    try:
        execute_db(
            'INSERT INTO audit_logs (user_id, action, entity_type, entity_id, detail, ip_address) VALUES (%s, %s, %s, %s, %s, %s)',
            (user_id, action, entity_type, str(entity_id) if entity_id else None, detail_json, ip)
        )
        logger.debug('Audit log recorded: action=%s, entity_type=%s, entity_id=%s', action, entity_type, entity_id)
    except Exception as e:
        # If user_id failed foreign key constraint (e.g. user was deleted), retry with user_id=None
        if user_id:
            try:
                execute_db(
                    'INSERT INTO audit_logs (user_id, action, entity_type, entity_id, detail, ip_address) VALUES (%s, %s, %s, %s, %s, %s)',
                    (None, action, entity_type, str(entity_id) if entity_id else None, detail_json, ip)
                )
                return
            except Exception:
                pass
        logger.error('Failed to record audit log: %s | Action: %s', e, action)
