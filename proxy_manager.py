# proxy_manager.py
import asyncio
import logging
from typing import Optional, List, Tuple, Dict
import aiohttp
import aiosqlite
from aiohttp import ClientTimeout
from datetime import datetime, timedelta
from urllib.parse import urlparse
import random
from database import db

logger = logging.getLogger(__name__)


class ProxyManager:
    def __init__(self, bot_token: str):
        self.bot_token = bot_token
        self._current_proxy = None
        self._working_proxies = []
        self._last_check_time = None
        self._check_interval = timedelta(minutes=5)
        self._lock = asyncio.Lock()
        self._is_checking = False
        self._is_initialized = False
        self._direct_available = False
        self._check_task = None
        
    def _mask_proxy(self, proxy: str) -> str:
        """Маскирует пароль в прокси для логирования"""
        try:
            parsed = urlparse(proxy)
            if parsed.password:
                return f"{parsed.scheme}://{parsed.username}:***@{parsed.hostname}:{parsed.port}"
            return proxy
        except:
            return proxy
    
    def _parse_proxy_url(self, proxy_url: str) -> Tuple[Optional[str], Optional[dict]]:
        """Разбирает URL прокси и возвращает строку для aiohttp"""
        try:
            if not proxy_url:
                return None, None
                
            # Нормализуем
            proxy_url = proxy_url.strip()
            if not proxy_url.startswith(('http://', 'https://', 'socks5://')):
                proxy_url = f"http://{proxy_url}"
            
            parsed = urlparse(proxy_url)
            
            # Для HTTP прокси
            if parsed.scheme in ['http', 'https']:
                if parsed.username and parsed.password:
                    proxy_str = f"http://{parsed.username}:{parsed.password}@{parsed.hostname}:{parsed.port}"
                else:
                    proxy_str = f"http://{parsed.hostname}:{parsed.port}"
                return proxy_str, {'proxy_type': 'http'}
                
            # Для SOCKS5 прокси
            elif parsed.scheme == 'socks5':
                if parsed.username and parsed.password:
                    proxy_str = f"socks5://{parsed.username}:{parsed.password}@{parsed.hostname}:{parsed.port}"
                else:
                    proxy_str = f"socks5://{parsed.hostname}:{parsed.port}"
                return proxy_str, {'proxy_type': 'socks5'}
                
            else:
                logger.warning(f"Неподдерживаемый тип прокси: {parsed.scheme}")
                return None, None
                
        except Exception as e:
            logger.error(f"Ошибка парсинга прокси {proxy_url}: {e}")
            return None, None
    
    async def _check_proxy(self, proxy: str, timeout: int = 10) -> bool:
        """Проверяет доступность прокси через Telegram API"""
        url = f"https://api.telegram.org/bot{self.bot_token}/getMe"
        
        try:
            proxy_str, _ = self._parse_proxy_url(proxy)
            if not proxy_str:
                return False
            
            timeout_obj = ClientTimeout(total=timeout)
            connector = aiohttp.TCPConnector(ssl=False)
            
            async with aiohttp.ClientSession(connector=connector, timeout=timeout_obj) as session:
                async with session.get(url, proxy=proxy_str) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get('ok', False)
                    return False
                    
        except Exception as e:
            logger.debug(f"Прокси {self._mask_proxy(proxy)} недоступен: {e}")
            return False
    
    async def _check_direct(self, timeout: int = 10) -> bool:
        """Проверяет работу без прокси"""
        url = f"https://api.telegram.org/bot{self.bot_token}/getMe"
        
        try:
            timeout_obj = ClientTimeout(total=timeout)
            connector = aiohttp.TCPConnector(ssl=False)
            
            async with aiohttp.ClientSession(connector=connector, timeout=timeout_obj) as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get('ok', False)
                    return False
                    
        except Exception as e:
            logger.debug(f"Прямое соединение недоступно: {e}")
            return False
    
    async def _check_and_update_proxy(self, proxy_url: str, check_action: callable = None) -> bool:
        """Проверяет прокси и обновляет его рейтинг в БД"""
        is_working = await self._check_proxy(proxy_url, timeout=10)
        
        # Если передан дополнительный action для проверки
        if is_working and check_action:
            try:
                # Пытаемся выполнить действие через прокси
                result = await check_action(proxy_url)
                if not result:
                    is_working = False
            except Exception as e:
                logger.warning(f"Действие через прокси {self._mask_proxy(proxy_url)} не удалось: {e}")
                is_working = False
        
        # Обновляем рейтинг в БД
        await db.update_proxy_rating(proxy_url, is_working, None if is_working else "Check failed")
        
        if is_working:
            logger.info(f"✅ Прокси {self._mask_proxy(proxy_url)} работает (рейтинг обновлен)")
        else:
            logger.debug(f"❌ Прокси {self._mask_proxy(proxy_url)} не работает")
        
        return is_working
    
    async def initialize(self, check_action: callable = None) -> None:
        """Инициализация - загружает прокси из БД и проверяет их"""
        logger.info("🔄 Инициализация менеджера прокси из БД...")
        
        # Проверяем работу без прокси
        logger.info("Проверка работы без прокси...")
        self._direct_available = await self._check_direct()
        if self._direct_available:
            logger.info("✅ Работа без прокси доступна")
        
        # Получаем все прокси из БД
        all_proxies = await db.get_all_proxies()
        
        if not all_proxies:
            logger.warning("⚠️ В БД нет прокси")
            self._is_initialized = True
            return
        
        logger.info(f"Найдено {len(all_proxies)} прокси в БД")
        
        # Проверяем все прокси параллельно
        tasks = []
        for proxy_id, proxy_url, rating, is_working, last_check, success_count, fail_count in all_proxies:
            # Если прокси давно не проверялся или имеет низкий рейтинг
            if not last_check or (datetime.now() - datetime.fromisoformat(last_check.replace('Z', '+00:00')) if last_check else timedelta(days=1)) > timedelta(hours=1):
                tasks.append(self._check_and_update_proxy(proxy_url, check_action))
            elif is_working:
                # Если прокси уже отмечен как рабочий, используем его
                tasks.append(asyncio.coroutine(lambda: True))  # Заглушка
        
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Собираем рабочие прокси
            self._working_proxies = []
            for i, result in enumerate(results):
                if isinstance(result, bool) and result:
                    proxy_url = all_proxies[i][1]
                    self._working_proxies.append(proxy_url)
        
        # Выбираем лучший прокси
        best_proxy = await db.get_best_proxy()
        if best_proxy:
            self._current_proxy = best_proxy
            logger.info(f"✅ Выбран прокси: {self._mask_proxy(best_proxy)}")
        elif self._direct_available:
            self._current_proxy = None
            logger.info("ℹ️ Используем прямое соединение")
        else:
            logger.warning("⚠️ Нет доступных прокси и прямого соединения")
        
        self._is_initialized = True
        
        # Запускаем периодическую проверку
        if self._check_task is None:
            self._check_task = asyncio.create_task(self._periodic_check(check_action))
    
    async def _periodic_check(self, check_action: callable = None):
        """Периодическая проверка всех прокси"""
        while True:
            try:
                await asyncio.sleep(3600)  # Каждый час
                logger.info("🔄 Периодическая проверка прокси...")
                
                # Получаем прокси для проверки
                proxies_to_check = await db.get_proxy_for_check()
                
                if proxies_to_check:
                    tasks = []
                    for proxy_id, proxy_url in proxies_to_check:
                        tasks.append(self._check_and_update_proxy(proxy_url, check_action))
                    
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    
                    # Обновляем список рабочих прокси
                    self._working_proxies = []
                    for proxy_id, proxy_url in proxies_to_check:
                        # Проверяем статус в БД
                        async with aiosqlite.connect(db.DB_NAME) as conn:
                            async with conn.execute('SELECT is_working FROM proxies WHERE id = ?', (proxy_id,)) as cursor:
                                row = await cursor.fetchone()
                                if row and row[0] == 1:
                                    self._working_proxies.append(proxy_url)
                    
                    logger.info(f"✅ После проверки: {len(self._working_proxies)} рабочих прокси")
                
                # Чистим плохие прокси
                await db.cleanup_bad_proxies()
                
                # Статистика
                stats = await db.get_proxy_stats()
                logger.info(f"📊 Статистика прокси: всего {stats['total']}, рабочих {stats['working']}, средний рейтинг {stats['avg_rating']:.1f}")
                
            except Exception as e:
                logger.error(f"Ошибка в периодической проверке: {e}")
    
    async def get_working_proxy(self) -> Optional[str]:
        """
        Возвращает работающий прокси с ротацией
        """
        if not self._is_initialized:
            await self.initialize()
        
        async with self._lock:
            # Если есть прямой доступ, пробуем его
            if self._direct_available:
                return None
            
            # Получаем рабочие прокси из БД
            working_proxies = await db.get_working_proxies(limit=10)
            
            if not working_proxies:
                logger.warning("⚠️ Нет рабочих прокси в БД")
                return None
            
            # Если текущий прокси в списке и еще работает
            if self._current_proxy:
                # Проверяем, есть ли он в списке рабочих
                current_in_list = any(proxy[0] == self._current_proxy for proxy in working_proxies)
                if current_in_list:
                    # Проверяем, не истекло ли время проверки
                    if not self._last_check_time or datetime.now() - self._last_check_time < self._check_interval:
                        return self._current_proxy
                    
                    # Проверяем прокси на лету
                    if await self._check_proxy(self._current_proxy, timeout=8):
                        self._last_check_time = datetime.now()
                        return self._current_proxy
                    else:
                        # Если не работает, обновляем рейтинг
                        await db.update_proxy_rating(self._current_proxy, False, "Failed on use")
                        logger.info(f"❌ Прокси {self._mask_proxy(self._current_proxy)} перестал работать при использовании")
            
            # Выбираем лучший прокси
            best_proxy = await db.get_best_proxy()
            if best_proxy:
                self._current_proxy = best_proxy
                logger.info(f"🔄 Переключились на прокси: {self._mask_proxy(best_proxy)}")
                return best_proxy
            
            return None
    
    def get_proxy_for_session(self) -> Optional[str]:
        """Возвращает прокси для использования в сессии"""
        if self._current_proxy:
            proxy_str, _ = self._parse_proxy_url(self._current_proxy)
            return proxy_str
        return None
    
    async def refresh_proxies(self, proxy_list: List[str], check_action: callable = None):
        """Обновляет список прокси из переданного списка"""
        logger.info(f"🔄 Обновление списка прокси: {len(proxy_list)} прокси")
        
        # Добавляем прокси в БД
        added = await db.add_proxies_batch(proxy_list)
        logger.info(f"Добавлено {added} новых прокси")
        
        # Проверяем новые прокси
        for proxy in proxy_list:
            await self._check_and_update_proxy(proxy, check_action)
        
        # Переинициализируем
        await self.initialize(check_action)
    
    async def add_proxy_manual(self, proxy_url: str, check_action: callable = None):
        """Добавляет один прокси вручную"""
        await db.add_proxy(proxy_url)
        await self._check_and_update_proxy(proxy_url, check_action)
        await self.initialize(check_action)
    
    async def get_stats(self) -> dict:
        """Получает статистику прокси"""
        return await db.get_proxy_stats()

    async def force_reinitialize(self):
        """Принудительно переинициализирует менеджер прокси, перечитывая БД"""
        logger.info("🔄 Принудительная переинициализация прокси из БД...")
        async with self._lock:
            # Сбрасываем состояние
            self._working_proxies = []
            self._current_proxy = None
            
            # Получаем все прокси из БД
            all_proxies = await db.get_all_proxies()
            
            if not all_proxies:
                logger.warning("⚠️ В БД нет прокси")
                self._is_initialized = True
                return False
            
            logger.info(f"Найдено {len(all_proxies)} прокси в БД")
            
            # Проверяем все прокси параллельно
            tasks = []
            for proxy_id, proxy_url, rating, is_working, last_check, success_count, fail_count in all_proxies:
                tasks.append(self._check_and_update_proxy(proxy_url))
            
            if tasks:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                # Собираем рабочие прокси
                self._working_proxies = []
                for i, result in enumerate(results):
                    if isinstance(result, bool) and result:
                        proxy_url = all_proxies[i][1]
                        self._working_proxies.append(proxy_url)
                        logger.info(f"✅ Найден рабочий прокси: {self._mask_proxy(proxy_url)}")
            
            # Выбираем лучший прокси
            best_proxy = await db.get_best_proxy()
            if best_proxy:
                self._current_proxy = best_proxy
                logger.info(f"✅ Выбран прокси: {self._mask_proxy(best_proxy)}")
                return True
            elif self._direct_available:
                self._current_proxy = None
                logger.info("ℹ️ Используем прямое соединение")
                return True
            else:
                logger.warning("⚠️ Нет доступных прокси и прямого соединения")
                return False

    async def add_proxy_and_check(self, proxy_url: str) -> bool:
        """Добавляет прокси и сразу проверяет его"""
        # Добавляем в БД
        await db.add_proxy(proxy_url)
        
        # Проверяем
        is_working = await self._check_and_update_proxy(proxy_url)
        
        if is_working:
            # Добавляем в рабочие
            if proxy_url not in self._working_proxies:
                self._working_proxies.append(proxy_url)
            self._current_proxy = proxy_url
            logger.info(f"✅ Прокси {self._mask_proxy(proxy_url)} добавлен и работает")
        else:
            logger.warning(f"❌ Прокси {self._mask_proxy(proxy_url)} не работает")
        
        return is_working

    async def get_proxies_stats(self) -> Dict:
        """Возвращает статистику по прокси из БД"""
        return await db.get_proxy_stats()