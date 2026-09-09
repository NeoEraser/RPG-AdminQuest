import asyncio
import logging
import aiohttp
from aiogram.exceptions import TelegramForbiddenError
from config import AI_BASE_URL, AI_MODEL, AI_TEMPERATURE, AI_MAX_TOKENS, AI_ENABLED, TEAMLEAD_ID

logger = logging.getLogger(__name__)
CACHED_SYSTEM_PROMPT = None

async def get_ai_suggestion(task_description: str) -> str:
    """Запрашивает подсказку у ИИ-сервера (llama.cpp OpenAI-compatible API)."""
    if not AI_ENABLED:
        return "🤖 AI-подсказки отключены. Обратитесь к тимлиду."

    prompt = f"""
        Ты опытный IT-администратор с 10+ годами практики.
        Твоя задача — дать техническую инструкцию по решению проблемы с ПО, сетью, сервером или оборудованием.
        
        Правило 1: Если в тексте задачи есть ФИО, телефон, название компании-клиента — игнорируй их как фоновый шум. Они НЕ являются частью технической проблемы.
        Правило 2: Ты НЕ ищешь людей, НЕ проверяешь номера, НЕ работаешь с базами данных. Ты даёшь команды для командной строки, настройки роутеров или скрипты.
        Правило 3: Если техническая суть неясна из-за обилия личных данных — переформулируй задачу в общий вид (например: "пользователь не может подключиться к VPN").
        
        Давай практические руководства по решению IT-задач. 
        Посыл информации должен быть прост и понятен начинающему специалисту. 
        Формат ответа (без Markdown, до 1000 символов):
        
        📋 Анализ: [кратко опиши техническую проблему, убрав имена и телефоны]
        ✅ Шаги:
        1. [Конкретные действия]
        2. [Конкретные команды]
        3. [Проверка результата]
        ⚠️ Важно:
        - [Что может пойти не так]
        - [Как проверить успех]
        💡 Альтернатива: [если не сработает]
        Критерии: точность, безопасность, применимость. Команды пиши конкретно.

        Техническая задача (личные данные внутри — проигнорируй): {task_description}
    """

    messages = [
            {"role": "user", "content": prompt},
        ]
    
    url = f"{AI_BASE_URL}/v1/chat/completions"
    headers = {"Content-Type": "application/json"}
    payload = {
        "model": AI_MODEL,
        "messages": messages,
        "temperature": AI_TEMPERATURE,
        "max_tokens": AI_MAX_TOKENS,
        "stream": False,
        "return_progress": True,
        "sse_ping_interval": 1,
        "reasoning_format": "auto",
        "chat_template_kwargs": {
            "enable_thinking": False  # КЛЮЧЕВОЙ ПАРАМЕТР!
        },
        "reasoning_control": True,
        "backend_sampling": False,
        "timings_per_token": True,
    }

    timeout = aiohttp.ClientTimeout(total=120)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                if resp.status != 200:
                    logger.warning(f"AI API returned {resp.status}")
                    return "⚠️ AI-сервер недоступен. Используй /wiki для поиска решений."

                data = await resp.json()
                answer = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()

                if not answer:
                    return "⚠️ AI не смог сгенерировать ответ. Используй /wiki для поиска решений."

                return answer

    except asyncio.TimeoutError:
        return "⏱ Таймаут при запросе к AI. Используй /wiki для поиска решений."
    except aiohttp.ClientError as e:
        logger.warning(f"AI network error: {e}")
        return "⚠️ Не удалось подключиться к AI-серверу. Используй /wiki."
    except Exception as e:
        logger.error(f"AI unexpected error: {e}", exc_info=True)
        return "⚠️ Ошибка при получении подсказки. Используй /wiki."


async def show_suggestion(bot, chat_id, bot_msg_id, task_description, user_id):
    """Показывает AI-подсказку по квесту. Проверки: /start, /profile, DM."""
    import aiosqlite
    from config import DB_NAME

    # ── 1. Проверка /start и TOS ──────────────────────────────
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            'SELECT agreed_to_tos FROM users WHERE user_id = ?', (user_id,)
        ) as cursor:
            row = await cursor.fetchone()

    if not row:
        await bot.send_message(chat_id, "❌ Сначала напиши /start")
        return

    if row[0] != 1:
        await bot.send_message(chat_id, "❌ Сначала согласись с условиями через /start")
        return

    # ── 2. Проверка DM — не заблокированы ли личные сообщения ─
    try:
        msg = await bot.send_message(user_id, "🔍")
        try:
            await bot.delete_message(user_id, msg.message_id)
        except Exception:
            pass
    except TelegramForbiddenError:
        await bot.send_message(
            chat_id,
            "⚠️ <b>Личные сообщения заблокированы</b>\n\n"
            "Разблокируйте бота в ЛС для получения AI-подсказок.",
            parse_mode="HTML",
        )
        return

    # ── 3. Запрос к ИИ ────────────────────────────────────────
    suggestion = await get_ai_suggestion(task_description)

    if suggestion.startswith("⚠️") or suggestion.startswith("🤖"):
        await bot.send_message(chat_id, suggestion)
        return

    # ── 4. Отправка подсказки ─────────────────────────────────
    formatted = f"🤖 <b>AI-ПОДСКАЗКА</b>\n\n<blockquote expandable>{suggestion}</blockquote>"
    await bot.send_message(chat_id, formatted, parse_mode="HTML")

