import os
import re
import time
import json
import ipaddress
import threading
import urllib.request
import urllib.parse
from functools import wraps
from flask import request, jsonify, flash, render_template, redirect, url_for, current_app
from utils.audit import log_audit
from utils.logger import get_logger

logger = get_logger("security")

_ip_lockout_lock = threading.Lock()
_ip_lockout_store = {}

MAX_FAILED_LOGIN_ATTEMPTS = 5
IP_LOCKOUT_DURATION_SECONDS = 15 * 60
ATTEMPT_WINDOW_SECONDS = 15 * 60

_vpn_cache_lock = threading.Lock()
_vpn_cache = {}
VPN_CACHE_TTL = 86400

KNOWN_VPN_KEYWORDS = [
    'vpn', 'proxy', 'hosting', 'datacenter', 'tor', 'exit node', 'mullvad', 'nordvpn',
    'expressvpn', 'surfshark', 'proton', 'ovh', 'linode', 'digitalocean', 'vultr',
    'hetzner', 'leaseweb', 'datacamp', 'choopa', 'm247', 'packetfabric', 'shadowsocks',
    'fastly', 'cloudflare', 'akamai', 'aws', 'amazon', 'azure', 'google cloud'
]


def is_private_ip(ip_str):
    if not ip_str or ip_str in ('localhost', '::1', 'testclient', '127.0.0.1'):
        return True
    try:
        ip = ipaddress.ip_address(ip_str)
        return (
            ip.is_private or
            ip.is_loopback or
            ip.is_reserved or
            ip.is_link_local or
            ip.is_unspecified
        )
    except ValueError:
        return True


def get_client_ip():
    if not request:
        return '127.0.0.1'

    cf_ip = request.headers.get('CF-Connecting-IP')
    if cf_ip and cf_ip.strip():
        return cf_ip.strip()

    x_real_ip = request.headers.get('X-Real-IP')
    if x_real_ip and x_real_ip.strip():
        return x_real_ip.strip()

    x_forwarded_for = request.headers.get('X-Forwarded-For')
    if x_forwarded_for:
        ips = [ip.strip() for ip in x_forwarded_for.split(',') if ip.strip()]
        for ip in ips:
            if not is_private_ip(ip):
                return ip
        if ips:
            return ips[0]

    return request.remote_addr or '127.0.0.1'


def check_ip_lockout(ip=None):
    if ip is None:
        ip = get_client_ip()

    now = time.time()
    with _ip_lockout_lock:
        data = _ip_lockout_store.get(ip)
        if not data:
            return False, 0, MAX_FAILED_LOGIN_ATTEMPTS

        if data.get('locked_until', 0) > now:
            remaining = int(data['locked_until'] - now)
            return True, remaining, 0

        if data.get('locked_until', 0) > 0 and data['locked_until'] <= now:
            data['failed_count'] = 0
            data['locked_until'] = 0

        if now - data.get('last_attempt', 0) > ATTEMPT_WINDOW_SECONDS:
            data['failed_count'] = 0

        remaining_attempts = max(0, MAX_FAILED_LOGIN_ATTEMPTS - data.get('failed_count', 0))
        return False, 0, remaining_attempts


def record_failed_ip_login(ip=None):
    if ip is None:
        ip = get_client_ip()

    now = time.time()
    with _ip_lockout_lock:
        data = _ip_lockout_store.setdefault(ip, {'failed_count': 0, 'locked_until': 0, 'last_attempt': now})

        if data.get('locked_until', 0) > now:
            remaining = int(data['locked_until'] - now)
            return True, remaining, 0

        if now - data.get('last_attempt', 0) > ATTEMPT_WINDOW_SECONDS:
            data['failed_count'] = 0

        data['failed_count'] += 1
        data['last_attempt'] = now

        if data['failed_count'] >= MAX_FAILED_LOGIN_ATTEMPTS:
            data['locked_until'] = now + IP_LOCKOUT_DURATION_SECONDS
            logger.warning("IP address %s locked out for %s seconds due to multiple failed login attempts", ip, IP_LOCKOUT_DURATION_SECONDS)
            return True, IP_LOCKOUT_DURATION_SECONDS, 0
        else:
            remaining_attempts = MAX_FAILED_LOGIN_ATTEMPTS - data['failed_count']
            return False, 0, remaining_attempts


