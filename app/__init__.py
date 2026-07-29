from flask import Flask, session, request
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_login import LoginManager
from flask_socketio import SocketIO
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_talisman import Talisman
import logging
from logging.handlers import RotatingFileHandler
import os
from datetime import timedelta
from app.remote_logger import setup_remote_logging

db = SQLAlchemy()
bcrypt = Bcrypt()
login_manager = LoginManager()
login_manager.login_view = 'main.login'
login_manager.login_message_category = 'info'
login_manager.session_protection = 'strong'  # Prevent session hijacking
socketio = SocketIO()
csrf = CSRFProtect()

# Custom function to get real IP when behind Cloudflare
def get_real_ip():
    """
    Get the real client IP address, handling Cloudflare proxy.
    Cloudflare adds CF-Connecting-IP header with the true client IP.
    """
    # Check if behind Cloudflare proxy
    cf_connecting_ip = request.headers.get('CF-Connecting-IP')
    if cf_connecting_ip:
        return cf_connecting_ip
    
    # Check X-Forwarded-For header (standard proxy header)
    x_forwarded_for = request.headers.get('X-Forwarded-For')
    if x_forwarded_for:
        # X-Forwarded-For can contain multiple IPs, get the first one (client IP)
        return x_forwarded_for.split(',')[0].strip()
    
    # Fall back to X-Real-IP
    x_real_ip = request.headers.get('X-Real-IP')
    if x_real_ip:
        return x_real_ip
    
    # Last resort: use remote_addr
    return request.remote_addr or '127.0.0.1'

# Initialize rate limiter with Cloudflare IP detection
# Note: No default limits - only specific routes (like login) have rate limiting
limiter = Limiter(
    key_func=get_real_ip,  # Use custom IP detection function
    default_limits=[],  # No default limits - IoT devices need unlimited API access
    storage_uri="memory://",  # Use Redis in production for distributed rate limiting
    headers_enabled=True
)

def create_app():
    app = Flask(__name__)
    app.config.from_object('config.Config')

    # Basic console logging so "python app.py" shows output
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s [%(name)s] %(message)s'
    )
    app.logger.setLevel(logging.INFO)
    
    # Configure file logging
    configure_logging(app)
    
    # Setup remote logging to logs.bitmantis.xyz
    setup_remote_logging(app)

    # Initialize extensions
    db.init_app(app)
    bcrypt.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)
    
    # Security headers (Talisman) - only enable in production or if forced
    if app.config.get('TALISMAN_FORCE_HTTPS', False):
        Talisman(
            app,
            force_https=app.config['TALISMAN_FORCE_HTTPS'],
            strict_transport_security=app.config['TALISMAN_STRICT_TRANSPORT_SECURITY'],
            strict_transport_security_max_age=app.config['TALISMAN_STRICT_TRANSPORT_SECURITY_MAX_AGE'],
            content_security_policy=app.config['TALISMAN_CSP'],
            frame_options='DENY',
            referrer_policy='strict-origin-when-cross-origin'
        )
    
    # Enable Socket.IO/Engine.IO logging to the root logger
    socketio.init_app(
        app,
        cors_allowed_origins=app.config['SOCKETIO_CORS_ALLOWED_ORIGINS'],
        logger=True,
        engineio_logger=True,
        ping_timeout=60,
        ping_interval=25
    )
    
    # Security request handlers
    @app.before_request
    def security_checks():
        """Add security headers and make sessions permanent"""
        session.permanent = True
        app.permanent_session_lifetime = app.config['PERMANENT_SESSION_LIFETIME']
    
    @app.after_request
    def add_security_headers(response):
        """Add additional security headers to every response"""
        # Prevent MIME sniffing
        response.headers['X-Content-Type-Options'] = 'nosniff'
        
        # Prevent clickjacking
        response.headers['X-Frame-Options'] = 'DENY'
        
        # Enable XSS filter
        response.headers['X-XSS-Protection'] = '1; mode=block'
        
        # Referrer policy
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        
        # Feature/Permissions policy
        response.headers['Permissions-Policy'] = (
            'camera=(), microphone=(), geolocation=(), '
            'payment=(), usb=()'
        )
        
        return response
    
    @app.errorhandler(429)
    def ratelimit_handler(e):
        """Custom rate limit exceeded handler"""
        app.logger.warning(
            f'Rate limit exceeded for {get_real_ip()} - {request.path}'
        )
        return {
            'error': 'Rate limit exceeded',
            'message': 'Too many requests. Please try again later.'
        }, 429

    from app.routes import main
    app.register_blueprint(main)

    with app.app_context():
        db.create_all()
        app.logger.info('✅ SENTINEL Application initialized successfully')
        app.logger.info(f'🔒 Security features enabled: CSRF, Rate Limiting, Secure Sessions')
        app.logger.info(f'🌐 Behind Cloudflare: {app.config.get("BEHIND_CLOUDFLARE", False)}')

    return app

def configure_logging(app):
    """Configure application logging with security event tracking"""
    if not app.debug:
        # Create logs directory if it doesn't exist
        log_dir = os.path.dirname(app.config.get('LOG_FILE', 'logs/sentinel_app.log'))
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir)
        
        # Application log handler
        log_file = app.config.get('LOG_FILE', 'logs/sentinel_app.log')
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=10
        )
        file_handler.setLevel(logging.INFO)
        file_formatter = logging.Formatter(
            '%(asctime)s %(levelname)s [%(name)s] [%(filename)s:%(lineno)d] %(message)s'
        )
        file_handler.setFormatter(file_formatter)
        app.logger.addHandler(file_handler)
        
        # Security events logger (separate file)
        security_log_file = app.config.get('SECURITY_LOG_FILE', 'logs/security_events.log')
        security_handler = RotatingFileHandler(
            security_log_file,
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=20  # Keep more security logs
        )
        security_handler.setLevel(logging.WARNING)
        security_formatter = logging.Formatter(
            '%(asctime)s SECURITY [%(levelname)s] %(message)s'
        )
        security_handler.setFormatter(security_formatter)
        
        security_logger = logging.getLogger('security')
        security_logger.addHandler(security_handler)
        security_logger.setLevel(logging.WARNING)

def log_security_event(event_type, details, severity='WARNING'):
    """
    Log security-related events for monitoring and auditing
    Logs to both local file and remote centralized logging server
    
    Security events are automatically sent with Type="security" to the remote API
    
    Args:
        event_type (str): Type of security event (e.g., 'login_failed', 'account_locked')
        details (dict): Event details (IP, user, reason, etc.)
        severity (str): Log severity level ('INFO', 'WARNING', 'ERROR', 'CRITICAL')
    
    Example:
        log_security_event('login_failed', {
            'username': 'john',
            'ip': '192.168.1.1',
            'reason': 'invalid_password',
            'attempts': 3
        })
    """
    security_logger = logging.getLogger('security')
    log_method = getattr(security_logger, severity.lower())
    
    log_message = f"{event_type} | {' | '.join(f'{k}={v}' for k, v in details.items())}"
    log_method(log_message)
    
    # Also send to remote logging (if configured)
    # This will be automatically sent as Type="security" by RemoteLogHandler
    from flask import current_app
    if hasattr(current_app, 'logger'):
        # Map to appropriate log level for remote logging
        if severity.upper() == 'CRITICAL' or severity.upper() == 'ERROR':
            current_app.logger.error(f"SECURITY: {log_message}")
        else:
            current_app.logger.warning(f"SECURITY: {log_message}")
