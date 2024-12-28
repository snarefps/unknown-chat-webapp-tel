#!/bin/bash

# رنگ‌ها برای نمایش بهتر پیام‌ها
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}Starting installation...${NC}"

# دریافت متغیرهای محیطی
read -p "Enter your domain (e.g., example.com): " DOMAIN
read -p "Enter your Telegram Bot Token: " BOT_TOKEN
read -p "Enter your Telegram Bot Username: " BOT_USERNAME

# نصب پکیج‌های مورد نیاز
echo -e "${BLUE}Installing system packages...${NC}"
sudo apt update
sudo apt install -y python3-pip python3-venv nginx certbot python3-certbot-nginx

# ایجاد محیط مجازی و نصب پکیج‌ها
echo -e "${BLUE}Setting up Python virtual environment...${NC}"
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install gunicorn

# ایجاد فایل کانفیگ nginx
echo -e "${BLUE}Creating Nginx configuration...${NC}"
sudo bash -c "cat > /etc/nginx/sites-available/$DOMAIN" << EOL
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
        alias $(pwd)/static;
    }

    client_max_body_size 16M;
}
EOL

# فعال‌سازی سایت در nginx
sudo ln -sf /etc/nginx/sites-available/$DOMAIN /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl restart nginx

# نصب SSL با Let's Encrypt
echo -e "${BLUE}Setting up SSL certificate...${NC}"
sudo certbot --nginx -d $DOMAIN --non-interactive --agree-tos --email admin@$DOMAIN

# ایجاد سرویس systemd
echo -e "${BLUE}Creating systemd service...${NC}"
sudo bash -c "cat > /etc/systemd/system/telegram-webapp.service" << EOL
[Unit]
Description=Telegram Web App
After=network.target

[Service]
User=$USER
WorkingDirectory=$(pwd)
Environment="PATH=$(pwd)/venv/bin"
Environment="BOT_TOKEN=$BOT_TOKEN"
Environment="BOT_USERNAME=$BOT_USERNAME"
Environment="DOMAIN=https://$DOMAIN"
ExecStart=$(pwd)/venv/bin/gunicorn -w 4 -b 127.0.0.1:5000 app:app
Restart=always

[Install]
WantedBy=multi-user.target
EOL

# راه‌اندازی و فعال‌سازی سرویس
sudo systemctl daemon-reload
sudo systemctl start telegram-webapp
sudo systemctl enable telegram-webapp

# تنظیم webhook تلگرام
echo -e "${BLUE}Setting up Telegram webhook...${NC}"
curl "https://api.telegram.org/bot$BOT_TOKEN/setWebhook?url=https://$DOMAIN/webhook"

echo -e "${GREEN}Installation completed!${NC}"
echo -e "${GREEN}Your web app is now running at https://$DOMAIN${NC}"
echo -e "${BLUE}To check the status of your app, run: sudo systemctl status telegram-webapp${NC}"
echo -e "${BLUE}To view logs, run: sudo journalctl -u telegram-webapp${NC}"
