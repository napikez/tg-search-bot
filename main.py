import asyncio
import os
import re
import uuid
import logging
from aiohttp import web
from aiogram import Bot, Dispatcher, Router, F, BaseMiddleware
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command, CommandStart
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.contacts import SearchRequest
from telethon.tl.functions.channels import GetFullChannelRequest

import db

# Настройка логирования, чтобы видеть действия юзеров в консоли Render
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

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
        user = event.from_user
        user_id = user.id
        
        # Логируем входящее сообщение или действие от любого юзера
        if isinstance(event, Message) and event.text:
            logger.info(f"USER ID: {user_id} | Username: @{user.username or 'None'} | Name: {user.first_name} | Text: {event.text}")

        if user_id not in ALLOWED_USERS and user_id != ADMIN_ID:
            if isinstance(event, Message):
                logger.warning(f"BLOCKED ACCESS FOR USER ID: {user_id} (@{user.username})")
                await event.answer(f"У вас нет доступа к боту.\nВаш ID: <code>{user_id}</code>\n\nПередайте его администратору.")
            elif isinstance(event, CallbackQuery):
                await event.answer("Нет доступа!", show_alert=True)
            return
        return await handler(event, data)

dp.message.middleware(AccessMiddleware())
dp.callback_query.middleware(AccessMiddleware())

# search_sessions/posts_sessions хранят состояние конкретного поиска конкретного юзера,
# чтобы кнопки "Назад/Далее" знали, что и с какой страницы листать.
# Ключ — короткий sid (первые 8 символов uuid4), а не весь запрос,
# так как callback_data в Telegram ограничен 64 байтами.
search_sessions = {}
posts_sessions = {}

PAGE_SIZE = 7          # каналов на страницу
POSTS_PAGE_SIZE = 3    # постов на страницу
LIVE_SEARCH_LIMIT = 50 # максимум, что реально отдаёт contacts.SearchRequest за раз
CONTACT_CHECK_DELAY = 1.2   # пауза между проверками контакта, чтобы не словить FloodWait
MESSAGE_SCAN_LIMIT = 150    # сколько последних постов канала пролистать в поисках контакта

# Слова-маркеры рядом с которыми @username в описании — почти наверняка контакт для связи,
# а не просто упоминание какого-то другого канала/человека.
CONTACT_MARKERS = re.compile(
    r'(реклам|по вопрос|связ|контакт|сотрудничеств|manager|admin|владелец|заказ|by[:\s]|автор)',
    re.IGNORECASE
)
MENTION_RE = re.compile(r'@([a-zA-Z0-9_]{4,32})')

def extract_contact(about_text, own_username):
    """
    Ищет в описании канала username, который похож на контакт для связи.
    Это эвристика: Telegram не даёт официального поля "контакт админа",
    поэтому 100% гарантии нет — только явное упоминание в тексте описания.
    """
    if not about_text:
        return None

    own = (own_username or '').lower()
    mentions = [m for m in MENTION_RE.findall(about_text) if m.lower() != own]
    if not mentions:
        return None

    # Приоритет — упоминание рядом с маркерным словом
    for line in about_text.split('\n'):
        if CONTACT_MARKERS.search(line):
            line_mentions = [m for m in MENTION_RE.findall(line) if m.lower() != own]
            if line_mentions:
                return line_mentions[0]

    # Фолбэк — если маркеров нет, но упоминание вообще есть в описании
    return mentions[0]

async def scan_messages_for_contact(chat, own_username, limit=MESSAGE_SCAN_LIMIT):
    """
    Пролистывает последние посты канала и ищет в тексте упоминание контакта
    по тем же маркерам, что и в описании (реклама/связь/по вопросам и т.п.).
    Используется как фолбэк, когда в описании канала контакта нет —
    администраторы часто пишут его отдельным закреплённым постом.
    """
    try:
        async for m in userbot.iter_messages(chat, limit=limit):
            if not m.text:
                continue
            contact = extract_contact(m.text, own_username)
            if contact:
                return contact
    except Exception as e:
        logger.warning(f"Message scan failed for @{own_username}: {e}")
    return None

def clean_html(text):
    if not text: return ""
    return re.sub(r'<[^>]+>', '', text).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

