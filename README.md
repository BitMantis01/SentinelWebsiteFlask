# 🛡️ SENTINEL - AI-Powered Neonatal Monitoring System

[![Python](https://img.shields.io/badge/Python-3.9%2B-blue.svg)](https://www.python.org/)
[![Framework](https://img.shields.io/badge/Framework-Flask%203.x-green.svg)](https://flask.palletsprojects.com/)
[![WebSockets](https://img.shields.io/badge/RealTime-Flask--SocketIO-orange.svg)](https://flask-socketio.readthedocs.io/)
[![Machine Learning](https://img.shields.io/badge/ML-statsmodels%20%7C%20scikit--learn-blueviolet.svg)](https://www.statsmodels.org/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**SENTINEL** is an enterprise-grade, real-time medical IoT and AI-driven monitoring web platform engineered for neonatal intensive care environments and clinical home care. The platform continuously ingests physiological signals from wearable footwear monitors, environmental hubs, and camera feeds to provide early warning clinical risk scoring (NEWS), time-series vital sign forecasting via ARIMA models, and intelligent alerting.

---

## 🌟 Key Features

### 🩺 Real-Time Physiological Vitals Tracking
- **Continuous Monitoring**: Ingests $SpO_2$, Heart Rate (BPM), Body Temperature, and infant movement metrics.
- **WebSocket Streaming**: Instant bi-directional dashboard updates via Flask-SocketIO.
- **Interactive Visualizations**: High-performance historical trend charts powered by Chart.js.

### 📈 ARIMA Vital Sign Predictive Engine
- **Medical-Grade Forecasting**: Utilizes AutoRegressive Integrated Moving Average (ARIMA) models to forecast vital trends.
- **Confidence Intervals & Error Metrics**: Calculates Mean Absolute Error (MAE), Root Mean Squared Error (RMSE), and $R^2$ scores to ensure model reliability.
- **Stationarity & Validation**: Automated Augmented Dickey-Fuller (ADF) tests and medical range constraints ($SpO_2$: 80-100%, HR: 60-200 BPM, Temp: 32-41°C).

### 🚨 National Early Warning Score (NEWS) System
- **Clinical Risk Categorization**: Calculates standardized NEWS scores for neonatal health assessment.
- **Multi-Tier Alerting**: Classifies status into **Green** (Normal), **Yellow** (Low Risk), **Orange** (Medium Risk), and **Red** (High Risk / Emergency).
- **Automated Cooldowns**: Prevents alert fatigue with configurable notification cooldown windows.

### 🌡️ Environmental & Acoustic Tracking (EnvHub)
- **Air Quality & Atmosphere**: Tracks Air Quality Index (AQI), ambient room temperature, and humidity.
- **Sound Level Monitoring**: Detects decibel thresholds and room acoustic levels.
- **Infant Cry Detection**: Integrates camera and audio analytics for infant distress signals.

### 🔒 Defense-in-Depth Security Framework
- **Anti-Brute Force Protection**: Account lockouts after consecutive failed login attempts.
- **Cloudflare Turnstile**: Modern, non-intrusive CAPTCHA challenge on authentication routes.
- **Rate Limiting**: Granular route-based rate limits via `Flask-Limiter`.
- **Security Headers**: HTTP security headers configured with `Flask-Talisman` (CSP, HSTS, X-Frame-Options, X-Content-Type-Options).
- **Remote Centralized Logging**: Secure audit trail dispatches security events and application logs to a remote logging service (`logs.bitmantis.xyz`).

---

## 🏗️ Architecture & Technology Stack

| Layer | Technology |
| :--- | :--- |
| **Backend Framework** | Python 3.9+, Flask, Flask-SQLAlchemy |
| **Real-time Engine** | Flask-SocketIO, Eventlet |
| **Database** | SQLite (Default for Dev), PostgreSQL/MySQL (Production Compatible) |
| **Data Science & ML** | Statsmodels (ARIMA), Scikit-Learn, Pandas, NumPy |
| **Frontend** | HTML5, JavaScript (ES6+), Tailwind CSS, Chart.js |
| **Security & Auth** | Flask-Login, Flask-Bcrypt, Flask-WTF (CSRF), Flask-Talisman |

---

## 📁 Repository Structure

```
SentinelWebsiteFlask/
├── app/
│   ├── __init__.py           # Application factory, extensions setup & security headers
│   ├── models.py             # SQLAlchemy models (User, Vitals, Predictions, Notifications)
│   ├── routes.py             # Application blueprints, API routes & authentication
│   ├── prediction_engine.py  # Advanced ARIMA time-series prediction logic
│   ├── notification.py       # Notification handler & push alert dispatcher
│   ├── remote_logger.py      # Centralized remote security & operational logger
│   ├── turnstile.py          # Cloudflare Turnstile verification helper
│   ├── chart_handler.py      # Data formatting utilities for frontend charts
│   ├── static/               # Assets (CSS, JS, icons, branding images)
│   └── templates/            # HTML Jinja2 templates & dashboard views
├── logs/                     # Application & security event logs (Git ignored)
├── instance/                 # SQLite database storage (Git ignored)
├── config.py                 # Core configuration class & environment mapping
├── main.py                   # Development server entry point (Port 5000)
├── app.py                    # Alternative entry point (Port 1904)
├── requirements.txt          # Python dependencies
├── .env.example              # Environment configuration template
├── robots.txt                # Search engine crawler policies
└── sitemap.xml               # Web index sitemap
```

---

## 🚀 Quick Start Guide

### Prerequisites
- **Python 3.9+** installed on your system.
- `pip` and `virtualenv`.

### 1. Clone the Repository
```bash
git clone https://github.com/your-username/SentinelWebsiteFlask.git
cd SentinelWebsiteFlask
```

### 2. Set Up Virtual Environment
```bash
# On Linux/macOS:
python3 -m venv venv
source venv/bin/activate

# On Windows (PowerShell):
python -m venv venv
.\venv\Scripts\Activate.ps1
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables
Copy `.env.example` to `.env` and update the required values:
```bash
cp .env.example .env
```

Generate a secure secret key for production:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### 5. Run the Application
Launch the server:
```bash
python main.py
```
The application will start on `http://127.0.0.1:5000` with WebSocket support enabled.

---

## 🔌 API Endpoint Summary

### Authentication Routes
- `POST /login` - User authentication (Rate limited, Cloudflare Turnstile protected)
- `POST /register` - New user account creation
- `GET /logout` - Terminates user session

### Dashboard Views
- `GET /dashboard/summary` - Centralized monitoring dashboard
- `GET /dashboard/vitals` - Detailed physiological data view
- `GET /dashboard/environment` - Ambient air quality & sound metrics
- `GET /dashboard/predictions` - ARIMA vital forecasting analytics
- `GET /dashboard/news` - Clinical NEWS score history & alerts

### IoT Ingestion & Data Endpoints
- `POST /api/footwear/data` - Endpoint for wearable footwear monitors
- `POST /api/envhub/data` - Endpoint for environmental hub sensor data
- `GET /api/vitals/latest` - Fetch latest vital sign readings (JSON)
- `GET /api/predictions/generate` - Trigger real-time ARIMA prediction model

---

## 🔐 Security & Compliance

- **Environment Isolation**: All credentials and API keys are strictly loaded via `.env`.
- **Database Privacy**: Production databases should be deployed outside root directories or managed via PostgreSQL/MySQL services.
- **CSRF & XSS Guard**: Standard Flask-WTF tokens enforced across non-GET methods with HTTP-only cookies.

---

## 👥 Researchers & Team

### Student Researchers
- **John Reyn Santino** — Researcher
- **Leynard Jomari** — Researcher
- **Mark Lester** — Researcher
- **Uriah Mishael** — Researcher

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
