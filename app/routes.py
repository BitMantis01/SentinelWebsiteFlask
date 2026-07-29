from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for, send_file, current_app, make_response, send_from_directory
from flask_login import login_user, current_user, logout_user, login_required
from flask_socketio import emit, join_room, leave_room
from app import db, bcrypt, socketio, limiter, csrf, log_security_event, get_real_ip
from app.models import User, CameraBox, EnvHubBox, FootwearMonitor, CameraImage, EnvHubData, FootwearData, NEWSScore, NEWSSettings, PredictionSession, AccuracyMetric, PredictionData, NotificationSettings, NotificationHistory
from app.notification import notification_handler
from app.turnstile import verify_turnstile
from datetime import datetime, timezone, timedelta
import re
from functools import wraps
from flask import g
import io
import base64
import traceback
import os

main = Blueprint('main', __name__)

# Vitals validation functions
def validate_heart_rate(bpm):
    """Validate heart rate: 60-200 bpm"""
    return bpm >= 60 and bpm <= 200 if bpm and bpm > 0 else False

def validate_spo2(spo2):
    """Validate SpO2: 80-100%"""
    return spo2 >= 80 and spo2 <= 100 if spo2 and spo2 > 0 else False

def validate_temperature(temp):
    """Validate body temperature: 32-41°C"""
    return temp >= 32 and temp <= 41 if temp and temp > 0 else False

def get_vitals_validation(bpm, spo2, temp):
    """Get validation status for all vitals"""
    return {
        'heart_rate_valid': validate_heart_rate(bpm),
        'spo2_valid': validate_spo2(spo2),
        'temperature_valid': validate_temperature(temp),
        'all_valid': validate_heart_rate(bpm) and validate_spo2(spo2) and validate_temperature(temp)
    }

# NEWS (Newborn Early Warning Score) functions
def calculate_temperature_score(temp):
    """Calculate NEWS temperature score"""
    if temp <= 35.9:
        return 2
    elif 36.0 <= temp <= 36.4:
        return 1
    elif 36.5 <= temp <= 37.5:
        return 0  # Normal
    elif 37.6 <= temp <= 38.0:
        return 1
    elif temp >= 38.1:
        return 2
    return 0

def calculate_heart_rate_score(hr):
    """Calculate NEWS heart rate score"""
    if hr < 60 or hr >= 190:
        return 3
    elif 60 <= hr <= 69:
        return 3
    elif 70 <= hr <= 79:
        return 2
    elif 80 <= hr <= 99:
        return 1
    elif 100 <= hr <= 159:
        return 0  # Normal
    elif 160 <= hr <= 179:
        return 1
    elif 180 <= hr <= 189:
        return 2
    return 0

def calculate_spo2_score(spo2):
    """Calculate NEWS SpO2 score"""
    if spo2 <= 89:
        return 2
    elif 90 <= spo2 <= 94:
        return 1
    elif spo2 >= 95:
        return 0  # Normal
    return 0

def calculate_news_score(temp, hr, spo2):
    """Calculate complete NEWS score and alert level"""
    temp_score = calculate_temperature_score(temp)
    hr_score = calculate_heart_rate_score(hr)
    spo2_score = calculate_spo2_score(spo2)
    total_score = temp_score + hr_score + spo2_score
    
    # Determine alert level and message
    if total_score == 0:
        alert_level = 'Green'
        alert_message = 'Normal monitoring - Continue routine care'
    elif total_score == 1:
        alert_level = 'Yellow'
        alert_message = 'Notify pediatrician within 1 hour'
    elif total_score == 2:
        alert_level = 'Orange'
        alert_message = 'Notify pediatrician within 30 minutes'
    else:  # total_score >= 3
        alert_level = 'Red'
        alert_message = 'IMMEDIATE pediatrician review required'
    
    return {
        'temperature_score': temp_score,
        'heart_rate_score': hr_score,
        'spo2_score': spo2_score,
        'total_score': total_score,
        'alert_level': alert_level,
        'alert_message': alert_message
    }

def get_news_status(user_id):
    """Get NEWS system enable/disable status for user"""
    settings = NEWSSettings.query.filter_by(user_id=user_id).first()
    if not settings:
        # Create default settings
        settings = NEWSSettings(user_id=user_id, news_enabled=True)
        db.session.add(settings)
        db.session.commit()
    return settings.news_enabled
from datetime import datetime, timezone, timedelta
import re
from functools import wraps
from flask import g
import io
import base64

main = Blueprint('main', __name__)

# Vitals validation functions
def validate_heart_rate(bpm):
    """Validate heart rate: 60-200 bpm"""
    return bpm >= 60 and bpm <= 200 if bpm and bpm > 0 else False

def validate_spo2(spo2):
    """Validate SpO2: 80-100%"""
    return spo2 >= 80 and spo2 <= 100 if spo2 and spo2 > 0 else False

def validate_temperature(temp):
    """Validate body temperature: 32-41°C"""
    return temp >= 32 and temp <= 41 if temp and temp > 0 else False

def get_vitals_validation(bpm, spo2, temp):
    """Get validation status for all vitals"""
    return {
        'heart_rate_valid': validate_heart_rate(bpm),
        'spo2_valid': validate_spo2(spo2),
        'temperature_valid': validate_temperature(temp),
        'all_valid': validate_heart_rate(bpm) and validate_spo2(spo2) and validate_temperature(temp)
    }

def is_strong_password(password):
    if len(password) < 8:
        return False
    if not re.search(r"[a-z]", password):
        return False
    if not re.search(r"[A-Z]", password):
        return False
    if not re.search(r"[0-9]", password):
        return False
    if not re.search(r"[!@#$%^&*()-_=+{};:,<.>]", password):
        return False
    return True

def api_key_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('x-api-key')
        if not api_key:
            log_security_event('api_key_missing', {
                'endpoint': request.endpoint,
                'path': request.path,
                'ip': get_real_ip(),
                'timestamp': datetime.now(timezone.utc).isoformat()
            }, severity='WARNING')
            return jsonify({"error": "API key is missing"}), 401
        
        user = User.query.filter_by(api_key=api_key).first()
        if not user:
            log_security_event('api_key_invalid', {
                'endpoint': request.endpoint,
                'path': request.path,
                'ip': get_real_ip(),
                'api_key_prefix': api_key[:8] + '...' if len(api_key) > 8 else 'short',
                'timestamp': datetime.now(timezone.utc).isoformat()
            }, severity='WARNING')
            return jsonify({"error": "Invalid API key"}), 401
        
        g.user = user  # Store user for the request context
        return f(*args, **kwargs)
    return decorated_function

@main.route('/')
def landing():
    return render_template('landing.html')

@main.route('/robots.txt')
def robots_txt():
    """Serve robots.txt for SEO - tells search engines what to index"""
    try:
        robots_path = os.path.join(current_app.root_path, '..', 'robots.txt')
        with open(robots_path, 'r') as f:
            content = f.read()
            # Replace template variables
            content = content.replace('{{ request.url_root }}', request.url_root)
        response = make_response(content)
        response.headers['Content-Type'] = 'text/plain'
        return response
    except FileNotFoundError:
        # Fallback robots.txt if file doesn't exist
        content = """User-agent: *
Allow: /
Disallow: /dashboard
Disallow: /api/
Disallow: /login
Disallow: /register
"""
        response = make_response(content)
        response.headers['Content-Type'] = 'text/plain'
        return response

@main.route('/sitemap.xml')
def sitemap_xml():
    """Serve sitemap.xml for SEO - helps search engines discover pages"""
    try:
        sitemap_path = os.path.join(current_app.root_path, '..', 'sitemap.xml')
        with open(sitemap_path, 'r') as f:
            content = f.read()
            # Replace template variables
            content = content.replace('{{ request.url_root }}', request.url_root)
            content = content.replace('2025-11-03', datetime.now(timezone.utc).strftime('%Y-%m-%d'))
        response = make_response(content)
        response.headers['Content-Type'] = 'application/xml'
        return response
    except FileNotFoundError:
        # Generate basic sitemap if file doesn't exist
        sitemap = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <url>
        <loc>{request.url_root}</loc>
        <lastmod>{datetime.now(timezone.utc).strftime('%Y-%m-%d')}</lastmod>
        <changefreq>weekly</changefreq>
        <priority>1.0</priority>
    </url>
