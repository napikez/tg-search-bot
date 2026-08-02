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
from telethon.tl.functions.messages import SearchGlobalRequest
from telethon.tl.types import User, InputMessagesFilterEmpty, InputPeerEmpty

import db
import tgstat_client

# РќР°СЃС‚СЂРѕР№РєР° Р»РѕРіРёСЂРѕРІР°РЅРёСЏ, С‡С‚РѕР±С‹ РІРёРґРµС‚СЊ РґРµР№СЃС‚РІРёСЏ СЋР·РµСЂРѕРІ РІ РєРѕРЅСЃРѕР»Рё Render
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
        
        # Р›РѕРіРёСЂСѓРµРј РІС…РѕРґСЏС‰РµРµ СЃРѕРѕР±С‰РµРЅРёРµ РёР»Рё РґРµР№СЃС‚РІРёРµ РѕС‚ Р»СЋР±РѕРіРѕ СЋР·РµСЂР°
        if isinstance(event, Message) and event.text:
            logger.info(f"USER ID: {user_id} | Username: @{user.username or 'None'} | Name: {user.first_name} | Text: {event.text}")

        if user_id not in ALLOWED_USERS and user_id != ADMIN_ID:
            if isinstance(event, Message):
                logger.warning(f"BLOCKED ACCESS FOR USER ID: {user_id} (@{user.username})")
                await event.answer(f"РЈ РІР°СЃ РЅРµС‚ РґРѕСЃС‚СѓРїР° Рє Р±РѕС‚Сѓ.\nР’Р°С€ ID: <code>{user_id}</code>\n\nРџРµСЂРµРґР°Р№С‚Рµ РµРіРѕ Р°РґРјРёРЅРёСЃС‚СЂР°С‚РѕСЂСѓ.")
            elif isinstance(event, CallbackQuery):
                await event.answer("РќРµС‚ РґРѕСЃС‚СѓРїР°!", show_alert=True)
            return
        return await handler(event, data)

dp.message.middleware(AccessMiddleware())
dp.callback_query.middleware(AccessMiddleware())

# search_sessions/posts_sessions С…СЂР°РЅСЏС‚ СЃРѕСЃС‚РѕСЏРЅРёРµ РєРѕРЅРєСЂРµС‚РЅРѕРіРѕ РїРѕРёСЃРєР° РєРѕРЅРєСЂРµС‚РЅРѕРіРѕ СЋР·РµСЂР°,
# С‡С‚РѕР±С‹ РєРЅРѕРїРєРё "РќР°Р·Р°Рґ/Р”Р°Р»РµРµ" Р·РЅР°Р»Рё, С‡С‚Рѕ Рё СЃ РєР°РєРѕР№ СЃС‚СЂР°РЅРёС†С‹ Р»РёСЃС‚Р°С‚СЊ.
# РљР»СЋС‡ вЂ” РєРѕСЂРѕС‚РєРёР№ sid (РїРµСЂРІС‹Рµ 8 СЃРёРјРІРѕР»РѕРІ uuid4), Р° РЅРµ РІРµСЃСЊ Р·Р°РїСЂРѕСЃ,
# С‚Р°Рє РєР°Рє callback_data РІ Telegram РѕРіСЂР°РЅРёС‡РµРЅ 64 Р±Р°Р№С‚Р°РјРё.
search_sessions = {}
posts_sessions = {}

PAGE_SIZE = 7          # РєР°РЅР°Р»РѕРІ РЅР° СЃС‚СЂР°РЅРёС†Сѓ
POSTS_PAGE_SIZE = 3    # РїРѕСЃС‚РѕРІ РЅР° СЃС‚СЂР°РЅРёС†Сѓ
LIVE_SEARCH_LIMIT = 50 # РјР°РєСЃРёРјСѓРј, С‡С‚Рѕ СЂРµР°Р»СЊРЅРѕ РѕС‚РґР°С‘С‚ contacts.SearchRequest Р·Р° СЂР°Р·
CONTACT_CHECK_DELAY = 1.2   # РїР°СѓР·Р° РјРµР¶РґСѓ РїСЂРѕРІРµСЂРєР°РјРё РєРѕРЅС‚Р°РєС‚Р°, С‡С‚РѕР±С‹ РЅРµ СЃР»РѕРІРёС‚СЊ FloodWait
MESSAGE_SCAN_LIMIT = 150    # СЃРєРѕР»СЊРєРѕ РїРѕСЃР»РµРґРЅРёС… РїРѕСЃС‚РѕРІ РєР°РЅР°Р»Р° РїСЂРѕР»РёСЃС‚Р°С‚СЊ РІ РїРѕРёСЃРєР°С… РєРѕРЅС‚Р°РєС‚Р°

