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
from pathlib import Path

# تنظیمات اصلی
BOT_TOKEN = '7743246613:AAFQPgQOQqRpCG3HtD7Ly-o8VAm-P6O0cEM'
BOT_USERNAME = 'aecvfaecvasbot'
DOMAIN = 'https://ideal-pangolin-solely.ngrok-free.app'

# تنظیمات Flask
app = Flask(__name__, template_folder='templates', static_folder='static')
app.config['SECRET_KEY'] = os.urandom(24)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

# تنظیمات Telegram bot
bot = telebot.TeleBot(BOT_TOKEN)

# تنظیمات مسیرها و دیتابیس
BASE_PATH = Path(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = BASE_PATH / 'user_database.db'

# ذخیره اتصال‌ها
class ConnectionManager:
    def __init__(self):
        self.active_connections = {}
        self.pending_connections = {}
        self._logger = logging.getLogger(__name__)
        
    def add_pending(self, requester_id, owner_id):
        self._logger.info(f"Adding pending connection: {requester_id} -> {owner_id}")
        self.pending_connections[requester_id] = owner_id
        self._logger.info(f"Current pending connections: {self.pending_connections}")
        
    def remove_pending(self, requester_id):
        self._logger.info(f"Removing pending connection for: {requester_id}")
        if requester_id in self.pending_connections:
            del self.pending_connections[requester_id]
            self._logger.info("Pending connection removed")
        self._logger.info(f"Current pending connections: {self.pending_connections}")
            
    def get_pending_owner(self, requester_id):
        return self.pending_connections.get(requester_id)
        
    def connect_users(self, user1_id, user2_id):
        self._logger.info(f"Connecting users: {user1_id} <-> {user2_id}")
        self.active_connections[user1_id] = user2_id
        self.active_connections[user2_id] = user1_id
        self._logger.info(f"Current active connections: {self.active_connections}")
        
    def disconnect_users(self, user_id):
        self._logger.info(f"Disconnecting user: {user_id}")
        if user_id in self.active_connections:
            other_user = self.active_connections[user_id]
            if other_user in self.active_connections:
                del self.active_connections[other_user]
            del self.active_connections[user_id]
            self._logger.info(f"Users disconnected. Current active connections: {self.active_connections}")
            return other_user
        return None
        
    def get_connected_user(self, user_id):
        return self.active_connections.get(user_id)
        
    def is_connected(self, user_id):
        return user_id in self.active_connections
        
    def find_pending_request(self, owner_id):
        self._logger.info(f"Finding pending request for owner: {owner_id}")
        self._logger.info(f"Current pending connections: {self.pending_connections}")
        for req_id, own_id in self.pending_connections.items():
            if own_id == owner_id:
                self._logger.info(f"Found pending request: {req_id}")
                return req_id
        self._logger.info("No pending request found")
        return None

    def get_all_pending(self):
        return self.pending_connections.copy()

# ایجاد نمونه از مدیریت اتصال
connections = ConnectionManager()

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
    web_app_info = types.WebAppInfo(url=f"{DOMAIN}/users?telegram_user_id={user_id}")
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
                
                # بررسی اتصال فعلی
                if connections.is_connected(message.from_user.id):
                    bot.reply_to(message, "⚠️ شما در حال حاضر در یک چت هستید! ابتدا آن را قطع کنید.")
                    return
                    
                if connections.is_connected(owner[0]):
                    bot.reply_to(message, "⚠️ کاربر مورد نظر در حال حاضر در چت است!")
                    return
                    
                connections.add_pending(message.from_user.id, owner[0])
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

@bot.message_handler(func=lambda message: message.text and message.text.startswith('/start '))
def handle_deep_linking(message):
    logger = logging.getLogger(__name__)
    logger.info(f"Deep linking handler called for user {message.from_user.id}")
    
    try:
        # دریافت شناسه کاربر هدف از پارامتر
        target_id = message.text.split()[1]
        requester_id = message.from_user.id
        
        logger.info(f"Processing deep link: requester={requester_id}, target={target_id}")
        
        # تبدیل به عدد
        target_id = int(target_id)
        
        if target_id == requester_id:
            bot.reply_to(message, "❌ شما نمی‌توانید با خودتان چت کنید!")
            return
            
        if connections.is_connected(requester_id):
            bot.reply_to(message, "⚠️ شما در حال حاضر در یک چت فعال هستید!")
            return
            
        # بررسی وجود درخواست قبلی
        existing_request = connections.get_pending_owner(requester_id)
        if existing_request:
            logger.info(f"Found existing request for {requester_id} -> {existing_request}")
            bot.reply_to(message, "⚠️ شما قبلاً یک درخواست ارسال کرده‌اید!")
            return
            
        # ذخیره درخواست
        connections.add_pending(requester_id, target_id)
        logger.info(f"Added new pending request: {requester_id} -> {target_id}")
        logger.info(f"Current pending connections: {connections.get_all_pending()}")
        
        # ارسال پیام به کاربر هدف
        keyboard = types.InlineKeyboardMarkup()
        accept_button = types.InlineKeyboardButton("✅ پذیرش", callback_data="accept_connection")
        reject_button = types.InlineKeyboardButton("❌ رد", callback_data="reject_connection")
        keyboard.add(accept_button, reject_button)
        
        try:
            bot.send_message(
                target_id,
                "⚡️ درخواستی برای پذیرش یافت شد!",
                reply_markup=keyboard
            )
            bot.reply_to(message, "✅ درخواست شما ارسال شد!")
            logger.info("Request message sent successfully")
        except Exception as e:
            logger.error(f"Error sending request message: {str(e)}")
            connections.remove_pending(requester_id)
            bot.reply_to(message, "❌ خطا در ارسال درخواست! لطفاً دوباره تلاش کنید.")
            
    except ValueError:
        logger.error("Invalid target_id format")
        bot.reply_to(message, "❌ لینک نامعتبر است!")
    except Exception as e:
        logger.error(f"Error in deep linking: {str(e)}")
        bot.reply_to(message, "❌ خطایی رخ داد! لطفاً دوباره تلاش کنید.")

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    logger = logging.getLogger(__name__)
    try:
        user_id = call.from_user.id
        logger.info(f"Received callback from user {user_id}: {call.data}")
        
        if call.data == "accept_connection":
            logger.info("Processing accept_connection")
            logger.info(f"All pending connections before processing: {connections.get_all_pending()}")
            
            requester_id = connections.find_pending_request(user_id)
            logger.info(f"Found requester_id: {requester_id}")
            
            if requester_id:
                # اول پیام تایید رو به کاربر نشون بدیم
                bot.answer_callback_query(call.id, "✅ درخواست پذیرفته شد")
                
                # حذف درخواست از لیست انتظار
                connections.remove_pending(requester_id)
                logger.info(f"Removed pending request. Current pending: {connections.get_all_pending()}")
                
                # اتصال کاربران
                connections.connect_users(user_id, requester_id)
                logger.info(f"Connected users. Active connections: {connections.active_connections}")
                
                try:
                    # ارسال پیام به درخواست‌دهنده
                    bot.send_message(
                        requester_id,
                        "✨ درخواست چت شما پذیرفته شد!\n\n💭 حالا می‌توانید پیام‌های خود را ارسال کنید.",
                        reply_markup=create_disconnect_button()
                    )
                    
                    # ارسال پیام به پذیرنده
                    bot.send_message(
                        user_id,
                        "🤝 شما درخواست چت را پذیرفتید!\n\n💭 حالا می‌توانید پیام‌های خود را ارسال کنید.",
                        reply_markup=create_disconnect_button()
                    )
                    
                    logger.info(f"Connection established between {user_id} and {requester_id}")
                    
                except Exception as e:
                    logger.error(f"Error sending confirmation messages: {str(e)}")
                    connections.disconnect_users(user_id)  # در صورت خطا اتصال رو قطع می‌کنیم
                    bot.send_message(user_id, "❌ خطا در برقراری ارتباط! لطفاً دوباره تلاش کنید.")
            else:
                logger.warning(f"No pending request found for user {user_id}")
                bot.answer_callback_query(call.id, "❌ درخواستی یافت نشد")
                bot.send_message(user_id, "⚠️ درخواستی برای پذیرش یافت نشد!")
                
        elif call.data == "reject_connection":
            bot.answer_callback_query(call.id, "❌ درخواست رد شد")
            requester_id = connections.get_pending_owner(user_id)
            
            if requester_id:
                connections.remove_pending(requester_id)
                bot.send_message(requester_id, "😔 متأسفانه درخواست چت شما پذیرفته نشد.\n\n✨ می‌توانید با کاربران دیگر گفتگو کنید!")
                bot.edit_message_text(
                    "🚫 شما این درخواست چت را رد کردید.",
                    call.message.chat.id,
                    call.message.message_id
                )
                
        elif call.data == "disconnect":
            bot.answer_callback_query(call.id, "❌ قطع ارتباط")
            other_user = connections.disconnect_users(user_id)
            
            if other_user:
                bot.send_message(user_id, "❌ چت پایان یافت!\n\n🌟 امیدواریم از این گفتگو لذت برده باشید.\n✨ می‌توانید دوباره با کاربران دیگر چت کنید!")
                bot.send_message(other_user, "❌ کاربر مقابل چت را پایان داد.\n\n🌟 امیدواریم از این گفتگو لذت برده باشید.\n✨ می‌توانید دوباره با کاربران دیگر چت کنید!")
                
    except Exception as e:
        logger.error(f"Error in callback handler: {str(e)}")
        bot.answer_callback_query(call.id, "❌ متأسفانه مشکلی پیش آمده! لطفاً دوباره تلاش کنید.")

@bot.message_handler(func=lambda message: True, content_types=['text', 'photo', 'video', 'document', 'audio', 'voice', 'video_note', 'sticker', 'animation'])
def handle_messages(message):
    logger = logging.getLogger(__name__)
    user_id = message.from_user.id
    
    try:
        # بررسی اتصال کاربر
        other_user = connections.get_connected_user(user_id)
        
        if other_user:
            logger.info(f"Sending message from {user_id} to {other_user}")
            
            try:
                if message.text:
                    bot.send_message(other_user, f"💬 پیام جدید:\n{message.text}")
                elif message.photo:
                    caption = message.caption if message.caption else ""
                    bot.send_photo(other_user, message.photo[-1].file_id, caption=f"🖼️ تصویر جدید:\n{caption}")
                elif message.video:
                    caption = message.caption if message.caption else ""
                    bot.send_video(other_user, message.video.file_id, caption=f"🎥 ویدیو جدید:\n{caption}")
                elif message.document:
                    caption = message.caption if message.caption else ""
                    bot.send_document(other_user, message.document.file_id, caption=f"📎 فایل جدید:\n{caption}")
                elif message.audio:
                    caption = message.caption if message.caption else ""
                    bot.send_audio(other_user, message.audio.file_id, caption=f"🎵 موزیک جدید:\n{caption}")
                elif message.voice:
                    caption = message.caption if message.caption else ""
                    bot.send_voice(other_user, message.voice.file_id, caption=f"🎤 پیام صوتی جدید:\n{caption}")
                elif message.video_note:
                    bot.send_video_note(other_user, message.video_note.file_id)
                elif message.sticker:
                    bot.send_sticker(other_user, message.sticker.file_id)
                elif message.animation:
                    caption = message.caption if message.caption else ""
                    bot.send_animation(other_user, message.animation.file_id, caption=f"✨ گیف جدید:\n{caption}")
                
            except Exception as e:
                logger.error(f"Error sending message: {str(e)}")
                bot.reply_to(message, "❌ خطا در ارسال پیام! لطفاً دوباره تلاش کنید.")
                
        else:
            bot.reply_to(message, """📝 برای شروع چت:

1️⃣ لینک اختصاصی خود را با دوستانتان به اشتراک بگذارید
2️⃣ یا از لینک دوستانتان استفاده کنید

✨ همین حالا چت را شروع کنید!""")
            
    except Exception as e:
        logger.error(f"Error in handle_messages: {str(e)}")
        bot.reply_to(message, "❌ خطایی رخ داد! لطفاً دوباره تلاش کنید.")

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
    # تنظیمات لاگینگ
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO,
        handlers=[
            logging.FileHandler(BASE_PATH / 'app.log'),
            logging.StreamHandler()
        ]
    )
    logger = logging.getLogger(__name__)
    logger.info("Starting bot...")
    
    # اطمینان از وجود دیتابیس
    conn, cursor = create_or_connect_database()
    if conn and cursor:
        conn.close()
    
    # اجرای سرور
    app.run(
        host='0.0.0.0',
        port=int(os.getenv('PORT', 5000)),
        debug=False,
        threaded=True
    )
