import os
import logging
import sqlite3
import time
from typing import Dict, List
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, 
    CommandHandler, 
    MessageHandler, 
    CallbackQueryHandler,
    ContextTypes,
    filters
)

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Глобальные переменные
BOT_USERNAME = ""
CHANNEL_ID = "-1002573803802"
ADMIN_CHAT_IDS = [int(id.strip()) for id in os.getenv('ADMIN_CHAT_IDS', '').split(',') if id.strip()]

# Инициализация базы данных
def init_db():
    with sqlite3.connect("messages.db") as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY,
                type TEXT,
                text TEXT,
                file_id TEXT,
                caption TEXT,
                status TEXT DEFAULT 'pending'
            )
        """)
        db.commit()

def get_next_id():
    with sqlite3.connect("messages.db") as db:
        cursor = db.execute("SELECT MAX(id) FROM messages")
        max_id = cursor.fetchone()[0]
        return (max_id or 0) + 1

def save_message(msg_id, msg_data):
    with sqlite3.connect("messages.db") as db:
        db.execute("""
            INSERT INTO messages (id, type, text, file_id, caption, status)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (msg_id, msg_data['type'], msg_data.get('text'), msg_data.get('file_id'), msg_data.get('caption'), 'pending'))
        db.commit()

def load_message(msg_id):
    with sqlite3.connect("messages.db") as db:
        cursor = db.execute("SELECT * FROM messages WHERE id = ?", (msg_id,))
        row = cursor.fetchone()
        if row:
            return {'type': row[1], 'text': row[2], 'file_id': row[3], 'caption': row[4], 'status': row[5]}
        return None

def update_message_status(msg_id, status):
    with sqlite3.connect("messages.db") as db:
        db.execute("UPDATE messages SET status = ? WHERE id = ?", (status, msg_id))
        db.commit()