# РЎР»РѕРІР°-РјР°СЂРєРµСЂС‹ СЂСЏРґРѕРј СЃ РєРѕС‚РѕСЂС‹РјРё @username РІ РѕРїРёСЃР°РЅРёРё вЂ” РїРѕС‡С‚Рё РЅР°РІРµСЂРЅСЏРєР° РєРѕРЅС‚Р°РєС‚ РґР»СЏ СЃРІСЏР·Рё,
# Р° РЅРµ РїСЂРѕСЃС‚Рѕ СѓРїРѕРјРёРЅР°РЅРёРµ РєР°РєРѕРіРѕ-С‚Рѕ РґСЂСѓРіРѕРіРѕ РєР°РЅР°Р»Р°/С‡РµР»РѕРІРµРєР°.
CONTACT_MARKERS = re.compile(
    r'(СЂРµРєР»Р°Рј|РїРѕ РІРѕРїСЂРѕСЃ|СЃРІСЏР·|РєРѕРЅС‚Р°РєС‚|СЃРѕС‚СЂСѓРґРЅРёС‡РµСЃС‚РІ|manager|admin|РІР»Р°РґРµР»РµС†|Р·Р°РєР°Р·|by[:\s]|Р°РІС‚РѕСЂ)',
    re.IGNORECASE
)
MENTION_RE = re.compile(r'@([a-zA-Z0-9_]{4,32})')

def extract_contact_candidates(text, own_username):
    """
    Р’РѕР·РІСЂР°С‰Р°РµС‚ РЈРџРћР РЇР”РћР§Р•РќРќР«Р™ СЃРїРёСЃРѕРє РєР°РЅРґРёРґР°С‚РѕРІ РІ РєРѕРЅС‚Р°РєС‚ РёР· С‚РµРєСЃС‚Р°:
    СЃРЅР°С‡Р°Р»Р° username СЂСЏРґРѕРј СЃ РјР°СЂРєРµСЂРЅС‹Рј СЃР»РѕРІРѕРј (РІС‹С€Рµ РїСЂРёРѕСЂРёС‚РµС‚),
    Р·Р°С‚РµРј РѕСЃС‚Р°Р»СЊРЅС‹Рµ СѓРїРѕРјРёРЅР°РЅРёСЏ. Р”СѓР±Р»РёРєР°С‚С‹ СѓР±РёСЂР°СЋС‚СЃСЏ СЃ СЃРѕС…СЂР°РЅРµРЅРёРµРј РїРѕСЂСЏРґРєР°.
    РЎРѕР±СЃС‚РІРµРЅРЅС‹Р№ username РєР°РЅР°Р»Р° РёСЃРєР»СЋС‡Р°РµС‚СЃСЏ СЃСЂР°Р·Сѓ.
    """
    if not text:
        return []

    own = (own_username or '').lower()
    ordered = []
    seen = set()

    def add(name):
        low = name.lower()
        if low != own and low not in seen:
            seen.add(low)
            ordered.append(name)

    for line in text.split('\n'):
        if CONTACT_MARKERS.search(line):
            for m in MENTION_RE.findall(line):
                add(m)

    for m in MENTION_RE.findall(text):
        add(m)

    return ordered

