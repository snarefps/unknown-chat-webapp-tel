#!/bin/bash

# تنظیم خطایابی
set -e
set -o pipefail

# رنگ‌ها برای نمایش بهتر پیام‌ها
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

# تابع لاگ کردن
log() {
    echo -e "${BLUE}[$(date +'%Y-%m-%d %H:%M:%S')] $1${NC}"
}

# تابع خطا
error() {
    echo -e "${RED}[ERROR] $1${NC}"
    exit 1
}

# تابع بررسی نتیجه دستورات
check_result() {
    if [ $? -ne 0 ]; then
        error "$1"
    fi
}

log "Starting installation..."

# دریافت متغیرهای محیطی
read -p "Enter your domain (e.g., example.com): " DOMAIN
read -p "Enter your Telegram Bot Token: " BOT_TOKEN
read -p "Enter your Telegram Bot Username: " BOT_USERNAME
read -p "Enter GitHub repository URL: " REPO_URL

# بررسی متغیرها
[ -z "$DOMAIN" ] && error "Domain cannot be empty"
[ -z "$BOT_TOKEN" ] && error "Bot token cannot be empty"
[ -z "$BOT_USERNAME" ] && error "Bot username cannot be empty"
[ -z "$REPO_URL" ] && error "Repository URL cannot be empty"

# نصب پکیج‌های مورد نیاز
log "Installing system packages..."
sudo apt update || error "Failed to update package list"
sudo apt install -y python3-pip python3-venv nginx certbot python3-certbot-nginx git || error "Failed to install packages"

# کلون کردن مخزن
log "Cloning repository..."
APP_DIR="/opt/telegram-webapp"
sudo mkdir -p $APP_DIR
sudo chown $USER:$USER $APP_DIR
git clone $REPO_URL $APP_DIR || error "Failed to clone repository"
cd $APP_DIR || error "Failed to change directory"

# ایجاد محیط مجازی و نصب پکیج‌ها
log "Setting up Python virtual environment..."
python3 -m venv venv || error "Failed to create virtual environment"
source venv/bin/activate || error "Failed to activate virtual environment"
pip install -r requirements.txt || error "Failed to install Python packages"
pip install gunicorn || error "Failed to install gunicorn"

# ایجاد فایل کانفیگ nginx
log "Creating Nginx configuration..."
sudo tee /etc/nginx/sites-available/$DOMAIN > /dev/null << EOL
server {
    server_name $DOMAIN;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location /static {
        alias $APP_DIR/static;
    }

    client_max_body_size 16M;
}
EOL
check_result "Failed to create Nginx config"

# فعال‌سازی سایت در nginx
log "Enabling Nginx site..."
sudo ln -sf /etc/nginx/sites-available/$DOMAIN /etc/nginx/sites-enabled/ || error "Failed to enable Nginx site"
sudo nginx -t || error "Nginx configuration test failed"
sudo systemctl restart nginx || error "Failed to restart Nginx"

# نصب SSL با Let's Encrypt
log "Setting up SSL certificate..."
sudo certbot --nginx -d $DOMAIN --non-interactive --agree-tos --email admin@$DOMAIN || error "SSL certificate installation failed"

# ایجاد سرویس systemd
log "Creating systemd service..."
sudo tee /etc/systemd/system/telegram-webapp.service > /dev/null << EOL
[Unit]
Description=Telegram Web App
After=network.target

[Service]
User=$USER
WorkingDirectory=$APP_DIR
Environment="PATH=$APP_DIR/venv/bin"
Environment="BOT_TOKEN=$BOT_TOKEN"
Environment="BOT_USERNAME=$BOT_USERNAME"
Environment="DOMAIN=https://$DOMAIN"
ExecStart=$APP_DIR/venv/bin/gunicorn -w 4 -b 127.0.0.1:5000 app:app
Restart=always

[Install]
WantedBy=multi-user.target
EOL
check_result "Failed to create systemd service"

# راه‌اندازی و فعال‌سازی سرویس
log "Starting and enabling service..."
sudo systemctl daemon-reload || error "Failed to reload systemd"
sudo systemctl start telegram-webapp || error "Failed to start service"
sudo systemctl enable telegram-webapp || error "Failed to enable service"

# تنظیم webhook تلگرام با خطایابی
log "Setting up Telegram webhook..."
WEBHOOK_RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" "https://api.telegram.org/bot$BOT_TOKEN/setWebhook?url=https://$DOMAIN/webhook")
if [ "$WEBHOOK_RESPONSE" != "200" ]; then
    error "Failed to set webhook. HTTP response code: $WEBHOOK_RESPONSE"
fi

log "Installation completed successfully!"
echo -e "${GREEN}Your web app is now running at https://$DOMAIN${NC}"
echo -e "${GREEN}Application is installed in: $APP_DIR${NC}"
echo -e "${BLUE}To check the status of your app, run: sudo systemctl status telegram-webapp${NC}"
echo -e "${BLUE}To view logs, run: sudo journalctl -u telegram-webapp${NC}"
echo -e "${BLUE}To update from git, run: cd $APP_DIR && git pull${NC}"

# بررسی وضعیت نهایی سرویس
log "Checking final service status..."
sudo systemctl status telegram-webapp --no-pager
