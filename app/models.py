from datetime import datetime, timezone
from app import db, login_manager
from flask_login import UserMixin
import string
import random

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def generate_api_key():
    return ''.join(random.choices(string.ascii_letters + string.digits, k=32))

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(60), nullable=False)
    use_case = db.Column(db.String(50), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    contact_number = db.Column(db.String(20), nullable=False)
    birthday = db.Column(db.Date, nullable=True)
    hospital_name = db.Column(db.String(100), nullable=True)
    api_key = db.Column(db.String(32), unique=True, nullable=False, default=generate_api_key)
    
    # Security fields for account lockout and tracking
    failed_login_attempts = db.Column(db.Integer, default=0, nullable=False)
    locked_until = db.Column(db.DateTime, nullable=True)
    last_login_at = db.Column(db.DateTime, nullable=True)
    last_login_ip = db.Column(db.String(45), nullable=True)  # IPv6 support
    
    camera_boxes = db.relationship('CameraBox', backref='owner', lazy=True, cascade="all, delete-orphan")
    envhub_boxes = db.relationship('EnvHubBox', backref='owner', lazy=True, cascade="all, delete-orphan")
    footwear_monitors = db.relationship('FootwearMonitor', backref='owner', lazy=True, cascade="all, delete-orphan")

class CameraBox(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.String(6), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    images = db.relationship('CameraImage', backref='device', lazy=True, cascade="all, delete-orphan")

class CameraImage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    image_data = db.Column(db.LargeBinary, nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    camera_box_id = db.Column(db.Integer, db.ForeignKey('camera_box.id'), nullable=False)

class EnvHubBox(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.String(6), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    data = db.relationship('EnvHubData', backref='device', lazy=True, cascade="all, delete-orphan")

class EnvHubData(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    temp = db.Column(db.Float, nullable=False)
    humidity = db.Column(db.Float, nullable=False)
    aqi = db.Column(db.Integer, nullable=False)
    mic = db.Column(db.Float, nullable=False)
    is_playing = db.Column(db.Boolean, nullable=False)
    current_volume = db.Column(db.Integer, nullable=False)
    current_track = db.Column(db.Integer, nullable=False)
    envhub_box_id = db.Column(db.Integer, db.ForeignKey('env_hub_box.id'), nullable=False)

class FootwearMonitor(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.String(6), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    baby_name = db.Column(db.String(100), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    data = db.relationship('FootwearData', backref='device', lazy=True, cascade="all, delete-orphan")

class FootwearData(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    spo2 = db.Column(db.Integer, nullable=False)
    heart_rate = db.Column(db.Integer, nullable=False)
    temperature = db.Column(db.Float, nullable=False)
    movement = db.Column(db.Boolean, nullable=False)
    footwear_monitor_id = db.Column(db.Integer, db.ForeignKey('footwear_monitor.id'), nullable=False)
    news_scores = db.relationship('NEWSScore', backref='footwear_data', lazy=True, cascade="all, delete-orphan")

class NEWSScore(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    footwear_data_id = db.Column(db.Integer, db.ForeignKey('footwear_data.id'), nullable=False)
    temperature_score = db.Column(db.Integer, nullable=False)
    heart_rate_score = db.Column(db.Integer, nullable=False)
    spo2_score = db.Column(db.Integer, nullable=False)
    total_score = db.Column(db.Integer, nullable=False)
    alert_level = db.Column(db.String(10), nullable=False)  # 'Green', 'Yellow', 'Orange', 'Red'
    alert_message = db.Column(db.String(255), nullable=False)
    news_enabled = db.Column(db.Boolean, nullable=False, default=True)

# Global NEWS system settings
class NEWSSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    news_enabled = db.Column(db.Boolean, nullable=False, default=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    
    user = db.relationship('User', backref='news_settings', lazy=True)

# Prediction System Models
class PredictionSession(db.Model):
    """Tracks individual prediction sessions with full metadata"""
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    footwear_monitor_id = db.Column(db.Integer, db.ForeignKey('footwear_monitor.id'), nullable=False)
    
    # Predicted ranges for all vital signs
    spo2_min = db.Column(db.Float, nullable=True)
    spo2_max = db.Column(db.Float, nullable=True)
    heart_rate_min = db.Column(db.Float, nullable=True)
    heart_rate_max = db.Column(db.Float, nullable=True)
    temperature_min = db.Column(db.Float, nullable=True)
    temperature_max = db.Column(db.Float, nullable=True)
    
    # ARIMA model specifications used
    spo2_model_order = db.Column(db.String(20), nullable=True)
    heart_rate_model_order = db.Column(db.String(20), nullable=True)
    temperature_model_order = db.Column(db.String(20), nullable=True)
    
    # Session quality indicators
    overall_quality = db.Column(db.String(20), nullable=True)  # 'excellent', 'good', 'poor'
    data_points_used = db.Column(db.Integer, nullable=True)
    
    user = db.relationship('User', backref='prediction_sessions')
    footwear_monitor = db.relationship('FootwearMonitor', backref='prediction_sessions')
    accuracy_records = db.relationship('AccuracyMetric', backref='session', lazy=True, cascade="all, delete-orphan")

class AccuracyMetric(db.Model):
    """Stores accuracy metrics for each vital sign prediction"""
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    session_id = db.Column(db.Integer, db.ForeignKey('prediction_session.id'), nullable=False)
    vital_sign = db.Column(db.String(20), nullable=False)  # 'spo2', 'heart_rate', 'temperature'
    
    # Core accuracy metrics
    mae = db.Column(db.Float, nullable=False)  # Mean Absolute Error
    rmse = db.Column(db.Float, nullable=False)  # Root Mean Squared Error
    mape = db.Column(db.Float, nullable=False)  # Mean Absolute Percentage Error
    r2_score = db.Column(db.Float, nullable=False)  # R-squared
    
    # Quality classification
    quality_grade = db.Column(db.String(20), nullable=False)  # 'excellent', 'good', 'poor'
    
    # Model information
    model_type = db.Column(db.String(50), nullable=False)  # 'ARIMA', 'Enhanced Statistical', etc.
    model_order = db.Column(db.String(20), nullable=True)
    aic_score = db.Column(db.Float, nullable=True)
    training_points = db.Column(db.Integer, nullable=False)
    test_points = db.Column(db.Integer, nullable=False)

class PredictionData(db.Model):
    """Stores individual prediction points with confidence intervals"""
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('prediction_session.id'), nullable=False)
    vital_sign = db.Column(db.String(20), nullable=False)
    
    # Prediction details
    prediction_timestamp = db.Column(db.DateTime, nullable=False)
    predicted_value = db.Column(db.Float, nullable=False)
    upper_bound = db.Column(db.Float, nullable=False)
    lower_bound = db.Column(db.Float, nullable=False)
    confidence_level = db.Column(db.Float, nullable=False, default=95.0)
    
    session = db.relationship('PredictionSession', backref='predictions')

# Notification System Models
class NotificationSettings(db.Model):
    """User notification preferences and settings"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    # Notification type toggles
    news_notifications_enabled = db.Column(db.Boolean, nullable=False, default=True)
    environmental_notifications_enabled = db.Column(db.Boolean, nullable=False, default=True)
    
    # Delivery method toggles
    website_notifications_enabled = db.Column(db.Boolean, nullable=False, default=True)
    push_notifications_enabled = db.Column(db.Boolean, nullable=False, default=False)
    
    # Cooldown settings (in minutes)
    news_cooldown_minutes = db.Column(db.Integer, nullable=False, default=30)
    environmental_cooldown_minutes = db.Column(db.Integer, nullable=False, default=15)
    
    # Push notification API key (user-specific for mobile integration)
    push_api_key = db.Column(db.String(50), nullable=True)
    
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    
    user = db.relationship('User', backref='notification_settings', lazy=True)

class NotificationHistory(db.Model):
    """Tracks all sent notifications for cooldown and history"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    # Notification details
    notification_type = db.Column(db.String(20), nullable=False)  # 'news', 'environmental'
    trigger_type = db.Column(db.String(50), nullable=False)  # 'news_alert', 'temperature_high', 'aqi_poor', etc.
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    
    # Delivery status
    website_sent = db.Column(db.Boolean, nullable=False, default=False)
    push_sent = db.Column(db.Boolean, nullable=False, default=False)
    
    # Device/source information
    device_id = db.Column(db.String(6), nullable=True)  # If related to specific device
    device_name = db.Column(db.String(100), nullable=True)
    
    # Trigger values (for environmental notifications)
    trigger_value = db.Column(db.Float, nullable=True)
    threshold_value = db.Column(db.Float, nullable=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    acknowledged_at = db.Column(db.DateTime, nullable=True)
    is_acknowledged = db.Column(db.Boolean, nullable=False, default=False)
    
    user = db.relationship('User', backref='notification_history', lazy=True)

class NotificationQueue(db.Model):
    """Queue for pending notifications to be processed"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    # Notification details
    notification_type = db.Column(db.String(20), nullable=False)
    trigger_type = db.Column(db.String(50), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    
    # Processing flags
    processed = db.Column(db.Boolean, nullable=False, default=False)
    processing_attempts = db.Column(db.Integer, nullable=False, default=0)
    max_attempts = db.Column(db.Integer, nullable=False, default=3)
    
    # Device information
    device_id = db.Column(db.String(6), nullable=True)
    trigger_value = db.Column(db.Float, nullable=True)
    
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    processed_at = db.Column(db.DateTime, nullable=True)
    
    user = db.relationship('User', backref='notification_queue', lazy=True)
