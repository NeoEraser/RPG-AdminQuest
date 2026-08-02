# main.py

import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import TOKEN, GROUP_ID
from database.db import init_db, add_proxies_batch
from services import api
from services.scheduler import scheduler, daily_plan_check, skill_decay_check, reset_monthly_exp, monthly_results_check, restore_timeouts
from services.custom_session import DynamicProxySession
from proxy_manager import ProxyManager
from services.proxy_monitor import ProxyMonitor

# Импортируем роутеры
from handlers import basic, quests, incidents, admin, quest_manager

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Включаем debug для aiogram
logging.getLogger('aiogram.dispatcher').setLevel(logging.DEBUG)
logging.getLogger('aiogram.client').setLevel(logging.DEBUG)
logging.getLogger('services.custom_session').setLevel(logging.DEBUG)

async def check_action_via_proxy(proxy_url: str) -> bool:
    """Проверяет, можно ли через прокси выполнить действие"""
    try:
        # Здесь можно вызвать любой метод API для проверки
        return True
    except:
        return False

async def run_bot_with_recovery():
    """Запускает бота с автоматическим восстановлением при падении"""
    max_restarts = 5
    restarts = 0
    
    while restarts < max_restarts:
        try:
            await main()
            break
        except Exception as e:
            restarts += 1
            error_str = str(e).lower()
            
            if "404" in error_str:
                logging.warning(f"⚠️ Ошибка 404 при запуске, пробуем перезапустить...")
                await asyncio.sleep(5)
                continue
            
            logging.error(f"❌ Бот упал с ошибкой: {e}")
            import traceback
            traceback.print_exc()
            
            if restarts < max_restarts:
                logging.info(f"🔄 Перезапуск бота через 30 секунд... (попытка {restarts + 1}/{max_restarts})")
                
                try:
                    from database import db
                    from proxy_manager import ProxyManager
                    temp_proxy_manager = ProxyManager(TOKEN)
                    await temp_proxy_manager.force_reinitialize()
                    logging.info("✅ Прокси перезагружены перед перезапуском")
                except Exception as reload_error:
                    logging.error(f"❌ Ошибка перезагрузки прокси: {reload_error}")
                
                await asyncio.sleep(30)
            else:
                logging.error("❌ Достигнут лимит перезапусков. Бот остановлен.")
                raise

async def main():
    # 1. Инициализация БД
    await init_db()
    
    # 2. Инициализируем менеджер прокси
    proxy_manager = ProxyManager(TOKEN)
    
    # 3. Инициализируем прокси
    logging.info("🔄 Инициализация прокси...")
    await proxy_manager.initialize(check_action=check_action_via_proxy)
    
    # 4. Создаем бота с динамической сессией
    session = DynamicProxySession(proxy_manager=proxy_manager)
    default_properties = DefaultBotProperties(parse_mode=ParseMode.HTML, protect_content=False)
    bot = Bot(token=TOKEN, session=session, default=default_properties)
    
    # 5. Инициализация API обертки
    api.api_wrapper = api.BotAPIMethods(bot, proxy_manager)
    api.proxy_manager = proxy_manager
    
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    
    # 6. Подключаем роутеры (только если они еще не подключены)
    attached_routers_ids = [id(r) for r in dp._routers] if hasattr(dp, '_routers') else []
    
    router_instances = [
        ('basic', basic.router),
        ('admin', admin.router),
        ('incidents', incidents.router),
        ('quests', quests.router),
        ('quest_manager', quest_manager.router)
    ]
    
    for name, router in router_instances:
        if id(router) not in attached_routers_ids:
            dp.include_router(router)
            logging.info(f"✅ Подключен роутер: {name}")
        else:
            logging.info(f"ℹ️ Роутер {name} уже подключен")
    
    # 7. Восстанавливаем таймауты после перезапуска
    await restore_timeouts(bot)
    
    # 8. Запускаем задачи по расписанию
    scheduler.add_job(daily_plan_check, 'cron', day_of_week='mon-thu', hour=18, minute=0, args=[bot])
    scheduler.add_job(skill_decay_check, 'cron', day_of_week='tue-fri', hour=10, minute=0, args=[bot])
    scheduler.add_job(reset_monthly_exp, 'cron', day=1, hour=0, minute=0, args=[bot])
    scheduler.add_job(monthly_results_check, 'cron', day='last', hour=12, minute=0, args=[bot, GROUP_ID])
    scheduler.start()
    
    # 9. Проверяем авторизацию бота
    try:
        me = await bot.get_me()
        logging.info(f"✅ Бот успешно авторизован: @{me.username}")
    except Exception as e:
        logging.error(f"❌ Ошибка авторизации бота: {e}")
        import traceback
        traceback.print_exc()
        logging.error("Бот не может запуститься. Проверьте прокси.")
        return
    
    # 10. Информация о прокси
    working_proxy = await proxy_manager.get_working_proxy()
    if working_proxy:
        logging.info(f"🚀 Бот запущен с прокси: {proxy_manager._mask_proxy(working_proxy)}")
    else:
        logging.info("🚀 Бот запущен без прокси")
    
    # 11. Статистика
    stats = await proxy_manager.get_stats()
    logging.info(f"📊 Статистика прокси: {stats}")
    
    # 12. Запускаем мониторинг прокси
    proxy_monitor = ProxyMonitor(proxy_manager, TOKEN)
    await proxy_monitor.start()
    
    # 13. Обработчик ошибок
    @dp.errors()
    async def handle_errors(update, exception):
        logging.error(f"❌ Ошибка обработки обновления: {exception}")
        logging.error(f"Тип ошибки: {type(exception)}")
        if update:
            logging.error(f"Обновление: {update}")
        import traceback
        traceback.print_exc()
        return True  # Подавляем ошибку
    
    # 14. Логирование обновлений
    @dp.update()
    async def log_update(update):
        logging.info(f"📨 Получено обновление: {update}")
        return update
    
    # 15. Запускаем поллинг
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logging.error(f"❌ Ошибка в polling: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        await proxy_monitor.stop()
        await session.close()
        logging.info("👋 Бот остановлен")


if __name__ == "__main__":
    try:
        asyncio.run(run_bot_with_recovery())
    except KeyboardInterrupt:
        logging.info("👋 Бот остановлен пользователем")
    except Exception as e:
        logging.error(f"❌ Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()