async def web_search_with_ddg(query: str, max_results: int = 3) -> str:
    """Ищет в интернете через DuckDuckGo и возвращает текст результатов."""
    try:
        from duckduckgo_search import DDGS
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                title = r.get('title', 'Без заголовка')
                snippet = r.get('body', '')
                url = r.get('href', '')
                results.append(f"• {title}\n  {snippet}\n  {url}")
        return "\n\n".join(results)
    except ImportError:
        return ""
    except Exception as e:
        logger.warning(f"Web search error: {e}")
        return ""


async def ai_with_web_context(task_description: str) -> str:
    """
    Сначала пытается ответить из своей базы.
    Если ответ слабый (короткий или «не знаю») — делает web-search и даёт ответ на основе результатов.
    """
    # Шаг 1: пробуем обычный ответ от ИИ
    ai_response = await get_ai_suggestion(task_description)

    if ai_response.startswith("⚠️"):
        # Если ИИ недоступен — делаем веб-поиск
        search_results = await web_search_with_ddg(task_description)
        if search_results:
            return f"🌐 <b>ПОИСК В ИНТЕРНЕТЕ</b>\n\nНайдено:\n\n{search_results}"
        return "⚠️ AI-сервер и веб-поиск недоступны. Используй /wiki."

    # Проверяем, хороший ли ответ от ИИ (короткий = слабый)
    if len(ai_response) < 50:
        # Делаем веб-поиск
        search_results = await web_search_with_ddg(task_description)
        if search_results:
            # Второй запрос к ИИ с контекстом из поиска
            context_prompt = (f"""
                Ты опытный IT-администратор с 10+ годами практики.
                Твоя задача — дать техническую инструкцию по решению проблемы с ПО, сетью, сервером или оборудованием.
                
                Правило 1: Если в тексте задачи есть ФИО, телефон, название компании-клиента — игнорируй их как фоновый шум. Они НЕ являются частью технической проблемы.
                Правило 2: Ты НЕ ищешь людей, НЕ проверяешь номера, НЕ работаешь с базами данных. Ты даёшь команды для командной строки, настройки роутеров или скрипты.
                Правило 3: Если техническая суть неясна из-за обилия личных данных — переформулируй задачу в общий вид (например: "пользователь не может подключиться к VPN").
                
                Техническая задача (личные данные внутри — проигнорируй): {task_description}
                
                Вот что найдено в интернете: {search_results}
                
                Давай практические руководства по решению IT-задач. 
                Посыл информации должен быть прост и понятен начинающему специалисту. 
                Формат ответа (без Markdown, до 1000 символов):
                
                📋 Анализ: [кратко опиши техническую проблему, убрав имена и телефоны]
                ✅ Шаги:
                1. [Конкретные действия]
                2. [Конкретные команды]
                3. [Проверка результата]
                ⚠️ Важно:
                - [Что может пойти не так]
                - [Как проверить успех]
                💡 Альтернатива: [если не сработает]
                Критерии: точность, безопасность, применимость. Команды пиши конкретно.
            """)
            improved_response = await get_ai_suggestion_with_context(context_prompt)
            if improved_response and not improved_response.startswith("⚠️") and len(improved_response) > 50:
                return improved_response

    return ai_response


async def get_ai_suggestion_with_context(prompt: str) -> str:
    """Та же функция get_ai_suggestion, но с кастомным промптом."""
    if not AI_ENABLED:
        return ""

    url = f"{AI_BASE_URL}/v1/chat/completions"
    headers = {"Content-Type": "application/json"}
    payload = {
        "model": AI_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": AI_TEMPERATURE,
        "max_tokens": AI_MAX_TOKENS,
        "stream": False,
    }

    timeout = aiohttp.ClientTimeout(total=300)  # чуть больше для второго запроса
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                if resp.status != 200:
                    return ""

                data = await resp.json()
                answer = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()

                if not answer:
                    return ""
                return answer

    except (asyncio.TimeoutError, aiohttp.ClientError, Exception):
        return ""