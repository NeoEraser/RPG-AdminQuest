# proxy_monitor.py - новый файл для мониторинга

import asyncio
import logging
from datetime import datetime, timedelta
from database import db
from proxy_manager import ProxyManager

logger = logging.getLogger(__name__)


class ProxyMonitor:
    """Мониторит состояние прокси и автоматически переключает при проблемах"""
    
    def __init__(self, proxy_manager: ProxyManager, bot_token: str):
        self.proxy_manager = proxy_manager
        self.bot_token = bot_token
        self.is_running = False
        self._task = None
    
    async def start(self):
        """Запускает мониторинг"""
        if self.is_running:
            return
        
        self.is_running = True
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info("🔄 Мониторинг прокси запущен")
    
    async def stop(self):
        """Останавливает мониторинг"""
        self.is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("🔄 Мониторинг прокси остановлен")
    
    async def _monitor_loop(self):
        """Основной цикл мониторинга"""
        while self.is_running:
            try:
                # Проверяем текущий прокси каждые 2 минуты
                await asyncio.sleep(120)
                
                current_proxy = self.proxy_manager._current_proxy
                if current_proxy:
                    # Проверяем текущий прокси
                    is_working = await self.proxy_manager._check_proxy(current_proxy, timeout=5)
                    if not is_working:
                        logger.warning(f"⚠️ Текущий прокси {self.proxy_manager._mask_proxy(current_proxy)} не отвечает!")
                        # Обновляем рейтинг
                        await db.update_proxy_rating(current_proxy, False, "Monitor check failed")
                        # Удаляем из рабочих
                        if current_proxy in self.proxy_manager._working_proxies:
                            self.proxy_manager._working_proxies.remove(current_proxy)
                        
                        # Ищем новый прокси
                        new_proxy = await self.proxy_manager.get_working_proxy()
                        if new_proxy:
                            logger.info(f"🔄 Переключились на новый прокси: {self.proxy_manager._mask_proxy(new_proxy)}")
                        else:
                            logger.warning("⚠️ Не найден новый рабочий прокси, пробуем перезагрузить...")
                            await self.proxy_manager.force_reinitialize()
                else:
                    # Если нет текущего прокси, пробуем найти
                    logger.info("🔍 Ищем рабочий прокси...")
                    await self.proxy_manager.force_reinitialize()
                
                # Проверяем статистику раз в час
                if datetime.now().minute == 0:
                    stats = await db.get_proxy_stats()
                    logger.info(f"📊 Статистика прокси: {stats}")
                    
                    # Если рабочих прокси мало, пробуем найти новые
                    if stats['working'] < 2 and stats['total'] > 0:
                        logger.warning("⚠️ Мало рабочих прокси, перепроверяем все...")
                        await self.proxy_manager.force_reinitialize()
                        
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"❌ Ошибка в мониторинге прокси: {e}")
                await asyncio.sleep(30)