</urlset>"""
        response = make_response(sitemap)
        response.headers['Content-Type'] = 'application/xml'
        return response

@main.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute")  # Rate limit login attempts
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    
    if request.method == 'POST':
        # Verify Turnstile challenge
        turnstile_token = request.form.get('cf-turnstile-response')
        success, error_message = verify_turnstile(turnstile_token, get_real_ip())
        
        if not success:
            flash(error_message or 'Please complete the security challenge.', 'danger')
            log_security_event('login_turnstile_failed', {
                'ip': get_real_ip(),
                'timestamp': datetime.now(timezone.utc).isoformat()
            }, severity='WARNING')
            return render_template('login.html', 
                                 turnstile_site_key=current_app.config.get('TURNSTILE_SITE_KEY'))
        
        email = request.form.get('email')
        password = request.form.get('password')
        user = User.query.filter_by(email=email).first()
        
        # Check if account is locked
        if user and user.locked_until:
            if user.locked_until > datetime.now(timezone.utc):
                remaining = (user.locked_until - datetime.now(timezone.utc)).seconds // 60
                flash(f'Account locked due to too many failed attempts. Try again in {remaining} minutes.', 'danger')
                
                log_security_event('login_attempt_locked', {
                    'email': email,
                    'ip': get_real_ip(),
                    'remaining_minutes': remaining,
                    'timestamp': datetime.now(timezone.utc).isoformat()
                })
                return render_template('login.html')
            else:
                # Lock expired, reset
                user.locked_until = None
                user.failed_login_attempts = 0
                db.session.commit()
        
        # Verify credentials
        if user and bcrypt.check_password_hash(user.password, password):
            # Successful login - reset attempts
            user.failed_login_attempts = 0
            user.locked_until = None
            user.last_login_at = datetime.now(timezone.utc)
            user.last_login_ip = get_real_ip()
            db.session.commit()
            
            log_security_event('login_success', {
                'user_id': user.id,
                'email': email,
                'ip': get_real_ip(),
                'timestamp': datetime.now(timezone.utc).isoformat()
            }, severity='INFO')
            
            login_user(user, remember=True)
            return redirect(url_for('main.dashboard'))
        else:
            # Failed login - increment attempts
            if user:
                user.failed_login_attempts += 1
                max_attempts = current_app.config.get('MAX_LOGIN_ATTEMPTS', 5)
                
                # Lock account after max failed attempts
                if user.failed_login_attempts >= max_attempts:
                    lockout_minutes = current_app.config.get('ACCOUNT_LOCKOUT_DURATION_MINUTES', 15)
                    user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=lockout_minutes)
                    db.session.commit()
                    
                    log_security_event('account_locked', {
                        'user_id': user.id,
                        'email': email,
                        'ip': get_real_ip(),
                        'failed_attempts': user.failed_login_attempts,
                        'lockout_minutes': lockout_minutes,
                        'timestamp': datetime.now(timezone.utc).isoformat()
                    }, severity='WARNING')
                    
                    flash(f'Account locked due to too many failed attempts. Try again in {lockout_minutes} minutes.', 'danger')
                else:
                    db.session.commit()
                    remaining = max_attempts - user.failed_login_attempts
                    flash(f'Login Unsuccessful. {remaining} attempts remaining before account lockout.', 'danger')
                    
                    log_security_event('login_failed', {
                        'email': email,
                        'ip': get_real_ip(),
                        'attempts': user.failed_login_attempts,
                        'remaining_attempts': remaining,
                        'timestamp': datetime.now(timezone.utc).isoformat()
                    })
            else:
                # User doesn't exist - still show generic message (prevent email enumeration)
                flash('Login Unsuccessful. Please check email and password', 'danger')
                
                log_security_event('login_failed_unknown_user', {
                    'email': email,
                    'ip': get_real_ip(),
                    'timestamp': datetime.now(timezone.utc).isoformat()
                })
    
    return render_template('login.html', 
                         turnstile_site_key=current_app.config.get('TURNSTILE_SITE_KEY'))

@main.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    if request.method == 'POST':
        # Verify Turnstile challenge
        turnstile_token = request.form.get('cf-turnstile-response')
        success, error_message = verify_turnstile(turnstile_token, get_real_ip())
        
        if not success:
            flash(error_message or 'Please complete the security challenge.', 'danger')
            log_security_event('register_turnstile_failed', {
                'ip': get_real_ip(),
                'timestamp': datetime.now(timezone.utc).isoformat()
            }, severity='WARNING')
            return render_template('register.html',
                                 turnstile_site_key=current_app.config.get('TURNSTILE_SITE_KEY'))
        
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        use_case = request.form.get('use_case')
        name = request.form.get('name')
        contact_number = request.form.get('contact_number')
        
        if password != confirm_password:
            flash('Passwords do not match!', 'danger')
            return redirect(url_for('main.register'))

        if not is_strong_password(password):
            flash('Password must be at least 8 characters long and contain at least one uppercase letter, one lowercase letter, one number, and one special character.', 'danger')
            return redirect(url_for('main.register'))

        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
        
        if use_case == 'Home':
            birthday = request.form.get('birthday')
            user = User(email=email, password=hashed_password, use_case=use_case, name=name, contact_number=contact_number, birthday=datetime.strptime(birthday, '%Y-%m-%d').date())
        else: # Hospital
            hospital_name = request.form.get('hospital_name')
            user = User(email=email, password=hashed_password, use_case=use_case, name=name, contact_number=contact_number, hospital_name=hospital_name)
        
        db.session.add(user)
        db.session.commit()
        
        # Log successful registration
        log_security_event('user_registered', {
            'email': email,
            'use_case': use_case,
            'ip': get_real_ip(),
            'timestamp': datetime.now(timezone.utc).isoformat()
        }, severity='INFO')
        
        flash('Your account has been created! You are now able to log in', 'success')
        return redirect(url_for('main.login'))
    return render_template('register.html',
                         turnstile_site_key=current_app.config.get('TURNSTILE_SITE_KEY'))

@main.route('/logout')
def logout():
    if current_user.is_authenticated:
        log_security_event('user_logout', {
            'user_id': current_user.id,
            'email': current_user.email,
            'ip': get_real_ip(),
            'timestamp': datetime.now(timezone.utc).isoformat()
        }, severity='INFO')
    logout_user()
    return redirect(url_for('main.landing'))

@main.route('/dashboard')
@login_required
def dashboard():
    return redirect(url_for('main.summary'))

@main.route('/dashboard/summary')
@login_required
def summary():
    return render_template('dashboard/summary.html')

@main.route('/dashboard/vitals')
@login_required
def vitals():
    return render_template('dashboard/vitals.html')

@main.route('/dashboard/environment')
@login_required
def environment():
    return render_template('dashboard/environment.html')

@main.route('/dashboard/predictions')
@login_required
def predictions():
    return render_template('dashboard/predictions.html')

@main.route('/dashboard/live-feed')
@login_required
def live_feed():
    return render_template('dashboard/live_feed.html')

@main.route('/dashboard/media-player')
@login_required
def media_player():
    return render_template('dashboard/media_player.html')

@main.route('/dashboard/news')
@login_required
def news():
    return render_template('dashboard/news.html')

@main.route('/dashboard/sleep-tracking')
@login_required
def sleep_tracking():
    return render_template('dashboard/sleep_tracking.html')

@main.route('/dashboard/cry-detection')
@login_required
def cry_detection():
    return render_template('dashboard/cry_detection.html')

@main.route('/dashboard/notifications')
@login_required
def notifications():
    return render_template('dashboard/notifications.html')

@main.route('/dashboard/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'update_profile':
            current_user.name = request.form.get('name')
            current_user.contact_number = request.form.get('contact_number')
            if current_user.use_case == 'Home':
                birthday = request.form.get('birthday')
                if birthday:
                    current_user.birthday = datetime.strptime(birthday, '%Y-%m-%d').date()
            else:
                current_user.hospital_name = request.form.get('hospital_name')
            
            db.session.commit()
            flash('Profile updated successfully!', 'success')
            
        elif action == 'change_password':
            current_password = request.form.get('current_password')
            new_password = request.form.get('new_password')
            confirm_password = request.form.get('confirm_password')
            
            if not bcrypt.check_password_hash(current_user.password, current_password):
                flash('Current password is incorrect.', 'danger')
                log_security_event('password_change_failed', {
                    'user_id': current_user.id,
                    'email': current_user.email,
                    'ip': get_real_ip(),
                    'reason': 'incorrect_current_password',
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }, severity='WARNING')
            elif new_password != confirm_password:
                flash('New passwords do not match.', 'danger')
            elif not is_strong_password(new_password):
                flash('Password must be at least 8 characters long and contain at least one uppercase letter, one lowercase letter, one number, and one special character.', 'danger')
            else:
                current_user.password = bcrypt.generate_password_hash(new_password).decode('utf-8')
                db.session.commit()
                flash('Password changed successfully!', 'success')
                log_security_event('password_changed', {
                    'user_id': current_user.id,
                    'email': current_user.email,
                    'ip': get_real_ip(),
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }, severity='INFO')
                
        elif action == 'delete_account':
            password = request.form.get('delete_password')
            if bcrypt.check_password_hash(current_user.password, password):
                user_email = current_user.email
                user_id = current_user.id
                
                log_security_event('account_deleted', {
                    'user_id': user_id,
                    'email': user_email,
                    'ip': get_real_ip(),
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }, severity='WARNING')
                
                db.session.delete(current_user)
                db.session.commit()
                logout_user()
                flash('Account deleted successfully.', 'success')
                return redirect(url_for('main.landing'))
            else:
                flash('Password is incorrect.', 'danger')
                log_security_event('account_deletion_failed', {
                    'user_id': current_user.id,
                    'email': current_user.email,
                    'ip': get_real_ip(),
                    'reason': 'incorrect_password',
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }, severity='WARNING')
    
    return render_template('dashboard/profile.html')

@main.route('/dashboard/link_device/<device_type>', methods=['POST'])
@login_required
def link_device(device_type):
    device_id = request.form.get('device_id')
    name = request.form.get('name')

    if not device_id or not name or not re.match(r'^[a-zA-Z0-9]{6}$', device_id):
        flash('Invalid device ID or name.', 'danger')
        return redirect(url_for('main.profile'))

    if device_type == 'camera':
        if CameraBox.query.filter_by(device_id=device_id).first():
            flash('Device ID already registered.', 'danger')
            return redirect(url_for('main.profile'))
        new_device = CameraBox(device_id=device_id, name=name, user_id=current_user.id)
    elif device_type == 'envhub':
        if EnvHubBox.query.filter_by(device_id=device_id).first():
            flash('Device ID already registered.', 'danger')
            return redirect(url_for('main.profile'))
        new_device = EnvHubBox(device_id=device_id, name=name, user_id=current_user.id)
    elif device_type == 'footwear':
        baby_name = request.form.get('baby_name')
        if not baby_name:
            flash('Baby name is required for footwear monitors.', 'danger')
            return redirect(url_for('main.profile'))
        if FootwearMonitor.query.filter_by(device_id=device_id).first():
            flash('Device ID already registered.', 'danger')
            return redirect(url_for('main.profile'))
        new_device = FootwearMonitor(device_id=device_id, name=name, baby_name=baby_name, user_id=current_user.id)
    else:
        flash('Invalid device type.', 'danger')
        return redirect(url_for('main.profile'))

    db.session.add(new_device)
    db.session.commit()
    
    log_security_event('device_linked', {
        'user_id': current_user.id,
        'email': current_user.email,
        'device_type': device_type,
        'device_id': device_id,
        'device_name': name,
        'ip': get_real_ip(),
        'timestamp': datetime.now(timezone.utc).isoformat()
    }, severity='INFO')
    
    flash(f'{device_type.capitalize()} device linked successfully!', 'success')
    return redirect(url_for('main.profile'))

@main.route('/dashboard/unlink_device/<device_type>/<int:device_id>', methods=['GET', 'POST'])
@login_required
def unlink_device(device_type, device_id):
    if device_type == 'camera':
        device = CameraBox.query.get_or_404(device_id)
    elif device_type == 'envhub':
        device = EnvHubBox.query.get_or_404(device_id)
    elif device_type == 'footwear':
        device = FootwearMonitor.query.get_or_404(device_id)
    else:
        flash('Invalid device type.', 'danger')
        return redirect(url_for('main.profile'))

    if device.owner != current_user:
        flash('You do not have permission to unlink this device.', 'danger')
        log_security_event('unauthorized_device_unlink_attempt', {
            'user_id': current_user.id,
            'email': current_user.email,
            'device_type': device_type,
            'device_id': device_id,
            'device_owner_id': device.owner.id,
            'ip': get_real_ip(),
            'timestamp': datetime.now(timezone.utc).isoformat()
        }, severity='WARNING')
        return redirect(url_for('main.profile'))

    log_security_event('device_unlinked', {
        'user_id': current_user.id,
        'email': current_user.email,
        'device_type': device_type,
        'device_id': device_id,
        'ip': get_real_ip(),
        'timestamp': datetime.now(timezone.utc).isoformat()
    }, severity='INFO')

    db.session.delete(device)
    db.session.commit()
    flash(f'{device_type.capitalize()} device unlinked.', 'success')
    return redirect(url_for('main.profile'))

# API Routes
@main.route('/api/camera-box', methods=['POST'])
@csrf.exempt  # API uses api_key authentication
@api_key_required
def receive_camera_data():
    device_id = request.headers.get('id')
    user = g.user
    
    camera_box = CameraBox.query.filter_by(device_id=device_id, user_id=user.id).first()
    if not camera_box:
        return jsonify({"error": "Device not registered to this user"}), 403

    image_data = request.get_data()
    new_image = CameraImage(image_data=image_data, camera_box_id=camera_box.id)
    db.session.add(new_image)
    
    # Prune old images, keep last 100
    images_to_prune = CameraImage.query.filter_by(camera_box_id=camera_box.id).order_by(CameraImage.timestamp.desc()).offset(100).all()
    for img in images_to_prune:
        db.session.delete(img)
        
    db.session.commit()
    return jsonify({"message": "Image received"}), 200

@main.route('/api/envhub-box', methods=['POST'])
@csrf.exempt  # API uses api_key authentication
@api_key_required
def receive_envhub_data():
    user = g.user
    data = request.json
    device_id = data.get('id')
    
    envhub_box = EnvHubBox.query.filter_by(device_id=device_id, user_id=user.id).first()
    if not envhub_box:
        return jsonify({"error": "Device not registered to this user"}), 403

    df_player_status = data.get('df_player_status', {})
    new_data = EnvHubData(
        temp=data.get('temp'),
        humidity=data.get('humidity'),
        aqi=data.get('aqi'),
        mic=data.get('mic'),
        is_playing=df_player_status.get('isPlaying'),
        current_volume=df_player_status.get('currentVolume'),
        current_track=df_player_status.get('currentTrack'),
        envhub_box_id=envhub_box.id
    )
    db.session.add(new_data)
    
    # Prune old data (older than 2 months)
    two_months_ago = datetime.now(timezone.utc) - timedelta(days=60)
    EnvHubData.query.filter(EnvHubData.timestamp < two_months_ago).delete()
    
    db.session.commit()
    
    # **NEW: Check for environmental alerts and trigger notifications**
    try:
        notification_handler.check_environmental_alerts(
            new_data, user.id, device_id, envhub_box.name
        )
    except Exception as env_error:
        current_app.logger.warning(f"Environmental notification check failed: {str(env_error)}")
    
    return jsonify({"message": "EnvHub data received"}), 200

@main.route('/api/footwear-monitor', methods=['POST'])
@csrf.exempt  # API uses api_key authentication
@api_key_required
def receive_footwear_data():
    user = g.user
    data = request.json
    device_id = data.get('id')

    footwear_monitor = FootwearMonitor.query.filter_by(device_id=device_id, user_id=user.id).first()
    if not footwear_monitor:
        return jsonify({"error": "Device not registered to this user"}), 403

    # Handle -1 values from ESP32 (invalid readings) and convert to acceptable values
    spo2_value = data.get('spo2')
    if spo2_value == -1:
        spo2_value = 0  # or None if your database allows NULL for spo2
    
    heart_rate_value = data.get('heart_rate')  # Fixed field name
    if heart_rate_value == -1:
        heart_rate_value = 0  # Convert -1 to 0 since database doesn't allow NULL
    
    temperature_value = data.get('temperature')
    if temperature_value == -1:
        temperature_value = 0.0
    
    movement_value = data.get('movement', 0)  # Default to 0 if not provided

    new_data = FootwearData(
        spo2=spo2_value,
        heart_rate=heart_rate_value,
        temperature=temperature_value,
        movement=movement_value,
        footwear_monitor_id=footwear_monitor.id
    )
    db.session.add(new_data)
    
    # Prune old data (older than 2 months)
    two_months_ago = datetime.now(timezone.utc) - timedelta(days=60)
    FootwearData.query.filter(FootwearData.timestamp < two_months_ago).delete()
    
    db.session.commit()
    
    # Emit new data event for real-time updates
    emit_new_data(user.id, device_id, 'footwear')
    
    # **NEW: Trigger automatic prediction update**
    # Check if we have enough data points for predictions
    data_count = FootwearData.query.filter_by(
        footwear_monitor_id=footwear_monitor.id
    ).count()
    
    if data_count >= 15:  # Minimum for medical-grade predictions
        try:
            # Emit prediction trigger event to connected clients
            room = f'user_{user.id}'
            socketio.emit('auto_prediction_trigger', {
                'device_id': device_id,
                'data_count': data_count,
                'new_data': {
                    'spo2': spo2_value,
                    'heart_rate': heart_rate_value,
                    'temperature': temperature_value,
                    'timestamp': new_data.timestamp.isoformat()
                }
            }, room=room)
            
        except Exception as pred_error:
            current_app.logger.warning(f"Auto-prediction trigger failed: {str(pred_error)}")
    
    # **NEW: Check for NEWS alerts and trigger notifications**
    try:
        if get_news_status(user.id) and spo2_value > 0 and heart_rate_value > 0 and temperature_value > 0:
            # Calculate NEWS score
            score_data = calculate_news_score(temperature_value, heart_rate_value, spo2_value)
            
            # Create NEWS score record
            news_score = NEWSScore(
                footwear_data_id=new_data.id,
                temperature_score=score_data['temperature_score'],
                heart_rate_score=score_data['heart_rate_score'],
                spo2_score=score_data['spo2_score'],
                total_score=score_data['total_score'],
                alert_level=score_data['alert_level'],
                alert_message=score_data['alert_message'],
                news_enabled=True
            )
            db.session.add(news_score)
            db.session.commit()
            
            # Trigger notification if alert level requires it
            if score_data['alert_level'] in ['Orange', 'Red']:
                notification_handler.check_news_alerts(
                    news_score, user.id, device_id, footwear_monitor.name, footwear_monitor.baby_name
                )
                
    except Exception as news_error:
        current_app.logger.warning(f"NEWS notification check failed: {str(news_error)}")
    
    return jsonify({
        "message": "Footwear data received",
        "data_count": data_count,
        "prediction_eligible": data_count >= 15
    }), 200

@main.route('/api/access-data', methods=['POST'])
@csrf.exempt  # API uses api_key authentication
def access_data():
    user = None
    # Check for API key first for devices
    api_key = request.headers.get('x-api-key')
    if api_key:
        user = User.query.filter_by(api_key=api_key).first()
    # If no valid API key, check for logged in user (for dashboard)
    elif current_user.is_authenticated:
        user = current_user
    
    if not user:
        return jsonify({"error": "Authentication required"}), 401

    data = request.json
    footwear_id = data.get('footwear_id')
    envhub_id = data.get('envhub_id')
    
    # Fetch latest data for the given devices owned by the authenticated user
    footwear_data = FootwearData.query.join(FootwearMonitor).filter(FootwearMonitor.device_id == footwear_id, FootwearMonitor.user_id == user.id).order_by(FootwearData.timestamp.desc()).first()
    envhub_data = EnvHubData.query.join(EnvHubBox).filter(EnvHubBox.device_id == envhub_id, EnvHubBox.user_id == user.id).order_by(EnvHubData.timestamp.desc()).first()
    footwear_monitor = FootwearMonitor.query.filter_by(device_id=footwear_id, user_id=user.id).first()

    # Get pending media commands
    commands = media_commands.get(envhub_id, [])
    
    response = {
        "footwear_id": footwear_id,
        "envhub_id": envhub_id,
        "BabyName": footwear_monitor.baby_name if footwear_monitor else "N/A",
        "BPM": footwear_data.heart_rate if footwear_data else -1,
        "BodyTemp": footwear_data.temperature if footwear_data else -1,
        "SpO2": footwear_data.spo2 if footwear_data else -1,
        "df_player_cmd": commands,
        "buzzer_cmd": 0 # This will be handled by AI logic later
    }
    
    # Clear commands after sending
    if envhub_id in media_commands:
        media_commands[envhub_id] = []
    
    return jsonify(response)

# Dashboard API endpoints
@main.route('/api/dashboard/summary')
@login_required
def dashboard_summary():
    # Get latest data for all user's devices
    latest_vitals = []
    latest_env = []
    latest_images = []
    
    for device in current_user.footwear_monitors:
        latest_data = FootwearData.query.filter_by(footwear_monitor_id=device.id).order_by(FootwearData.timestamp.desc()).first()
        if latest_data:
            validation = get_vitals_validation(latest_data.heart_rate, latest_data.spo2, latest_data.temperature)
            latest_vitals.append({
                'device_id': device.device_id,
                'device_name': device.name,
                'baby_name': device.baby_name,
                'bpm': latest_data.heart_rate,
                'spo2': latest_data.spo2,
                'temperature': latest_data.temperature,
                'movement': latest_data.movement,
                'timestamp': latest_data.timestamp.isoformat(),
                'validation': validation
            })
    
    for device in current_user.envhub_boxes:
        latest_data = EnvHubData.query.filter_by(envhub_box_id=device.id).order_by(EnvHubData.timestamp.desc()).first()
        if latest_data:
            latest_env.append({
                'device_name': device.name,
                'temp': latest_data.temp,
                'humidity': latest_data.humidity,
                'aqi': latest_data.aqi,
                'mic': latest_data.mic,
                'is_playing': latest_data.is_playing,
                'current_volume': latest_data.current_volume,
                'current_track': latest_data.current_track,
                'timestamp': latest_data.timestamp.isoformat()
            })
    
    for device in current_user.camera_boxes:
        latest_image = CameraImage.query.filter_by(camera_box_id=device.id).order_by(CameraImage.timestamp.desc()).first()
        if latest_image:
            image_base64 = base64.b64encode(latest_image.image_data).decode('utf-8')
            latest_images.append({
                'device_name': device.name,
                'image_data': image_base64,
                'timestamp': latest_image.timestamp.isoformat()
            })
    
    return jsonify({
        'vitals': latest_vitals,
        'environment': latest_env,
        'images': latest_images
    })

@main.route('/api/dashboard/vitals')
@login_required
def dashboard_vitals():
    device_id = request.args.get('device_id')
    limit = request.args.get('limit')
    hours = request.args.get('hours')  # Keep for backward compatibility
    
    if device_id:
        # Look up device by device_id (not database id)
        device = FootwearMonitor.query.filter_by(device_id=device_id, user_id=current_user.id).first_or_404()
        
        if limit and limit != '0':
            # Limit by number of data points - get newest N records first, then reverse
            data = FootwearData.query.filter(
                FootwearData.footwear_monitor_id == device.id
            ).order_by(FootwearData.timestamp.desc()).limit(int(limit)).all()
            # Reverse to get chronological order (oldest to newest)
            data = data[::-1]
        elif hours:
            # Limit by time range (backward compatibility)
            since = datetime.now(timezone.utc) - timedelta(hours=int(hours))
            data = FootwearData.query.filter(
                FootwearData.footwear_monitor_id == device.id,
                FootwearData.timestamp >= since
            ).order_by(FootwearData.timestamp.asc()).all()
        else:
            # Default to last 50 data points in chronological order
            data = FootwearData.query.filter(
                FootwearData.footwear_monitor_id == device.id
            ).order_by(FootwearData.timestamp.desc()).limit(50).all()
            # Reverse to get chronological order (oldest to newest)
            data = data[::-1]
        
        vitals_data = []
        for d in data:
            validation = get_vitals_validation(d.heart_rate, d.spo2, d.temperature)
            vitals_data.append({
                'timestamp': d.timestamp.isoformat(),
                'bpm': d.heart_rate,
                'spo2': d.spo2,
                'temperature': d.temperature,
                'movement': d.movement,
                'validation': validation
            })
        
        return jsonify({
            'device_name': device.name,
            'baby_name': device.baby_name,
            'data': vitals_data
        })
    
    return jsonify({'error': 'Device ID required'}), 400

@main.route('/api/dashboard/environment')
@login_required
def dashboard_environment():
    device_id = request.args.get('device_id')
    limit = request.args.get('limit')
    hours = request.args.get('hours')  # Keep for backward compatibility
    
    if device_id:
        # Look up device by device_id (not database id)
        device = EnvHubBox.query.filter_by(device_id=device_id, user_id=current_user.id).first_or_404()
        
        if limit and limit != '0':
            # Limit by number of data points - get newest N records first, then reverse
            data = EnvHubData.query.filter(
                EnvHubData.envhub_box_id == device.id
            ).order_by(EnvHubData.timestamp.desc()).limit(int(limit)).all()
            # Reverse to get chronological order (oldest to newest)
            data = data[::-1]
        elif hours:
            # Limit by time range (backward compatibility)
            since = datetime.now(timezone.utc) - timedelta(hours=int(hours))
            data = EnvHubData.query.filter(
                EnvHubData.envhub_box_id == device.id,
                EnvHubData.timestamp >= since
            ).order_by(EnvHubData.timestamp.asc()).all()
        else:
            # Default to last 50 data points in chronological order
            data = EnvHubData.query.filter(
                EnvHubData.envhub_box_id == device.id
            ).order_by(EnvHubData.timestamp.desc()).limit(50).all()
            # Reverse to get chronological order (oldest to newest)
            data = data[::-1]
        
        return jsonify({
            'device_name': device.name,
            'data': [{
                'timestamp': d.timestamp.isoformat(),
                'temp': d.temp,
                'humidity': d.humidity,
                'aqi': d.aqi,
                'mic': d.mic
            } for d in data]
        })
    
    return jsonify({'error': 'Device ID required'}), 400

@main.route('/api/dashboard/images')
@login_required
def dashboard_images():
    device_id = request.args.get('device_id')
    limit = int(request.args.get('limit', 20))
    
    if device_id:
        device = CameraBox.query.filter_by(id=device_id, user_id=current_user.id).first_or_404()
        images = CameraImage.query.filter_by(camera_box_id=device.id).order_by(CameraImage.timestamp.desc()).limit(limit).all()
        
        return jsonify({
            'device_name': device.name,
            'images': [{
                'id': img.id,
                'timestamp': img.timestamp.isoformat(),
                'image_data': base64.b64encode(img.image_data).decode('utf-8')
            } for img in images]
        })
    
    return jsonify({'error': 'Device ID required'}), 400

# Media player commands storage (in-memory for simplicity)
media_commands = {}

@main.route('/api/dashboard/audio-status', methods=['GET'])
@login_required
def audio_status():
    # Check if user has any EnvHub devices (not footwear monitors)
    envhub_devices = EnvHubBox.query.filter_by(user_id=current_user.id).all()
    
    if not envhub_devices:
        return jsonify({'has_devices': False})
    
    status_data = []
    for device in envhub_devices:
        # Get latest data for this device using the foreign key relationship
        latest_data = EnvHubData.query.filter_by(envhub_box_id=device.id).order_by(EnvHubData.timestamp.desc()).first()
        
        if latest_data:
            status_data.append({
                'name': device.name,
                'device_id': device.device_id,
                'isPlaying': latest_data.is_playing,
                'currentVolume': latest_data.current_volume,
                'currentTrack': latest_data.current_track,
                'last_update': latest_data.timestamp.isoformat()
            })
    
    return jsonify({'has_devices': True, 'status': status_data})

@main.route('/api/dashboard/audio-command', methods=['POST'])
@login_required
def send_audio_command():
    data = request.json
    command = data.get('command')
    
    # Validate command
    valid_commands = [
        'play1', 'play2', 'play3', 'play4', 'play5', 'play6',
        'play7', 'play8', 'play9', 'play10', 'play11', 'play12',
        'stop_current', 'resume_current', 'volume_up', 'volume_down'
    ]
    
    if command not in valid_commands:
        return jsonify({'success': False, 'message': 'Invalid command'}), 400
    
    # Get all user's EnvHub devices with audio capability
    envhub_devices = EnvHubBox.query.filter_by(user_id=current_user.id).all()
    
    if not envhub_devices:
        return jsonify({'success': False, 'message': 'No audio devices found'}), 404
    
    # Store command for all devices (they will pick it up via access-data API)
    for device in envhub_devices:
        if device.device_id not in media_commands:
            media_commands[device.device_id] = []
        media_commands[device.device_id] = [command]  # Replace with new command
    
    return jsonify({'success': True, 'command_sent': command})

@main.route('/api/dashboard/media-command', methods=['POST'])
@login_required
def send_media_command():
    data = request.json
    device_id = data.get('device_id')
    command = data.get('command')
    
    device = EnvHubBox.query.filter_by(device_id=device_id, user_id=current_user.id).first()
    if not device:
        return jsonify({'error': 'Device not found'}), 404
    
    # Store command with timestamp
    if device_id not in media_commands:
        media_commands[device_id] = []
    
    media_commands[device_id] = [command]  # Replace with new command
    
    return jsonify({'message': 'Command sent'})

@main.route('/api/user/devices')
@login_required
def get_user_devices():
    """Get all devices linked to the current user"""
    devices = {
        'footwear_monitors': [
            {
                'id': monitor.id,
                'device_id': monitor.device_id,
                'name': monitor.name,
                'baby_name': monitor.baby_name
            }
            for monitor in current_user.footwear_monitors
        ],
        'envhub_boxes': [
            {
                'id': box.id,
                'device_id': box.device_id,
                'name': box.name
            }
            for box in current_user.envhub_boxes
        ],
        'camera_boxes': [
            {
                'id': box.id,
                'device_id': box.device_id,
                'name': box.name
            }
            for box in current_user.camera_boxes
        ]
    }
    
    return jsonify(devices)

# Sleep Tracking API Routes
@main.route('/api/sleep/data/<device_id>')
@login_required
def get_sleep_data(device_id):
    """Get sleep tracking data for a specific device"""
    try:
        # Get recent vitals data to analyze sleep patterns
        recent_data = FootwearData.query.filter_by(
            footwear_monitor_id=device_id
        ).order_by(FootwearData.timestamp.desc()).limit(100).all()
        
        sleep_analysis = []
        for data in recent_data:
            # Simple sleep state analysis based on movement and heart rate
            movement = data.movement or 0
            heart_rate = data.heart_rate or 100
            
            if movement > 0.7:
                sleep_state = 'awake'
            elif movement > 0.4:
                sleep_state = 'light'
            elif heart_rate < 90:
                sleep_state = 'deep'
            else:
                sleep_state = 'rem'
            
            sleep_analysis.append({
                'timestamp': data.timestamp.isoformat(),
                'sleep_state': sleep_state,
                'movement': movement,
                'heart_rate': heart_rate,
                'temperature': data.temperature
            })
        
        return jsonify({
            'device_id': device_id,
            'sleep_data': sleep_analysis,
            'total_records': len(sleep_analysis)
        })
    
    except Exception as e:
        print(f"Error getting sleep data: {e}")
        return jsonify({'error': str(e)}), 500

@main.route('/api/sleep/quality/<device_id>')
@login_required
def get_sleep_quality(device_id):
    """Get sleep quality metrics for a device"""
    try:
        # Simulate sleep quality calculation
        import random
        quality_score = random.randint(60, 100)
        
        return jsonify({
            'device_id': device_id,
            'quality_score': quality_score,
            'quality_rating': 'Excellent' if quality_score >= 85 else 'Good' if quality_score >= 70 else 'Fair' if quality_score >= 55 else 'Poor',
            'deep_sleep_percentage': random.randint(15, 45),
            'rem_sleep_percentage': random.randint(15, 40),
            'total_sleep_hours': random.randint(6, 12),
            'awakenings': random.randint(0, 5)
        })
    
    except Exception as e:
        print(f"Error calculating sleep quality: {e}")
        return jsonify({'error': str(e)}), 500

# Cry Detection API Routes
@main.route('/api/cry/data/<device_id>')
@login_required
def get_cry_data(device_id):
    """Get cry detection data for a specific device"""
    try:
        # Get recent audio/microphone data
        recent_data = EnvHubData.query.filter_by(
            envhub_box_id=device_id
        ).order_by(EnvHubData.timestamp.desc()).limit(50).all()
        
        cry_events = []
        for data in recent_data:
            # Simulate cry detection based on microphone levels
            mic_level = data.mic or 0
            if mic_level > 60:  # Threshold for potential cry
                import random
                cry_types = ['hungry', 'tired', 'pain', 'attention', 'unknown']
                
                cry_events.append({
                    'timestamp': data.timestamp.isoformat(),
                    'type': random.choice(cry_types),
                    'confidence': random.randint(60, 95),
                    'volume': mic_level,
                    'duration': random.randint(10, 180),
                    'frequency': random.randint(200, 2000)
                })
        
        return jsonify({
            'device_id': device_id,
            'cry_events': cry_events,
            'total_events': len(cry_events)
        })
    
    except Exception as e:
        print(f"Error getting cry data: {e}")
        return jsonify({'error': str(e)}), 500

@main.route('/api/cry/analysis/<device_id>')
@login_required
def get_cry_analysis(device_id):
    """Get cry pattern analysis for a device"""
    try:
        import random
        from collections import Counter
        
        # Simulate cry type distribution
        cry_types = ['hungry', 'tired', 'pain', 'attention', 'unknown']
        type_counts = {cry_type: random.randint(0, 20) for cry_type in cry_types}
        
        return jsonify({
            'device_id': device_id,
            'type_distribution': type_counts,
            'total_cries_today': sum(type_counts.values()),
            'average_volume': random.randint(45, 75),
            'peak_volume': random.randint(70, 95),
            'most_common_type': max(type_counts.items(), key=lambda x: x[1])[0] if any(type_counts.values()) else 'none'
        })
    
    except Exception as e:
        print(f"Error getting cry analysis: {e}")
        return jsonify({'error': str(e)}), 500

# NEWS API Routes
@main.route('/api/news/status')
@login_required
def news_status():
    """Get NEWS system enable/disable status"""
    status = get_news_status(current_user.id)
    return jsonify({'news_enabled': status})

@main.route('/api/news/toggle', methods=['POST'])
@login_required
def toggle_news():
    """Toggle NEWS system enable/disable"""
    settings = NEWSSettings.query.filter_by(user_id=current_user.id).first()
    if not settings:
        settings = NEWSSettings(user_id=current_user.id, news_enabled=True)
        db.session.add(settings)
    
    # Toggle the status
    settings.news_enabled = not settings.news_enabled
    settings.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    
    return jsonify({
        'news_enabled': settings.news_enabled,
        'message': f'NEWS system {"enabled" if settings.news_enabled else "disabled"}'
    })

@main.route('/api/news/current_vital_data')
@login_required
def current_vital_data():
    """Get current vital signs with NEWS scores"""
    device_id = request.args.get('device_id')
    if not device_id:
        return jsonify({'error': 'Device ID required'}), 400
    
    # Get the footwear monitor for this user
    monitor = FootwearMonitor.query.filter_by(device_id=device_id, user_id=current_user.id).first()
    if not monitor:
        return jsonify({'error': 'Device not found'}), 404
    
    # Get latest vital signs data
    latest_data = FootwearData.query.filter_by(footwear_monitor_id=monitor.id).order_by(FootwearData.timestamp.desc()).first()
    if not latest_data:
        return jsonify({'error': 'No data available'}), 404
    
    # Check if NEWS is enabled
    news_enabled = get_news_status(current_user.id)
    
    # Get or calculate NEWS score
    news_score = None
    if news_enabled:
        # Look for existing NEWS score for this data point
        news_score = NEWSScore.query.filter_by(footwear_data_id=latest_data.id).first()
        
        # If no existing score and data is valid, calculate new one
        if not news_score and latest_data.temperature > 0 and latest_data.heart_rate > 0 and latest_data.spo2 > 0:
            score_data = calculate_news_score(latest_data.temperature, latest_data.heart_rate, latest_data.spo2)
            news_score = NEWSScore(
                footwear_data_id=latest_data.id,
                temperature_score=score_data['temperature_score'],
                heart_rate_score=score_data['heart_rate_score'],
                spo2_score=score_data['spo2_score'],
                total_score=score_data['total_score'],
                alert_level=score_data['alert_level'],
                alert_message=score_data['alert_message'],
                news_enabled=news_enabled
            )
            db.session.add(news_score)
            db.session.commit()
    
    response_data = {
        'device_id': device_id,
        'device_name': monitor.name,
        'baby_name': monitor.baby_name,
        'timestamp': latest_data.timestamp.isoformat(),
        'temperature': latest_data.temperature,
        'heart_rate': latest_data.heart_rate,
        'spo2': latest_data.spo2,
        'movement': latest_data.movement,
        'news_enabled': news_enabled
    }
    
    if news_score:
        response_data['news_score'] = {
            'temperature_score': news_score.temperature_score,
            'heart_rate_score': news_score.heart_rate_score,
            'spo2_score': news_score.spo2_score,
            'total_score': news_score.total_score,
            'alert_level': news_score.alert_level,
            'alert_message': news_score.alert_message
        }
    
    return jsonify(response_data)

@main.route('/api/news/history')
@login_required
def news_history():
    """Get historical NEWS scores"""
    device_id = request.args.get('device_id')
    limit = int(request.args.get('limit', 20))
    
    if not device_id:
        return jsonify({'error': 'Device ID required'}), 400
    
    # Get the footwear monitor
    monitor = FootwearMonitor.query.filter_by(device_id=device_id, user_id=current_user.id).first()
    if not monitor:
        return jsonify({'error': 'Device not found'}), 404
    
    # Get historical NEWS scores with vital signs data
    history = db.session.query(NEWSScore, FootwearData).join(
        FootwearData, NEWSScore.footwear_data_id == FootwearData.id
    ).filter(
        FootwearData.footwear_monitor_id == monitor.id
    ).order_by(NEWSScore.timestamp.desc()).limit(limit).all()
    
    history_data = []
    for news_score, vital_data in history:
        history_data.append({
            'timestamp': news_score.timestamp.isoformat(),
            'temperature': vital_data.temperature,
            'heart_rate': vital_data.heart_rate,
            'spo2': vital_data.spo2,
            'movement': vital_data.movement,
            'news_score': {
                'temperature_score': news_score.temperature_score,
                'heart_rate_score': news_score.heart_rate_score,
                'spo2_score': news_score.spo2_score,
                'total_score': news_score.total_score,
                'alert_level': news_score.alert_level,
                'alert_message': news_score.alert_message
            }
        })
    
    return jsonify({
        'device_name': monitor.name,
        'baby_name': monitor.baby_name,
        'history': history_data
    })

# SocketIO Event Handlers
@socketio.on('connect')
def handle_connect():
    """Handle WebSocket connection - REQUIRE AUTHENTICATION"""
    if not current_user.is_authenticated:
        current_app.logger.warning(f'Unauthenticated WebSocket connection attempt from {get_real_ip()}')
        log_security_event('websocket_unauthorized', {
            'ip': get_real_ip(),
            'sid': request.sid,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }, severity='WARNING')
        return False  # Reject connection
    
    current_app.logger.info(f'Authenticated client connected: User {current_user.id} from {get_real_ip()}')
    emit('connected', {'data': 'Connected to server', 'user_id': current_user.id})

@socketio.on('disconnect')
def handle_disconnect():
    if current_user.is_authenticated:
        current_app.logger.info(f'Client disconnected: User {current_user.id}')
    else:
        current_app.logger.info(f'Anonymous client disconnected: {request.sid}')

@socketio.on('join_user_room')
def handle_join_user_room(data=None):
    """Join user-specific room - REQUIRE AUTHENTICATION"""
    if not current_user.is_authenticated:
        current_app.logger.warning(f'Unauthenticated room join attempt from {request.remote_addr}')
        return False
    
    # Only allow users to join their own room
    room = f'user_{current_user.id}'
    join_room(room)
    current_app.logger.info(f'User {current_user.id} joined room {room}')
    emit('joined_room', {'room': room})

@socketio.on('leave_user_room')
def handle_leave_user_room(data=None):
    """Leave user-specific room"""
    if not current_user.is_authenticated:
        return False
    
    room = f'user_{current_user.id}'
    leave_room(room)
    current_app.logger.info(f'User {current_user.id} left room {room}')
    emit('left_room', {'room': room})

# Helper function to emit new data events
def emit_new_data(user_id, device_id, data_type):
    """Emit new data event to user's room"""
    room = f'user_{user_id}'
    socketio.emit('new_data', {
        'device_id': device_id,
        'data_type': data_type,
        'timestamp': datetime.now(timezone.utc).isoformat()
    }, room=room)

