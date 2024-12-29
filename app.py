from flask import Flask, request, render_template, redirect, url_for
import telebot
from telebot import types
import sqlite3
import os
import random
import string
from collections import defaultdict
import asyncio
import logging
import requests

BOT_TOKEN = '7359047596:AAFzCjMQM1YuovahhOqXB1BS9lijCxu29Ew'
BOT_USERNAME = 'your_bot_username'  # Add your bot username here
bot = telebot.TeleBot(BOT_TOKEN)

# Flask app setup
app = Flask(__name__, template_folder='templates', static_folder='static')

# Database configuration
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
    if not ensure_directory_exists():
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

def create_web_app_button(user_id):
    web_app_info = types.WebAppInfo(url=f"https://your-domain.com/users?telegram_user_id={user_id}")
    markup = types.InlineKeyboardMarkup()
    web_app_btn = types.InlineKeyboardButton("باز کردن وب اپلیکیشن", web_app=web_app_info)
    markup.add(web_app_btn)
    return markup

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
    except Exception as e:
        print(f"خطا در دریافت عکس پروفایل: {e}")
        return "https://via.placeholder.com/150"

@bot.message_handler(commands=['start'])
def handle_start(message):
    try:
        conn, cursor = create_or_connect_database()
        if not conn or not cursor:
            bot.reply_to(message, "❌ خطا در اتصال به پایگاه داده!")
            return

        user_id = message.from_user.id
        username = message.from_user.username or "بدون نام کاربری"
        
        # Check if user exists
        cursor.execute('SELECT special_link FROM users WHERE telegram_user_id = ?', (user_id,))
        existing_user = cursor.fetchone()
        
        if existing_user:
            special_link = existing_user[0]
        else:
            # Generate a unique link
            while True:
                special_link = generate_unique_link()
                cursor.execute('SELECT id FROM users WHERE special_link = ?', (special_link,))
                if not cursor.fetchone():
                    break
            
            # Insert new user
            cursor.execute('''
                INSERT INTO users (numeric_id, username, telegram_user_id, special_link)
                VALUES (?, ?, ?, ?)
            ''', (user_id, username, user_id, special_link))
            conn.commit()
        
        # Send welcome message
        bot.reply_to(
            message,
            f"""👋 سلام به ربات چت ناشناس خوش آمدید!

🔑 لینک اختصاصی شما:
https://t.me/{BOT_USERNAME}?start={special_link}

✨ با اشتراک‌گذاری این لینک، دوستانتان می‌توانند به صورت ناشناس با شما چت کنند.

⚡️ برای شروع چت:
1️⃣ لینک خود را به اشتراک بگذارید
2️⃣ یا از لینک دوستانتان استفاده کنید

❤️ امیدواریم تجربه خوبی داشته باشید!""",
            reply_markup=create_web_app_button(user_id)
        )
        
    except Exception as e:
        print(f"خطا در هندل استارت: {e}")
        bot.reply_to(message, "❌ متأسفانه مشکلی پیش آمده! لطفاً دوباره تلاش کنید.")
    finally:
        if conn:
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
        bot.reply_to(message, """📝 برای شروع چت:

1️⃣ لینک اختصاصی خود را با دوستانتان به اشتراک بگذارید
2️⃣ یا از لینک دوستانتان استفاده کنید

✨ همین حالا چت را شروع کنید!""")

# Flask route to display user data
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/users')
def user_profile():
    telegram_user_id = request.args.get('telegram_user_id')
    if not telegram_user_id:
        return redirect(url_for('index'))
    
    conn, cursor = create_or_connect_database()
    if not conn or not cursor:
        return "Database Error", 500
    
    try:
        cursor.execute('SELECT * FROM users WHERE telegram_user_id = ?', (telegram_user_id,))
        user = cursor.fetchone()
        if not user:
            return "User not found", 404
            
        return render_template('user_profile.html', user=user)
    finally:
        conn.close()

@app.route('/users/all')
def display_users():
    conn, cursor = create_or_connect_database()
    if not conn or not cursor:
        return "Database Error", 500
    
    try:
        cursor.execute('SELECT * FROM users ORDER BY created_at DESC')
        users = cursor.fetchall()
        
        user_list = []
        for user in users:
            user_dict = {
                'id': user[0],
                'numeric_id': user[1],
                'username': user[2],
                'telegram_user_id': user[3],
                'special_link': user[4],
                'created_at': user[5],
                'profile_photo': get_user_profile_photo(user[3])
            }
            user_list.append(user_dict)
            
        return {'users': user_list}
    finally:
        conn.close()

# Flask webhook route
@bot.message_handler(func=lambda message: True)
def echo_all(message):
    bot.reply_to(message, message.text)

if __name__ == "__main__":
    # Set up logging
    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
    logger = logging.getLogger(__name__)
    
    # Create database tables
    create_or_connect_database()
    
    # Start bot polling in a separate thread
    import threading
    bot_thread = threading.Thread(target=bot.polling, kwargs={'none_stop': True})
    bot_thread.start()
    
    # Run Flask app
    app.run(host='0.0.0.0', port=5000)
