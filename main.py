import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.client.session.aiohttp import AiohttpSession

from config import TOKEN, PROXY_URL, GROUP_ID
from database.db import init_db
from services import api
from services.scheduler import scheduler, daily_plan_check, skill_decay_check, reset_monthly_exp, monthly_results_check, restore_timeouts

# Импортируем роутеры
from handlers import basic, quests, incidents, admin, quest_manager

logging.basicConfig(level=logging.INFO)

async def main():
    default_properties = DefaultBotProperties(parse_mode=ParseMode.HTML)
    session = AiohttpSession(proxy=PROXY_URL) if PROXY_URL else None
    bot = Bot(token=TOKEN, session=session, default=default_properties)

    # Инициализация API обертки для тегов (передаем в модуль API)
    api.api_wrapper = api.BotAPIMethods(bot, proxy=PROXY_URL)

    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    # Инициализация БД
    await init_db()

    # Подключаем роутеры
    dp.include_router(basic.router)
    dp.include_router(admin.router)
    dp.include_router(incidents.router)
    dp.include_router(quests.router)
    dp.include_router(quest_manager.router)

    # Восстанавливаем таймауты после перезапуска
    await restore_timeouts(bot)

    # Запускаем задачи по расписанию (передаем бот инстанс)
    scheduler.add_job(daily_plan_check, 'cron', day_of_week='mon-thu', hour=18, minute=0, args=[bot])
    scheduler.add_job(skill_decay_check, 'cron', day_of_week = 'tue-fri', hour=10, minute=0, args=[bot]) # Проверка на АФК каждое утро
    scheduler.add_job(reset_monthly_exp, 'cron', day=1, hour=0, minute=0, args=[bot])
    scheduler.add_job(monthly_results_check, 'cron', day='last', hour=12, minute=0, args=[bot, GROUP_ID])
    scheduler.start()

    logging.info("РПГ-Бот запущен. Модули загружены.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())