async def resolve_real_contact(candidates):
    """
    РР· СЃРїРёСЃРєР° РєР°РЅРґРёРґР°С‚РѕРІ РІРѕР·РІСЂР°С‰Р°РµС‚ РїРµСЂРІС‹Р№, РєРѕС‚РѕСЂС‹Р№ СЂРµР°Р»СЊРЅРѕ СЂРµР·РѕР»РІРёС‚СЃСЏ
    РІ Р»РёС‡РЅС‹Р№ Р°РєРєР°СѓРЅС‚ (User), Р° РЅРµ РІ РєР°РЅР°Р»/С‡Р°С‚/Р±РѕС‚Р° вЂ” РёРЅР°С‡Рµ С‚СѓРґР° С„РёР·РёС‡РµСЃРєРё
    РЅРµР»СЊР·СЏ РЅР°РїРёСЃР°С‚СЊ РІ Р›РЎ. Р­С‚Рѕ РѕС‚СЃРµРєР°РµС‚ СЃР»СѓС‡Р°Рё РІСЂРѕРґРµ "@AuroraTeam", РєРѕРіРґР°
    РїРѕРґ РјР°СЂРєРµСЂРЅС‹Рј СЃР»РѕРІРѕРј РЅР° СЃР°РјРѕРј РґРµР»Рµ СѓРїРѕРјСЏРЅСѓС‚ РµС‰С‘ РѕРґРёРЅ РєР°РЅР°Р»/СЃРѕРѕР±С‰РµСЃС‚РІРѕ.

    Р’Р°Р¶РЅРѕ: РґР°Р¶Рµ РїРѕРґС‚РІРµСЂР¶РґС‘РЅРЅС‹Р№ User РЅРµ РіР°СЂР°РЅС‚РёСЂСѓРµС‚, С‡С‚Рѕ Сѓ РЅРµРіРѕ РѕС‚РєСЂС‹С‚С‹ Р›РЎ вЂ”
    РїСЂРёРІР°С‚РЅРѕСЃС‚СЊ РјРѕР¶РµС‚ Р±Р»РѕРєРёСЂРѕРІР°С‚СЊ СЃРѕРѕР±С‰РµРЅРёСЏ РѕС‚ РїРѕСЃС‚РѕСЂРѕРЅРЅРёС…, Telegram API
    РЅРµ РґР°С‘С‚ РїСѓР±Р»РёС‡РЅРѕРіРѕ СЃРїРѕСЃРѕР±Р° РїСЂРѕРІРµСЂРёС‚СЊ СЌС‚Рѕ Р·Р°СЂР°РЅРµРµ Р±РµР· СЂРµР°Р»СЊРЅРѕР№ РѕС‚РїСЂР°РІРєРё.
    """
    for candidate in candidates:
        try:
            entity = await userbot.get_entity(candidate)
        except Exception:
            continue
        if isinstance(entity, User) and not entity.bot and not entity.deleted:
            return candidate
        await asyncio.sleep(0.3)  # РјР°Р»РµРЅСЊРєР°СЏ РїР°СѓР·Р° РјРµР¶РґСѓ СЂРµР·РѕР»РІР°РјРё РєР°РЅРґРёРґР°С‚РѕРІ
    return None

async def scan_messages_for_contact_candidates(chat, own_username, limit=MESSAGE_SCAN_LIMIT):
    """
    РџСЂРѕР»РёСЃС‚С‹РІР°РµС‚ РїРѕСЃР»РµРґРЅРёРµ РїРѕСЃС‚С‹ РєР°РЅР°Р»Р° Рё СЃРѕР±РёСЂР°РµС‚ РєР°РЅРґРёРґР°С‚РѕРІ РІ РєРѕРЅС‚Р°РєС‚
    РїРѕ С‚РµРј Р¶Рµ РјР°СЂРєРµСЂР°Рј, С‡С‚Рѕ Рё РІ РѕРїРёСЃР°РЅРёРё. РСЃРїРѕР»СЊР·СѓРµС‚СЃСЏ РєР°Рє РёСЃС‚РѕС‡РЅРёРє
    РґРѕРїРѕР»РЅРёС‚РµР»СЊРЅС‹С… РєР°РЅРґРёРґР°С‚РѕРІ, РєРѕРіРґР° РІ РѕРїРёСЃР°РЅРёРё РєР°РЅР°Р»Р° РЅРёС‡РµРіРѕ С‚РѕР»РєРѕРІРѕРіРѕ РЅРµС‚ вЂ”
    Р°РґРјРёРЅРёСЃС‚СЂР°С‚РѕСЂС‹ С‡Р°СЃС‚Рѕ РїРёС€СѓС‚ РєРѕРЅС‚Р°РєС‚ РѕС‚РґРµР»СЊРЅС‹Рј Р·Р°РєСЂРµРїР»С‘РЅРЅС‹Рј РїРѕСЃС‚РѕРј.
    """
    candidates = []
    seen = set()
    try:
        async for m in userbot.iter_messages(chat, limit=limit):
            if not m.text:
                continue
            for c in extract_contact_candidates(m.text, own_username):
                if c.lower() not in seen:
                    seen.add(c.lower())
                    candidates.append(c)
    except Exception as e:
        logger.warning(f"Message scan failed for @{own_username}: {e}")
    return candidates
    return None

