from flask import Flask, request, render_template
import telebot
from telebot import types
import sqlite3
import os
import random
import string
import logging
import threading
import time
from datetime import datetime

# تنظیمات اصلی
BOT_TOKEN = os.getenv('BOT_TOKEN')
BOT_USERNAME = os.getenv('BOT_USERNAME')
DOMAIN = os.getenv('DOMAIN', 'https://your-domain.com')

# ایجاد نمونه‌های اصلی
bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)

# مسیر دیتابیس
DB_PATH = 'user_database.db'

# ساختارهای داده برای مدیریت چت
class ChatManager:
    def __init__(self):
        self.active_chats = {}  # {user_id: {'partner_id': id, 'last_activity': timestamp}}
        self.pending_requests = {}  # {from_id: to_id}
        self.lock = threading.Lock()
    
    def add_pending_request(self, from_id, to_id):
        with self.lock:
            if from_id not in self.active_chats and to_id not in self.active_chats:
                self.pending_requests[from_id] = to_id
                return True
        return False
    
    def accept_request(self, from_id, to_id):
        with self.lock:
            if from_id in self.pending_requests and self.pending_requests[from_id] == to_id:
                current_time = time.time()
                self.active_chats[from_id] = {'partner_id': to_id, 'last_activity': current_time}
                self.active_chats[to_id] = {'partner_id': from_id, 'last_activity': current_time}
                del self.pending_requests[from_id]
                return True
        return False
    
    def end_chat(self, user_id):
        with self.lock:
            if user_id in self.active_chats:
                partner_id = self.active_chats[user_id]['partner_id']
                if partner_id in self.active_chats:
                    del self.active_chats[partner_id]
                del self.active_chats[user_id]
                return partner_id
        return None
    
    def update_activity(self, user_id):
        with self.lock:
            if user_id in self.active_chats:
                self.active_chats[user_id]['last_activity'] = time.time()
                partner_id = self.active_chats[user_id]['partner_id']
                self.active_chats[partner_id]['last_activity'] = time.time()

    def get_chat_partner(self, user_id):
        return self.active_chats.get(user_id, {}).get('partner_id')

    def is_user_in_chat(self, user_id):
        return user_id in self.active_chats

chat_manager = ChatManager()

# دیتابیس
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  telegram_id INTEGER UNIQUE,
                  username TEXT,
                  special_link TEXT UNIQUE,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    conn.close()

def generate_special_link():
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))

def register_user(telegram_id, username):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        special_link = generate_special_link()
        c.execute('INSERT OR IGNORE INTO users (telegram_id, username, special_link) VALUES (?, ?, ?)',
                 (telegram_id, username, special_link))
        conn.commit()
        return special_link
    finally:
        conn.close()

def get_user_by_link(special_link):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute('SELECT telegram_id FROM users WHERE special_link = ?', (special_link,))
        result = c.fetchone()
        return result[0] if result else None
    finally:
        conn.close()

# کیبوردها
def create_chat_keyboard():
    keyboard = types.InlineKeyboardMarkup()
    disconnect_btn = types.InlineKeyboardButton("❌ پایان چت", callback_data="end_chat")
    keyboard.add(disconnect_btn)
    return keyboard

def create_request_keyboard():
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    accept_btn = types.InlineKeyboardButton("✅ قبول", callback_data="accept_chat")
    reject_btn = types.InlineKeyboardButton("❌ رد", callback_data="reject_chat")
    keyboard.add(accept_btn, reject_btn)
    return keyboard

# دستورات ربات
@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    username = message.from_user.username or "بدون نام کاربری"
    
    special_link = register_user(user_id, username)
    
    if len(message.text.split()) > 1:
        # اگر لینک دعوت داشته باشد
        invite_code = message.text.split()[1]
        target_id = get_user_by_link(invite_code)
        
        if target_id and target_id != user_id:
            if chat_manager.add_pending_request(user_id, target_id):
                bot.send_message(target_id,
                               f"درخواست چت جدید از طرف {username}!",
                               reply_markup=create_request_keyboard())
                bot.reply_to(message, "درخواست چت ارسال شد. لطفاً منتظر پاسخ بمانید.")
            else:
                bot.reply_to(message, "امکان برقراری چت وجود ندارد. لطفاً بعداً تلاش کنید.")
        else:
            bot.reply_to(message, "لینک نامعتبر است.")
    else:
        welcome_text = f"""
سلام! به ربات چت ناشناس خوش آمدید.
لینک اختصاصی شما:
{DOMAIN}/start?start={special_link}
این لینک را برای شروع چت به دیگران بدهید.
"""
        bot.reply_to(message, welcome_text)

@bot.callback_query_handler(func=lambda call: True)
def handle_query(call):
    user_id = call.from_user.id
    
    if call.data == "accept_chat":
        for from_id, to_id in chat_manager.pending_requests.items():
            if to_id == user_id:
                if chat_manager.accept_request(from_id, user_id):
                    bot.edit_message_text("چت شروع شد! می‌توانید پیام بدهید.",
                                        call.message.chat.id,
                                        call.message.message_id,
                                        reply_markup=create_chat_keyboard())
                    bot.send_message(from_id,
                                   "درخواست چت پذیرفته شد! می‌توانید پیام بدهید.",
                                   reply_markup=create_chat_keyboard())
                break
    
    elif call.data == "reject_chat":
        for from_id, to_id in list(chat_manager.pending_requests.items()):
            if to_id == user_id:
                del chat_manager.pending_requests[from_id]
                bot.edit_message_text("درخواست چت رد شد.",
                                    call.message.chat.id,
                                    call.message.message_id)
                bot.send_message(from_id, "متأسفانه درخواست چت شما رد شد.")
                break
    
    elif call.data == "end_chat":
        partner_id = chat_manager.end_chat(user_id)
        if partner_id:
            bot.edit_message_text("چت پایان یافت.",
                                call.message.chat.id,
                                call.message.message_id)
            bot.send_message(partner_id, "چت توسط طرف مقابل پایان یافت.")

@bot.message_handler(func=lambda message: True)
def handle_messages(message):
    user_id = message.from_user.id
    
    if chat_manager.is_user_in_chat(user_id):
        partner_id = chat_manager.get_chat_partner(user_id)
        chat_manager.update_activity(user_id)
        
        try:
            if message.content_type == 'text':
                bot.send_message(partner_id, message.text)
            elif message.content_type in ['photo', 'video', 'document', 'audio', 'voice', 'sticker']:
                if message.caption:
                    getattr(bot, f'send_{message.content_type}')(
                        partner_id,
                        getattr(message, message.content_type)[-1].file_id,
                        caption=message.caption
                    )
                else:
                    getattr(bot, f'send_{message.content_type}')(
                        partner_id,
                        getattr(message, message.content_type)[-1].file_id
                    )
        except Exception as e:
            logging.error(f"Error sending message: {e}")
            bot.send_message(user_id, "خطا در ارسال پیام. لطفاً دوباره تلاش کنید.")

# مسیرهای Flask
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return ''
    return 'OK'

if __name__ == "__main__":
    # راه‌اندازی دیتابیس
    init_db()
    
    # تنظیم لاگینگ
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # راه‌اندازی ربات در thread جداگانه
    bot_thread = threading.Thread(target=bot.polling, daemon=True)
    bot_thread.start()
    
    # راه‌اندازی Flask
    app.run(host='0.0.0.0', port=5000)
