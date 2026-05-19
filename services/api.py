import logging
import aiohttp
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

class BotAPIMethods:
    def __init__(self, bot: Bot, proxy: str = None):
        self.bot = bot
        self.proxy = proxy
        self.base_url = f"https://api.telegram.org/bot{bot.token}"
    
    async def set_chat_member_tag(self, chat_id: int, user_id: int, tag: str) -> bool:
        url = f"{self.base_url}/setChatMemberTag"
        payload = {"chat_id": chat_id, "user_id": user_id, "tag": tag}
        connector = aiohttp.TCPConnector(ssl=False) if self.proxy else None
        
        async with aiohttp.ClientSession(connector=connector) as session:
            try:
                proxy_kwargs = {'proxy': self.proxy} if self.proxy else {}
                async with session.post(url, json=payload, **proxy_kwargs) as response:
                    result = await response.json()
                    if result.get("ok"):
                        return True
                    else:
                        raise TelegramAPIError(method="setChatMemberTag", message=result.get("description", "Unknown error"))
            except aiohttp.ClientError as e:
                logging.error(f"Ошибка HTTP запроса: {e}")
                raise

# Глобальная переменная, которая будет инициализирована в main.py
api_wrapper = None
async def update_telegram_tag(chat_id: int, user_id: int, level: int):
    from services.rpg import get_tag_title # Локальный импорт во избежание циклов
    if not api_wrapper: return
    new_tag = get_tag_title(level)
    try:
        if await api_wrapper.set_chat_member_tag(chat_id, user_id, new_tag):
            logging.info(f"Тег '{new_tag}' установлен для пользователя {user_id}")
    except TelegramAPIError as e:
        error_text = str(e).lower()
        if "not enough rights" in error_text or "forbidden" in error_text:
            logging.warning(f"Нет прав на смену тегов в чате {chat_id}.")
        elif "tag_invalid" in error_text:
            logging.error(f"Telegram отклонил тег '{new_tag}'.")