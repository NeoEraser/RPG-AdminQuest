# api.py
import logging
import aiohttp
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

logger = logging.getLogger(__name__)


class BotAPIMethods:
    def __init__(self, bot: Bot, proxy_manager):
        self.bot = bot
        self.proxy_manager = proxy_manager
        self.base_url = f"https://api.telegram.org/bot{bot.token}"
    
    async def set_chat_member_tag(self, chat_id: int, user_id: int, tag: str) -> bool:
        try:
            url = f"{self.base_url}/setChatMemberTag"
            payload = {"chat_id": chat_id, "user_id": user_id, "tag": tag}
        
            # Получаем сессию из бота
            session = self.bot.session
            if session and hasattr(session, '_session'):
                async with session._session.post(url, json=payload) as response:
                    result = await response.json()
                    if result.get("ok"):
                        return True
                    else:
                        raise TelegramAPIError(
                            method="setChatMemberTag", 
                            message=result.get("description", "Unknown error")
                        )
            else:
                # Fallback на aiohttp напрямую
                async with aiohttp.ClientSession() as session:
                    async with session.post(url, json=payload) as response:
                        result = await response.json()
                        if result.get("ok"):
                            return True
                        else:
                            raise TelegramAPIError(
                                method="setChatMemberTag", 
                                message=result.get("description", "Unknown error")
                            )
        except Exception as e:
            logger.error(f"Ошибка установки тега: {e}")
            raise


# Глобальная переменная
api_wrapper = None
proxy_manager = None


async def update_telegram_tag(chat_id: int, user_id: int, level: int):
    from services.rpg import get_tag_title
    if not api_wrapper:
        return
    new_tag = get_tag_title(level)
    try:
        if await api_wrapper.set_chat_member_tag(chat_id, user_id, new_tag):
            logger.info(f"Тег '{new_tag}' установлен для пользователя {user_id}")
    except TelegramAPIError as e:
        error_text = str(e).lower()
        if "not enough rights" in error_text or "forbidden" in error_text:
            logger.warning(f"Нет прав на смену тегов в чате {chat_id}.")
        elif "tag_invalid" in error_text:
            logger.error(f"Telegram отклонил тег '{new_tag}'.")
        else:
            raise