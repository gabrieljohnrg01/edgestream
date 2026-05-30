# EdgeStream Deployment Guide (Debian / Ubuntu Linux)

This guide walks you through deploying EdgeStream for a production environment on a Debian-based Linux server. We will use **Gunicorn** as the production WSGI server, **WhiteNoise** for serving static files, and **systemd** to run everything seamlessly in the background.

## Prerequisites

1. **Update and Install System Dependencies**:
   SSH into your Debian server and run:
   ```bash
   sudo apt update
   sudo apt upgrade -y
   sudo apt install -y python3 python3-venv python3-pip ffmpeg git
   ```
2. **Database**: The project uses SQLite by default, which is perfectly fine for personal media servers. 

---

## Step 1: Prepare the Environment

1. **Move the Project to the Server**
   Clone or copy your EdgeStream project folder to a standard location on your server, such as `/opt/edgestream`:
   ```bash
   sudo mkdir -p /opt/edgestream
   sudo chown -R $USER:$USER /opt/edgestream
   # (Copy your files into /opt/edgestream here)
   cd /opt/edgestream
   ```

2. **Create a Virtual Environment**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

3. **Install Dependencies**
   First, let's swap `waitress` for `gunicorn`, which is the industry standard for Linux deployments.
   ```bash
   # Remove waitress from requirements.txt if it's there
   sed -i '/waitress/d' requirements.txt
   
   # Add gunicorn
   echo "gunicorn>=21.2.0" >> requirements.txt
   
   # Install everything
   pip install -r requirements.txt
   ```

---

## Step 2: Configure Environment Variables

Do NOT run the production server with `DEBUG=True`. 

1. Copy `.env.example` and rename it to `.env`:
   ```bash
   cp .env.example .env
   ```
2. Open `.env` (using `nano .env`) and set the following:
   - **`DJANGO_SECRET_KEY`**: Generate a long, random string. Do not share this.
   - **`DJANGO_DEBUG`**: Set to `False`.
   - **`DJANGO_ALLOWED_HOSTS`**: Add your server's IP address or domain name (e.g., `192.168.1.50, mydomain.com`).

---

## Step 3: Prepare Django

Run the following commands to finalize the database and static files:

1. **Apply Migrations**
   ```bash
   python manage.py migrate
   ```

2. **Collect Static Files**
   This command gathers all CSS, JS, and image files into a single `staticfiles/` directory so WhiteNoise can compress and cache them:
   ```bash
   python manage.py collectstatic --noinput
   ```

3. **Create a Superuser** (If you haven't already)
   ```bash
   python manage.py createsuperuser
   ```

---

## Step 4: Run as Systemd Services (Background)

To ensure EdgeStream runs automatically when the server boots and stays running in the background, we will create two `systemd` services: one for the Web Server, and one for the Background Video Converter.

### 1. The Web Server Service
Create a new service file:
```bash
sudo nano /etc/systemd/system/edgestream-web.service
```
Paste the following configuration (adjust `User=` to your actual linux username, e.g., `root` or `debian`):
```ini
[Unit]
Description=EdgeStream Web Server
After=network.target

[Service]
User=root
Group=root
WorkingDirectory=/opt/edgestream
Environment="PATH=/opt/edgestream/venv/bin"
ExecStart=/opt/edgestream/venv/bin/gunicorn mediaserver.wsgi:application --bind 0.0.0.0:8000 --workers 3
Restart=always

[Install]
WantedBy=multi-user.target
```

### 2. The Background Conversion Worker
Create a second service file:
```bash
sudo nano /etc/systemd/system/edgestream-worker.service
```
Paste the following configuration:
```ini
[Unit]
Description=EdgeStream Video Conversion Worker
After=network.target

[Service]
User=root
Group=root
WorkingDirectory=/opt/edgestream
Environment="PATH=/opt/edgestream/venv/bin"
# A bash loop that continuously processes the queue without terminating
ExecStart=/bin/bash -c 'while true; do /opt/edgestream/venv/bin/python manage.py process_conversion_queue --limit 10; sleep 10; done'
Restart=always

[Install]
WantedBy=multi-user.target
```

### 3. Enable and Start the Services

Now, reload the systemd daemon so it registers your new files, and start them up!

```bash
sudo systemctl daemon-reload

sudo systemctl enable edgestream-web
sudo systemctl start edgestream-web

sudo systemctl enable edgestream-worker
sudo systemctl start edgestream-worker
```

You can check their status at any time using:
```bash
sudo systemctl status edgestream-web
sudo systemctl status edgestream-worker
```

---

## Congratulations!
Your EdgeStream production deployment is complete. It is now permanently running in the background on port `8000`. You can access it from other devices on your network using `http://YOUR_SERVER_IP:8000`. 

*(Optional: For a fully professional setup, you can install NGINX to reverse-proxy port 80 to port 8000, and secure it using Let's Encrypt SSL!)*
