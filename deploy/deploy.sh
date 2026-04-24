#!/bin/bash
# deploy.sh — ReliefAgent Data Platform deployment script
# Usage: sudo bash deploy/deploy.sh
# Prerequisites: Ubuntu 22.04+, Python 3.11+

set -euo pipefail

APP_DIR="/opt/reliefagent"
LOG_DIR="/var/log/reliefagent"
REPO_URL="https://github.com/your-org/RedAgent.git"
BRANCH="main"

echo "=== ReliefAgent Deployment ==="

# 1. Install system dependencies
echo "[1/7] Installing system packages..."
apt-get update -qq
apt-get install -y python3 python3-venv python3-pip nginx certbot python3-certbot-nginx

# 2. Clone/update the repository
if [ -d "$APP_DIR" ]; then
    echo "[2/7] Updating repository..."
    cd "$APP_DIR"
    git fetch origin
    git reset --hard "origin/$BRANCH"
else
    echo "[2/7] Cloning repository..."
    git clone -b "$BRANCH" "$REPO_URL" "$APP_DIR"
    cd "$APP_DIR"
fi

# 3. Create virtual environment and install dependencies
echo "[3/7] Installing Python dependencies..."
python3 -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install -r requirements.txt

# 4. Create .env from example if not exists
if [ ! -f .env ]; then
    echo "[4/7] Creating .env from .env.example (EDIT THIS FILE!)"
    cp .env.example .env
    echo "⚠  IMPORTANT: Edit $APP_DIR/.env before starting the service!"
    echo "   Required: OLLAMA_API_KEY, FIREBASE_API_KEY, ADMIN_UIDS, CORS_ORIGINS"
else
    echo "[4/7] .env already exists, skipping..."
fi

# 5. Create data directories
echo "[5/7] Creating data directories..."
mkdir -p reliefweb_downloads reliefweb_chroma output
mkdir -p "$LOG_DIR"
chown -R www-data:www-data "$APP_DIR" "$LOG_DIR"

# 6. Install systemd service
echo "[6/7] Installing systemd service..."
cp deploy/reliefagent.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable reliefagent

# 7. Install nginx config (placeholder — update domain first)
echo "[7/7] Nginx config available at deploy/nginx.conf"
echo "   Copy to /etc/nginx/sites-available/ and update domain, then:"
echo "   sudo ln -s /etc/nginx/sites-available/reliefagent /etc/nginx/sites-enabled/"
echo "   sudo certbot --nginx -d yourdomain.com"

echo ""
echo "=== Next Steps ==="
echo "1. Edit $APP_DIR/.env — set OLLAMA_API_KEY, ADMIN_UIDS, CORS_ORIGINS"
echo "2. Place firebase-service-account.json in $APP_DIR/"
echo "3. Update deploy/nginx.conf with your domain, copy to /etc/nginx/sites-available/"
echo "4. sudo nginx -t && sudo systemctl reload nginx"
echo "5. sudo systemctl start reliefagent"
echo "6. sudo systemctl status reliefagent"
echo ""
echo "Logs: tail -f $LOG_DIR/error.log"