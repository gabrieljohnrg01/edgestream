# EdgeStream Deployment Guide (Multi-Project Server)

Since you are hosting EdgeStream on a Debian server *alongside another project*, we need to ensure they don't clash. We will achieve this by giving EdgeStream its own dedicated internal port (e.g., `8001`) and using NGINX's `server_name` directive to route traffic correctly based on the subdomain requested by your Cloudflare Tunnel.

## Architectural Overview
1. **Cloudflare Tunnel**: You configure your tunnel so that your EdgeStream domain (e.g., `stream.yourdomain.com`) routes to `http://localhost:80`.
2. **NGINX**: Listens on port 80. When it sees traffic specifically for `stream.yourdomain.com`, it intercepts the media files directly, and passes the web traffic to Gunicorn on port `8001`.
3. **Gunicorn**: Runs EdgeStream entirely on port `8001` to avoid conflicting with your other project (which might be using `8000`).

---

## Step 1: Set Up the Project

Assuming your code is in `/home/gab/edgestream`:
```bash
cd /home/gab/edgestream
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**Configure `.env`**:
```bash
cp .env.example .env
nano .env
```
- `DJANGO_SECRET_KEY`: Set to a secure random string.
- `DJANGO_DEBUG`: Set to `False`.
- `DJANGO_ALLOWED_HOSTS`: Set to your specific Cloudflare domain (e.g., `stream.yourdomain.com`).

**Prepare Database and Static Files**:
```bash
python manage.py migrate
python manage.py collectstatic --noinput
```

---

## Step 2: Configure NGINX for Coexistence

Create a dedicated NGINX configuration file for EdgeStream:
```bash
sudo nano /etc/nginx/sites-available/edgestream
```

Paste the following, making sure to replace `stream.yourdomain.com` with your actual domain:
```nginx
server {
    listen 80;
    
    # CRITICAL: This ensures NGINX only routes traffic here if the tunnel asks for this specific domain!
    server_name stream.yourdomain.com; 

    # 1. Serve heavy media/HLS files directly bypassing Django
    location /media/ {
        alias /home/gab/edgestream/media/;
        add_header Accept-Ranges bytes;
    }

    location /hls/ {
        alias /home/gab/edgestream/media/hls/;
        add_header Cache-Control "public, max-age=31536000, immutable";
        add_header Access-Control-Allow-Origin *;
        types {
            application/vnd.apple.mpegurl m3u8;
            video/mp2t ts;
        }
    }

    # 2. Proxy web traffic to EdgeStream's unique port (8001)
    location / {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Enable the configuration and reload NGINX:
```bash
sudo ln -s /etc/nginx/sites-available/edgestream /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

---

## Step 3: Run EdgeStream as Systemd Services

We need to bind Gunicorn to port `8001` so it doesn't break your other project.

1. **Gunicorn Web Server**:
   ```bash
   sudo nano /etc/systemd/system/edgestream-web.service
   ```
   ```ini
   [Unit]
   Description=EdgeStream Gunicorn Server
   After=network.target

   [Service]
   User=root
   Group=root
   WorkingDirectory=/home/gab/edgestream
   Environment="PATH=/home/gab/edgestream/venv/bin"
   # Notice we are binding to 8001 here!
   ExecStart=/home/gab/edgestream/venv/bin/gunicorn mediaserver.wsgi:application --bind 127.0.0.1:8001 --workers 3
   Restart=always

   [Install]
   WantedBy=multi-user.target
   ```

2. **Background Video Converter Worker**:
   ```bash
   sudo nano /etc/systemd/system/edgestream-worker.service
   ```
   ```ini
   [Unit]
   Description=EdgeStream Background Worker
   After=network.target

   [Service]
   User=root
   WorkingDirectory=/home/gab/edgestream
   Environment="PATH=/home/gab/edgestream/venv/bin"
   # This loop automatically detects new files (scan_media) and then converts them!
   ExecStart=/bin/bash -c 'while true; do /home/gab/edgestream/venv/bin/python manage.py scan_media; /home/gab/edgestream/venv/bin/python manage.py process_conversion_queue --limit 10; sleep 30; done'
   Restart=always

   [Install]
   WantedBy=multi-user.target
   ```

3. **Start Both Services**:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now edgestream-web
   sudo systemctl enable --now edgestream-worker
   ```

---

## Step 4: Configure Cloudflare Tunnel

In your Cloudflare Zero Trust Dashboard:
1. Go to your active Tunnel.
2. Under the **Public Hostname** tab, add a new hostname (e.g., `stream.yourdomain.com`).
3. Set the **Service** to: `http://localhost:80`

**How it works**:
When someone visits `stream.yourdomain.com`, Cloudflare securely hits NGINX on port 80. NGINX reads the `server_name` block and realizes the request is for EdgeStream. It then serves the video chunks directly or passes the web traffic to Gunicorn running safely on port 8001, leaving your other project completely untouched!
