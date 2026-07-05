# Edgestream

A Django-based media server built for Ubuntu deployments with HLS conversion, responsive TV-friendly UI, search, and a conversion queue dashboard.

## Features

- Netflix-style browsing for Movies and Series
- HLS queue and conversion workflow
- Hidden-until-converted media visibility
- Search across movies and series
- `/queue/` dashboard for monitoring conversion status
- Nginx-friendly static and media serving
- Environment-driven production configuration

## Ubuntu Setup

### 1. Install system dependencies

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip ffmpeg nginx git curl
```

Optional tools for live-watching media folders:

```bash
sudo apt install -y inotify-tools
```

### 2. Clone the repository

```bash
cd /opt
sudo git clone <your-repo-url> signalyx-media-server
cd signalyx-media-server
sudo chown -R $USER:$USER .
```

### 3. Create a Python virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Configure environment variables

Use shell exports or create a `.env` file for your deployment environment.

Recommended variables:

```bash
export DJANGO_SECRET_KEY='replace-with-a-long-random-secret'
export DJANGO_DEBUG=False
export DJANGO_ALLOWED_HOSTS='localhost,127.0.0.1,your-domain.com'
export MEDIA_ROOT='/var/www/media'
export HLS_ROOT='/var/www/media/hls'
export DJANGO_SECURE_SSL_REDIRECT=True
export DJANGO_SESSION_COOKIE_SECURE=True
export DJANGO_CSRF_COOKIE_SECURE=True
export DJANGO_SECURE_HSTS_SECONDS=31536000
export DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS=True
export DJANGO_SECURE_HSTS_PRELOAD=True
```

If you use a process manager such as systemd, set these environment variables in the service file instead of exporting them manually.

### 5. Initialize the database

```bash
python manage.py migrate
```

### 6. Prepare media and static folders

```bash
sudo mkdir -p /var/www/media/movies
sudo mkdir -p /var/www/media/series
sudo mkdir -p /var/www/media/hls
mkdir -p staticfiles
```

Adjust ownership if the service user is different from your current user:

```bash
sudo chown -R $USER:$USER /var/www/media
```

### 7. Run the development server

```bash
source venv/bin/activate
python manage.py runserver 0.0.0.0:8000
```

Then open `http://127.0.0.1:8000/` in your browser.

## Daily Operation

- Place movies under `/var/www/media/movies`
- Place series episodes under `/var/www/media/series`
- The app only shows converted media once `is_converted=True`
- Search titles via the header search box or `/search/`
- Track conversion progress via `/queue/`

## Conversion Workflow

### Run conversion tasks manually

```bash
source venv/bin/activate
python manage.py scan_media
python manage.py process_conversion_queue
```

### Watch media folders automatically

```bash
source venv/bin/activate
python manage.py watch_media
```

### Recommended production worker

Use the included systemd service and script for automatic conversion:

```bash
sudo cp hls-converter.service /etc/systemd/system/
sudo cp hls_converter.sh /usr/local/bin/hls_converter.sh
sudo chmod +x /usr/local/bin/hls_converter.sh
sudo systemctl daemon-reload
sudo systemctl enable --now hls-converter.service
```

Then verify the service:

```bash
sudo systemctl status hls-converter.service
```

## Production Deployment

### 1. Collect static files

```bash
source venv/bin/activate
python manage.py collectstatic --noinput
```

### 2. Configure Gunicorn

Install Gunicorn in the virtual environment:

```bash
source venv/bin/activate
pip install gunicorn
```

Start Gunicorn for testing:

```bash
gunicorn mediaserver.wsgi:application --bind 127.0.0.1:8000
```

### 3. Configure Nginx

Use the provided config files as examples.

- `nginx_media_server.conf` — main proxy for Django and static/media handling
- `nginx-hls.conf` — HLS playlist/segment headers for proper streaming

Copy the Nginx config into `/etc/nginx/sites-available/` and create symlinks:

```bash
sudo cp nginx_media_server.conf /etc/nginx/sites-available/signalyx_media_server
sudo ln -s /etc/nginx/sites-available/signalyx_media_server /etc/nginx/sites-enabled/
```

If you want HLS served from Nginx directly, include `nginx-hls.conf` in your site config or main Nginx config.

### 4. Reload Nginx

```bash
sudo nginx -t
sudo systemctl reload nginx
```

### 5. Secure the deployment

- Ensure `DEBUG=False`
- Use a strong `DJANGO_SECRET_KEY`
- Set `DJANGO_ALLOWED_HOSTS`
- Enable HTTPS via Certbot or your certificate provider
- Ensure `DJANGO_SECURE_SSL_REDIRECT=True`
- Ensure `DJANGO_SESSION_COOKIE_SECURE=True`
- Ensure `DJANGO_CSRF_COOKIE_SECURE=True`

## Ubuntu Deployment Checklist

- [ ] Installed `python3`, `python3-venv`, `python3-pip`, `ffmpeg`, `nginx`
- [ ] Created and activated Python virtual environment
- [ ] Installed Python dependencies from `requirements.txt`
- [ ] Migrated the database
- [ ] Created `/var/www/media` and `/var/www/media/hls`
- [ ] Collected static files
- [ ] Configured Gunicorn and Nginx
- [ ] Configured `hls-converter.service`
- [ ] Verified `/search/` and `/queue/` routes
- [ ] Enabled HTTPS and secure cookies

## Configuration Notes

- `MEDIA_ROOT` defaults to `media/` in `mediaserver/settings.py`
- `HLS_ROOT` defaults to `media/hls`
- `STATIC_ROOT` is set to `staticfiles`
- `STATICFILES_DIRS` includes `library/static`

## Helpful Commands

```bash
# Activate environment
source venv/bin/activate

# Run migrations
python manage.py migrate

# Collect static files
python manage.py collectstatic --noinput

# Start dev server
python manage.py runserver 0.0.0.0:8000

# Scan media and queue conversions
python manage.py scan_media

# Process queued conversions
python manage.py process_conversion_queue

# Run watch mode for new files
python manage.py watch_media
```

## Final Note

This repository is ready for Ubuntu server deployment. The production guide above covers system packages, media folders, Gunicorn, Nginx, and the HLS conversion worker.