# ==================== PREDICTION SYSTEM API ENDPOINTS ====================

@main.route('/api/predict_all', methods=['POST'])
@login_required
@csrf.exempt  # CSRF protection not needed for authenticated API
def predict_all_vitals():
    """
    Generate predictions for all vital signs using ARIMA models
    Supports both manual trigger and automatic WebSocket-triggered updates
    """
    try:
        data = request.get_json() or {}
        device_id = data.get('device_id')
        steps = data.get('steps', 20)
        confidence_level = data.get('confidence_level', 95)
        
        # Enhanced logging for debugging
        current_app.logger.info(f"Prediction request received: device_id={device_id}, steps={steps}, confidence={confidence_level}")
        current_app.logger.info(f"Request data: {data}")
        current_app.logger.info(f"User: {current_user.id}, {current_user.email}")
        
        # Validate device selection
        if not device_id:
            current_app.logger.error("Prediction request missing device_id")
            return jsonify({
                'error': 'Device ID is required',
                'details': 'Please select a footwear monitor device'
            }), 400
        
        # Validate steps and confidence level
        if not isinstance(steps, int) or steps < 1 or steps > 100:
            current_app.logger.error(f"Invalid steps value: {steps}")
            return jsonify({
                'error': 'Invalid steps parameter',
                'details': 'Steps must be an integer between 1 and 100'
            }), 400
        
        if not isinstance(confidence_level, (int, float)) or confidence_level < 50 or confidence_level > 99:
            current_app.logger.error(f"Invalid confidence_level: {confidence_level}")
            return jsonify({
                'error': 'Invalid confidence_level parameter',
                'details': 'Confidence level must be between 50 and 99'
            }), 400
        
        # Get user's specific footwear monitor
        footwear_monitor = FootwearMonitor.query.filter_by(
            device_id=device_id, 
            user_id=current_user.id
        ).first()
        
        if not footwear_monitor:
            current_app.logger.error(f"Device not found: device_id={device_id}, user_id={current_user.id}")
            return jsonify({
                'error': f'Device {device_id} not found or not authorized',
                'details': 'This device is not linked to your account'
            }), 404
        
        current_app.logger.info(f"Device found: {footwear_monitor.name} (ID: {footwear_monitor.id})")
        
        # Get historical data (up to 100 most recent valid points)
        historical_data = FootwearData.query.filter_by(
            footwear_monitor_id=footwear_monitor.id
        ).order_by(FootwearData.timestamp.desc()).limit(100).all()
        
        if len(historical_data) < 15:
            return jsonify({
                'error': f'Insufficient data points for device {device_id}: {len(historical_data)} (minimum 15 required for medical-grade predictions)',
                'device_info': {
                    'device_id': device_id,
                    'device_name': footwear_monitor.name,
                    'baby_name': footwear_monitor.baby_name,
                    'current_data_count': len(historical_data),
                    'required_minimum': 15
                }
            }), 400
        
        # Reverse to chronological order for prediction engine
        historical_data.reverse()
        
        # Generate predictions for all vital signs using the proper prediction engine
        from .prediction_engine import prediction_engine
        
        predictions = {}
        accuracy_records = []
        session_quality_scores = []
        
        vital_signs = ['spo2', 'heart_rate', 'temperature']
        
        for vital_sign in vital_signs:
            try:
                # Use the proper prediction engine
                prediction_result = prediction_engine.generate_predictions(
                    historical_data, 
                    vital_sign, 
                    steps=steps, 
                    confidence_level=confidence_level
                )
                
                if 'error' in prediction_result:
                    predictions[vital_sign] = {'error': prediction_result['error']}
                    continue
                
                predictions[vital_sign] = prediction_result
                
                # Extract quality score for session tracking
                if 'accuracy' in prediction_result:
                    quality_map = {'excellent': 3, 'good': 2, 'poor': 1}
                    quality_score = quality_map.get(prediction_result['accuracy'].get('quality', 'poor'), 1)
                    session_quality_scores.append(quality_score)
                
            except Exception as e:
                current_app.logger.error(f"Prediction failed for {vital_sign}: {str(e)}")
                predictions[vital_sign] = {'error': f'Prediction failed: {str(e)}'}
        
        # Create prediction session record
        session = PredictionSession(
            user_id=current_user.id,
            footwear_monitor_id=footwear_monitor.id,
            data_points_used=len(historical_data)
        )
        
        # Store predicted ranges and model information
        if 'spo2' in predictions and 'predictions' in predictions['spo2']:
            spo2_values = [p['value'] for p in predictions['spo2']['predictions']]
            session.spo2_min = min(spo2_values)
            session.spo2_max = max(spo2_values)
            if 'model_info' in predictions['spo2']:
                session.spo2_model_order = str(predictions['spo2']['model_info'].get('order', ''))
        
        if 'heart_rate' in predictions and 'predictions' in predictions['heart_rate']:
            hr_values = [p['value'] for p in predictions['heart_rate']['predictions']]
            session.heart_rate_min = min(hr_values)
            session.heart_rate_max = max(hr_values)
            if 'model_info' in predictions['heart_rate']:
                session.heart_rate_model_order = str(predictions['heart_rate']['model_info'].get('order', ''))
        
        if 'temperature' in predictions and 'predictions' in predictions['temperature']:
            temp_values = [p['value'] for p in predictions['temperature']['predictions']]
            session.temperature_min = min(temp_values)
            session.temperature_max = max(temp_values)
            if 'model_info' in predictions['temperature']:
                session.temperature_model_order = str(predictions['temperature']['model_info'].get('order', ''))
        
        # Calculate overall session quality
        if session_quality_scores:
            avg_quality = sum(session_quality_scores) / len(session_quality_scores)
            if avg_quality >= 2.5:
                session.overall_quality = 'excellent'
            elif avg_quality >= 1.5:
                session.overall_quality = 'good'
            else:
                session.overall_quality = 'poor'
        else:
            session.overall_quality = 'poor'
        
        db.session.add(session)
        db.session.commit()
        
        # Store accuracy metrics and prediction data
        for vital_sign in vital_signs:
            if vital_sign in predictions and 'accuracy' in predictions[vital_sign]:
                accuracy = predictions[vital_sign]['accuracy']
                model_info = predictions[vital_sign].get('model_info', {})
                
                # Store accuracy metrics
                accuracy_record = AccuracyMetric(
                    session_id=session.id,
                    vital_sign=vital_sign,
                    mae=accuracy.get('mae', 0.0),
                    rmse=accuracy.get('rmse', 0.0),
                    mape=accuracy.get('mape', 0.0),
                    r2_score=accuracy.get('r2', 0.0),
                    quality_grade=accuracy.get('quality', 'poor'),
                    model_type=model_info.get('type', 'Unknown'),
                    model_order=str(model_info.get('order', '')),
                    aic_score=model_info.get('aic', 0.0),
                    training_points=model_info.get('training_points', 0),
                    test_points=model_info.get('test_points', 0)
                )
                db.session.add(accuracy_record)
                
                # Store individual prediction points
                if 'predictions' in predictions[vital_sign]:
                    for pred in predictions[vital_sign]['predictions']:
                        pred_data = PredictionData(
                            session_id=session.id,
                            vital_sign=vital_sign,
                            prediction_timestamp=datetime.fromisoformat(pred['timestamp'].replace('Z', '+00:00')),
                            predicted_value=pred['value'],
                            upper_bound=pred['upper_bound'],
                            lower_bound=pred['lower_bound'],
                            confidence_level=confidence_level
                        )
                        db.session.add(pred_data)
        
        db.session.commit()
        
        # Emit real-time update to connected clients
        room = f'user_{current_user.id}'
        socketio.emit('prediction_update', {
            'predictions': predictions,
            'session_id': session.id,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'device_info': {
                'device_id': footwear_monitor.device_id,
                'device_name': footwear_monitor.name,
                'baby_name': footwear_monitor.baby_name,
                'data_points': len(historical_data)
            }
        }, room=room)
        
        return jsonify({
            'predictions': predictions,
            'session_id': session.id,
            'device_info': {
                'device_id': footwear_monitor.device_id,
                'baby_name': footwear_monitor.baby_name,
                'data_points': len(historical_data)
            },
            'status': 'success',
            'timestamp': datetime.now(timezone.utc).isoformat()
        })
        
    except ValueError as ve:
        current_app.logger.error(f"Prediction API validation error: {str(ve)}\n{traceback.format_exc()}")
        return jsonify({
            'error': 'Invalid input data',
            'details': str(ve)
        }), 400
    except KeyError as ke:
        current_app.logger.error(f"Prediction API missing key: {str(ke)}\n{traceback.format_exc()}")
        return jsonify({
            'error': 'Missing required field',
            'details': f'Required field missing: {str(ke)}'
        }), 400
    except Exception as e:
        current_app.logger.error(f"Prediction API error: {str(e)}\n{traceback.format_exc()}")
        return jsonify({
            'error': f'Prediction generation failed: {str(e)}',
            'details': 'An unexpected error occurred. Please check server logs.'
        }), 500

