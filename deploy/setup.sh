#!/bin/bash
# ============================================================
# setup.sh — ReliefAgent Production Setup (Oracle Cloud)
#
# Run as root on a fresh Oracle Linux 9 VM:
#   sudo bash deploy/setup.sh
#   sudo bash deploy/setup.sh --non-interactive
#   sudo bash deploy/setup.sh --env-file /path/to/.env
#   sudo bash deploy/setup.sh --skip-iptables-flush
#
# Creates the symlink-based release directory structure:
#   /opt/reliefagent/
#   ├── current → releases/YYYYMMDD_HHMMSS   (symlink)
#   ├── releases/                             (timestamped deploys)
#   ├── data/                                 (shared persistent data)
#   └── backups/
# ============================================================

set -euo pipefail

# ── Parse arguments ──────────────────────────────────────────────
NON_INTERACTIVE=false
ENV_FILE=""
SKIP_IPTABLES=false
BRANCH="main"

for arg in "$@"; do
    case "$arg" in
        --non-interactive) NON_INTERACTIVE=true ;;
        --env-file=*) ENV_FILE="${arg#--env-file=}" ;;
        --skip-iptables-flush) SKIP_IPTABLES=true ;;
        --branch=*) BRANCH="${arg#--branch=}" ;;
    esac
done

APP_DIR="/opt/reliefagent"
APP_USER="reliefagent"
DATA_DIR="$APP_DIR/data"
RELEASES_DIR="$APP_DIR/releases"
LOG_DIR="/var/log/reliefagent"
REPO_URL="https://github.com/serkankzlrmk/RedAgent.git"

echo "============================================================"
echo "  ReliefAgent Data Platform — Production Setup"
echo "  Branch: $BRANCH"
echo "============================================================"
echo ""

# ── 1. System packages ──────────────────────────────────────────
echo "[1/10] Installing system packages..."

# Detect package manager (Oracle Linux/RHEL uses dnf, Ubuntu uses apt)
if command -v dnf &>/dev/null; then
    PKG_MGR="dnf"
    dnf update -y -q
    dnf install -y \
        python3 python3-pip \
        nginx certbot python3-certbot-nginx \
        git curl wget sqlite \
        firewalld iptables-services
elif command -v apt-get &>/dev/null; then
    PKG_MGR="apt"
    apt-get update -qq
    apt-get install -y \
        python3 python3-venv python3-pip \
        nginx certbot python3-certbot-nginx \
        git curl wget sqlite3 \
        ufw iptables-persistent
else
    echo "ERROR: Unsupported package manager. Use Oracle Linux 9 or Ubuntu 24.04."
    exit 1
fi

# ── 2. Firewall ─────────────────────────────────────────────────
echo "[2/10] Configuring firewall..."

if [ "$PKG_MGR" = "dnf" ]; then
    # Oracle Linux / RHEL — use firewalld
    systemctl enable --now firewalld
    firewall-cmd --permanent --add-service=ssh
    firewall-cmd --permanent --add-service=http
    firewall-cmd --permanent --add-service=https
    firewall-cmd --reload
else
    # Ubuntu — use ufw
    ufw --force reset
    ufw default deny incoming
    ufw default allow outgoing
    ufw allow 22/tcp
    ufw allow 80/tcp
    ufw allow 443/tcp
    ufw --force enable
fi

if [ "$SKIP_IPTABLES" = false ]; then
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
    if [ "$PKG_MGR" = "dnf" ]; then
        service iptables save
    else
        apt-get install -y iptables-persistent
        echo iptables-persistent iptables-persistent/autosave_v4 boolean true | debconf-set-selections
        echo iptables-persistent iptables-persistent/autosave_v6 boolean true | debconf-set-selections
        netfilter-persistent save
    fi
else
    echo "  Skipping iptables flush (--skip-iptables-flush)"
fi

# ── 3. Create app user ──────────────────────────────────────────
echo "[3/10] Creating app user..."
if ! id "$APP_USER" &>/dev/null; then
    useradd -r -s /bin/false -d "$APP_DIR" "$APP_USER"
fi

# ── 4. Create directory structure ───────────────────────────────
echo "[4/10] Creating directory structure..."
mkdir -p "$APP_DIR"
mkdir -p "$DATA_DIR"
mkdir -p "$RELEASES_DIR"
mkdir -p "$APP_DIR/backups"
mkdir -p "$DATA_DIR/reliefweb_chroma"
mkdir -p "$DATA_DIR/output"
mkdir -p "$LOG_DIR"

# ── 5. Clone repository (first release) ─────────────────────────
echo "[5/10] Cloning repository..."
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
FIRST_RELEASE="$RELEASES_DIR/$TIMESTAMP"

