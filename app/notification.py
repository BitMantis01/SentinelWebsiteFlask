import requests
import urllib.parse
from datetime import datetime, timezone, timedelta
from flask import current_app
from app import db, socketio
from app.models import (
    NotificationSettings, NotificationHistory, NotificationQueue, 
    User, NEWSScore, EnvHubData, FootwearData
)

class NotificationHandler:
    """Centralized notification system for NEWS and Environmental alerts"""
    
    def __init__(self):
        self.base_notification_url = "https://sentinel.bitmantis.xyz/dashboard/notifications"
        self.push_api_base = "http://xdroid.net/api/message"
        
        # Environmental thresholds
        self.env_thresholds = {
            'temperature': {'min': 20.0, 'max': 26.0, 'unit': '°C'},
            'humidity': {'min': 40.0, 'max': 60.0, 'unit': '%'},
            'aqi': {'max': 100, 'unit': 'AQI'},
            'noise': {'max': 50.0, 'unit': 'dB'}
        }
        
        # NEWS alert levels requiring notification
        self.news_alert_levels = ['Orange', 'Red']
    
    def get_or_create_settings(self, user_id):
        """Get user notification settings or create default ones"""
        settings = NotificationSettings.query.filter_by(user_id=user_id).first()
        if not settings:
            settings = NotificationSettings(
                user_id=user_id,
                news_notifications_enabled=True,
                environmental_notifications_enabled=True,
                website_notifications_enabled=True,
                push_notifications_enabled=False,
                news_cooldown_minutes=30,
                environmental_cooldown_minutes=15,
                push_api_key=None
            )
            db.session.add(settings)
            db.session.commit()
        return settings
    
    def is_in_cooldown(self, user_id, notification_type):
        """Check if notification type is in cooldown period"""
        settings = self.get_or_create_settings(user_id)
        
        if notification_type == 'news':
            cooldown_minutes = settings.news_cooldown_minutes
        elif notification_type == 'environmental':
            cooldown_minutes = settings.environmental_cooldown_minutes
        else:
            return False
        
        cooldown_threshold = datetime.now(timezone.utc) - timedelta(minutes=cooldown_minutes)
        
        # Check if any notification of this type was sent within cooldown period
        recent_notification = NotificationHistory.query.filter(
            NotificationHistory.user_id == user_id,
            NotificationHistory.notification_type == notification_type,
            NotificationHistory.created_at > cooldown_threshold
        ).first()
        
        return recent_notification is not None
    
    def send_website_notification(self, user_id, title, content, notification_data=None):
        """Send real-time website notification via WebSocket"""
        try:
            # Convert UTC to GMT+8 for display
            gmt8_timezone = timezone(timedelta(hours=8))
            current_time_gmt8 = datetime.now(timezone.utc).astimezone(gmt8_timezone)
            
            room = f'user_{user_id}'
            notification_payload = {
                'title': title,
                'content': content,
                'timestamp': current_time_gmt8.isoformat(),
                'type': 'alert',
                'data': notification_data or {}
            }
            
            socketio.emit('new_notification', notification_payload, room=room)
            return True
        except Exception as e:
            current_app.logger.error(f"Website notification failed: {str(e)}")
            return False
    
    def send_push_notification(self, user_id, title, content):
        """Send push notification via xdroid.net API"""
        try:
            settings = self.get_or_create_settings(user_id)
            
            if not settings.push_notifications_enabled:
                return False
            
            # Prepare API parameters
            params = {
                'k': settings.push_api_key,
                't': title[:100],  # Limit title length
                'c': content[:500],  # Limit content length
                'u': self.base_notification_url
            }
            
            # Send request to xdroid.net API
            response = requests.get(self.push_api_base, params=params, timeout=10)
            
            if response.status_code == 200:
                current_app.logger.info(f"Push notification sent to user {user_id}: {title}")
                return True
            else:
                current_app.logger.warning(f"Push notification failed: {response.status_code} - {response.text}")
                return False
                
        except requests.RequestException as e:
            current_app.logger.error(f"Push notification request failed: {str(e)}")
            return False
        except Exception as e:
            current_app.logger.error(f"Push notification error: {str(e)}")
            return False
    
    def create_notification(self, user_id, notification_type, trigger_type, title, content, 
                          device_id=None, device_name=None, trigger_value=None, threshold_value=None):
        """Create and send notification if conditions are met"""
        try:
            settings = self.get_or_create_settings(user_id)
            
            # Check if notification type is enabled
            if notification_type == 'news' and not settings.news_notifications_enabled:
                return False
            elif notification_type == 'environmental' and not settings.environmental_notifications_enabled:
                return False
            
            # Check cooldown
            if self.is_in_cooldown(user_id, notification_type):
                current_app.logger.info(f"Notification blocked by cooldown: {notification_type} for user {user_id}")
                return False
            
            # Send notifications
            website_sent = False
            push_sent = False
            
            notification_data = {
                'device_id': device_id,
                'device_name': device_name,
                'trigger_value': trigger_value,
                'threshold_value': threshold_value,
                'trigger_type': trigger_type
            }
            
            if settings.website_notifications_enabled:
                website_sent = self.send_website_notification(user_id, title, content, notification_data)
            
            if settings.push_notifications_enabled:
                push_sent = self.send_push_notification(user_id, title, content)
            
            # Record in history
            history_record = NotificationHistory(
                user_id=user_id,
                notification_type=notification_type,
                trigger_type=trigger_type,
                title=title,
                content=content,
                website_sent=website_sent,
                push_sent=push_sent,
                device_id=device_id,
                device_name=device_name,
                trigger_value=trigger_value,
                threshold_value=threshold_value
            )
            
            db.session.add(history_record)
            db.session.commit()
            
            current_app.logger.info(f"Notification created for user {user_id}: {title}")
            return True
            
        except Exception as e:
            current_app.logger.error(f"Notification creation failed: {str(e)}")
            db.session.rollback()
            return False
    
    def check_news_alerts(self, news_score, user_id, device_id, device_name, baby_name):
        """Check and send NEWS alert notifications"""
        if news_score.alert_level not in self.news_alert_levels:
            return False
        
        # Determine urgency and content
        if news_score.alert_level == 'Red':
            title = f"🚨 URGENT: {baby_name} Critical Alert"
            urgency = "IMMEDIATE"
        else:  # Orange
            title = f"⚠️ WARNING: {baby_name} Alert"
            urgency = "within 30 minutes"
        
        content = (
            f"NEWS Score: {news_score.total_score} ({news_score.alert_level})\n"
            f"Action Required: {news_score.alert_message}\n"
            f"Device: {device_name} ({device_id})\n"
            f"Time: {news_score.timestamp.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            f"Vital Signs:\n"
            f"• Temperature: {news_score.footwear_data.temperature}°C (Score: {news_score.temperature_score})\n"
            f"• Heart Rate: {news_score.footwear_data.heart_rate} BPM (Score: {news_score.heart_rate_score})\n"
            f"• SpO2: {news_score.footwear_data.spo2}% (Score: {news_score.spo2_score})"
        )
        
        return self.create_notification(
            user_id=user_id,
            notification_type='news',
            trigger_type=f'news_{news_score.alert_level.lower()}',
            title=title,
            content=content,
            device_id=device_id,
            device_name=device_name,
            trigger_value=news_score.total_score,
            threshold_value=2 if news_score.alert_level == 'Orange' else 3
        )
    
    def check_environmental_alerts(self, env_data, user_id, device_id, device_name):
        """Check and send environmental alert notifications"""
        alerts = []
        
        # Temperature check
        if env_data.temp < self.env_thresholds['temperature']['min']:
            alerts.append({
                'type': 'temperature_low',
                'title': f"🌡️ Low Temperature Alert - {device_name}",
                'value': env_data.temp,
                'threshold': self.env_thresholds['temperature']['min'],
                'message': f"Temperature is {env_data.temp}°C (below {self.env_thresholds['temperature']['min']}°C)"
            })
        elif env_data.temp > self.env_thresholds['temperature']['max']:
            alerts.append({
                'type': 'temperature_high',
                'title': f"🌡️ High Temperature Alert - {device_name}",
                'value': env_data.temp,
                'threshold': self.env_thresholds['temperature']['max'],
                'message': f"Temperature is {env_data.temp}°C (above {self.env_thresholds['temperature']['max']}°C)"
            })
        
        # Humidity check
        if env_data.humidity < self.env_thresholds['humidity']['min']:
            alerts.append({
                'type': 'humidity_low',
                'title': f"💧 Low Humidity Alert - {device_name}",
                'value': env_data.humidity,
                'threshold': self.env_thresholds['humidity']['min'],
                'message': f"Humidity is {env_data.humidity}% (below {self.env_thresholds['humidity']['min']}%)"
            })
        elif env_data.humidity > self.env_thresholds['humidity']['max']:
            alerts.append({
                'type': 'humidity_high',
                'title': f"💧 High Humidity Alert - {device_name}",
                'value': env_data.humidity,
                'threshold': self.env_thresholds['humidity']['max'],
                'message': f"Humidity is {env_data.humidity}% (above {self.env_thresholds['humidity']['max']}%)"
            })
        
        # AQI check
        if env_data.aqi > self.env_thresholds['aqi']['max']:
            alerts.append({
                'type': 'aqi_poor',
                'title': f"🏭 Poor Air Quality Alert - {device_name}",
                'value': env_data.aqi,
                'threshold': self.env_thresholds['aqi']['max'],
                'message': f"Air Quality Index is {env_data.aqi} (above {self.env_thresholds['aqi']['max']})"
            })
        
        # Noise level check
        if env_data.mic > self.env_thresholds['noise']['max']:
            alerts.append({
                'type': 'noise_high',
                'title': f"🔊 High Noise Alert - {device_name}",
                'value': env_data.mic,
                'threshold': self.env_thresholds['noise']['max'],
                'message': f"Noise level is {env_data.mic}dB (above {self.env_thresholds['noise']['max']}dB)"
            })
        
        # Send notifications for each alert
        success_count = 0
        for alert in alerts:
            content = (
                f"{alert['message']}\n"
                f"Device: {device_name} ({device_id})\n"
                f"Time: {env_data.timestamp.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                f"Current Environmental Readings:\n"
                f"• Temperature: {env_data.temp}°C\n"
                f"• Humidity: {env_data.humidity}%\n"
                f"• Air Quality: {env_data.aqi} AQI\n"
                f"• Noise Level: {env_data.mic} dB"
            )
            
            if self.create_notification(
                user_id=user_id,
                notification_type='environmental',
                trigger_type=alert['type'],
                title=alert['title'],
                content=content,
                device_id=device_id,
                device_name=device_name,
                trigger_value=alert['value'],
                threshold_value=alert['threshold']
            ):
                success_count += 1
        
        return success_count > 0
    
    def acknowledge_notification(self, notification_id, user_id):
        """Mark notification as acknowledged"""
        try:
            notification = NotificationHistory.query.filter_by(
                id=notification_id, 
                user_id=user_id
            ).first()
            
            if notification:
                notification.is_acknowledged = True
                notification.acknowledged_at = datetime.now(timezone.utc)
                db.session.commit()
                return True
                
        except Exception as e:
            current_app.logger.error(f"Failed to acknowledge notification: {str(e)}")
            db.session.rollback()
        
        return False
    
    def get_notification_history(self, user_id, limit=50, notification_type=None):
        """Get user's notification history"""
        query = NotificationHistory.query.filter_by(user_id=user_id)
        
        if notification_type:
            query = query.filter_by(notification_type=notification_type)
        
        return query.order_by(NotificationHistory.created_at.desc()).limit(limit).all()
    
    def update_settings(self, user_id, settings_data):
        """Update user notification settings"""
        try:
            settings = self.get_or_create_settings(user_id)
            
            # Update settings
            if 'news_notifications_enabled' in settings_data:
                settings.news_notifications_enabled = settings_data['news_notifications_enabled']
            if 'environmental_notifications_enabled' in settings_data:
                settings.environmental_notifications_enabled = settings_data['environmental_notifications_enabled']
            if 'website_notifications_enabled' in settings_data:
                settings.website_notifications_enabled = settings_data['website_notifications_enabled']
            if 'push_notifications_enabled' in settings_data:
                settings.push_notifications_enabled = settings_data['push_notifications_enabled']
            if 'news_cooldown_minutes' in settings_data:
                settings.news_cooldown_minutes = max(1, min(1440, int(settings_data['news_cooldown_minutes'])))  # 1 min to 24 hours
            if 'environmental_cooldown_minutes' in settings_data:
                settings.environmental_cooldown_minutes = max(1, min(1440, int(settings_data['environmental_cooldown_minutes'])))
            if 'push_api_key' in settings_data:
                settings.push_api_key = settings_data['push_api_key']
            
            settings.updated_at = datetime.now(timezone.utc)
            db.session.commit()
            
            return True
            
        except Exception as e:
            current_app.logger.error(f"Failed to update notification settings: {str(e)}")
            db.session.rollback()
            return False
    
    def get_notification_stats(self, user_id):
        """Get notification statistics for user"""
        try:
            total_notifications = NotificationHistory.query.filter_by(user_id=user_id).count()
            news_notifications = NotificationHistory.query.filter_by(user_id=user_id, notification_type='news').count()
            env_notifications = NotificationHistory.query.filter_by(user_id=user_id, notification_type='environmental').count()
            acknowledged = NotificationHistory.query.filter_by(user_id=user_id, is_acknowledged=True).count()
            
            return {
                'total': total_notifications,
                'news': news_notifications,
                'environmental': env_notifications,
                'acknowledged': acknowledged,
                'unacknowledged': total_notifications - acknowledged
            }
            
        except Exception as e:
            current_app.logger.error(f"Failed to get notification stats: {str(e)}")
            return {}
    
    def send_test_notification(self, user_id, notification_type='environmental', delivery_method='website'):
        """Send a test notification with proper history recording"""
        try:
            from datetime import datetime, timezone, timedelta
            
            # Convert UTC to GMT+8 (Philippines/Singapore timezone)
            gmt8_timezone = timezone(timedelta(hours=8))
            current_time_gmt8 = datetime.now(timezone.utc).astimezone(gmt8_timezone)
            
            title = f"🧪 Test {notification_type.capitalize()} Notification"
            content = f"This is a test {notification_type} notification sent at {current_time_gmt8.strftime('%Y-%m-%d %H:%M:%S GMT+8')}."
            
            settings = self.get_or_create_settings(user_id)
            website_sent = False
            push_sent = False
            
            # Send based on delivery method
            if delivery_method == 'website' and settings.website_notifications_enabled:
                website_sent = self.send_website_notification(user_id, title, content, {'test': True})
            elif delivery_method == 'push' and settings.push_notifications_enabled:
                push_sent = self.send_push_notification(user_id, title, content)
            elif delivery_method == 'both':
                if settings.website_notifications_enabled:
                    website_sent = self.send_website_notification(user_id, title, content, {'test': True})
                if settings.push_notifications_enabled:
                    push_sent = self.send_push_notification(user_id, title, content)
            
            # Record in history
            history_record = NotificationHistory(
                user_id=user_id,
                notification_type=notification_type,
                trigger_type='test',
                title=title,
                content=content,
                website_sent=website_sent,
                push_sent=push_sent,
                device_id='test-device',
                device_name='Test Device',
                trigger_value=0,
                threshold_value=0
            )
            
            db.session.add(history_record)
            db.session.commit()
            
            return website_sent or push_sent
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Test notification failed: {str(e)}")
            return False

# Global notification handler instance
notification_handler = NotificationHandler()
