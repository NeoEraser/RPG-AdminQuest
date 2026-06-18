# custom_session.py
import asyncio
import logging
from typing import Optional, Dict, Any, AsyncIterator, List
from aiogram.client.session.base import BaseSession
from aiogram.types import User, Update
from aiogram.client.default import Default
from aiohttp import ClientSession, TCPConnector, ClientTimeout
from proxy_manager import ProxyManager

logger = logging.getLogger(__name__)


class DynamicProxySession(BaseSession):
    """Кастомная сессия с динамической сменой прокси и восстановлением"""

    def __init__(self, proxy_manager: ProxyManager, **kwargs):
        super().__init__(**kwargs)
        self.proxy_manager = proxy_manager
        self._session: Optional[ClientSession] = None
        self._timeout = kwargs.get('timeout', 60)
        self._current_proxy = None
        self._consecutive_failures = 0
        self._max_consecutive_failures = 10

    async def _create_session(self, proxy: Optional[str] = None) -> ClientSession:
        """Создает сессию с указанным прокси"""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

        connector = TCPConnector(
            ssl=False,
            force_close=True,
            limit=100,
            limit_per_host=30,
            enable_cleanup_closed=True
        )
        timeout = ClientTimeout(total=self._timeout)

        if proxy:
            proxy_str, _ = self.proxy_manager._parse_proxy_url(proxy)
            if proxy_str:
                self._current_proxy = proxy
                return ClientSession(
                    connector=connector,
                    timeout=timeout,
                    proxy=proxy_str,
                    trust_env=False
                )

        self._current_proxy = None
        return ClientSession(
            connector=connector,
            timeout=timeout,
            trust_env=False
        )

    async def _ensure_session(self) -> ClientSession:
        """Гарантирует наличие активной сессии"""
        if self._session is None or self._session.closed:
            proxy = await self.proxy_manager.get_working_proxy()
            self._session = await self._create_session(proxy)
        return self._session

    async def _reload_proxies_from_db(self) -> bool:
        """Перезагружает список прокси из БД"""
        logger.warning("🔄 Перезагрузка прокси из БД...")
        try:
            self._consecutive_failures = 0
            await self.proxy_manager.force_reinitialize()

            proxy = await self.proxy_manager.get_working_proxy()
            if self._session and not self._session.closed:
                await self._session.close()
            self._session = await self._create_session(proxy)

            return True
        except Exception as e:
            logger.error(f"❌ Ошибка перезагрузки прокси: {e}")
            return False

    def _clean_payload(self, payload: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Очищает payload от None, пустых строк и Default объектов"""
        if not payload:
            return None

        cleaned = {}
        for key, value in payload.items():
            if value is None:
                continue
            if isinstance(value, str) and value == '':
                continue
            if isinstance(value, list) and not value:
                continue
            if key == 'offset' and value < 0:
                continue
            if isinstance(value, Default):
                continue
            if isinstance(value, dict):
                cleaned_value = self._clean_payload(value)
                if cleaned_value:
                    cleaned[key] = cleaned_value
                continue
            cleaned[key] = value

        return cleaned if cleaned else None

    def _extract_method_name(self, method: Any) -> str:
        """Извлекает имя метода"""
        if isinstance(method, str):
            method_str = method.strip()
            if '?' in method_str:
                method_str = method_str.split('?')[0]
            if ' ' in method_str:
                method_str = method_str.split(' ')[0]
            return method_str
        if hasattr(method, '__name__'):
            return method.__name__
        if hasattr(method, '__class__'):
            return method.__class__.__name__
        return str(method)

    def _serialize_value(self, value: Any) -> Any:
        """Рекурсивно сериализует значение для JSON"""
        if value is None or isinstance(value, Default):
            return None
        if isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, list):
            return [self._serialize_value(item) for item in value if item is not None]
        if isinstance(value, dict):
            result = {}
            for k, v in value.items():
                serialized = self._serialize_value(v)
                if serialized is not None:
                    result[k] = serialized
            return result if result else None
        if hasattr(value, '__dict__'):
            return self._serialize_value(value.__dict__)
        try:
            return str(value)
        except:
            return None

    async def make_request(
        self,
        bot: Any,
        method: Any,
        payload: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> Any:
        """Выполняет запрос к Telegram API с динамической сменой прокси"""

        method_name = self._extract_method_name(method)
        logger.debug(f"📤 Запрос: {method_name}")

        # Специальная обработка getUpdates
        if method_name.lower() == 'getupdates':
            return await self._handle_get_updates(bot, method, payload)

        # Извлечение параметров из объекта метода
        if hasattr(method, 'model_dump'):
            method_params = method.model_dump(exclude_none=True)
            if method_params:
                if payload is None:
                    payload = {}
                for key, value in method_params.items():
                    if not isinstance(value, Default):
                        payload[key] = value

        real_method = method_name.lstrip('/')

        # Принудительно устанавливаем parse_mode=HTML для методов отправки
        if real_method.lower() in ['sendmessage', 'editmessagetext', 'sendphoto', 'senddocument', 'sendanimation', 'sendsticker']:
            if payload and 'parse_mode' not in payload:
                payload['parse_mode'] = 'HTML'
            elif payload and isinstance(payload.get('parse_mode'), Default):
                payload['parse_mode'] = 'HTML'

        cleaned_payload = self._clean_payload(payload)
        serialized_payload = self._serialize_value(cleaned_payload) if cleaned_payload else None

        total_attempts = 0
        max_total_attempts = 20

        while total_attempts < max_total_attempts:
            try:
                session = await self._ensure_session()

                url = f"https://api.telegram.org/bot{bot.token}/{real_method}"
                http_method = kwargs.get('http_method', 'POST')

                if http_method.upper() == 'GET':
                    async with session.get(url, params=serialized_payload) as response:
                        response_data = await response.json()
                else:
                    async with session.post(url, json=serialized_payload) as response:
                        response_data = await response.json()

                self._consecutive_failures = 0

                if response_data.get('ok'):
                    result = response_data.get('result')

                    if real_method.lower() == 'getme' and isinstance(result, dict):
                        return User(**result)

                    return result

                error_code = response_data.get('error_code')
                if error_code == 429:
                    retry_after = response_data.get('parameters', {}).get('retry_after', 5)
                    await asyncio.sleep(retry_after + 1)
                    continue

                if error_code == 404:
                    continue

                from aiogram.exceptions import TelegramAPIError
                raise TelegramAPIError(
                    message=f"Error {error_code}: {response_data.get('description', 'Unknown error')}",
                    method=real_method
                )

            except Exception as e:
                total_attempts += 1
                error_str = str(e).lower()

                is_network_error = any(kw in error_str for kw in [
                    'cannot connect', 'timeout', 'connection', 'network',
                    'ssl', 'proxy', 'dns', 'connector', 'clientconnectorerror',
                    'connectionerror', 'connecterror', 'connectionrefused'
                ])

                if is_network_error:
                    self._consecutive_failures += 1

                    if self._session and not self._session.closed:
                        await self._session.close()
                        self._session = None

                    if self._consecutive_failures >= self._max_consecutive_failures:
                        await self._reload_proxies_from_db()
                        total_attempts = 0
                        continue

                    if self._current_proxy:
                        current_proxy = self._current_proxy
                        if current_proxy in self.proxy_manager._working_proxies:
                            self.proxy_manager._working_proxies.remove(current_proxy)
                        self.proxy_manager._current_proxy = None

                        from database import db
                        await db.update_proxy_rating(current_proxy, False, str(e)[:200])

                    await asyncio.sleep(min(2 ** (total_attempts // 3), 15))
                    continue

                if "404" in error_str:
                    continue

                raise

        raise Exception("Все попытки запроса исчерпаны")

    async def _handle_get_updates(self, bot: Any, method: Any, payload: Optional[Dict[str, Any]]) -> List[Update]:
        """Обрабатывает getUpdates отдельно"""
        if hasattr(method, 'model_dump'):
            method_params = method.model_dump(exclude_none=True)
            if method_params:
                if payload is None:
                    payload = {}
                for key, value in method_params.items():
                    if not isinstance(value, Default):
                        payload[key] = value

        cleaned_payload = self._clean_payload(payload)

        for attempt in range(5):
            try:
                session = await self._ensure_session()
                url = f"https://api.telegram.org/bot{bot.token}/getUpdates"

                async with session.get(url, params=cleaned_payload) as response:
                    response_data = await response.json()

                if response_data.get('ok'):
                    result = response_data.get('result')
                    if isinstance(result, list):
                        updates = []
                        for update_data in result:
                            if isinstance(update_data, dict):
                                try:
                                    updates.append(Update(**update_data))
                                except Exception:
                                    updates.append(update_data)
                            else:
                                updates.append(update_data)
                        return updates
                    return []

                error_code = response_data.get('error_code')
                if error_code == 429:
                    retry_after = response_data.get('parameters', {}).get('retry_after', 5)
                    await asyncio.sleep(retry_after + 1)
                    continue

                if error_code == 404:
                    return []

                return []

            except Exception as e:
                logger.error(f"❌ getUpdates ошибка (попытка {attempt + 1}): {e}")
                if attempt < 4:
                    await asyncio.sleep(2 ** attempt)

        return []

    async def stream_content(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[int] = None,
        chunk_size: int = 1024,
        **kwargs
    ) -> AsyncIterator[bytes]:
        """Потоковая загрузка контента"""
        session = await self._ensure_session()

        try:
            if timeout:
                connector = TCPConnector(ssl=False, enable_cleanup_closed=True)
                temp_timeout = ClientTimeout(total=timeout)
                async with ClientSession(connector=connector, timeout=temp_timeout) as temp_session:
                    async with temp_session.get(url, headers=headers) as response:
                        response.raise_for_status()
                        async for chunk in response.content.iter_chunked(chunk_size):
                            yield chunk
            else:
                async with session.get(url, headers=headers) as response:
                    response.raise_for_status()
                    async for chunk in response.content.iter_chunked(chunk_size):
                        yield chunk
        except Exception as e:
            logger.error(f"❌ Ошибка потоковой загрузки: {e}")
            raise

    async def close(self) -> None:
        """Закрывает сессию"""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
        await super().close()