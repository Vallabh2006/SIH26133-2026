import time
from datetime import datetime
from flask import Blueprint, request, jsonify, session, current_app
from utils.auth_helpers import get_current_user
from utils.db import query_db, execute_db
from app import limiter

api_bp = Blueprint('api', __name__, url_prefix='/api')

SUPPORTED_LANGUAGES = {'en', 'hi', 'mr', 'ta', 'te', 'kn', 'bn', 'gu', 'pa', 'ml', 'or'}


@api_bp.route('/health')
def health_check():
    try:
        db_check = query_db('SELECT 1 as healthy', one=True)
        db_ok = bool(db_check and db_check.get('healthy') == 1)
    except Exception:
        db_ok = False
    return jsonify({
        'ok': True,
        'data': {
            'status': 'healthy' if db_ok else 'degraded',
            'database': 'connected' if db_ok else 'disconnected',
            'timestamp': datetime.now().isoformat()
        },
        'message': 'Health check completed'
    })


@api_bp.route('/time')
def server_world_time():
    now = datetime.now()
    return jsonify({
        'ok': True,
        'data': {
            'epoch_ms': int(time.time() * 1000),
            'iso': now.isoformat(),
            'timezone': 'Asia/Kolkata (IST)',
            'formatted': now.strftime('%b %d, %Y - %I:%M:%S %p'),
            'date': now.strftime('%Y-%m-%d'),
            'time': now.strftime('%H:%M')
        },
        'message': 'Current server time'
    })


@api_bp.route('/notifications')
@limiter.limit('300 per hour')
def get_notifications():
    user = get_current_user()
    if not user:
        return jsonify({'ok': False, 'error': 'Unauthorized', 'code': 'UNAUTHORIZED'}), 401

    unread_only = request.args.get('unread', '0') == '1'
    if unread_only:
        notifs = query_db(
            'SELECT id, title, body, link, is_read, created_at FROM notifications '
            'WHERE user_id = %s AND is_read = 0 ORDER BY created_at DESC LIMIT 20',
            (user['id'],)
        ) or []
    else:
        notifs = query_db(
            'SELECT id, title, body, link, is_read, created_at FROM notifications '
            'WHERE user_id = %s ORDER BY created_at DESC LIMIT 50',
            (user['id'],)
        ) or []

    unread_count = query_db(
        'SELECT COUNT(*) as cnt FROM notifications WHERE user_id = %s AND is_read = 0',
        (user['id'],),
        one=True
    )
    count = unread_count['cnt'] if unread_count else 0

    formatted_notifs = [
        {
            'id': n['id'],
            'title': n['title'],
            'body': n.get('body', ''),
            'link': n.get('link', ''),
            'is_read': bool(n.get('is_read')),
            'created_at': n['created_at'].isoformat() if hasattr(n['created_at'], 'isoformat') else str(n['created_at'])
        } for n in notifs
    ]

    return jsonify({
        'ok': True,
        'data': {
            'count': count,
            'notifications': formatted_notifs
        },
        'count': count,
        'notifications': formatted_notifs
    })


@api_bp.route('/notifications/mark-read', methods=['POST'])
def mark_notifications_read():
    user = get_current_user()
    if not user:
        return jsonify({'ok': False, 'error': 'Unauthorized', 'code': 'UNAUTHORIZED'}), 401

    data = request.get_json(silent=True) or {}
    notification_id = data.get('id')

    if notification_id:
        execute_db('UPDATE notifications SET is_read = 1 WHERE id = %s AND user_id = %s', (notification_id, user['id']))
    else:
        execute_db('UPDATE notifications SET is_read = 1 WHERE user_id = %s', (user['id'],))

    return jsonify({'ok': True, 'data': {'notification_id': notification_id}, 'message': 'Notifications marked as read'})


@api_bp.route('/auth/set-lang', methods=['POST'])
@api_bp.route('/set-lang', methods=['POST'])
def set_lang():
    data = request.get_json(silent=True) or {}
    lang = (data.get('lang') or 'en').strip().lower()
    if lang not in SUPPORTED_LANGUAGES:
        lang = 'en'
        
    session['lang'] = lang

    if 'user_id' in session:
        try:
            execute_db('UPDATE users SET lang_pref = %s WHERE id = %s', (lang, session['user_id']))
        except Exception:
            pass

    is_secure = request.is_secure or (request.headers.get('X-Forwarded-Proto') == 'https')
    resp = jsonify({'ok': True, 'data': {'lang': lang}, 'lang': lang, 'message': 'Language updated'})
    resp.set_cookie('lang', lang, max_age=365*24*3600, httponly=True, samesite='Lax', secure=is_secure)
    return resp
