import aiosqlite

DB_PATH = "bot_data.db"


async def init_db():
    """Создаёт таблицу при первом запуске и докатывает недостающие колонки
    на уже существующей базе (для тех, кто обновляется с прошлой версии)."""
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
        # Миграция для баз, созданных до появления полей contact_*
        cur = await db.execute("PRAGMA table_info(channels)")
        existing_cols = {row[1] for row in await cur.fetchall()}
        if "contact_username" not in existing_cols:
            await db.execute("ALTER TABLE channels ADD COLUMN contact_username TEXT DEFAULT NULL")
        if "contact_checked" not in existing_cols:
            await db.execute("ALTER TABLE channels ADD COLUMN contact_checked INTEGER DEFAULT 0")
        await db.commit()


async def upsert_channel(username: str, title: str, participants_count, keyword: str):
    """
    Добавляет канал в базу или обновляет его, если уже есть.
    Ключевые слова копятся — один и тот же канал может быть найден
    по разным запросам, и база от этого со временем растёт.
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
    Фиксирует результат проверки описания канала на наличие контакта.
    contact_checked ставится в 1 в любом случае, чтобы при следующем
    поиске не гонять GetFullChannelRequest повторно на один и тот же канал.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE channels SET contact_username = ?, contact_checked = 1 WHERE username = ?",
            (contact_username, username),
        )
        await db.commit()


async def get_unchecked_usernames(usernames: list[str]) -> list[str]:
    """Из списка usernames возвращает те, для которых ещё не проверяли контакт."""
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
    Возвращает каналы по ключевому слову, отсортированные по числу подписчиков.
    По умолчанию contacts_only=True — отдаёт только те, у кого в описании
    найден явный контакт для связи (см. пометку о границах точности выше).
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
                "count": c if c is not None else "неизвестно",
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
