"""
Remote Logging Handler for SENTINEL
Sends logs to centralized logging server at logs.bitmantis.xyz

API Endpoint: https://logs.bitmantis.xyz/api/logs
Authentication: Bearer token in Authorization header
Log Types: debug, info, security, error
"""
import requests
import logging
from datetime import datetime, timezone
import json
import os
from threading import Thread


class RemoteLogHandler(logging.Handler):
    """
    Custom logging handler that sends logs to remote centralized logging API
    
    Supports four log types:
    - debug: Development and troubleshooting information
    - info: General operational messages
    - security: Authentication and access control events
    - error: Failures and exceptions
    """
    
    def __init__(self, api_url, api_key, app_name="SentinelWebsite"):
        super().__init__()
        self.api_url = api_url
        self.api_key = api_key
        self.app_name = app_name
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        })
    
    def emit(self, record):
        """
        Send log record to remote server
        Runs in separate thread to avoid blocking application
        """
        try:
            # Run in background thread to not block application
            thread = Thread(target=self._send_log, args=(record,))
            thread.daemon = True
            thread.start()
        except Exception:
            # Silently fail - don't break app if logging fails
            pass
    
    def _send_log(self, record):
        """
        Internal method to send log to remote server via API
        """
        try:
            # Map Python log levels to API log types
            log_type = self._get_log_type(record)
            
            # Format timestamp in ISO8601 format (e.g., "2025-10-26T14:30:00Z")
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            
            # Prepare log payload according to API requirements
            payload = {
                "Name": self.app_name,
                "Timestamp": timestamp,
                "Type": log_type,
                "LogMessage": self.format(record)
            }
            
            # Send to remote server with timeout
            response = self.session.post(
                self.api_url,
                json=payload,
                timeout=5  # 5 second timeout
            )
            
            # Check response status
            if response.status_code == 201:
                # Success - log received
                pass
            elif response.status_code in (200, 204):
                # Also acceptable success codes
                pass
            elif response.status_code == 401:
                print(f"Remote logging authentication failed: Missing or invalid token")
            elif response.status_code == 403:
                print(f"Remote logging forbidden: Invalid API key")
            elif response.status_code == 400:
                print(f"Remote logging bad request: Invalid data - {response.text}")
            else:
                print(f"Remote logging failed with status {response.status_code}")
                
        except requests.exceptions.Timeout:
            # Timeout - don't block the app
            pass
        except requests.exceptions.ConnectionError:
            # Connection failed - silently fail
            pass
        except Exception as e:
            # Catch all exceptions to prevent breaking the app
            print(f"Remote logging error: {str(e)}")
    
    def _get_log_type(self, record):
        """
        Map Python logging levels to API log types (debug, info, security, error)
        
        Mapping:
        - DEBUG (10) -> debug
        - INFO (20) -> info
        - WARNING (30) -> security or info (depends on logger name)
        - ERROR (40) -> error
        - CRITICAL (50) -> error
        """
        # Check if this is a security event (from security logger or SECURITY tag)
        if (record.name == 'security' or 
            'SECURITY' in record.getMessage().upper() or
            hasattr(record, 'security_event')):
            return "security"
        
        # Map by level
        if record.levelno >= logging.ERROR:  # ERROR (40) or CRITICAL (50)
            return "error"
        elif record.levelno >= logging.WARNING:  # WARNING (30)
            return "info"  # General warnings go to info
        elif record.levelno >= logging.INFO:  # INFO (20)
            return "info"
        else:  # DEBUG (10)
            return "debug"


def setup_remote_logging(app):
    """
    Setup remote logging handler for Flask app to send logs to logs.bitmantis.xyz
    
    Requires environment variables:
    - LOG_API_URL: API endpoint (default: https://logs.bitmantis.xyz/api/logs)
    - LOG_API_KEY: Bearer token for authentication
    
    Args:
        app: Flask application instance
    
    Returns:
        RemoteLogHandler instance or None if not configured
    """
    # Get configuration from environment or app config
    api_url = os.environ.get('LOG_API_URL') or app.config.get('LOG_API_URL')
    api_key = os.environ.get('LOG_API_KEY') or app.config.get('LOG_API_KEY')
    
    # Set default API URL if not provided
    if not api_url:
        api_url = 'https://logs.bitmantis.xyz/api/logs'
    
    # Only enable if API key is configured
    if not api_key or api_key == 'your_api_key_here':
        app.logger.warning("Remote logging not configured - set LOG_API_KEY in .env")
        app.logger.info("Logs will only be stored locally in logs/ directory")
        return None
    
    try:
        # Create remote handler
        remote_handler = RemoteLogHandler(
            api_url=api_url,
            api_key=api_key,
            app_name="SentinelWebsite"
        )
        
        # Set formatter (customize the log message format)
        formatter = logging.Formatter(
            '[%(name)s] %(levelname)s: %(message)s'
        )
        remote_handler.setFormatter(formatter)
        
        # Set level (send INFO and above to remote server)
        remote_handler.setLevel(logging.INFO)
        
        # Add to app logger
        app.logger.addHandler(remote_handler)
        
        # Also add to security logger if it exists
        security_logger = logging.getLogger('security')
        if security_logger:
            security_logger.addHandler(remote_handler)
        
        app.logger.info(f"✅ Remote logging enabled - sending logs to {api_url}")
        app.logger.info("📊 Dashboard available at: https://logs.bitmantis.xyz")
        return remote_handler
        
    except Exception as e:
        app.logger.error(f"❌ Failed to setup remote logging: {str(e)}")
        return None


def log_security_event_remote(app, event_type, details):
    """
    Helper function to log security events to remote logging system
    
    Security events are sent with Type="security" to the API
    
    Args:
        app: Flask application instance
        event_type: Type of security event (e.g., 'login_failed', 'account_locked')
        details: Dictionary with event details (IP, user, reason, etc.)
    
    Example:
        log_security_event_remote(app, 'login_failed', {
            'username': 'john',
            'ip': '192.168.1.1',
            'reason': 'invalid_password'
        })
    """
    message = f"SECURITY EVENT: {event_type} | {json.dumps(details)}"
    
    # Create a security-specific log record
    security_logger = logging.getLogger('security')
    security_logger.warning(message)
    
    # Also log to main app logger with SECURITY prefix
    app.logger.warning(message)


def log_error_remote(app, error_message, exception=None):
    """
    Helper function to log errors to remote logging system
    
    Error logs are sent with Type="error" to the API
    
    Args:
        app: Flask application instance
        error_message: Error description
        exception: Optional exception object for stack trace
    
    Example:
        try:
            risky_operation()
        except Exception as e:
            log_error_remote(app, "Operation failed", e)
    """
    if exception:
        message = f"ERROR: {error_message} | Exception: {str(exception)}"
        # Include exception info for better debugging
        app.logger.error(message, exc_info=True)
    else:
        message = f"ERROR: {error_message}"
        app.logger.error(message)


def log_info_remote(app, info_message):
    """
    Helper function to log general operational info to remote logging system
    
    Info logs are sent with Type="info" to the API
    
    Args:
        app: Flask application instance
        info_message: General operational information
    
    Example:
        log_info_remote(app, "User settings updated successfully")
    """
    app.logger.info(f"INFO: {info_message}")


def log_debug_remote(app, debug_message):
    """
    Helper function to log debug information to remote logging system
    
    Debug logs are sent with Type="debug" to the API
    
    Args:
        app: Flask application instance
        debug_message: Debug/troubleshooting information
    
    Example:
        log_debug_remote(app, f"Processing data batch: {batch_id}")
    """
    app.logger.debug(f"DEBUG: {debug_message}")

