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

APP_DIR="/opt/telegram-webapp"

log "Starting update process..."

# رفتن به دایرکتوری برنامه
cd $APP_DIR || error "Failed to change directory to $APP_DIR"

# گرفتن تغییرات جدید از گیت‌هاب
log "Pulling latest changes from GitHub..."
git pull || error "Failed to pull changes from GitHub"

# فعال‌سازی محیط مجازی
log "Activating virtual environment..."
source venv/bin/activate || error "Failed to activate virtual environment"

# نصب پکیج‌های جدید
log "Installing/Updating Python packages..."
pip install -r requirements.txt || error "Failed to install/update packages"

# ری‌استارت سرویس
log "Restarting service..."
sudo systemctl restart telegram-webapp || error "Failed to restart service"

# نمایش وضعیت سرویس
log "Checking service status..."
sudo systemctl status telegram-webapp --no-pager

log "Update completed successfully!"
echo -e "${GREEN}Your web app has been updated and restarted${NC}"
echo -e "${BLUE}To view logs, run: sudo journalctl -u telegram-webapp -f${NC}"
