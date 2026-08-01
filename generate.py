import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession

api_id = int(input("Вставь API_ID (только цифры) и нажми Enter: "))
api_hash = input("Вставь API_HASH и нажми Enter: ")

async def main():
    client = TelegramClient(StringSession(), api_id, api_hash)
    await client.start()
    print("\n=== ВАША СЕССИЯ (SESSION_STRING) скопируй текст ниже ===")
    print(client.session.save())
    print("========================================================\n")
    await client.disconnect()

asyncio.run(main())
