"""
Cloudflare Turnstile verification helper
"""
import requests
from flask import current_app


def verify_turnstile(token, remote_ip):
    """
    Verify Cloudflare Turnstile token
    
    Args:
        token (str): The Turnstile response token from the client
        remote_ip (str): The user's IP address
    
    Returns:
        tuple: (success: bool, error_message: str or None)
    """
    # Skip verification if Turnstile is not configured
    if not current_app.config.get('TURNSTILE_ENABLED'):
        current_app.logger.warning('Turnstile verification skipped - not configured')
        return True, None
    
    secret_key = current_app.config.get('TURNSTILE_SECRET_KEY')
    
    if not token:
        return False, 'Turnstile verification failed. Please complete the challenge.'
    
    try:
        # Verify with Cloudflare
        response = requests.post(
            'https://challenges.cloudflare.com/turnstile/v0/siteverify',
            data={
                'secret': secret_key,
                'response': token,
                'remoteip': remote_ip
            },
            timeout=10
        )
        
        result = response.json()
        
        if result.get('success'):
            return True, None
        else:
            error_codes = result.get('error-codes', [])
            current_app.logger.warning(f'Turnstile verification failed: {error_codes}')
            
            # Map error codes to user-friendly messages
            if 'timeout-or-duplicate' in error_codes:
                return False, 'Challenge expired. Please refresh and try again.'
            elif 'invalid-input-response' in error_codes:
                return False, 'Invalid challenge response. Please try again.'
            else:
                return False, 'Verification failed. Please try again.'
    
    except requests.exceptions.Timeout:
        current_app.logger.error('Turnstile verification timeout')
        return False, 'Verification service timeout. Please try again.'
    
    except Exception as e:
        current_app.logger.error(f'Turnstile verification error: {str(e)}')
        # In case of service failure, allow login (fail open)
        # Change to False for stricter security (fail closed)
        return True, None