@main.route('/api/prediction_history', methods=['GET'])
@login_required
def get_prediction_history():
    """Get recent prediction sessions with metadata"""
    try:
        limit = request.args.get('limit', 10, type=int)
        
        sessions = PredictionSession.query.filter_by(
            user_id=current_user.id
        ).order_by(PredictionSession.timestamp.desc()).limit(limit).all()
        
        history = []
        for session in sessions:
            session_data = {
                'id': session.id,
                'timestamp': session.timestamp.isoformat(),
                'baby_name': session.footwear_monitor.baby_name,
                'device_id': session.footwear_monitor.device_id,
                'data_points_used': session.data_points_used,
                'overall_quality': session.overall_quality,
                'predicted_ranges': {
                    'spo2': {'min': session.spo2_min, 'max': session.spo2_max},
                    'heart_rate': {'min': session.heart_rate_min, 'max': session.heart_rate_max},
                    'temperature': {'min': session.temperature_min, 'max': session.temperature_max}
                },
                'model_orders': {
                    'spo2': session.spo2_model_order,
                    'heart_rate': session.heart_rate_model_order,
                    'temperature': session.temperature_model_order
                }
            }
            history.append(session_data)
        
        return jsonify({'history': history, 'total_sessions': len(sessions)})
        
    except Exception as e:
        current_app.logger.error(f"History API error: {str(e)}")
        return jsonify({'error': 'Failed to retrieve prediction history'}), 500

