# EdgeStream Deployment Guide

This guide covers deploying the entire EdgeStream ecosystem, including the Django backend media server and compiling the React Native mobile app for Android/iOS.

---

## Part 1: Backend Deployment (Django + Gunicorn + Nginx)

For production, you should not use the built-in `python manage.py runserver` command. Instead, you should use Gunicorn as the application server and Nginx as a reverse proxy to serve static media files efficiently.

### 1. Configure Production Settings
Ensure your environment variables are set correctly for production. You can use a `.env` file in the root of the project.
- `DJANGO_DEBUG=False`
- `DJANGO_SECRET_KEY='your-super-secret-key'`
- `DJANGO_SECURE_SSL_REDIRECT=True` (If using HTTPS)

### 2. Install Gunicorn
Install Gunicorn into your Python environment:
```bash
pip install gunicorn
```

### 3. Run with Gunicorn
Run the Django app using Gunicorn on port 8000:
```bash
gunicorn --workers 3 --bind 0.0.0.0:8000 mediaserver.wsgi:application
```
*Note: Run this inside a daemon or service manager like `systemd` or `supervisor` to keep it running in the background.*

### 4. Serve Media and Static Files (Nginx)
Nginx should sit in front of Gunicorn to handle static assets and media files (which are large and slow to serve via Python). 
Sample Nginx Configuration:
```nginx
server {
    listen 80;
    server_name edgestream.iceboxers.qzz.io;

    location /static/ {
        alias /path/to/edgestream/staticfiles/;
    }

    location /media/ {
        alias /path/to/edgestream/media/;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_addrs;
    }
}
```

---

## Part 2: Mobile App Deployment (Expo EAS)

The React Native mobile app (`edgestream-app`) can be packaged into an installable `.apk` or `.aab` for Android, and an `.ipa` for iOS using Expo Application Services (EAS).

### 1. Update Production URLs
Before building the app, make sure it points to your production server!
1. Open `edgestream-app/config.js`.
2. Change the `API_URL` and `BASE_URL` to point to your new live server:
```javascript
export const BASE_URL = 'https://edgestream.iceboxers.qzz.io';
export const API_URL = 'https://edgestream.iceboxers.qzz.io/api';
```

### 2. Install EAS CLI
Install the Expo EAS command-line tool globally on your system:
```bash
npm install -g eas-cli
```

### 3. Log in to Expo
Authenticate your terminal with your Expo account:
```bash
eas login
```

### 4. Build for Android (APK)
We have already configured `eas.json` to support direct `.apk` building.
Run this command to build an APK that you can drag and drop onto any Android device:
```bash
eas build -p android --profile preview
```

### 5. Build for Android (Play Store)
If you want to publish the app to the Google Play Store, you need an Android App Bundle (`.aab`):
```bash
eas build -p android --profile production
```

### 6. Build for iOS
Building for iOS requires an Apple Developer account ($99/yr). If you have one, run:
```bash
eas build -p ios
```

---

## Architecture Summary
- **Database**: SQLite (Upgrade to PostgreSQL recommended for heavy traffic).
- **Video Conversion**: FFMPEG runs synchronously or asynchronously depending on implementation. Keep `media/hls` writable.
- **Frontend App**: React Native (Expo). Uses JWT for authentication.
