from flask import Flask, request, render_template, redirect, url_for
import telebot
from telebot import types
import sqlite3
import os
import random
import string
from collections import defaultdict
import logging
import requests
from pathlib import Path
import time
import threading

# تنظیمات اصلی
BOT_TOKEN = os.getenv('BOT_TOKEN')
BOT_USERNAME = os.getenv('BOT_USERNAME')
DOMAIN = os.getenv('DOMAIN', 'https://your-domain.com')

# تنظیم لاگینگ
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot_debug.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(BOT_TOKEN)

# تنظیمات Flask
app = Flask(__name__, template_folder='templates', static_folder='static')
app.config['SECRET_KEY'] = os.urandom(24)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# تنظیمات مسیرها و دیتابیس
BASE_PATH = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_PATH, 'user_database.db')

# Store active connections and pending requests
active_connections = defaultdict(dict)
pending_connections = {}

def ensure_directory_exists():
    try:
        os.makedirs(BASE_PATH, exist_ok=True)
        return True
    except Exception as e:
        print(f"خطای دایرکتوری: {e}")
        return False

def create_or_connect_database():
    try:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        cursor = conn.cursor()
        
        cursor.execute('''CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            numeric_id INTEGER UNIQUE,
            username TEXT,
            telegram_user_id INTEGER UNIQUE,
            special_link TEXT UNIQUE,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )''')
        conn.commit()
        return conn, cursor
    except Exception as e:
        print(f"خطای پایگاه داده: {e}")
        return None, None

def generate_unique_link():
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))

def create_connection_buttons():
    markup = types.InlineKeyboardMarkup(row_width=2)
    accept_btn = types.InlineKeyboardButton("✅ قبول", callback_data='accept_connection')
    reject_btn = types.InlineKeyboardButton("❌ رد", callback_data='reject_connection')
    markup.add(accept_btn, reject_btn)
    return markup

def create_disconnect_button():
    keyboard = types.InlineKeyboardMarkup()
    disconnect_btn = types.InlineKeyboardButton("❌ قطع ارتباط", callback_data="disconnect")
    keyboard.add(disconnect_btn)
    return keyboard