@main.route('/api/accuracy_trends', methods=['GET'])
@login_required
def get_accuracy_trends():
    """Get accuracy trends with filtering options"""
    try:
        vital_sign_filter = request.args.get('vital_sign', 'all')
        limit = request.args.get('limit', 30, type=int)
        
        query = AccuracyMetric.query.join(PredictionSession).filter(
            PredictionSession.user_id == current_user.id
        ).order_by(AccuracyMetric.timestamp.desc())
        
        if vital_sign_filter != 'all':
            query = query.filter(AccuracyMetric.vital_sign == vital_sign_filter)
        
        metrics = query.limit(limit).all()
        
        trends = []
        for metric in metrics:
            trend_data = {
                'timestamp': metric.timestamp.isoformat(),
                'vital_sign': metric.vital_sign,
                'mae': metric.mae,
                'rmse': metric.rmse,
                'mape': metric.mape,
                'r2_score': metric.r2_score,
                'quality_grade': metric.quality_grade,
                'model_type': metric.model_type,
                'model_order': metric.model_order,
                'aic_score': metric.aic_score,
                'training_points': metric.training_points,
                'test_points': metric.test_points
            }
            trends.append(trend_data)
        
        return jsonify({'trends': trends, 'filter': vital_sign_filter})
        
    except Exception as e:
        current_app.logger.error(f"Accuracy trends API error: {str(e)}")
        return jsonify({'error': 'Failed to retrieve accuracy trends'}), 500

