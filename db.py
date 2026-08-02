import aiosqlite

DB_PATH = "bot_data.db"


async def init_db():
    """РЎРѕР·РґР°С‘С‚ С‚Р°Р±Р»РёС†Сѓ РїСЂРё РїРµСЂРІРѕРј Р·Р°РїСѓСЃРєРµ Рё РґРѕРєР°С‚С‹РІР°РµС‚ РЅРµРґРѕСЃС‚Р°СЋС‰РёРµ РєРѕР»РѕРЅРєРё
    РЅР° СѓР¶Рµ СЃСѓС‰РµСЃС‚РІСѓСЋС‰РµР№ Р±Р°Р·Рµ (РґР»СЏ С‚РµС…, РєС‚Рѕ РѕР±РЅРѕРІР»СЏРµС‚СЃСЏ СЃ РїСЂРѕС€Р»РѕР№ РІРµСЂСЃРёРё)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS channels (
                username TEXT PRIMARY KEY,
                title TEXT,
                participants_count INTEGER,
                keywords TEXT DEFAULT '',
                contact_username TEXT DEFAULT NULL,
                contact_checked INTEGER DEFAULT 0
            )
            """
        )
        # РњРёРіСЂР°С†РёСЏ РґР»СЏ Р±Р°Р·, СЃРѕР·РґР°РЅРЅС‹С… РґРѕ РїРѕСЏРІР»РµРЅРёСЏ РїРѕР»РµР№ contact_*
        cur = await db.execute("PRAGMA table_info(channels)")
        existing_cols = {row[1] for row in await cur.fetchall()}
        if "contact_username" not in existing_cols:
            await db.execute("ALTER TABLE channels ADD COLUMN contact_username TEXT DEFAULT NULL")
        if "contact_checked" not in existing_cols:
            await db.execute("ALTER TABLE channels ADD COLUMN contact_checked INTEGER DEFAULT 0")
        await db.commit()


