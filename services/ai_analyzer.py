import json
import asyncio
import logging
import re
import aiohttp
from dataclasses import dataclass
from typing import Optional
from config import AI_BASE_URL, AI_MODEL, AI_TEMPERATURE, AI_MAX_TOKENS, AI_ENABLED, COMPANIES

logger = logging.getLogger(__name__)


# ──────────────────────────── Приоритетная матрица ───────────────────────────

def calculate_priority(emp_score: int, scope_score: int) -> tuple[str, int]:
    """
    Приоритет = employee_level × scope_level.
    Чем меньше число (особенно отрицательное) — тем выше приоритет.

    A (кто столкнулся):
        Директор / гендиректор / босс      → +3
        Бухгалтер / бухгалтерия             → +2
        Менеджер / руководитель / сотрудник  → +1
        Простой / обычный                   → -1

    B (охват):
        Вся компания / все / весь офис      → -3
        Отдел / магазин / филиал / офис     → -2
        Один / одна / парочка / несколько   → -1

    Результат:
        ≤ -5  → critical
        -2 .. -4  → high
        1 .. 2      → medium
        ≥ 3         → low
    """
    value = emp_score * scope_score

    if value <= -5:
        return "critical", value
    elif value <= -2:
        return "high", value
    elif value <= 2:
        return "medium", value
    else:
        return "low", value


# ──────────────────────────── Поиск по БД компаний ───────────────────────────

async def search_company(name: str) -> Optional[dict]:
    """Ищет компанию в COMPANIES по точному или частичному совпадению."""
    if not COMPANIES:
        return None

    name_lower = name.lower().strip()
    best_match = None
    best_score = 0

    for company in COMPANIES:
        comp_name = company["name"].lower()

        if comp_name == name_lower:
            return company

        if comp_name in name_lower or name_lower in comp_name:
            score = len(comp_name)
            if score > best_score:
                best_score = score
                best_match = company

        comp_words = comp_name.split()
        text_words = name_lower.split()
        overlap = len(set(comp_words) & set(text_words))
        if overlap > best_score:
            best_score = overlap
            best_match = company

    return best_match


# ──────────────────────────── AI-анализ задачи ───────────────────────────

@dataclass
class TaskAnalysis:
    company: Optional[str] = None
    is_vip: bool = False
    contact_name: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    employee_score: int = 0
    scope_score: int = 0
    priority: str = "medium"
    priority_value: int = 0