@bot.message_handler(commands=['start'])
def handle_start(message):
    try:
        logger.info(f"Start command received from user {message.from_user.id}")
        conn, cursor = create_or_connect_database()
        if not conn or not cursor:
            logger.error("Database connection failed")
            bot.reply_to(message, "خطای سیستم. لطفا بعدا دوباره تلاش کنید.")
            return

        if len(message.text.split()) > 1:
            special_link = message.text.split()[1]
            logger.debug(f"Processing special link: {special_link}")
            cursor.execute("SELECT telegram_user_id FROM users WHERE special_link = ?", (special_link,))
            owner = cursor.fetchone()
            
            if owner:
                if owner[0] == message.from_user.id:
                    logger.warning(f"User {message.from_user.id} tried to chat with themselves")
                    bot.reply_to(message, "⚠️ شما نمی‌توانید با خودتان چت کنید!")
                    return
                    
                logger.info(f"Creating chat request from {message.from_user.id} to {owner[0]}")
                pending_connections[message.from_user.id] = owner[0]
                bot.send_message(
                    owner[0],
                    f"✨ درخواست چت جدید!\n\n👤 کاربر {message.from_user.username or 'ناشناس'} می‌خواهد با شما گفتگو کند.",
                    reply_markup=create_connection_buttons()
                )
                bot.reply_to(message, "🌟 درخواست چت شما ارسال شد!\n\n⏳ لطفاً منتظر پاسخ بمانید...")
            else:
                logger.warning(f"Invalid special link used: {special_link}")
                bot.reply_to(message, "⚠️ لینک نامعتبر است.")
        else:
            cursor.execute("SELECT * FROM users WHERE telegram_user_id = ?", (message.from_user.id,))
            existing_user = cursor.fetchone()
            
            if existing_user:
                logger.info(f"Existing user {message.from_user.id} started bot")
                special_link = existing_user[4]
                share_link = f"https://t.me/{BOT_USERNAME}?start={special_link}"
                bot.reply_to(
                    message, 
                    f"""🎉 خوش برگشتید!
🔗 لینک اختصاصی شما:
{share_link}"""
                )
            else:
                logger.info(f"Registering new user {message.from_user.id}")
                special_link = generate_unique_link()
                numeric_id = random.randint(10000, 99999)
                
                cursor.execute(
                    "INSERT INTO users (numeric_id, username, telegram_user_id, special_link) VALUES (?, ?, ?, ?)",
                    (numeric_id, message.from_user.username, message.from_user.id, special_link)
                )
                conn.commit()
                
                share_link = f"https://t.me/{BOT_USERNAME}?start={special_link}"
                welcome_msg = f"""
🎈 به ربات ما خوش آمدید!
🔗 لینک اختصاصی شما: 
{share_link}"""
                bot.reply_to(message, welcome_msg)

    except Exception as e:
        logger.error(f"Error in start handler: {e}", exc_info=True)
        bot.reply_to(message, "❌ متأسفانه مشکلی پیش آمده! لطفاً دوباره تلاش کنید.")
    finally:
        if conn:
            conn.close()

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    try:
        logger.info(f"Callback received: {call.data} from user {call.from_user.id}")
        if call.data == 'accept_connection':
            requester_id = None
            for req_id, owner_id in pending_connections.items():
                if owner_id == call.from_user.id:
                    requester_id = req_id
                    logger.info(f"Accepting chat request: {req_id} -> {owner_id}")
                    active_connections[owner_id] = {'connected_to': req_id}
                    active_connections[req_id] = {'connected_to': owner_id}
                    del pending_connections[req_id]
                    break
            
            if requester_id:
                logger.debug(f"Chat established between {call.from_user.id} and {requester_id}")
                bot.edit_message_text(
                    "✅ ارتباط برقرار شد.",
                    call.message.chat.id,
                    call.message.message_id,
                    reply_markup=create_disconnect_button()
                )
                bot.send_message(
                    requester_id,
                    "✅ درخواست چت شما پذیرفته شد!",
                    reply_markup=create_disconnect_button()
                )
                
        elif call.data == 'reject_connection':
            for req_id, owner_id in list(pending_connections.items()):
                if owner_id == call.from_user.id:
                    logger.info(f"Rejecting chat request from {req_id}")
                    bot.send_message(req_id, "❌ درخواست چت شما رد شد.")
                    del pending_connections[req_id]
                    bot.edit_message_text(
                        "❌ درخواست رد شد.",
                        call.message.chat.id,
                        call.message.message_id
                    )
                    break
                
        elif call.data == "disconnect":
            user_id = call.from_user.id
            if user_id in active_connections:
                other_user = active_connections[user_id].get('connected_to')
                if other_user:
                    logger.info(f"Disconnecting chat between {user_id} and {other_user}")
                    bot.send_message(other_user, "❌ چت به پایان رسید.")
                    del active_connections[user_id]
                    del active_connections[other_user]
                    bot.edit_message_text(
                        "❌ چت به پایان رسید.",
                        call.message.chat.id,
                        call.message.message_id
                    )
                    
    except Exception as e:
        logger.error(f"Error in callback handler: {e}", exc_info=True)
        bot.answer_callback_query(call.id, "خطایی رخ داد. لطفاً دوباره تلاش کنید.")

@bot.message_handler(func=lambda message: True)
def handle_messages(message):
    try:
        user_id = message.from_user.id
        logger.debug(f"Message received from user {user_id}: {message.content_type}")
        
        if user_id in active_connections:
            other_user = active_connections[user_id].get('connected_to')
            if other_user:
                logger.debug(f"Forwarding message from {user_id} to {other_user}")
                try:
                    if message.content_type == 'text':
                        bot.send_message(other_user, message.text)
                    elif message.content_type in ['photo', 'video', 'document', 'audio', 'voice', 'sticker']:
                        file_id = None
                        if message.content_type == 'photo':
                            file_id = message.photo[-1].file_id
                        else:
                            file_id = getattr(message, message.content_type).file_id
                        
                        if message.caption:
                            getattr(bot, f'send_{message.content_type}')(other_user, file_id, caption=message.caption)
                        else:
                            getattr(bot, f'send_{message.content_type}')(other_user, file_id)
                            
                except Exception as e:
                    logger.error(f"Error sending message: {e}", exc_info=True)
                    bot.reply_to(message, "❌ خطا در ارسال پیام!")
            else:
                logger.warning(f"User {user_id} in active_connections but no partner found")
        else:
            logger.debug(f"User {user_id} not in active chat")
            bot.reply_to(message, "برای شروع چت، از دستور /start استفاده کنید.")
            
    except Exception as e:
        logger.error(f"Error in message handler: {e}", exc_info=True)
        bot.reply_to(message, "خطایی رخ داد. لطفاً دوباره تلاش کنید.")

@app.route('/')
def index():
    return "Welcome to Chat Bot"

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return ''
    return 'OK'

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # راه‌اندازی ربات در thread جداگانه
    bot_thread = threading.Thread(target=bot.polling, daemon=True)
    bot_thread.start()
    
    # راه‌اندازی Flask
    app.run(host='0.0.0.0', port=5000)