def clear_ip_login_attempts(ip=None):
    if ip is None:
        ip = get_client_ip()
    with _ip_lockout_lock:
        if ip in _ip_lockout_store:
            _ip_lockout_store[ip]['failed_count'] = 0
            _ip_lockout_store[ip]['locked_until'] = 0


def check_vpn_proxy(ip=None):
    block_vpn = os.getenv('BLOCK_VPN', 'false').lower() == 'true'
    is_testing = False
    if current_app:
        block_vpn = current_app.config.get('BLOCK_VPN', block_vpn)
        is_testing = bool(current_app.testing or current_app.config.get('TESTING'))

    if is_testing:
        if not request or not request.headers.get('X-Force-VPN-Check'):
            return False, None

    if not block_vpn:
        return False, None

    if ip is None:
        ip = get_client_ip()

    if is_testing and request and request.headers.get('X-Force-VPN-Check') == '1':
        return True, 'Simulated VPN Connection'

    if is_private_ip(ip):
        return False, None

    if is_testing and request and request.headers.get('X-Bypass-VPN-Check') == '1':
        return False, None

    if request:
        proxy_headers = ['HTTP_VIA', 'HTTP_X_FORWARDED_FOR_PROXY', 'HTTP_PROXY_CONNECTION']
        for hdr in proxy_headers:
            if request.environ.get(hdr):
                return True, 'Proxy header detected'

    now = time.time()
    with _vpn_cache_lock:
        cached = _vpn_cache.get(ip)
        if cached and cached.get('expires', 0) > now:
            return cached['is_vpn'], cached['reason']

    is_vpn = False
    reason = None

    try:
        url = f"http://ip-api.com/json/{urllib.parse.quote(ip)}?fields=status,message,proxy,hosting,org,as,query"
        req = urllib.request.Request(url, headers={'User-Agent': 'AnvayaVistara-Security/1.0'})
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            if data.get('status') == 'success':
                if data.get('proxy'):
                    is_vpn = True
                    reason = 'VPN / Proxy detected'
                elif data.get('hosting'):
                    is_vpn = True
                    reason = f"Datacenter / Hosting network detected ({data.get('org', 'Cloud Provider')})"
                else:
                    org_str = (data.get('org', '') + ' ' + data.get('as', '')).lower()
                    for kw in KNOWN_VPN_KEYWORDS:
                        if kw in org_str:
                            is_vpn = True
                            reason = f"VPN / Anonymizer network detected ({kw})"
                            break
    except Exception:
        is_vpn = False
        reason = None

    with _vpn_cache_lock:
        _vpn_cache[ip] = {
            'is_vpn': is_vpn,
            'reason': reason,
            'expires': now + VPN_CACHE_TTL
        }

    return is_vpn, reason


def block_if_vpn():
    is_vpn, reason = check_vpn_proxy()
    if is_vpn:
        client_ip = get_client_ip()
        log_audit('vpn_blocked_access', 'security', None, {'ip': client_ip, 'reason': reason, 'path': request.path})
        logger.warning("Access blocked from VPN/Proxy: ip=%s, reason=%s, path=%s", client_ip, reason, request.path)
        msg = 'Security Notice: VPN, Proxy, or Anonymizing network detected. Login and registration are restricted from VPN/Proxy connections. Please disconnect your VPN to continue.'
        if request.is_json or request.path.startswith('/api/'):
            return jsonify({'error': 'VPN_DETECTED', 'message': msg, 'reason': reason}), 403
        flash(msg, 'error')
        if request.path.startswith('/signup'):
            return render_template('signup.html', form_data={})
        return render_template('login.html', active_tab='username', form_data={})
    return None
