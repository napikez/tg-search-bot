import os
import logging
import aiohttp

logger = logging.getLogger(__name__)

TGSTAT_TOKEN = os.getenv("TGSTAT_TOKEN")
BASE_URL = "https://api.tgstat.ru"


async def search_channels(keyword: str, limit: int = 50):
    """
    РџРѕРёСЃРє РєР°РЅР°Р»РѕРІ С‡РµСЂРµР· TGStat API (РјРµС‚РѕРґ channels/search).
    РўСЂРµР±СѓРµС‚ РїР»Р°С‚РЅС‹Р№ С‚Р°СЂРёС„ TGStat API Stat (S Рё РІС‹С€Рµ) Рё С‚РѕРєРµРЅ РІ РїРµСЂРµРјРµРЅРЅРѕР№
    РѕРєСЂСѓР¶РµРЅРёСЏ TGSTAT_TOKEN. Р•СЃР»Рё С‚РѕРєРµРЅ РЅРµ Р·Р°РґР°РЅ вЂ” РїСЂРѕСЃС‚Рѕ РІРѕР·РІСЂР°С‰Р°РµС‚
    РїСѓСЃС‚РѕР№ СЃРїРёСЃРѕРє, Р±РѕС‚ РїСЂРё СЌС‚РѕРј РїСЂРѕРґРѕР»Р¶Р°РµС‚ СЂР°Р±РѕС‚Р°С‚СЊ РЅР° Р¶РёРІРѕРј РїРѕРёСЃРєРµ Telethon.

    Р’РѕР·РІСЂР°С‰Р°РµС‚ СЃРїРёСЃРѕРє СЃР»РѕРІР°СЂРµР№: username, title, participants_count.
    """
    if not TGSTAT_TOKEN:
        return []

    params = {"token": TGSTAT_TOKEN, "q": keyword, "limit": limit}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{BASE_URL}/channels/search", params=params, timeout=15) as resp:
                data = await resp.json()
    except Exception as e:
        logger.warning(f"TGStat request failed: {e}")
        return []

    if data.get("status") != "ok":
        logger.warning(f"TGStat returned error: {data}")
        return []

    items = data.get("response", {}).get("items", [])
    channels = []
    for item in items:
        username = item.get("username")
        if username:
            channels.append({
                "username": username,
                "title": item.get("title") or username,
                "participants_count": item.get("participants_count"),
            })
    return channels