def clean_html(text):
    if not text: return ""
    return re.sub(r'<[^>]+>', '', text).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

def build_channels_page_text(keyword, channels, page, total_pages, total_found):
    start = page * PAGE_SIZE
    page_items = channels[start:start + PAGE_SIZE]
    text = (
        f"Р РµР·СѓР»СЊС‚Р°С‚С‹ РїРѕ Р·Р°РїСЂРѕСЃСѓ: <b>{keyword}</b>\n"
        f"РќР°Р№РґРµРЅРѕ СЃ РєРѕРЅС‚Р°РєС‚РѕРј: {total_found} | РЎС‚СЂР°РЅРёС†Р° {page + 1}/{total_pages}\n\n"
    )
    for c in page_items:
        text += (
            f"<b>{c['title']}</b>\n"
            f"Username: @{c['username']}\n"
            f"РџРѕРґРїРёСЃС‡РёРєРѕРІ: {c['count']}\n"
            f"РљРѕРЅС‚Р°РєС‚: @{c['contact']}\n"
            f"РЎСЃС‹Р»РєР°: https://t.me/{c['username']}\n"
            + "-" * 30 + "\n"
        )
    return text

def build_pagination_kb(prefix, sid, page, total_pages):
    row = []
    if page > 0:
        row.append(InlineKeyboardButton(text="РќР°Р·Р°Рґ", callback_data=f"{prefix}:{sid}:{page - 1}"))
    if page < total_pages - 1:
        row.append(InlineKeyboardButton(text="Р”Р°Р»РµРµ", callback_data=f"{prefix}:{sid}:{page + 1}"))
    buttons = [row] if row else []
    buttons.append([InlineKeyboardButton(text="Р’ РјРµРЅСЋ", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

@router.message(Command("allow"))
async def allow_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer("Р¤РѕСЂРјР°С‚ РІС‹РґР°С‡Рё РґРѕСЃС‚СѓРїР°: <code>/allow 12345678</code>")
        return
    uid = int(args[1])
    ALLOWED_USERS.add(uid)
    save_users()
    logger.info(f"ADMIN gave access to user ID: {uid}")
    await message.answer(f"РџРѕР»СЊР·РѕРІР°С‚РµР»СЊ <code>{uid}</code> РїРѕР»СѓС‡РёР» РґРѕСЃС‚СѓРї.")

@router.message(Command("unallow"))
async def unallow_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer("Р¤РѕСЂРјР°С‚ СѓРґР°Р»РµРЅРёСЏ РґРѕСЃС‚СѓРїР°: <code>/unallow 12345678</code>")
        return
    uid = int(args[1])
    if uid == ADMIN_ID:
        await message.answer("РќРµР»СЊР·СЏ Р·Р°Р±СЂР°С‚СЊ РґРѕСЃС‚СѓРї Сѓ РіР»Р°РІРЅРѕРіРѕ Р°РґРјРёРЅРёСЃС‚СЂР°С‚РѕСЂР°!")
        return
    if uid in ALLOWED_USERS:
        ALLOWED_USERS.remove(uid)
        save_users()
        logger.info(f"ADMIN removed access for user ID: {uid}")
        await message.answer(f"вќЊ РџРѕР»СЊР·РѕРІР°С‚РµР»СЊ <code>{uid}</code> Р»РёС€РµРЅ РґРѕСЃС‚СѓРїР° Рє Р±РѕС‚Сѓ.")
    else:
        await message.answer("Р­С‚РѕС‚ РїРѕР»СЊР·РѕРІР°С‚РµР»СЊ РЅРµ РЅР°Р№РґРµРЅ РІ СЃРїРёСЃРєРµ РґРѕСЃС‚СѓРїРѕРІ.")

@router.message(Command("showusers"))
async def showusers_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    users_list = "\n".join([f"вЂў <code>{uid}</code>" for uid in ALLOWED_USERS])
    await message.answer(f"рџ“‹ <b>РЎРїРёСЃРѕРє РїРѕР»СЊР·РѕРІР°С‚РµР»РµР№ СЃ РґРѕСЃС‚СѓРїРѕРј:</b>\n\n{users_list}")

@router.message(Command("recheck_contacts"))
async def recheck_contacts_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    await db.reset_contact_checks()
    await message.answer(
        "Р¤Р»Р°РіРё РїСЂРѕРІРµСЂРєРё РєРѕРЅС‚Р°РєС‚РѕРІ СЃР±СЂРѕС€РµРЅС‹. РџСЂРё СЃР»РµРґСѓСЋС‰РёС… /search "
        "РєР°РЅР°Р»С‹ Р±СѓРґСѓС‚ РїРµСЂРµРїСЂРѕРІРµСЂРµРЅС‹ РїРѕ РѕР±РЅРѕРІР»С‘РЅРЅРѕР№ Р»РѕРіРёРєРµ РІРµСЂРёС„РёРєР°С†РёРё."
    )

@router.message(Command("stats"))
async def stats_cmd(message: Message):
    total = await db.total_channels_count()
    with_contact = await db.total_with_contact_count()
    await message.answer(
        f"Р’ Р±Р°Р·Рµ РІСЃРµРіРѕ РєР°РЅР°Р»РѕРІ: <b>{total}</b>\n"
        f"РР· РЅРёС… СЃ РЅР°Р№РґРµРЅРЅС‹Рј РєРѕРЅС‚Р°РєС‚РѕРј РІ РѕРїРёСЃР°РЅРёРё: <b>{with_contact}</b>"
    )

@router.message(Command("logs"))
async def logs_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("вљ™пёЏ Р›РѕРіРёСЂРѕРІР°РЅРёРµ Р°РєС‚РёРІРЅРѕ. Р’СЃРµ РґРµР№СЃС‚РІРёСЏ РїРѕР»СЊР·РѕРІР°С‚РµР»РµР№ РѕС‚РѕР±СЂР°Р¶Р°СЋС‚СЃСЏ РІ РєРѕРЅСЃРѕР»Рё Render РІ СЂРµР°Р»СЊРЅРѕРј РІСЂРµРјРµРЅРё.")

@router.message(CommandStart())
async def start_cmd(message: Message):
    user_name = clean_html(message.from_user.first_name)
    text = (
        f"Hello my friend {user_name}\n\n"
        "РљРѕРјР°РЅРґС‹ (РЅР°Р¶РјРё, С‡С‚РѕР±С‹ СЃРєРѕРїРёСЂРѕРІР°С‚СЊ):\n"
        "<code>/search</code> [СЃР»РѕРІРѕ] вЂ” РїРѕРёСЃРє РєР°РЅР°Р»РѕРІ.\n"
        "<code>/posts</code> [РєР°РЅР°Р»] [СЃР»РѕРІРѕ] вЂ” РїРѕРёСЃРє РїРѕСЃС‚РѕРІ.\n\n"
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
        await message.answer("РџСЂРёРјРµСЂ: <code>/search С‚РµС…РЅРѕР»РѕРіРёРё</code>")
        return
    keyword = args[1].lower().strip()
    msg = await message.answer("РџРѕРёСЃРє...")

    try:
        # 1. Р–РёРІРѕР№ Р·Р°РїСЂРѕСЃ Рє Telegram вЂ” Р±РµСЂС‘Рј РјР°РєСЃРёРјСѓРј, С‡С‚Рѕ РІРѕРѕР±С‰Рµ РѕС‚РґР°С‘С‚ SearchRequest
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

        # 1.05 Р‘РµСЃРїР»Р°С‚РЅРѕРµ СЂР°СЃС€РёСЂРµРЅРёРµ Р¶РёРІРѕРіРѕ РїРѕРёСЃРєР° вЂ” messages.SearchGlobal РёС‰РµС‚
        # РїРѕ РЎРћРћР‘Р©Р•РќРРЇРњ РІРѕ РІСЃРµС… РїСѓР±Р»РёС‡РЅС‹С… С‡Р°С‚Р°С… (РЅРµ РїРѕ РЅР°Р·РІР°РЅРёСЏРј РєР°РЅР°Р»РѕРІ, РєР°Рє
        # contacts.search), Рё С‡Р°СЃС‚Рѕ РЅР°С…РѕРґРёС‚ РєР°РЅР°Р»С‹, РєРѕС‚РѕСЂС‹Рµ РѕР±С‹С‡РЅС‹Р№ РїРѕРёСЃРє
        # РЅРµ РїРѕРєР°Р·С‹РІР°РµС‚. РќРµ С‚СЂРµР±СѓРµС‚ С‚РѕРєРµРЅРѕРІ Рё РїРѕРґРїРёСЃРѕРє вЂ” С‚РѕС‚ Р¶Рµ MTProto-Р°РєРєР°СѓРЅС‚.
        try:
            global_result = await userbot(SearchGlobalRequest(
                q=keyword,
                filter=InputMessagesFilterEmpty(),
                min_date=None,
                max_date=None,
                offset_rate=0,
                offset_peer=InputPeerEmpty(),
                offset_id=0,
                limit=LIVE_SEARCH_LIMIT,
                broadcasts_only=True,  # РёРЅС‚РµСЂРµСЃСѓСЋС‚ С‚РѕР»СЊРєРѕ РєР°РЅР°Р»С‹, РЅРµ РіСЂСѓРїРїС‹/С‡Р°С‚С‹
            ))
            for chat in getattr(global_result, 'chats', []):
                username = getattr(chat, 'username', None)
                if username and username not in live_channels:
                    live_channels[username] = chat
                    await db.upsert_channel(
                        username=username,
                        title=clean_html(chat.title),
                        participants_count=getattr(chat, 'participants_count', None),
                        keyword=keyword,
                    )
        except Exception as e:
            logger.warning(f"SearchGlobal failed: {e}")

        # 1.1 Р”РѕРїРѕР»РЅСЏРµРј СЂРµР·СѓР»СЊС‚Р°С‚Р°РјРё РёР· TGStat (РµСЃР»Рё Р·Р°РґР°РЅ TGSTAT_TOKEN) вЂ” Сѓ РЅРёС…
        # СЃРІРѕСЏ Р±РѕР»СЊС€Р°СЏ РїСЂРѕРёРЅРґРµРєСЃРёСЂРѕРІР°РЅРЅР°СЏ Р±Р°Р·Р° РєР°РЅР°Р»РѕРІ, С€РёСЂРµ, С‡РµРј РѕС‚РґР°С‘С‚ Р¶РёРІРѕР№
        # РїРѕРёСЃРє Telegram Р·Р° РѕРґРёРЅ SearchRequest. TGStat РЅРµ РґР°С‘С‚ РѕР±СЉРµРєС‚ chat,
        # РїРѕСЌС‚РѕРјСѓ С‚Р°РєРёРµ РєР°РЅР°Р»С‹ СЂРµР·РѕР»РІРёРј С‡РµСЂРµР· Telethon РѕС‚РґРµР»СЊРЅРѕ.
        tgstat_channels = await tgstat_client.search_channels(keyword, limit=LIVE_SEARCH_LIMIT)
        for item in tgstat_channels:
            username = item['username']
            if username in live_channels:
                continue  # СѓР¶Рµ РµСЃС‚СЊ РёР· Р¶РёРІРѕРіРѕ РїРѕРёСЃРєР°, РЅРµ РґСѓР±Р»РёСЂСѓРµРј СЂР°Р±РѕС‚Сѓ
            try:
                chat = await userbot.get_entity(username)
            except Exception as e:
                logger.warning(f"TGStat channel @{username} not resolvable via Telethon: {e}")
                continue
            live_channels[username] = chat
            await db.upsert_channel(
                username=username,
                title=clean_html(item.get('title') or username),
                participants_count=item.get('participants_count'),
                keyword=keyword,
            )
            await asyncio.sleep(0.3)

        # 2. Р”Р»СЏ РЅРѕРІС‹С… (РµС‰С‘ РЅРµ РїСЂРѕРІРµСЂРµРЅРЅС‹С…) РєР°РЅР°Р»РѕРІ Р»РµР·РµРј РІ РїРѕР»РЅСѓСЋ РёРЅС„Сѓ Рё РїР°СЂСЃРёРј
        # РѕРїРёСЃР°РЅРёРµ РЅР° РїСЂРµРґРјРµС‚ РєРѕРЅС‚Р°РєС‚Р°. РЈР¶Рµ РїСЂРѕРІРµСЂРµРЅРЅС‹Рµ вЂ” РЅРµ С‚СЂРѕРіР°РµРј РїРѕРІС‚РѕСЂРЅРѕ,
        # С‡С‚РѕР±С‹ РЅРµ РїРµСЂРµСЃС‡РёС‚С‹РІР°С‚СЊ РѕРґРЅРѕ Рё С‚Рѕ Р¶Рµ Рё РЅРµ Р»РѕРІРёС‚СЊ FloodWait.
        to_check = await db.get_unchecked_usernames(list(live_channels.keys()))
        if to_check:
            await msg.edit_text(
                f"РџРѕРёСЃРє... РїСЂРѕРІРµСЂСЏСЋ РєРѕРЅС‚Р°РєС‚С‹ РІ {len(to_check)} РЅРѕРІС‹С… РєР°РЅР°Р»Р°С… "
                f"(РѕРїРёСЃР°РЅРёРµ + РїРѕСЃР»РµРґРЅРёРµ РїРѕСЃС‚С‹, РјРѕР¶РµС‚ Р·Р°РЅСЏС‚СЊ РІСЂРµРјСЏ)."
            )
        for username in to_check:
            try:
                chat = live_channels[username]
                full = await userbot(GetFullChannelRequest(channel=chat))
                about = getattr(full.full_chat, 'about', '') or ''
                candidates = extract_contact_candidates(about, username)

                # Р•СЃР»Рё РІ РѕРїРёСЃР°РЅРёРё РєР°РЅРґРёРґР°С‚РѕРІ РЅРµС‚ вЂ” РґРѕР±Р°РІР»СЏРµРј РєР°РЅРґРёРґР°С‚РѕРІ РёР· РїРѕСЃС‚РѕРІ РєР°РЅР°Р»Р°
                if not candidates:
                    candidates = await scan_messages_for_contact_candidates(chat, username)

                # РџСЂРѕРІРµСЂСЏРµРј РєР°РЅРґРёРґР°С‚РѕРІ РїРѕ РѕС‡РµСЂРµРґРё: РЅСѓР¶РµРЅ СЂРµР°Р»СЊРЅС‹Р№ Р»РёС‡РЅС‹Р№ Р°РєРєР°СѓРЅС‚,
                # Р° РЅРµ РµС‰С‘ РѕРґРёРЅ РєР°РЅР°Р»/Р±РѕС‚, СЃР»СѓС‡Р°Р№РЅРѕ СѓРїРѕРјСЏРЅСѓС‚С‹Р№ СЂСЏРґРѕРј СЃ РјР°СЂРєРµСЂРЅС‹Рј СЃР»РѕРІРѕРј
                contact = await resolve_real_contact(candidates)

                await db.set_contact_info(username, contact)
            except Exception as e:
                logger.warning(f"Contact check failed for @{username}: {e}")
                await db.set_contact_info(username, None)
            await asyncio.sleep(CONTACT_CHECK_DELAY)

        # 3. Р§РёС‚Р°РµРј РЅР°РєРѕРїР»РµРЅРЅСѓСЋ Р±Р°Р·Сѓ вЂ” С‚РѕР»СЊРєРѕ РєР°РЅР°Р»С‹, РіРґРµ РєРѕРЅС‚Р°РєС‚ РЅР°Р№РґРµРЅ
        channels = await db.search_channels(keyword, contacts_only=True)

        if not channels:
            await msg.edit_text(
                "РљР°РЅР°Р»РѕРІ СЃ СЏРІРЅС‹Рј РєРѕРЅС‚Р°РєС‚РѕРј РІ РѕРїРёСЃР°РЅРёРё РЅРµ РЅР°Р№РґРµРЅРѕ.\n"
                "РџРѕРїСЂРѕР±СѓР№С‚Рµ РґСЂСѓРіРѕРµ СЃР»РѕРІРѕ вЂ” Р±Р°Р·Р° РїРѕРїРѕР»РЅСЏРµС‚СЃСЏ СЃ РєР°Р¶РґС‹Рј РїРѕРёСЃРєРѕРј."
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
        await msg.edit_text("РћС€РёР±РєР° РїРѕРёСЃРєР°.")

@router.callback_query(F.data.startswith("search:"))
async def search_page_cb(call: CallbackQuery):
    _, sid, page_str = call.data.split(":")
    page = int(page_str)

    session = search_sessions.get(sid)
    if not session:
        await call.answer("РЎРµСЃСЃРёСЏ РїРѕРёСЃРєР° СѓСЃС‚Р°СЂРµР»Р°, РІС‹РїРѕР»РЅРёС‚Рµ /search Р·Р°РЅРѕРІРѕ.", show_alert=True)
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
        f"РџРѕСЃС‚С‹ РёР· <b>@{channel}</b> РїРѕ СЃР»РѕРІСѓ <b>{keyword}</b>\n"
        f"РЎС‚СЂР°РЅРёС†Р° {page + 1}/{total_pages}\n\n"
    )
    for p in page_items:
        text += (
            f"Р”Р°С‚Р°: {p['date']}\n{p['text']}...\n"
            f"РћСЂРёРіРёРЅР°Р»: https://t.me/{channel}/{p['id']}\n"
            + "-" * 30 + "\n"
        )
    return text

@router.message(Command("posts"))
async def posts_cmd(message: Message):
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.answer("РџСЂРёРјРµСЂ: <code>/posts durov telegram</code>")
        return
    channel = args[1].replace('@', '')
    keyword = args[2]
    msg = await message.answer("РџРѕРёСЃРє РїРѕСЃС‚РѕРІ...")

    try:
        posts = []
        # Р›РёРјРёС‚ РїРѕРґРЅСЏС‚ РґРѕ 200 СЃРѕРѕР±С‰РµРЅРёР№ РёСЃС‚РѕСЂРёРё РєР°РЅР°Р»Р° РЅР° РїСЂРѕСЃРјРѕС‚СЂ,
        # СЂРµР·СѓР»СЊС‚Р°С‚ РїРѕСЃС‚СЂР°РЅРёС‡РЅРѕ Р»РёСЃС‚Р°РµС‚СЃСЏ СѓР¶Рµ Р±РµР· РїРѕРІС‚РѕСЂРЅС‹С… Р·Р°РїСЂРѕСЃРѕРІ Рє Telegram.
        async for m in userbot.iter_messages(channel, search=keyword, limit=200):
            if m.text:
                posts.append({'text': clean_html(m.text)[:200], 'id': m.id, 'date': m.date.strftime("%d.%m.%Y")})

        if not posts:
            await msg.edit_text("РџРѕСЃС‚С‹ РЅРµ РЅР°Р№РґРµРЅС‹. РџРѕРїСЂРѕР±СѓР№С‚Рµ РґСЂСѓРіРѕРµ СЃР»РѕРІРѕ.")
            return

        sid = uuid.uuid4().hex[:8]
        posts_sessions[sid] = {"channel": channel, "keyword": keyword, "posts": posts}

        total_pages = max(1, (len(posts) + POSTS_PAGE_SIZE - 1) // POSTS_PAGE_SIZE)
        text = build_posts_page_text(channel, keyword, posts, 0, total_pages)
        kb = build_pagination_kb("posts", sid, 0, total_pages)

        await msg.edit_text(text, disable_web_page_preview=True, reply_markup=kb)
    except Exception as e:
        logger.error(f"Posts error: {e}")
        await msg.edit_text("РћС€РёР±РєР°. Р’РѕР·РјРѕР¶РЅРѕ, РєР°РЅР°Р» С‡Р°СЃС‚РЅС‹Р№.")

@router.callback_query(F.data.startswith("posts:"))
async def posts_page_cb(call: CallbackQuery):
    _, sid, page_str = call.data.split(":")
    page = int(page_str)

    session = posts_sessions.get(sid)
    if not session:
        await call.answer("РЎРµСЃСЃРёСЏ РїРѕРёСЃРєР° СѓСЃС‚Р°СЂРµР»Р°, РІС‹РїРѕР»РЅРёС‚Рµ /posts Р·Р°РЅРѕРІРѕ.", show_alert=True)
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
    await call.message.edit_text("РСЃРїРѕР»СЊР·СѓР№С‚Рµ <code>/search</code> РёР»Рё <code>/posts</code>.")

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