if [ -d "$FIRST_RELEASE" ]; then
    echo "  Release $TIMESTAMP already exists, pulling updates..."
    cd "$FIRST_RELEASE"
    git fetch origin
    git reset --hard "origin/$BRANCH"
else
    git clone -b "$BRANCH" "$REPO_URL" "$FIRST_RELEASE"
    cd "$FIRST_RELEASE"
fi

# Record release info
GIT_SHA=$(git rev-parse HEAD)
cat > "$FIRST_RELEASE/RELEASE_INFO" <<EOF
TIMESTAMP=$TIMESTAMP
GIT_SHA=$GIT_SHA
BRANCH=$BRANCH
DEPLOYER=$(whoami)
DEPLOY_DATE=$(date -Iseconds)
EOF

# ── 6. Python virtual environment ───────────────────────────────
echo "[6/10] Installing Python dependencies..."
cd "$FIRST_RELEASE"

# Oracle Linux 9 may not have venv module — install if missing
if ! python3 -c "import venv" &>/dev/null; then
    if [ "$PKG_MGR" = "dnf" ]; then
        dnf install -y python3-venv
    fi
fi

python3 -m venv venv
venv/bin/pip install --upgrade pip setuptools wheel
venv/bin/pip install -r requirements.txt
venv/bin/pip install gunicorn

# ── 7. Environment file ─────────────────────────────────────────
echo "[7/10] Setting up .env..."

if [ -n "$ENV_FILE" ] && [ -f "$ENV_FILE" ]; then
    # Use provided env file
    cp "$ENV_FILE" "$DATA_DIR/.env"
    echo "  ✓ Copied .env from $ENV_FILE"
elif [ ! -f "$DATA_DIR/.env" ]; then
    # Create from template
    cp "$FIRST_RELEASE/.env.example" "$DATA_DIR/.env"

    # Generate a random secret key
    SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')
    sed -i "s/^SECRET_KEY=.*/SECRET_KEY=$SECRET_KEY/" "$DATA_DIR/.env" 2>/dev/null || true

    echo ""
    echo "  ⚠  IMPORTANT: Edit $DATA_DIR/.env before starting!"
    echo "     Required values:"
    echo "     - LLM_PROVIDER=openrouter"
    echo "     - OPENROUTER_API_KEY=<your-openrouter-key>"
    echo "     - ACTIVE_MODEL=google/gemini-2.5-flash"
    echo "     - ADMIN_UIDS=<your-firebase-uid>"
    echo "     - RELIEFWEB_APPNAME=<your-approved-appname>"
    echo "     - CORS_ORIGINS=https://your-ip-or-domain"
    echo "     - SECRET_KEY=$SECRET_KEY"
    echo "     - SERVER_PORT=5001"
    echo ""
    echo "  Also place firebase-service-account.json in $DATA_DIR/"
    echo ""

    if [ "$NON_INTERACTIVE" = false ]; then
        read -p "  Press Enter after you've configured .env and added service-account JSON..." -r
    else
        echo "  (--non-interactive mode: continuing without .env configuration)"
        echo "  ⚠  You MUST configure .env before starting the service!"
    fi
else
    echo "  .env already exists in $DATA_DIR/, skipping..."
fi

# ── 8. Link shared data into first release ──────────────────────
echo "[8/10] Linking shared data..."

# Symlink .env
ln -sf "$DATA_DIR/.env" "$FIRST_RELEASE/.env"

# Symlink firebase service account
if [ -f "$DATA_DIR/firebase-service-account.json" ]; then
    ln -sf "$DATA_DIR/firebase-service-account.json" "$FIRST_RELEASE/firebase-service-account.json"
fi

# Symlink databases (may not exist yet — that's OK)
ln -sf "$DATA_DIR/reliefweb.db" "$FIRST_RELEASE/reliefweb.db" 2>/dev/null || true
ln -sf "$DATA_DIR/chats.db" "$FIRST_RELEASE/chats.db" 2>/dev/null || true

# Symlink data directories
ln -sfn "$DATA_DIR/reliefweb_chroma" "$FIRST_RELEASE/reliefweb_chroma"
ln -sfn "$DATA_DIR/output" "$FIRST_RELEASE/output"

# ── 9. Set current symlink + systemd service ────────────────────
echo "[9/10] Setting up current symlink and systemd service..."

# Point current to first release
ln -sfn "$FIRST_RELEASE" "$APP_DIR/current"

# Install systemd service
cp "$FIRST_RELEASE/deploy/reliefagent.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable reliefagent

# ── 10. Nginx ───────────────────────────────────────────────────
echo "[10/10] Configuring Nginx..."