@main.route('/api/device_status/<device_id>')
@login_required
def get_device_status(device_id):
    """
    Get device connection status and data availability for predictions
    """
    try:
        # Verify device ownership
        footwear_monitor = FootwearMonitor.query.filter_by(
            device_id=device_id, 
            user_id=current_user.id
        ).first()
        
        if not footwear_monitor:
            return jsonify({'error': 'Device not found or not authorized'}), 404
        
        # Count available data points
        data_count = FootwearData.query.filter_by(
            footwear_monitor_id=footwear_monitor.id
        ).count()
        
        # Get latest data point
        latest_data = FootwearData.query.filter_by(
            footwear_monitor_id=footwear_monitor.id
        ).order_by(FootwearData.timestamp.desc()).first()
        
        # Determine status
        if data_count >= 15:
            status = 'ready'
            status_message = 'Ready for predictions'
        elif data_count > 0:
            status = 'insufficient_data'
            status_message = f'Need {15 - data_count} more data points'
        else:
            status = 'no_data'
            status_message = 'No data available'
        
        response_data = {
            'device_id': device_id,
            'device_name': footwear_monitor.name,
            'baby_name': footwear_monitor.baby_name,
            'status': status,
            'status_message': status_message,
            'data_count': data_count,
            'required_minimum': 15,
            'prediction_ready': data_count >= 15
        }
        
        if latest_data:
            response_data['latest_data'] = {
                'timestamp': latest_data.timestamp.isoformat(),
                'heart_rate': latest_data.heart_rate,
                'spo2': latest_data.spo2,
                'temperature': latest_data.temperature,
                'movement': latest_data.movement
            }
        
        return jsonify(response_data)
        
    except Exception as e:
        current_app.logger.error(f"Device status check error: {str(e)}")
        return jsonify({'error': 'Failed to check device status'}), 500

