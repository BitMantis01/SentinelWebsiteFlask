import os
from datetime import timedelta
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Config:
    # ===========================================
    # CRITICAL: Secret Key (REQUIRED)
    # ===========================================
    SECRET_KEY = os.environ.get('SECRET_KEY')
    if not SECRET_KEY:
        if os.environ.get('FLASK_ENV') == 'production':
            raise ValueError("ERROR: SECRET_KEY environment variable MUST be set in production!")
        else:
            print("⚠️  WARNING: SECRET_KEY not set! Using insecure default. Set SECRET_KEY in .env file!")
            SECRET_KEY = 'dev-insecure-key-change-immediately'
    
    # ===========================================
    # Database Configuration
    # ===========================================
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', 'sqlite:///site.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'pool_recycle': 300,
    }
    
    # ===========================================
    # Session Security Settings
    # ===========================================
    # Force HTTPS for cookies in production
    SESSION_COOKIE_SECURE = os.environ.get('FLASK_ENV') == 'production'
    
    # Prevent JavaScript access to session cookies (XSS protection)
    SESSION_COOKIE_HTTPONLY = True
    
    # CSRF protection via cookies
    SESSION_COOKIE_SAMESITE = 'Lax'
    
    # Session expires after configured hours (default 24)
    session_hours = int(os.environ.get('SESSION_LIFETIME_HOURS', 24))
    PERMANENT_SESSION_LIFETIME = timedelta(hours=session_hours)
    
    # Custom cookie name (security through obscurity)
    SESSION_COOKIE_NAME = 'sentinel_session'
    
    # Regenerate session on each request
    SESSION_REFRESH_EACH_REQUEST = True
    
    # ===========================================
    # CSRF Protection Settings
    # ===========================================
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = None  # Don't expire CSRF tokens
    WTF_CSRF_SSL_STRICT = os.environ.get('FLASK_ENV') == 'production'
    WTF_CSRF_METHODS = ['POST', 'PUT', 'PATCH', 'DELETE']
    
    # ===========================================
    # Rate Limiting Configuration
    # ===========================================
    # Use memory storage for development, Redis for production
    RATELIMIT_STORAGE_URL = os.environ.get('REDIS_URL', 'memory://')
    RATELIMIT_STRATEGY = 'fixed-window'
    RATELIMIT_HEADERS_ENABLED = True
    
    # ===========================================
    # Account Security Settings
    # ===========================================
    MAX_LOGIN_ATTEMPTS = int(os.environ.get('MAX_LOGIN_ATTEMPTS', 5))
    ACCOUNT_LOCKOUT_DURATION_MINUTES = int(os.environ.get('ACCOUNT_LOCKOUT_DURATION_MINUTES', 15))
    
    # ===========================================
    # API Rate Limits (requests per minute)
    # ===========================================
    API_RATE_LIMIT_VITALS = int(os.environ.get('API_RATE_LIMIT_VITALS', 60))
    API_RATE_LIMIT_ENVIRONMENT = int(os.environ.get('API_RATE_LIMIT_ENVIRONMENT', 60))
    API_RATE_LIMIT_CAMERA = int(os.environ.get('API_RATE_LIMIT_CAMERA', 30))
    LOGIN_RATE_LIMIT = int(os.environ.get('LOGIN_RATE_LIMIT', 5))
    
    # ===========================================
    # CORS & WebSocket Configuration
    # ===========================================
    SOCKETIO_CORS_ALLOWED_ORIGINS = os.environ.get(
        'SOCKETIO_CORS_ALLOWED_ORIGINS',
        'http://localhost:5000,http://localhost:1904'
    ).split(',')
    
    # ===========================================
    # Cloudflare Proxy Configuration
    # ===========================================
    BEHIND_CLOUDFLARE = os.environ.get('BEHIND_CLOUDFLARE', 'false').lower() == 'true'
    PROXY_COUNT = int(os.environ.get('PROXY_COUNT', 1))
    
    # ===========================================
    # Security Headers (Talisman)
    # ===========================================
    TALISMAN_FORCE_HTTPS = os.environ.get('FLASK_ENV') == 'production'
    TALISMAN_STRICT_TRANSPORT_SECURITY = True
    TALISMAN_STRICT_TRANSPORT_SECURITY_MAX_AGE = 31536000  # 1 year
    
    # Content Security Policy
    TALISMAN_CSP = {
        'default-src': "'self'",
        'script-src': [
            "'self'",
            "'unsafe-inline'",  # Required for inline scripts
            'cdn.jsdelivr.net',
            'cdn.socket.io',
            'cdnjs.cloudflare.com',
            'challenges.cloudflare.com'  # Cloudflare Turnstile
        ],
        'style-src': [
            "'self'",
            "'unsafe-inline'",  # Required for Tailwind CSS
            'cdn.jsdelivr.net'
        ],
        'img-src': ["'self'", 'data:', 'blob:'],
        'font-src': ["'self'", 'cdn.jsdelivr.net'],
        'connect-src': ["'self'", 'wss:', 'ws:', 'challenges.cloudflare.com'],  # Turnstile API
        'frame-src': ["'self'", 'challenges.cloudflare.com'],  # Turnstile iframe
        'frame-ancestors': "'none'",  # Prevent clickjacking
    }
    
    # ===========================================
    # Logging Configuration
    # ===========================================
    LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')
    LOG_FILE = os.environ.get('LOG_FILE', 'logs/sentinel_app.log')
    SECURITY_LOG_FILE = os.environ.get('SECURITY_LOG_FILE', 'logs/security_events.log')
    
    # Remote Logging Server (Centralized Logging at logs.bitmantis.xyz)
    # API Endpoint: POST https://logs.bitmantis.xyz/api/logs
    # Authentication: Bearer token in Authorization header
    # Dashboard: https://logs.bitmantis.xyz
    # Log Types: debug, info, security, error
    LOG_API_URL = os.environ.get('LOG_API_URL', 'https://logs.bitmantis.xyz/api/logs')
    LOG_API_KEY = os.environ.get('LOG_API_KEY')  # Required for remote logging
    
    # ===========================================
    # Cloudflare Turnstile (CAPTCHA)
    # ===========================================
    TURNSTILE_SITE_KEY = os.environ.get('TURNSTILE_SITE_KEY')
    TURNSTILE_SECRET_KEY = os.environ.get('TURNSTILE_SECRET_KEY')
    TURNSTILE_ENABLED = bool(TURNSTILE_SITE_KEY and TURNSTILE_SECRET_KEY)