if [ "$PKG_MGR" = "dnf" ]; then
    # Oracle Linux / RHEL — nginx uses conf.d/ not sites-available/
    cp "$FIRST_RELEASE/deploy/nginx.conf" /etc/nginx/conf.d/reliefagent.conf
    # Remove default server block if it conflicts
    if [ -f /etc/nginx/nginx.conf ] && grep -q "server {" /etc/nginx/nginx.conf; then
        # Comment out the default server block in nginx.conf to avoid conflict
        sed -i '/^server {/,/^}/s/^/#/' /etc/nginx/nginx.conf 2>/dev/null || true
    fi
else
    # Ubuntu — use sites-available/sites-enabled
    cp "$FIRST_RELEASE/deploy/nginx.conf" /etc/nginx/sites-available/reliefagent
    rm -f /etc/nginx/sites-enabled/default
    ln -sf /etc/nginx/sites-available/reliefagent /etc/nginx/sites-enabled/
fi

nginx -t
systemctl enable nginx

# ── Set permissions ─────────────────────────────────────────────
chown -R "$APP_USER:$APP_USER" "$APP_DIR"
chown -R "$APP_USER:$APP_USER" "$LOG_DIR"
chmod 600 "$DATA_DIR/.env" 2>/dev/null || true
chmod 600 "$DATA_DIR/firebase-service-account.json" 2>/dev/null || true

# ── Validate .env ──────────────────────────────────────────────
echo ""
echo "Validating .env..."
ENV_VALID=true
REQUIRED_VARS=("LLM_PROVIDER" "OPENROUTER_API_KEY" "ACTIVE_MODEL" "ADMIN_UIDS" "RELIEFWEB_APPNAME" "SERVER_PORT" "SECRET_KEY")

for var in "${REQUIRED_VARS[@]}"; do
    VALUE=$(grep -E "^${var}=" "$DATA_DIR/.env" 2>/dev/null | cut -d= -f2- | tr -d '"' | tr -d "'")
    if [ -z "$VALUE" ] || echo "$VALUE" | grep -qiE 'your-|<.*>|placeholder|change-me'; then
        echo "  ✗ $var is not configured"
        ENV_VALID=false
    else
        echo "  ✓ $var is set"
    fi
done

if [ ! -f "$DATA_DIR/firebase-service-account.json" ]; then
    echo "  ✗ firebase-service-account.json not found in $DATA_DIR/"
    ENV_VALID=false
else
    echo "  ✓ firebase-service-account.json found"
fi

# ── Summary ─────────────────────────────────────────────────────
echo ""
echo "============================================================"
echo "  Setup Complete!"
echo "============================================================"
echo ""
echo "  Directory structure:"
echo "    $APP_DIR/current → $TIMESTAMP"
echo "    $APP_DIR/releases/$TIMESTAMP/"
echo "    $APP_DIR/data/  (.env, DBs, ChromaDB)"
echo ""

if [ "$ENV_VALID" = false ]; then
    echo "  ⚠  .env is not fully configured!"
    echo "  Edit $DATA_DIR/.env and add firebase-service-account.json"
    echo "  Then start the service:"
    echo ""
else
    echo "  .env is configured ✓"
    echo ""
fi

echo "  Start the service:"
echo "    sudo systemctl start reliefagent"
echo "    sudo systemctl reload nginx"
echo ""
echo "  Verify:"
echo "    curl http://localhost/api/health"
echo ""
echo "  Update nginx server_name:"
if [ "$PKG_MGR" = "dnf" ]; then
    echo "    sudo nano /etc/nginx/conf.d/reliefagent.conf"
else
    echo "    sudo nano /etc/nginx/sites-available/reliefagent"
fi
echo "    Replace YOUR_SERVER_IP with your domain or IP"
echo "    sudo nginx -t && sudo systemctl reload nginx"
echo ""
echo "  For HTTPS (recommended):"
echo "    sudo certbot --nginx -d yourdomain.com"
echo ""
echo "  Future updates:"
echo "    sudo bash $APP_DIR/current/deploy/deploy.sh main"
echo ""
echo "  Rollback:"
echo "    sudo bash $APP_DIR/current/deploy/rollback.sh"
echo "    sudo bash $APP_DIR/current/deploy/rollback.sh --list"
echo ""
echo "  Useful commands:"
echo "    sudo systemctl status reliefagent   # check status"
echo "    sudo journalctl -u reliefagent -f   # live logs"
echo "    sudo bash $APP_DIR/current/deploy/backup.sh  # manual backup"
echo ""
echo "  Add backup cron:"
echo "    echo '0 3 * * * /opt/reliefagent/current/deploy/backup.sh' | sudo tee /etc/cron.d/reliefagent-backup"
echo "============================================================"
echo "  tail -f $LOG_DIR/error.log          # gunicorn logs"
echo "  sudo systemctl restart reliefagent  # restart app"
echo "  cd $APP_DIR && sudo -u reliefagent git pull origin main && sudo systemctl restart reliefagent  # update"
echo ""