# ==================== NOTIFICATION SYSTEM API ENDPOINTS ====================

@main.route('/api/notifications/settings', methods=['GET'])
@login_required
def get_notification_settings():
    """Get user notification settings"""
    try:
        settings = notification_handler.get_or_create_settings(current_user.id)
        
        return jsonify({
            'news_notifications_enabled': settings.news_notifications_enabled,
            'environmental_notifications_enabled': settings.environmental_notifications_enabled,
            'website_notifications_enabled': settings.website_notifications_enabled,
            'push_notifications_enabled': settings.push_notifications_enabled,
            'news_cooldown_minutes': settings.news_cooldown_minutes,
            'environmental_cooldown_minutes': settings.environmental_cooldown_minutes,
            'push_api_key': settings.push_api_key,
            'updated_at': settings.updated_at.isoformat()
        })
        
    except Exception as e:
        current_app.logger.error(f"Failed to get notification settings: {str(e)}")
        return jsonify({'error': 'Failed to retrieve notification settings'}), 500

@main.route('/api/notifications/settings', methods=['POST'])
@login_required
def update_notification_settings():
    """Update user notification settings"""
    try:
        data = request.get_json()
        
        if notification_handler.update_settings(current_user.id, data):
            return jsonify({'message': 'Settings updated successfully'})
        else:
            return jsonify({'error': 'Failed to update settings'}), 500
            
    except Exception as e:
        current_app.logger.error(f"Failed to update notification settings: {str(e)}")
        return jsonify({'error': 'Failed to update notification settings'}), 500

