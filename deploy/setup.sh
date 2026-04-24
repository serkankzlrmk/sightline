#!/bin/bash
# ============================================================
# setup.sh — ReliefAgent Production Setup (Oracle Cloud ARM)
# Run as root on a fresh Ubuntu 24.04 VM:
#   sudo bash deploy/setup.sh
# ============================================================

set -euo pipefail

APP_DIR="/opt/reliefagent"
APP_USER="reliefagent"
LOG_DIR="/var/log/reliefagent"
REPO_URL="https://github.com/serkankzlrmk/RedAgent.git"
BRANCH="main"

echo "============================================================"
echo "  ReliefAgent Data Platform — Production Setup"
echo "============================================================"
echo ""

# ── 1. System packages ──────────────────────────────────────────
echo "[1/9] Installing system packages..."
apt-get update -qq
apt-get install -y \
    python3 python3-venv python3-pip \
    nginx certbot python3-certbot-nginx \
    git curl wget \
    ufw

# ── 2. Firewall ─────────────────────────────────────────────────
echo "[2/9] Configuring firewall..."
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

# Oracle Cloud has iptables blocking by default — flush them
iptables -P INPUT ACCEPT
iptables -P FORWARD ACCEPT
iptables -P OUTPUT ACCEPT
iptables -F
# Re-apply essential rules
iptables -A INPUT -i lo -j ACCEPT
iptables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -A INPUT -p tcp --dport 22 -j ACCEPT
iptables -A INPUT -p tcp --dport 80 -j ACCEPT
iptables -A INPUT -p tcp --dport 443 -j ACCEPT
iptables -A INPUT -j DROP
# Persist iptables rules
apt-get install -y iptables-persistent
echo iptables-persistent iptables-persistent/autosave_v4 boolean true | debconf-set-selections
echo iptables-persistent iptables-persistent/autosave_v6 boolean true | debconf-set-selections
netfilter-persistent save

# ── 3. Create app user ──────────────────────────────────────────
echo "[3/9] Creating app user..."
if ! id "$APP_USER" &>/dev/null; then
    useradd -r -s /bin/false -d "$APP_DIR" "$APP_USER"
fi

# ── 4. Clone repository ─────────────────────────────────────────
echo "[4/9] Cloning repository..."
if [ -d "$APP_DIR" ]; then
    cd "$APP_DIR"
    git fetch origin
    git reset --hard "origin/$BRANCH"
else
    git clone -b "$BRANCH" "$REPO_URL" "$APP_DIR"
    cd "$APP_DIR"
fi

# ── 5. Python virtual environment ───────────────────────────────
echo "[5/9] Installing Python dependencies..."
python3 -m venv venv
venv/bin/pip install --upgrade pip setuptools wheel
venv/bin/pip install -r requirements.txt
venv/bin/pip install gunicorn

# ── 6. Data directories ─────────────────────────────────────────
echo "[6/9] Creating data directories..."
mkdir -p "$APP_DIR/reliefweb_downloads"
mkdir -p "$APP_DIR/reliefweb_chroma"
mkdir -p "$APP_DIR/output"
mkdir -p "$LOG_DIR"

# ── 7. Environment file ─────────────────────────────────────────
echo "[7/9] Setting up .env..."
if [ ! -f "$APP_DIR/.env" ]; then
    cp "$APP_DIR/.env.example" "$APP_DIR/.env"
    echo ""
    echo "  ⚠  IMPORTANT: Edit $APP_DIR/.env before starting!"
    echo "     Required values:"
    echo "     - OLLAMA_API_KEY=<your-ollama-cloud-key>"
    echo "     - ADMIN_UIDS=<your-firebase-uid>"
    echo "     - CORS_ORIGINS=https://your-ip-or-domain"
    echo "     - SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
    echo ""
    echo "  Also place firebase-service-account.json in $APP_DIR/"
    echo ""
    read -p "  Press Enter after you've configured .env and added service-account JSON..."
else
    echo "  .env already exists, skipping..."
fi

# ── 8. Systemd service ──────────────────────────────────────────
echo "[8/9] Installing systemd service..."
cp "$APP_DIR/deploy/reliefagent.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable reliefagent

# ── 9. Nginx ────────────────────────────────────────────────────
echo "[9/9] Configuring Nginx..."
cp "$APP_DIR/deploy/nginx.conf" /etc/nginx/sites-available/reliefagent
rm -f /etc/nginx/sites-enabled/default
ln -sf /etc/nginx/sites-available/reliefagent /etc/nginx/sites-enabled/
nginx -t
systemctl enable nginx

# ── Set permissions ─────────────────────────────────────────────
chown -R "$APP_USER:$APP_USER" "$APP_DIR"
chown -R "$APP_USER:$APP_USER" "$LOG_DIR"
chmod 600 "$APP_DIR/.env"
chmod 600 "$APP_DIR/firebase-service-account.json" 2>/dev/null || true

echo ""
echo "============================================================"
echo "  Setup Complete!"
echo "============================================================"
echo ""
echo "  Next steps:"
echo "  1. Edit $APP_DIR/.env (OLLAMA_API_KEY, ADMIN_UIDS, etc.)"
echo "  2. Place firebase-service-account.json in $APP_DIR/"
echo "  3. Update /etc/nginx/sites-available/reliefagent with your IP/domain"
echo "  4. sudo systemctl start reliefagent"
echo "  5. sudo systemctl reload nginx"
echo "  6. Test: curl http://localhost/api/health"
echo ""
echo "  For HTTPS (recommended):"
echo "  sudo certbot --nginx -d yourdomain.com"
echo ""
echo "  Useful commands:"
echo "  sudo systemctl status reliefagent   # check status"
echo "  sudo journalctl -u reliefagent -f   # live logs"
echo "  tail -f $LOG_DIR/error.log          # gunicorn logs"
echo "  sudo systemctl restart reliefagent  # restart app"
echo "  cd $APP_DIR && sudo -u reliefagent git pull origin main && sudo systemctl restart reliefagent  # update"
echo ""