def build_channels_page_text(keyword, channels, page, total_pages, total_found):
    start = page * PAGE_SIZE
    page_items = channels[start:start + PAGE_SIZE]
    text = (
        f"Результаты по запросу: <b>{keyword}</b>\n"
        f"Найдено с контактом: {total_found} | Страница {page + 1}/{total_pages}\n\n"
    )
    for c in page_items:
        text += (
            f"<b>{c['title']}</b>\n"
            f"Username: @{c['username']}\n"
            f"Подписчиков: {c['count']}\n"
            f"Контакт: @{c['contact']}\n"
            f"Ссылка: https://t.me/{c['username']}\n"
            + "-" * 30 + "\n"
        )
    return text

def build_pagination_kb(prefix, sid, page, total_pages):
    row = []
    if page > 0:
        row.append(InlineKeyboardButton(text="Назад", callback_data=f"{prefix}:{sid}:{page - 1}"))
    if page < total_pages - 1:
        row.append(InlineKeyboardButton(text="Далее", callback_data=f"{prefix}:{sid}:{page + 1}"))
    buttons = [row] if row else []
    buttons.append([InlineKeyboardButton(text="В меню", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

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
    logger.info(f"ADMIN gave access to user ID: {uid}")
    await message.answer(f"Пользователь <code>{uid}</code> получил доступ.")

@router.message(Command("unallow"))
async def unallow_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer("Формат удаления доступа: <code>/unallow 12345678</code>")
        return
    uid = int(args[1])
    if uid == ADMIN_ID:
        await message.answer("Нельзя забрать доступ у главного администратора!")
        return
    if uid in ALLOWED_USERS:
        ALLOWED_USERS.remove(uid)
        save_users()
        logger.info(f"ADMIN removed access for user ID: {uid}")
        await message.answer(f"❌ Пользователь <code>{uid}</code> лишен доступа к боту.")
    else:
        await message.answer("Этот пользователь не найден в списке доступов.")

@router.message(Command("showusers"))
async def showusers_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    users_list = "\n".join([f"• <code>{uid}</code>" for uid in ALLOWED_USERS])
    await message.answer(f"📋 <b>Список пользователей с доступом:</b>\n\n{users_list}")

@router.message(Command("stats"))
async def stats_cmd(message: Message):
    total = await db.total_channels_count()
    with_contact = await db.total_with_contact_count()
    await message.answer(
        f"В базе всего каналов: <b>{total}</b>\n"
        f"Из них с найденным контактом в описании: <b>{with_contact}</b>"
    )

@router.message(Command("logs"))
async def logs_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("⚙️ Логирование активно. Все действия пользователей отображаются в консоли Render в реальном времени.")

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
    keyword = args[1].lower().strip()
    msg = await message.answer("Поиск...")

    try:
        # 1. Живой запрос к Telegram — берём максимум, что вообще отдаёт SearchRequest
        result = await userbot(SearchRequest(q=keyword, limit=LIVE_SEARCH_LIMIT))
        live_channels = {}
        for chat in result.chats:
            username = getattr(chat, 'username', None)
            if username:
                live_channels[username] = chat
                await db.upsert_channel(
                    username=username,
                    title=clean_html(chat.title),
                    participants_count=getattr(chat, 'participants_count', None),
                    keyword=keyword,
                )

        # 2. Для новых (ещё не проверенных) каналов лезем в полную инфу и парсим
        # описание на предмет контакта. Уже проверенные — не трогаем повторно,
        # чтобы не пересчитывать одно и то же и не ловить FloodWait.
        to_check = await db.get_unchecked_usernames(list(live_channels.keys()))
        if to_check:
            await msg.edit_text(
                f"Поиск... проверяю контакты в {len(to_check)} новых каналах "
                f"(описание + последние посты, может занять время)."
            )
        for username in to_check:
            try:
                chat = live_channels[username]
                full = await userbot(GetFullChannelRequest(channel=chat))
                about = getattr(full.full_chat, 'about', '') or ''
                contact = extract_contact(about, username)

                # Если в описании контакта нет — пробуем найти его в постах канала
                if not contact:
                    contact = await scan_messages_for_contact(chat, username)

                await db.set_contact_info(username, contact)
            except Exception as e:
                logger.warning(f"Contact check failed for @{username}: {e}")
                await db.set_contact_info(username, None)
            await asyncio.sleep(CONTACT_CHECK_DELAY)

        # 3. Читаем накопленную базу — только каналы, где контакт найден
        channels = await db.search_channels(keyword, contacts_only=True)

        if not channels:
            await msg.edit_text(
                "Каналов с явным контактом в описании не найдено.\n"
                "Попробуйте другое слово — база пополняется с каждым поиском."
            )
            return

        sid = uuid.uuid4().hex[:8]
        search_sessions[sid] = {"keyword": keyword, "user_id": message.from_user.id}

        total_pages = max(1, (len(channels) + PAGE_SIZE - 1) // PAGE_SIZE)
        text = build_channels_page_text(keyword, channels, 0, total_pages, len(channels))
        kb = build_pagination_kb("search", sid, 0, total_pages)

        await msg.edit_text(text, reply_markup=kb, disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"Search error: {e}")
        await msg.edit_text("Ошибка поиска.")

@router.callback_query(F.data.startswith("search:"))
async def search_page_cb(call: CallbackQuery):
    _, sid, page_str = call.data.split(":")
    page = int(page_str)

    session = search_sessions.get(sid)
    if not session:
        await call.answer("Сессия поиска устарела, выполните /search заново.", show_alert=True)
        return

    keyword = session["keyword"]
    channels = await db.search_channels(keyword, contacts_only=True)
    total_pages = max(1, (len(channels) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))

    text = build_channels_page_text(keyword, channels, page, total_pages, len(channels))
    kb = build_pagination_kb("search", sid, page, total_pages)

    await call.message.edit_text(text, reply_markup=kb, disable_web_page_preview=True)
    await call.answer()

def build_posts_page_text(channel, keyword, posts, page, total_pages):
    start = page * POSTS_PAGE_SIZE
    page_items = posts[start:start + POSTS_PAGE_SIZE]
    text = (
        f"Посты из <b>@{channel}</b> по слову <b>{keyword}</b>\n"
        f"Страница {page + 1}/{total_pages}\n\n"
    )
    for p in page_items:
        text += (
            f"Дата: {p['date']}\n{p['text']}...\n"
            f"Оригинал: https://t.me/{channel}/{p['id']}\n"
            + "-" * 30 + "\n"
        )
    return text

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
        # Лимит поднят до 200 сообщений истории канала на просмотр,
        # результат постранично листается уже без повторных запросов к Telegram.
        async for m in userbot.iter_messages(channel, search=keyword, limit=200):
            if m.text:
                posts.append({'text': clean_html(m.text)[:200], 'id': m.id, 'date': m.date.strftime("%d.%m.%Y")})

        if not posts:
            await msg.edit_text("Посты не найдены. Попробуйте другое слово.")
            return

        sid = uuid.uuid4().hex[:8]
        posts_sessions[sid] = {"channel": channel, "keyword": keyword, "posts": posts}

        total_pages = max(1, (len(posts) + POSTS_PAGE_SIZE - 1) // POSTS_PAGE_SIZE)
        text = build_posts_page_text(channel, keyword, posts, 0, total_pages)
        kb = build_pagination_kb("posts", sid, 0, total_pages)

        await msg.edit_text(text, disable_web_page_preview=True, reply_markup=kb)
    except Exception as e:
        logger.error(f"Posts error: {e}")
        await msg.edit_text("Ошибка. Возможно, канал частный.")

@router.callback_query(F.data.startswith("posts:"))
async def posts_page_cb(call: CallbackQuery):
    _, sid, page_str = call.data.split(":")
    page = int(page_str)

    session = posts_sessions.get(sid)
    if not session:
        await call.answer("Сессия поиска устарела, выполните /posts заново.", show_alert=True)
        return

    posts = session["posts"]
    total_pages = max(1, (len(posts) + POSTS_PAGE_SIZE - 1) // POSTS_PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))

    text = build_posts_page_text(session["channel"], session["keyword"], posts, page, total_pages)
    kb = build_pagination_kb("posts", sid, page, total_pages)

    await call.message.edit_text(text, disable_web_page_preview=True, reply_markup=kb)
    await call.answer()

@router.callback_query(F.data == "menu")
async def menu_cb(call: CallbackQuery):
    await call.message.edit_text("Используйте <code>/search</code> или <code>/posts</code>.")

async def ping_handler(request):
    return web.Response(text="Bot is alive")

async def main():
    dp.include_router(router)
    await db.init_db()
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
