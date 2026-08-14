"""
База знаний Wiki для RPG-AdminQuest.

Сценарии использования:
  1. Пассивный: при сдаче квеста бот предлагает сохранить решение.
  2. Активный: инженер пишет "помощь ключевое_слово" — бот выдаёт решения.
  3. Ручное добавление: тимлид может добавить статью через команду.
"""

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Tuple

import aiosqlite

from config import DB_NAME, TEAMLEAD_ID

logger = logging.getLogger(__name__)


# ─────────────────────────── DB functions ───────────────────────────

async def init_wiki_table():
    """Создаёт таблицу wiki при старте."""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS wiki (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                category TEXT DEFAULT 'Other',
                tags TEXT DEFAULT '',
                author_id INTEGER,
                author_name TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                likes INTEGER DEFAULT 0,
                is_verified INTEGER DEFAULT 0,
                FOREIGN KEY (author_id) REFERENCES users(user_id)
            )
        ''')
        await db.execute('CREATE INDEX IF NOT EXISTS idx_wiki_category ON wiki(category)')
        await db.execute('CREATE INDEX IF NOT EXISTS idx_wiki_tags ON wiki(tags)')
        await db.execute('CREATE INDEX IF NOT EXISTS idx_wiki_verified ON wiki(is_verified)')
        await db.commit()


async def save_wiki_article(
    title: str,
    content: str,
    category: str = "Other",
    tags: str = "",
    author_id: int = None,
    author_name: str = None,
    is_verified: int = 0
) -> int:
    """Добавляет статью в Wiki. Возвращает ID."""
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('''
            INSERT INTO wiki (title, content, category, tags, author_id, author_name, is_verified)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (title, content, category, tags, author_id, author_name, is_verified)) as cursor:
            article_id = cursor.lastrowid
        await db.commit()
    logger.info(f"✅ Wiki статья #{article_id} добавлена: {title}")
    return article_id


async def search_wiki(query: str, limit: int = 5) -> List[Tuple]:
    """
    Ищет статьи по запросу (title + content + tags).
    Возвращает список: (id, title, content, category, tags, author_name, likes, created_at)
    """
    query_clean = query.lower().strip()
    if not query_clean:
        return []

    async with aiosqlite.connect(DB_NAME) as db:
        # Ищем по title, content и tags (LIKE с % для частичного совпадения)
        async with db.execute('''
            SELECT id, title, content, category, tags, author_name, likes, created_at
            FROM wiki
            WHERE (title LIKE ? OR content LIKE ? OR tags LIKE ?)
              AND is_verified = 1
            ORDER BY likes DESC, created_at DESC
            LIMIT ?
        ''', (
            f'%{query_clean}%',
            f'%{query_clean}%',
            f'%{query_clean}%',
            limit
        )) as cursor:
            return await cursor.fetchall()


async def get_wiki_by_category(category: str, limit: int = 10) -> List[Tuple]:
    """Получает статьи по категории."""
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('''
            SELECT id, title, content, category, tags, author_name, likes, created_at
            FROM wiki
            WHERE category = ? AND is_verified = 1
            ORDER BY likes DESC
            LIMIT ?
        ''', (category, limit)) as cursor:
            return await cursor.fetchall()


async def get_all_categories() -> List[str]:
    """Получает все категории из wiki."""
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT DISTINCT category FROM wiki ORDER BY category') as cursor:
            return [row[0] for row in await cursor.fetchall()]


async def like_wiki_article(article_id: int, user_id: int) -> bool:
    """Ставит лайк статье."""
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('UPDATE wiki SET likes = likes + 1 WHERE id = ?', (article_id,)) as cursor:
            rows = cursor.rowcount
        await db.commit()
        return rows > 0


async def get_wiki_stats() -> dict:
    """Статистика wiki: общее кол-во, по категориям, топ авторов."""
    async with aiosqlite.connect(DB_NAME) as db:
        stats = {}

        async with db.execute('SELECT COUNT(*) FROM wiki') as c:
            stats['total'] = (await c.fetchone())[0]

        async with db.execute('SELECT COUNT(*) FROM wiki WHERE is_verified = 1') as c:
            stats['verified'] = (await c.fetchone())[0]

        async with db.execute('SELECT category, COUNT(*) FROM wiki GROUP BY category ORDER BY COUNT(*) DESC') as c:
            stats['by_category'] = dict(await c.fetchall())

        async with db.execute('''
            SELECT author_name, COUNT(*) as cnt
            FROM wiki WHERE author_id IS NOT NULL
            GROUP BY author_id ORDER BY cnt DESC LIMIT 5
        ''') as c:
            stats['top_authors'] = await c.fetchall()

        return stats


