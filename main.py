import asyncio
import os
import re
from aiohttp import web
from aiogram import Bot, Dispatcher, Router, F, BaseMiddleware
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command, CommandStart
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.contacts import SearchRequest

BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = int(os.getenv("API_ID", 0))
API_HASH = os.getenv("API_HASH")
SESSION_STRING = os.getenv("SESSION_STRING")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
router = Router()
userbot = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)

START_GIF_URL = "https://i.postimg.cc/Y0z1tvpv/pinnsaver-c4f2378bff1a8783e55571f6099484da.gif"

ALLOWED_USERS = {ADMIN_ID}
if os.path.exists("users.txt"):
    with open("users.txt", "r") as f:
        for line in f:
            if line.strip().isdigit():
                ALLOWED_USERS.add(int(line.strip()))

def save_users():
    with open("users.txt", "w") as f:
        for uid in ALLOWED_USERS:
            f.write(f"{uid}\n")

class AccessMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user_id = event.from_user.id
        if user_id not in ALLOWED_USERS and user_id != ADMIN_ID:
            if isinstance(event, Message):
                await event.answer(f"У вас нет доступа к боту.\nВаш ID: <code>{user_id}</code>\n\nПередайте его администратору.")
            elif isinstance(event, CallbackQuery):
                await event.answer("Нет доступа!", show_alert=True)
            return
        return await handler(event, data)

dp.message.middleware(AccessMiddleware())
dp.callback_query.middleware(AccessMiddleware())

search_cache = {}

def clean_html(text):
    if not text: return ""
    return re.sub(r'<[^>]+>', '', text).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

@router.message(Command("allow"))
async def allow_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer("Формат выдачи доступа: <code>/allow 12345678</code>")
        return
    uid = int(args[1])
    ALLOWED_USERS.add(uid)
    save_users()
    await message.answer(f"Пользователь <code>{uid}</code> получил доступ.")

@router.message(CommandStart())
async def start_cmd(message: Message):
    user_name = clean_html(message.from_user.first_name)
    text = (
        f"Hello my friend {user_name}\n\n"
        "Команды (нажми, чтобы скопировать):\n"
        "<code>/search</code> [слово] — поиск каналов.\n"
        "<code>/posts</code> [канал] [слово] — поиск постов.\n\n"
        "Admin: @xurder / @lurder"
    )
    try:
        await message.answer_animation(animation=START_GIF_URL, caption=text)
    except Exception:
        await message.answer(text)

@router.message(Command("search"))
async def search_cmd(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Пример: <code>/search технологии</code>")
        return
    keyword = args[1].lower()
    msg = await message.answer("Поиск...")
    
    try:
        result = await userbot(SearchRequest(q=keyword, limit=5))
        channels = []
        for chat in result.chats:
            if getattr(chat, 'username', None):
                channels.append({
                    'title': clean_html(chat.title),
                    'username': chat.username,
                    'count': getattr(chat, 'participants_count', 'Неизвестно')
                })
        
        if not channels:
            await msg.edit_text("Ничего не найдено.")
            return
            
        search_cache[keyword] = channels
        
        text = f"Результаты по запросу: <b>{keyword}</b>\n\n"
        for c in channels:
            text += f"<b>{c['title']}</b>\nUsername: @{c['username']}\nСсылка: https://t.me/{c['username']}\n" + "-"*30 + "\n"
            
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="В меню", callback_data="menu")]])
        await msg.edit_text(text, reply_markup=kb)
    except Exception as e:
        await msg.edit_text("Ошибка поиска.")

@router.message(Command("posts"))
async def posts_cmd(message: Message):
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.answer("Пример: <code>/posts durov telegram</code>")
        return
    channel = args[1].replace('@', '')
    keyword = args[2]
    msg = await message.answer("Поиск постов...")
    
    try:
        posts = []
        async for m in userbot.iter_messages(channel, search=keyword, limit=3):
            if m.text:
                posts.append({'text': clean_html(m.text)[:200], 'id': m.id, 'date': m.date.strftime("%d.%m.%Y")})
        
        if not posts:
            await msg.edit_text("Посты не найдены.")
            return
            
        text = f"Посты из <b>@{channel}</b> по слову <b>{keyword}</b>:\n\n"
        for p in posts:
            text += f"Дата: {p['date']}\n{p['text']}...\nОригинал: https://t.me/{channel}/{p['id']}\n" + "-"*30 + "\n"
            
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="В меню", callback_data="menu")]])
        await msg.edit_text(text, disable_web_page_preview=True, reply_markup=kb)
    except Exception:
        await msg.edit_text("Ошибка. Возможно, канал частный.")

@router.callback_query(F.data == "menu")
async def menu_cb(call: CallbackQuery):
    await call.message.edit_text("Используйте <code>/search</code> или <code>/posts</code>.")

async def ping_handler(request):
    return web.Response(text="Bot is alive")

async def main():
    dp.include_router(router)
    await userbot.start()
    
    app = web.Application()
    app.router.add_get('/', ping_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    
    try:
        await dp.start_polling(bot)
    finally:
        await userbot.disconnect()
        await bot.session.close()
        await runner.cleanup()

if __name__ == "__main__":
    asyncio.run(main())
