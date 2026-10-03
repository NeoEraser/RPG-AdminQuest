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
        url = f"{self.base_url}/setChatMemberTag"
        payload = {"chat_id": chat_id, "user_id": user_id, "tag": tag}

        # Получаем актуальный прокси из менеджера
        proxy = None
        if self.proxy_manager:
            try:
                proxy = await self.proxy_manager.get_working_proxy()
            except Exception as e:
                logger.warning(f"Не удалось получить прокси: {e}")
                proxy = None

        # Если у бота кастомная сессия — используем её внутреннюю aiohttp-сессию
        bot_session = getattr(self.bot.session, "_session", None)

        try:
            if bot_session and not bot_session.closed:
                if proxy:
                    async with bot_session.post(url, json=payload, proxy=proxy) as response:
                        result = await response.json()
                else:
                    async with bot_session.post(url, json=payload) as response:
                        result = await response.json()
            else:
                # Fallback: своя сессия
                async with aiohttp.ClientSession() as session:
                    if proxy:
                        async with session.post(url, json=payload, proxy=proxy) as response:
                            result = await response.json()
                    else:
                        async with session.post(url, json=payload) as response:
                            result = await response.json()

            if result.get("ok"):
                return True
            raise TelegramAPIError(
                method="setChatMemberTag",
                message=result.get("description", "Unknown error"),
            )
        except TelegramAPIError:
            raise
        except Exception as e:
            logger.error(f"Ошибка установки тега: {e}")
            return False


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
