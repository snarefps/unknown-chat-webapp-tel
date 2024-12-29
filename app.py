import logging
from flask import Flask, request, render_template, redirect, url_for
import telebot
from telebot import types
import sqlite3
import os
import random
import string
from collections import defaultdict
import asyncio
import requests
from pathlib import Path
import time
import threading

# Configure logging at the beginning of the file
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# تنظیمات اصلی
BOT_TOKEN = os.getenv('BOT_TOKEN')
BOT_USERNAME = os.getenv('BOT_USERNAME')
DOMAIN = os.getenv('DOMAIN', 'https://your-domain.com')
bot = telebot.TeleBot(BOT_TOKEN)

# تنظیمات Flask
app = Flask(__name__, template_folder='templates', static_folder='static')
app.config['SECRET_KEY'] = os.urandom(24)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# تنظیمات مسیرها و دیتابیس
BASE_PATH = '/opt/telegram-webapp'
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

# Improved error handling and logging for database connection
def create_or_connect_database():
    if not ensure_directory_exists():
        logger.error("Failed to ensure directory exists.")
        return None, None

    try:
        database_exists = os.path.exists(DB_PATH)
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        cursor = conn.cursor()
        
        if not database_exists:
            cursor.execute('''
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    numeric_id INTEGER UNIQUE,
                    username TEXT,
                    telegram_user_id INTEGER UNIQUE,
                    special_link TEXT UNIQUE,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.commit()
        logger.info("Database connected successfully.")
        return conn, cursor
    except sqlite3.Error as e:
        logger.error(f"Database error: {e}")
        return None, None
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
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

def create_web_app_button(user_id):
    keyboard = types.InlineKeyboardMarkup()
    web_app_info = types.WebAppInfo(url=f"https://chatbot.smart-flow.com.tr/users?telegram_user_id={user_id}")
    web_app_button = types.InlineKeyboardButton(text="🌐 باز کردن وب اپلیکیشن", web_app=web_app_info)
    keyboard.add(web_app_button)
    return keyboard

# Example of adding timeout to a network request
def get_user_profile_photo(user_id):
    try:
        user_profile_photos = bot.get_user_profile_photos(user_id)
        if user_profile_photos.total_count > 0:
            file_id = user_profile_photos.photos[0][0].file_id
            file_info = bot.get_file(file_id)
            file_path = file_info.file_path
            return f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
        else:
            return "https://via.placeholder.com/150"
    except requests.exceptions.Timeout:
        logger.error("Request timed out")
        return "https://via.placeholder.com/150"
    except Exception as e:
        logger.error(f"Error fetching user profile photo: {e}")
        return "https://via.placeholder.com/150"

@bot.message_handler(commands=['start'])
def handle_start(message):
    try:
        conn, cursor = create_or_connect_database()
        if not conn or not cursor:
            bot.reply_to(message, "خطای سیستم. لطفا بعدا دوباره تلاش کنید.")
            return

        # پردازش پارامتر start
        if len(message.text.split()) > 1:
            special_link = message.text.split()[1]
            cursor.execute("SELECT telegram_user_id FROM users WHERE special_link = ?", (special_link,))
            owner = cursor.fetchone()
            
            if owner:
                # بررسی ارتباط با خود
                if owner[0] == message.from_user.id:
                    bot.reply_to(message, "⚠️ شما نمی‌توانید با خودتان چت کنید!")
                    return
                    
                pending_connections[message.from_user.id] = owner[0]
                bot.send_message(
                    owner[0],
                    f"✨ درخواست چت جدید!\n\n👤 کاربر {message.from_user.username or 'ناشناس'} می‌خواهد با شما گفتگو کند.\n\n🤝 مایل به برقراری ارتباط هستید؟",
                    reply_markup=create_connection_buttons()
                )
                bot.reply_to(message, "🌟 درخواست چت شما ارسال شد!\n\n⏳ لطفاً منتظر پاسخ بمانید...", reply_markup=create_web_app_button(message.from_user.id))
            else:
                bot.reply_to(message, "⚠️ اوه! لینک ارتباطی که استفاده کردید معتبر نیست.\n\n🔄 لطفاً دوباره تلاش کنید.", reply_markup=create_web_app_button(message.from_user.id))
        else:
            # ثبت نام کاربر جدید
            cursor.execute("SELECT * FROM users WHERE telegram_user_id = ?", (message.from_user.id,))
            existing_user = cursor.fetchone()
            
            if existing_user:
                bot.reply_to(
                    message, 
                    f"""🎉 خوش برگشتید {message.from_user.first_name} عزیز!

🔗 لینک اختصاصی شما:
t.me/{bot.get_me().username}?start={existing_user[4]}

💫 با اشتراک‌گذاری این لینک، دوستانتان می‌توانند مستقیماً با شما چت کنند!""",
                    reply_markup=create_web_app_button(message.from_user.id)
                )
            else:
                numeric_id = random.randint(10000, 99999)
                special_link = generate_unique_link()
                
                cursor.execute(
                    "INSERT INTO users (numeric_id, username, telegram_user_id, special_link) VALUES (?, ?, ?, ?)",
                    (numeric_id, message.from_user.username, message.from_user.id, special_link)
                )
                conn.commit()
                
                welcome_msg = f"""
🎈 {message.from_user.first_name} عزیز، به ربات ما خوش آمدید!

📝 اطلاعات پروفایل شما:
🔢 شناسه: {numeric_id}
🔗 لینک اختصاصی شما: 
t.me/{bot.get_me().username}?start={special_link}

✨ با اشتراک‌گذاری لینک اختصاصی خود، دوستانتان می‌توانند مستقیماً با شما چت کنند!
                """
                bot.reply_to(message, welcome_msg, reply_markup=create_web_app_button(message.from_user.id))

    except Exception as e:
        print(f"خطا در هندلر شروع: {e}")
        bot.reply_to(message, "❌ متأسفانه مشکلی پیش آمده!\n\n🔄 لطفاً چند لحظه دیگر دوباره تلاش کنید.", reply_markup=create_web_app_button(message.from_user.id))
    finally:
        conn.close()

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    try:
        user_id = call.from_user.id
        
        if call.data == "accept_connection":
            requester_id = None
            for req_id, owner_id in pending_connections.items():
                if owner_id == user_id:
                    requester_id = req_id
                    active_connections[owner_id] = {'connected_to': req_id}
                    active_connections[req_id] = {'connected_to': owner_id}
                    del pending_connections[req_id]
                    break
                
            if requester_id:
                disconnect_message = bot.send_message(
                    requester_id,
                    """✨ درخواست چت شما پذیرفته شد!

💭 حالا می‌توانید پیام‌های خود را ارسال کنید.

❤️ امیدواریم گفتگوی خوبی داشته باشید!

⚠️ برای قطع ارتباط از دکمه زیر استفاده کنید:""",
                    reply_markup=create_disconnect_button()
                )
                bot.pin_chat_message(requester_id, disconnect_message.message_id)
                
                owner_disconnect_message = bot.send_message(
                    user_id,
                    """🤝 شما درخواست چت را پذیرفتید!

💭 حالا می‌توانید پیام‌های خود را ارسال کنید.

❤️ امیدواریم گفتگوی خوبی داشته باشید!

⚠️ برای قطع ارتباط از دکمه زیر استفاده کنید:""",
                    reply_markup=create_disconnect_button()
                )
                bot.pin_chat_message(user_id, owner_disconnect_message.message_id)
                
        elif call.data == "reject_connection":
            requester_id = None
            for req_id, owner_id in pending_connections.items():
                if owner_id == user_id:
                    requester_id = req_id
                    del pending_connections[req_id]
                    break
            
            if requester_id:
                bot.send_message(requester_id, "😔 متأسفانه درخواست چت شما پذیرفته نشد.\n\n✨ می‌توانید با کاربران دیگر گفتگو کنید!")
                bot.edit_message_text(
                    "🚫 شما این درخواست چت را رد کردید.",
                    call.message.chat.id,
                    call.message.message_id
                )
                
        elif call.data == "disconnect":
            if user_id in active_connections:
                other_user = active_connections[user_id].get('connected_to')
                if other_user:
                    try:
                        bot.unpin_all_chat_messages(user_id)
                        bot.unpin_all_chat_messages(other_user)
                    except:
                        pass

                    bot.send_message(user_id, """❌ چت پایان یافت!

🌟 امیدواریم از این گفتگو لذت برده باشید.
✨ می‌توانید دوباره با کاربران دیگر چت کنید!""")
                    bot.send_message(other_user, """❌ کاربر مقابل چت را پایان داد.

🌟 امیدواریم از این گفتگو لذت برده باشید.
✨ می‌توانید دوباره با کاربران دیگر چت کنید!""")
                    
                    del active_connections[user_id]
                    del active_connections[other_user]
                    
    except Exception as e:
        print(f"خطا در هندلر کال‌بک: {e}")
        bot.answer_callback_query(call.id, "❌ متأسفانه مشکلی پیش آمده! لطفاً دوباره تلاش کنید.")

@bot.message_handler(func=lambda message: True, content_types=['text', 'photo', 'video', 'document', 'audio', 'voice', 'video_note', 'sticker', 'animation'])
def handle_messages(message):
    if message.from_user.id in active_connections:
        other_user = active_connections[message.from_user.id].get('connected_to')
        if other_user:
            try:
                # ارسال متن
                if message.text:
                    bot.send_message(other_user, f"💬 پیام جدید:\n{message.text}")
                
                # ارسال عکس
                elif message.photo:
                    caption = message.caption if message.caption else ""
                    bot.send_photo(other_user, message.photo[-1].file_id, caption=f"🖼️ تصویر جدید:\n{caption}")
                
                # ارسال ویدیو
                elif message.video:
                    caption = message.caption if message.caption else ""
                    bot.send_video(other_user, message.video.file_id, caption=f"🎥 ویدیو جدید:\n{caption}")
                
                # ارسال فایل
                elif message.document:
                    caption = message.caption if message.caption else ""
                    bot.send_document(other_user, message.document.file_id, caption=f"📎 فایل جدید:\n{caption}")
                
                # ارسال صوت
                elif message.audio:
                    caption = message.caption if message.caption else ""
                    bot.send_audio(other_user, message.audio.file_id, caption=f"🎵 موزیک جدید:\n{caption}")
                
                # ارسال ویس
                elif message.voice:
                    caption = message.caption if message.caption else ""
                    bot.send_voice(other_user, message.voice.file_id, caption=f"🎤 پیام صوتی جدید:\n{caption}")
                
                # ارسال ویدیو نوت
                elif message.video_note:
                    bot.send_video_note(other_user, message.video_note.file_id)
                
                # ارسال استیکر
                elif message.sticker:
                    bot.send_sticker(other_user, message.sticker.file_id)
                
                # ارسال گیف
                elif message.animation:
                    caption = message.caption if message.caption else ""
                    bot.send_animation(other_user, message.animation.file_id, caption=f"✨ گیف جدید:\n{caption}")
                
            except Exception as e:
                print(f"خطا در ارسال پیام: {e}")
                bot.send_message(message.chat.id, "❌ خطا در ارسال پیام! لطفاً دوباره تلاش کنید.")
    else:
        # bot.reply_to(message, """📝 برای شروع چت:
        # 1️⃣ لینک اختصاصی خود را با دوستانتان به اشتراک بگذارید
        # 2️⃣ یا از لینک دوستانتان استفاده کنید
        # ✨ همین حالا چت را شروع کنید!
        # """)
        bot.reply_to(message, "", reply_markup=create_web_app_button(message.from_user.id))

# Flask route to display user data
@app.route('/')
def index():
    return redirect(url_for('display_users'))

@app.route('/user/<int:telegram_user_id>')
def user_profile(telegram_user_id):
    conn, cursor = create_or_connect_database()
    if not conn or not cursor:
        return "Database error", 500
        
    cursor.execute("SELECT numeric_id, username, telegram_user_id, special_link, created_at FROM users WHERE telegram_user_id = ?", (telegram_user_id,))
    user = cursor.fetchall()
    
    if not user:
        return "User not found", 404
        
    profile_photo_url = get_user_profile_photo(telegram_user_id)
    return render_template('index.html', users=user, profile_photo_url=profile_photo_url)

@app.route('/users')
def display_users():
    telegram_user_id = request.args.get('telegram_user_id')
    if telegram_user_id:
        return redirect(url_for('user_profile', telegram_user_id=telegram_user_id))
        
    conn, cursor = create_or_connect_database()
    if not conn or not cursor:
        return "Database error", 500
        
    cursor.execute("SELECT numeric_id, username, telegram_user_id, special_link, created_at FROM users")
    users = cursor.fetchall()
    
    if not users:
        return "No users found", 404
        
    profile_photo_url = get_user_profile_photo(users[0][2])
    return render_template('index.html', users=users, profile_photo_url=profile_photo_url)

# Flask webhook route
@app.route('/webhook', methods=['POST'])
def webhook():
    logger = logging.getLogger(__name__)
    logger.debug("Received webhook request")
    try:
        json_data = request.get_json(force=True)
        logger.debug(f"Webhook data: {json_data}")
        update = telebot.types.Update.de_json(json_data)
        bot.process_new_updates([update])
        return 'ok'
    except Exception as e:
        logger.error(f"Error in webhook: {e}")
        return str(e), 500

# Start the Flask app
if __name__ == "__main__":
    logger.info("Starting bot...")
    
    # اطمینان از وجود دایرکتوری‌ها
    ensure_directory_exists()
    
    def run_flask():
        app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
    
    def run_bot():
        while True:
            try:
                logger.info("Starting bot polling...")
                bot.polling(none_stop=True)
            except Exception as e:
                logger.error(f"Bot polling error: {e}")
                continue
    
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    
    flask_thread.start()
    bot_thread.start()
    
    try:
        # نگه داشتن برنامه در حال اجرا
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