# Клавиатура для админа
def get_admin_keyboard(msg_id: int, content_type: str):
    keyboard = [
        [
            InlineKeyboardButton("✅ Принять", callback_data=f"approve_{msg_id}_{content_type}"),
            InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{msg_id}")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

# Вспомогательные функции для сообщений
def create_text_admin_message(user, text):
    return (
        f"🔒 Новое текстовое сообщение:\n\n"
        f"👤 От: {user.first_name}\n"
        f"🆔 ID: {user.id}\n"
        f"📧 @{user.username if user.username else 'нет'}\n\n"
        f"💬 Текст: {text}"
    )

def create_media_admin_message(user, media_type):
    return (
        f"🔒 Новое медиа-сообщение:\n\n"
        f"👤 От: {user.first_name}\n"
        f"🆔 ID: {user.id}\n"
        f"📧 @{user.username if user.username else 'нет'}\n\n"
        f"📦 Тип: {media_type}"
    )

async def send_media_content(context, chat_id, content_type, file_id, caption, msg_id):
    if content_type == "photo":
        await context.bot.send_photo(
            chat_id=chat_id,
            photo=file_id,
            caption=caption,
            reply_markup=get_admin_keyboard(msg_id, content_type)
        )
    elif content_type == "video":
        await context.bot.send_video(
            chat_id=chat_id,
            video=file_id,
            caption=caption,
            reply_markup=get_admin_keyboard(msg_id, content_type)
        )
    elif content_type == "animation":
        await context.bot.send_animation(
            chat_id=chat_id,
            animation=file_id,
            caption=caption,
            reply_markup=get_admin_keyboard(msg_id, content_type)
        )

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    welcome_text = (
        "👋 Привет! Я бот для красного диспатча.\n\n"
        "📨 Просто отправь мне сообщение, и я передам его владельцу канала.\n"
        "🔒 Все сообщения полностью анонимны.\n\n"
        "⚡️ Напиши что-нибудь, чтобы начать!"
    )
    
    await update.message.reply_text(welcome_text)

# Обработка всех типов сообщений
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    try:
        # Определяем тип контента
        if update.message.text:
            content_type = "text"
            content = update.message.text
            admin_message = create_text_admin_message(user, content)
            msg_data = {'type': 'text', 'text': content}
            
        elif update.message.photo:
            content_type = "photo" 
            content = update.message.photo[-1].file_id
            admin_message = create_media_admin_message(user, "📷 Фото")
            msg_data = {'type': 'photo', 'file_id': content, 'caption': update.message.caption or ''}
            
        elif update.message.video:
            content_type = "video"
            content = update.message.video.file_id
            admin_message = create_media_admin_message(user, "🎥 Видео")
            msg_data = {'type': 'video', 'file_id': content, 'caption': update.message.caption or ''}
            
        elif update.message.animation:
            content_type = "animation"
            content = update.message.animation.file_id
            admin_message = create_media_admin_message(user, "🎬 GIF")
            msg_data = {'type': 'animation', 'file_id': content, 'caption': update.message.caption or ''}
            
        else:
            await update.message.reply_text("❌ Этот тип сообщения не поддерживается.")
            return
        
        # Сохраняем в базу данных
        msg_id = get_next_id()
        save_message(msg_id, msg_data)
        
        # Отправляем админам
        for admin_id in ADMIN_CHAT_IDS:
            if content_type == "text":
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=admin_message,
                    reply_markup=get_admin_keyboard(msg_id, content_type),
                    parse_mode='HTML'
                )
            else:
                await send_media_content(context, admin_id, content_type, content, admin_message, msg_id)
        
        await update.message.reply_text("✅ Сообщение отправлено на модерацию!")
        
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        await update.message.reply_text("❌ Ошибка отправки.")

# Обработка кнопок модерации
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    parts = data.split('_')
    
    if data.startswith('approve_'):
        msg_id = int(parts[1])
        content_type = parts[2]
        
        # Загружаем сообщение из базы
        msg_data = load_message(msg_id)
        if not msg_data:
            await query.answer("❌ Сообщение не найдено!", show_alert=True)
            return
        
        # Проверяем не было ли уже отправлено
        if msg_data['status'] != 'pending':
            await query.answer("❌ Сообщение уже было обработано!", show_alert=True)
            return
        
        # Отправляем в канал
        try:
            if content_type == "text":
                await context.bot.send_message(
                    chat_id=CHANNEL_ID,
                    text=f"📨 Анонимное сообщение:\n\n<blockquote>{msg_data['text']}</blockquote>\n\n👉 <a href=\"https://t.me/dispatchbdl_bot?start=send\">Отправить своё сообщение</a>",
                    parse_mode='HTML'
                )
            elif content_type == "photo":
                await context.bot.send_photo(
                    chat_id=CHANNEL_ID,
                    photo=msg_data['file_id'],
                    caption=f"📨 Анонимное сообщение\n\n{msg_data.get('caption', '')}\n\n👉 <a href=\"https://t.me/dispatchbdl_bot?start=send\">Отправить своё сообщение</a>",
                    parse_mode='HTML'
                )
            elif content_type == "video":
                await context.bot.send_video(
                    chat_id=CHANNEL_ID,
                    video=msg_data['file_id'],
                    caption=f"📨 Анонимное сообщение\n\n{msg_data.get('caption', '')}\n\n👉 <a href=\"https://t.me/dispatchbdl_bot?start=send\">Отправить своё сообщение</a>",
                    parse_mode='HTML'
                )
            elif content_type == "animation":
                await context.bot.send_animation(
                    chat_id=CHANNEL_ID,
                    animation=msg_data['file_id'],
                    caption=f"📨 Анонимное сообщение\n\n{msg_data.get('caption', '')}\n\n👉 <a href=\"https://t.me/dispatchbdl_bot?start=send\">Отправить своё сообщение</a>",
                    parse_mode='HTML'
                )
            
            # Обновляем статус в базе
            update_message_status(msg_id, 'approved')
            
            # Обновляем сообщение у админа
            await query.edit_message_text(
                text=query.message.text + "\n\n✅ Опубликовано в канале!",
                reply_markup=None
            )
            
        except Exception as e:
            logger.error(f"Ошибка отправки в канал: {e}")
            await query.answer("❌ Ошибка отправки в канал!", show_alert=True)
    
    elif data.startswith('reject_'):
        msg_id = int(parts[1])
        
        # Обновляем статус в базе
        update_message_status(msg_id, 'rejected')
        
        await query.edit_message_text(
            text=query.message.text + "\n\n❌ Сообщение отклонено.",
            reply_markup=None
        )

# Инициализация бота
async def post_init(application: Application):
    global BOT_USERNAME
    init_db()
    bot_info = await application.bot.get_me()
    BOT_USERNAME = bot_info.username
    print(f"🤖 Бот @{BOT_USERNAME} запущен!")
    print(f"👥 Админы: {ADMIN_CHAT_IDS}")
    print(f"📢 Канал: {CHANNEL_ID}")

# Основная функция
def main():
    application = Application.builder().token(os.getenv('BOT_TOKEN')).post_init(post_init).build()
    
    # Обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.ANIMATION, handle_message))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    print("🟢 Бот запускается...")
    application.run_polling()

if __name__ == "__main__":
    main()