async def analyze_task_with_ai(task_description: str) -> TaskAnalysis:
    """
    Отправляет описание задачи в ИИ.
    ИИ извлекает: компанию, контакт, телефон, локацию,
    уровень сотрудника, охват проблемы, вычисляет приоритет.
    """
    company_names = "\n".join(c["name"] for c in COMPANIES) if COMPANIES else "(нет компаний)"
    vip_list = "\n".join(c["name"] for c in COMPANIES if c.get("vip")) or "(нет VIP)"

    prompt = (
        "Ты аналитик IT-отдела. Проанализируй задачу и извлеки информацию.\n\n"

        f"База компаний ({len(COMPANIES)} записей):\n{company_names}\n\n"
        f"VIP-компании:\n{vip_list}\n\n"

        f"Задача:\n\"{task_description}\"\n\n"

        "Извлеки поля JSON:\n"
        '  "company" — название компании (если найдена в базе — используй точное название)\n'
        '  "is_vip" — true/false (является ли компания VIP из базы)\n'
        '  "contact_name" — имя контактного лица (если упоминается)\n'
        '  "phone" — номер телефона (если упоминается)\n'
        '  "address" — адрес/локация (кабинет, этаж, здание)\n\n'

        "Кто столкнулся с проблемой (employee_level):\n"
        "  директор / гендиректор / босс / главный          → 3\n"
        "  бухгалтер / бухгалтерия                           → 2\n"
        "  менеджер / руководитель / сотрудник               → 1\n"
        "  простой / обычный                                 → -1\n"
        "  если неясно                                       → 0\n\n"

        "Сколько людей затронуто (scope_level):\n"
        "  вся компания / все / весь офис                    → -3\n"
        "  отдел / магазин / филиал / офис                   → -2\n"
        "  один / одна / парочка / несколько                 → -1\n"
        "  если неясно                                       → 0\n\n"

        "ВЕРНИ ТОЛЬКО JSON:\n"
        '{\n  "company": "ООО Ромашка",\n  "is_vip": false,\n  "contact_name": "Мария Петрова",\n'
        '  "phone": "+7 (999) 123-45-67",\n  "address": "3 этаж, каб. 312",\n'
        '  "employee_level": 1,\n  "scope_level": -1\n}'

        "\n\nНе добавляй Markdown-обёртки, только чистый JSON."
    )

    url = f"{AI_BASE_URL}/v1/chat/completions"
    headers = {"Content-Type": "application/json"}
    payload = {
        "model": AI_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": AI_MAX_TOKENS,
        "stream": False,
    }

    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=60)
        ) as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                if resp.status != 200:
                    logger.warning(f"AI-analyze status {resp.status}")
                    return TaskAnalysis()

                data = await resp.json()
                raw = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()

                # Убираем markdown-обёртки если ИИ их добавил
                raw = re.sub(r'```(?:json)?\s*', '', raw)
                raw = raw.rstrip('`').strip()

                # Парсим JSON
                parsed = None
                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError:
                    m = re.search(r'\{[^}]+\}', raw, re.DOTALL)
                    if m:
                        try:
                            parsed = json.loads(m.group())
                        except json.JSONDecodeError:
                            logger.warning(f"Bad JSON from AI: {raw[:200]}")
                    else:
                        logger.warning(f"No JSON in AI response: {raw[:200]}")

                if not parsed:
                    return TaskAnalysis()

                emp = parsed.get("employee_level", 0)
                scope = parsed.get("scope_level", 0)

                analysis = TaskAnalysis(
                    company=parsed.get("company"),
                    is_vip=parsed.get("is_vip", False),
                    contact_name=parsed.get("contact_name"),
                    phone=parsed.get("phone"),
                    address=parsed.get("address"),
                    employee_score=emp,
                    scope_score=scope,
                )

                # Вычисляем приоритет
                if emp == 0 or scope == 0:
                    analysis.priority = "medium"
                    analysis.priority_value = 1
                else:
                    analysis.priority, analysis.priority_value = calculate_priority(emp, scope)

                # Проверка по БД компаний (гибрид)
                if analysis.company:
                    matched = await search_company(analysis.company)
                    if matched:
                        analysis.is_vip = matched.get("vip", False)
                        analysis.company = matched["name"]

                        # VIP → повышаем приоритет на 1 уровень
                        boost = {"low": "medium", "medium": "high", "high": "critical"}
                        if analysis.priority in boost:
                            analysis.priority = boost[analysis.priority]
                            analysis.priority_value -= 1

                return analysis

    except asyncio.TimeoutError:
        logger.warning("AI-analyze timeout")
    except aiohttp.ClientError as e:
        logger.warning(f"AI-analyze network: {e}")
    except Exception as e:
        logger.error(f"AI-analyze error: {e}", exc_info=True)

    return TaskAnalysis()


# ──────────────────────────── Форматирование ───────────────────────────

def format_analysis_inline(analysis: TaskAnalysis) -> str:
    """Возвращает красивый текст для вставки в сообщение о квесте."""
    if not (analysis.company or analysis.contact_name or analysis.phone or analysis.address):
        return ""

    lines = ["📋 <b>АНАЛИЗ ЗАДАЧИ</b>"]

    if analysis.company:
        vip_tag = "⭐VIP" if analysis.is_vip else ""
        lines.append(f"🏢 Компания: <b>{analysis.company}</b>{vip_tag}")

    if analysis.contact_name:
        lines.append(f"👤 Контакт: {analysis.contact_name}")

    if analysis.phone:
        lines.append(f"📞 Телефон: {analysis.phone}")

    if analysis.address:
        lines.append(f"📍 Локация: {analysis.address}")

    em = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}
    lines.append(f"{em.get(analysis.priority, '🟡')} Приоритет: <b>{analysis.priority.upper()}</b>")

    return "\n".join(lines)