@main.route('/api/notifications/history', methods=['GET'])
@login_required
def get_notification_history():
    """Get user notification history with filtering"""
    try:
        limit = request.args.get('limit', 50, type=int)
        notification_type = request.args.get('type', None)  # 'news' or 'environmental'
        acknowledged = request.args.get('acknowledged', None)  # 'true', 'false', or None for all
        
        query = NotificationHistory.query.filter_by(user_id=current_user.id)
        
        if notification_type:
            query = query.filter_by(notification_type=notification_type)
        
        if acknowledged is not None:
            is_ack = acknowledged.lower() == 'true'
            query = query.filter_by(is_acknowledged=is_ack)
        
        notifications = query.order_by(
            NotificationHistory.created_at.desc()
        ).limit(limit).all()
        
        history = []
        for notif in notifications:
            history.append({
                'id': notif.id,
                'notification_type': notif.notification_type,
                'trigger_type': notif.trigger_type,
                'title': notif.title,
                'content': notif.content,
                'device_id': notif.device_id,
                'device_name': notif.device_name,
                'trigger_value': notif.trigger_value,
                'threshold_value': notif.threshold_value,
                'website_sent': notif.website_sent,
                'push_sent': notif.push_sent,
                'is_acknowledged': notif.is_acknowledged,
                'created_at': notif.created_at.isoformat(),
                'acknowledged_at': notif.acknowledged_at.isoformat() if notif.acknowledged_at else None
            })
        
        return jsonify({
            'notifications': history,
            'total': len(history),
            'filters': {
                'type': notification_type,
                'acknowledged': acknowledged,
                'limit': limit
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"Failed to get notification history: {str(e)}")
        return jsonify({'error': 'Failed to retrieve notification history'}), 500

@main.route('/api/notifications/<int:notification_id>/acknowledge', methods=['POST'])
@login_required
def acknowledge_notification(notification_id):
    """Acknowledge a specific notification"""
    try:
        if notification_handler.acknowledge_notification(notification_id, current_user.id):
            return jsonify({'message': 'Notification acknowledged'})
        else:
            return jsonify({'error': 'Failed to acknowledge notification'}), 400
            
    except Exception as e:
        current_app.logger.error(f"Failed to acknowledge notification: {str(e)}")
        return jsonify({'error': 'Failed to acknowledge notification'}), 500

@main.route('/api/notifications/stats', methods=['GET'])
@login_required
def get_notification_stats():
    """Get notification statistics for user dashboard"""
    try:
        stats = notification_handler.get_notification_stats(current_user.id)
        return jsonify(stats)
        
    except Exception as e:
        current_app.logger.error(f"Failed to get notification stats: {str(e)}")
        return jsonify({'error': 'Failed to retrieve notification statistics'}), 500

@main.route('/api/notifications/test', methods=['POST'])
@login_required
def test_notification():
    """Send test notification (for debugging/testing)"""
    try:
        data = request.get_json() or {}
        notification_type = data.get('type', 'environmental')  # 'news' or 'environmental'
        delivery_method = data.get('method', 'website')  # 'website' or 'push'
        
        success = notification_handler.send_test_notification(
            current_user.id, notification_type, delivery_method
        )
        
        if success:
            return jsonify({'message': f'Test {delivery_method} notification sent successfully'})
        else:
            return jsonify({'error': f'Failed to send test {delivery_method} notification'}), 500
            
    except Exception as e:
        current_app.logger.error(f"Test notification failed: {str(e)}")
        return jsonify({'error': 'Test notification failed'}), 500

@main.route('/api/notifications/clear-all', methods=['POST'])
@login_required
def clear_all_notifications():
    """Mark all notifications as acknowledged"""
    try:
        NotificationHistory.query.filter_by(
            user_id=current_user.id,
            is_acknowledged=False
        ).update({
            'is_acknowledged': True,
            'acknowledged_at': datetime.now(timezone.utc)
        })
        
        db.session.commit()
        return jsonify({'message': 'All notifications marked as acknowledged'})
        
    except Exception as e:
        current_app.logger.error(f"Failed to clear all notifications: {str(e)}")
        db.session.rollback()
        return jsonify({'error': 'Failed to clear notifications'}), 500

# ==================== WEBSOCKET EVENT HANDLERS ====================

@socketio.on('join_prediction_room')
def handle_join_prediction_room(data):
    """Join user-specific room for prediction updates"""
    if current_user.is_authenticated:
        room = f'user_{current_user.id}'
        join_room(room)
        emit('joined_prediction_room', {'room': room, 'user_id': current_user.id})

@socketio.on('leave_prediction_room')
def handle_leave_prediction_room(data):
    """Leave user-specific prediction room"""
    if current_user.is_authenticated:
        room = f'user_{current_user.id}'
        leave_room(room)
        emit('left_prediction_room', {'room': room})

@socketio.on('request_prediction_update')
def handle_prediction_request(data):
    """Handle manual prediction update requests"""
    if current_user.is_authenticated:
        try:
            device_id = data.get('device_id')
            # Trigger prediction update (client will call /api/predict_all)
            emit('prediction_request_acknowledged', {
                'device_id': device_id,
                'timestamp': datetime.now(timezone.utc).isoformat()
            })
        except Exception as e:
            emit('prediction_error', {'error': str(e)})

# ADMIN Panel Route (unchanged)