def normalize_wiki_text(value: str) -> str:
    """Нормализует текст для поиска по ключевым словам."""
    value = re.sub(r'[^a-zA-ZА-Яа-я0-9\s]', ' ', (value or '').lower())
    return ' '.join(value.split())


def collect_search_terms(text: str, min_len: int = 2) -> List[str]:
    """Возвращает ключевые слова из описания проблемы."""
    excluded = {
        'новый', 'новая', 'новое', 'квест', 'задача', 'задачи', 'инцидент',
        'проблема', 'ошибка', 'сотрудник', 'клиент', 'подсказка', 'помощь',
        'решение', 'мне', 'нужно', 'сделать', 'уже', 'через', 'после', 'перед',
        'не', 'нет', 'где', 'когда', 'что', 'как', 'и', 'или', 'на', 'в', 'по',
    }
    terms = []
    for word in normalize_wiki_text(text).split():
        if len(word) >= min_len and word not in excluded:
            terms.append(word)
    return list(dict.fromkeys(terms))


async def search_wiki_by_text(text: str, limit: int = 5) -> List[Tuple]:
    """Ищет похожие статьи по смыслу текста задачи."""
    terms = collect_search_terms(text)
    if not terms:
        return []

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('''
            SELECT id, title, content, category, tags, author_name, likes, created_at
            FROM wiki
            WHERE is_verified = 1
            ORDER BY likes DESC, created_at DESC
        ''') as cursor:
            rows = await cursor.fetchall()

    scored = []
    for row in rows:
        row_id, title, content, category, tags, author_name, likes, created_at = row
        title_text = normalize_wiki_text(title)
        content_text = normalize_wiki_text(content)
        tags_text = normalize_wiki_text(tags or '')

        score = 0
        for term in terms:
            if term in title_text:
                score += 8
            if term in tags_text:
                score += 6
            if term in content_text:
                score += 3

        if score > 0:
            scored.append((score, row))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [row for _, row in scored[:limit]]


async def get_wiki_article_by_id(article_id: int):
    """Возвращает запись статьи по ID.
    Формат: (id, title, content, category, tags, author_name, likes, created_at, is_verified)
    """
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('''
            SELECT id, title, content, category, tags, author_name, likes, created_at, is_verified
            FROM wiki WHERE id = ?
        ''', (article_id,)) as cursor:
            row = await cursor.fetchone()
            return row


# ─────────────────────────── category matching ───────────────────────────
# Используем ту же систему категорий, что и в category_detector
CATEGORIES = {
    "1С": ["1с", "1c", "один с", "бухгалтер", "бух", "отчет", "конфигурация", "sbis", "упд", "платеж"],
    "Windows": ["windows", "win", "виндоус", "система", "bsod", "синий экран", "реестр", "переустановка", "обновление", "драйвер"],
    "Office": ["office", "word", "excel", "powerpoint", "outlook", "пиар", "ворд", "экселл", "макрос", "vba"],
    "Network": ["vpn", "сеть", "сетевой", "ip", "маршрут", "dns", "dhcp", "firewall", "домен", "ад"],
    "AutoCAD": ["autocad", "revit", "чертеж", "2d", "3d", "cad"],
    "Printer": ["принтер", "печать", "картридж", "тонер", "hp", "xerox", "brother", "canon", "замятие"],
    "Mobile": ["мобиль", "смартфон", "android", "ios", "iphone", "приложение", "экран", "батарея"],
    "Hardware": ["монитор", "клавиатура", "мышь", "видеокарта", "процессор", "ssd", "ram"],
}


def suggest_wiki_category(text: str) -> str:
    """Предлагает категорию на основе текста."""
    text_lower = text.lower()
    scores = {}
    for category, keywords in CATEGORIES.items():
        score = sum(1 for kw in keywords if kw in text_lower)
        if score > 0:
            scores[category] = score
    if scores:
        return max(scores, key=scores.get)
    return "Other"


def suggest_wiki_title(text: str) -> str:
    """Предлагает заголовок статьи на основе описания квеста."""
    # Берём первые слова до 50 символов
    title = text.strip()[:60]
    if len(title) == 60:
        last_space = title.rfind(' ', 0, 55)
        if last_space > 5:
            title = title[:last_space]
    return title
