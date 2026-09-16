import os
from dotenv import load_dotenv

load_dotenv()

_secret_key = os.getenv('SECRET_KEY')
if not _secret_key:
    raise RuntimeError('SECRET_KEY environment variable must be set. Generate one with: python -c "import secrets; print(secrets.token_hex(32))"')

class Config:
    SECRET_KEY = _secret_key

    DB_TYPE = os.getenv('DB_TYPE', 'postgres')
    PG_HOST = os.getenv('PG_HOST', os.getenv('PGHOST', '/tmp'))
    PG_PORT = int(os.getenv('PG_PORT', os.getenv('PGPORT', 5432)))
    PG_USER = os.getenv('PG_USER', os.getenv('PGUSER', 'vallabh'))
    PG_PASSWORD = os.getenv('PG_PASSWORD', os.getenv('PGPASSWORD', ''))
    PG_DB = os.getenv('PG_DB', os.getenv('PGDATABASE', 'postgres'))
    PG_SSLMODE = os.getenv('PG_SSLMODE')

    SESSION_TYPE = os.getenv('SESSION_TYPE', 'filesystem')
    SESSION_FILE_DIR = os.path.join(os.path.dirname(__file__), '.flask_sessions')
    SESSION_PERMANENT = True
    PERMANENT_SESSION_LIFETIME = 3600
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    _redis_url = os.getenv('SESSION_REDIS')
    if SESSION_TYPE == 'redis' and _redis_url:
        import redis
        SESSION_REDIS = redis.from_url(_redis_url)

    MAX_CONTENT_LENGTH = 16 * 1024 * 1024

    WTF_CSRF_SSL_STRICT = False
    WTF_CSRF_TIME_LIMIT = None
    OTP_ISSUER = 'Anvaya Vistara'
    OTP_VALIDITY_SECONDS = int(os.getenv('OTP_VALIDITY_SECONDS', 600))

    RATELIMIT_ENABLED = os.getenv('RATELIMIT_ENABLED', 'true').lower() == 'true'
    RATELIMIT_DEFAULT = os.getenv('RATELIMIT_DEFAULT', '1000 per hour; 200 per minute')
    RATELIMIT_STORAGE_URI = os.getenv('RATELIMIT_STORAGE_URI', 'memory://')
    BLOCK_VPN = os.getenv('BLOCK_VPN', 'true').lower() == 'true'

class DevConfig(Config):
    DEBUG = True
    TESTING = False
    RATELIMIT_ENABLED = os.getenv('RATELIMIT_ENABLED', 'false').lower() == 'true'
    RATELIMIT_DEFAULT = '5000 per hour; 1000 per minute'

class ProdConfig(Config):
    DEBUG = False
    TESTING = False
    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    RATELIMIT_ENABLED = True

class TestConfig(Config):
    DEBUG = False
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False

config_map = {
    'development': DevConfig,
    'production': ProdConfig,
    'testing': TestConfig,
    'default': DevConfig,
}