async def upsert_channel(username: str, title: str, participants_count, keyword: str):
    """
    Р”РѕР±Р°РІР»СЏРµС‚ РєР°РЅР°Р» РІ Р±Р°Р·Сѓ РёР»Рё РѕР±РЅРѕРІР»СЏРµС‚ РµРіРѕ, РµСЃР»Рё СѓР¶Рµ РµСЃС‚СЊ.
    РљР»СЋС‡РµРІС‹Рµ СЃР»РѕРІР° РєРѕРїСЏС‚СЃСЏ вЂ” РѕРґРёРЅ Рё С‚РѕС‚ Р¶Рµ РєР°РЅР°Р» РјРѕР¶РµС‚ Р±С‹С‚СЊ РЅР°Р№РґРµРЅ
    РїРѕ СЂР°Р·РЅС‹Рј Р·Р°РїСЂРѕСЃР°Рј, Рё Р±Р°Р·Р° РѕС‚ СЌС‚РѕРіРѕ СЃРѕ РІСЂРµРјРµРЅРµРј СЂР°СЃС‚С‘С‚.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT keywords FROM channels WHERE username = ?", (username,)
        )
        row = await cur.fetchone()

        count_value = participants_count if isinstance(participants_count, int) else None

        if row:
            keywords = set(filter(None, row[0].split(",")))
            keywords.add(keyword)
            await db.execute(
                "UPDATE channels SET title = ?, participants_count = ?, keywords = ? WHERE username = ?",
                (title, count_value, ",".join(keywords), username),
            )
        else:
            await db.execute(
                "INSERT INTO channels (username, title, participants_count, keywords) VALUES (?, ?, ?, ?)",
                (username, title, count_value, keyword),
            )
        await db.commit()


async def set_contact_info(username: str, contact_username):
    """
    Р¤РёРєСЃРёСЂСѓРµС‚ СЂРµР·СѓР»СЊС‚Р°С‚ РїСЂРѕРІРµСЂРєРё РѕРїРёСЃР°РЅРёСЏ РєР°РЅР°Р»Р° РЅР° РЅР°Р»РёС‡РёРµ РєРѕРЅС‚Р°РєС‚Р°.
    contact_checked СЃС‚Р°РІРёС‚СЃСЏ РІ 1 РІ Р»СЋР±РѕРј СЃР»СѓС‡Р°Рµ, С‡С‚РѕР±С‹ РїСЂРё СЃР»РµРґСѓСЋС‰РµРј
    РїРѕРёСЃРєРµ РЅРµ РіРѕРЅСЏС‚СЊ GetFullChannelRequest РїРѕРІС‚РѕСЂРЅРѕ РЅР° РѕРґРёРЅ Рё С‚РѕС‚ Р¶Рµ РєР°РЅР°Р».
    """
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE channels SET contact_username = ?, contact_checked = 1 WHERE username = ?",
            (contact_username, username),
        )
        await db.commit()


async def get_unchecked_usernames(usernames: list[str]) -> list[str]:
    """РР· СЃРїРёСЃРєР° usernames РІРѕР·РІСЂР°С‰Р°РµС‚ С‚Рµ, РґР»СЏ РєРѕС‚РѕСЂС‹С… РµС‰С‘ РЅРµ РїСЂРѕРІРµСЂСЏР»Рё РєРѕРЅС‚Р°РєС‚."""
    if not usernames:
        return []
    async with aiosqlite.connect(DB_PATH) as db:
        placeholders = ",".join("?" for _ in usernames)
        cur = await db.execute(
            f"SELECT username FROM channels WHERE username IN ({placeholders}) AND contact_checked = 1",
            usernames,
        )
        already_checked = {row[0] for row in await cur.fetchall()}
        return [u for u in usernames if u not in already_checked]


async def search_channels(keyword: str, contacts_only: bool = True):
    """
    Р’РѕР·РІСЂР°С‰Р°РµС‚ РєР°РЅР°Р»С‹ РїРѕ РєР»СЋС‡РµРІРѕРјСѓ СЃР»РѕРІСѓ, РѕС‚СЃРѕСЂС‚РёСЂРѕРІР°РЅРЅС‹Рµ РїРѕ С‡РёСЃР»Сѓ РїРѕРґРїРёСЃС‡РёРєРѕРІ.
    РџРѕ СѓРјРѕР»С‡Р°РЅРёСЋ contacts_only=True вЂ” РѕС‚РґР°С‘С‚ С‚РѕР»СЊРєРѕ С‚Рµ, Сѓ РєРѕРіРѕ РІ РѕРїРёСЃР°РЅРёРё
    РЅР°Р№РґРµРЅ СЏРІРЅС‹Р№ РєРѕРЅС‚Р°РєС‚ РґР»СЏ СЃРІСЏР·Рё (СЃРј. РїРѕРјРµС‚РєСѓ Рѕ РіСЂР°РЅРёС†Р°С… С‚РѕС‡РЅРѕСЃС‚Рё РІС‹С€Рµ).
    """
    query = """
        SELECT username, title, participants_count, contact_username
        FROM channels
        WHERE keywords LIKE ?
    """
    params = [f"%{keyword}%"]
    if contacts_only:
        query += " AND contact_username IS NOT NULL"
    query += " ORDER BY participants_count DESC NULLS LAST"

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(query, params)
        rows = await cur.fetchall()
        return [
            {
                "username": u,
                "title": t,
                "count": c if c is not None else "РЅРµРёР·РІРµСЃС‚РЅРѕ",
                "contact": contact,
            }
            for u, t, c, contact in rows
        ]


async def total_channels_count() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM channels")
        row = await cur.fetchone()
        return row[0] if row else 0


async def total_with_contact_count() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM channels WHERE contact_username IS NOT NULL")
        row = await cur.fetchone()
        return row[0] if row else 0


async def reset_contact_checks():
    """
    РЎР±СЂР°СЃС‹РІР°РµС‚ С„Р»Р°Рі РїСЂРѕРІРµСЂРєРё Сѓ РІСЃРµС… РєР°РЅР°Р»РѕРІ, С‡С‚РѕР±С‹ РїСЂРё СЃР»РµРґСѓСЋС‰РёС… РїРѕРёСЃРєР°С…
    РєРѕРЅС‚Р°РєС‚ РїРµСЂРµСЃС‡РёС‚Р°Р»СЃСЏ Р·Р°РЅРѕРІРѕ РїРѕ РѕР±РЅРѕРІР»С‘РЅРЅРѕР№ Р»РѕРіРёРєРµ РІРµСЂРёС„РёРєР°С†РёРё.
    РСЃРїРѕР»СЊР·СѓРµС‚СЃСЏ РѕРґРёРЅ СЂР°Р· РїРѕСЃР»Рµ РѕР±РЅРѕРІР»РµРЅРёСЏ Р±РѕС‚Р°, РЅРµ РІ РѕР±С‹С‡РЅРѕР№ СЂР°Р±РѕС‚Рµ.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE channels SET contact_checked = 0, contact_username = NULL")
        await db.commit()
