"""
Модуль для генерации и поиска эмбеддингов статей Wiki.
Хранение эмбеддингов: в колонке wiki.embedding в виде JSON-строки списка чисел.
Использует sentence-transformers для генерации эмбеддингов.

API:
- async def init_model(model_name: str = 'all-MiniLM-L6-v2')
- async def embed_text(text: str) -> list[float]
- async def index_article(article_id: int)
- async def reindex_all()
- async def search_similar_articles(query: str, top_k: int = 5) -> List[Tuple]

"""
import asyncio
import json
import logging
from typing import List, Tuple

import aiosqlite
import numpy as np

from config import DB_NAME

logger = logging.getLogger(__name__)

# lazy-loaded model
_model = None
_model_name = 'all-MiniLM-L6-v2'


# Флаг, указывающий, доступна ли локальная библиотека для эмбеддингов
_model_available = True

def _ensure_model(model_name: str = None):
    global _model, _model_name, _model_available
    if model_name:
        _model_name = model_name
    if _model is None:
        try:
            from sentence_transformers import SentenceTransformer
        except ModuleNotFoundError:
            logger.warning("sentence-transformers не установлена — эмбеддинги недоступны. Установите пакет или запустите бота в venv.")
            _model_available = False
            return
        except Exception as e:
            logger.exception("Не удалось инициализировать sentence-transformers: %s", e)
            _model_available = False
            return
        try:
            _model = SentenceTransformer(_model_name)
            _model_available = True
        except Exception as e:
            logger.exception("Ошибка при загрузке модели SentenceTransformer: %s", e)
            _model_available = False


async def init_model(model_name: str = None):
    """Инициализировать модель (можно вызвать при старте)."""
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, _ensure_model, model_name)
    except Exception:
        # Любые исключения уже залогированы в _ensure_model — помним, что это фоновая задача
        logger.debug("init_model завершилась с исключением (см. предыдущие логи)")


async def embed_text(text: str) -> List[float]:
    """Возвращает эмбеддинг для текста (list of floats). Если модель недоступна — возвращает пустой список.
    Вызователь должен корректно обрабатывать пустой результат и делать fallback на LIKE-поиск.
    """
    if not text:
        return []
    if not _model_available or _model is None:
        logger.debug("embed_text: модель эмбеддингов недоступна, возвращаю пустой вектор")
        return []
    loop = asyncio.get_running_loop()

    def _encode(t):
        return _model.encode(t, show_progress_bar=True)

    vec = await loop.run_in_executor(None, _encode, text)
    # convert numpy array to list
    return vec.tolist()


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    if a is None or b is None:
        return -1.0
    an = np.linalg.norm(a)
    bn = np.linalg.norm(b)
    if an == 0 or bn == 0:
        return -1.0
    return float(np.dot(a, b) / (an * bn))


async def index_article(article_id: int):
    """Генерирует эмбеддинг для статьи и сохраняет в колонку wiki.embedding (JSON)."""
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT title, content FROM wiki WHERE id = ?', (article_id,)) as c:
            row = await c.fetchone()
            if not row:
                return False
            title, content = row
            text = f"{title}\n\n{content}"

    emb = await embed_text(text)
    emb_json = json.dumps(emb)
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('UPDATE wiki SET embedding = ? WHERE id = ?', (emb_json, article_id))
        await db.commit()
    return True


async def reindex_all(batch_size: int = 50):
    """Переиндексация всех подтверждённых статей (is_verified = 1).
    Запускает индексацию пакетами, чтобы не перегружать память.
    Если модель эмбеддингов недоступна, задача корректно завершится без исключения.

    Возвращает словарь с результатом: {"total": int, "updated": int, "failed": int}
    """
    result = {"total": 0, "updated": 0, "failed": 0}

    if not _model_available:
        logger.warning("reindex_all: модель эмбеддингов недоступна, пропускаю переиндексацию")
        return result

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT id, title, content FROM wiki WHERE is_verified = 1') as c:
            rows = await c.fetchall()

    result["total"] = len(rows)

    for row in rows:
        article_id = row[0]
        try:
            ok = await index_article(article_id)
            if ok:
                result["updated"] += 1
            else:
                result["failed"] += 1
        except Exception:
            logger.exception(f"Ошибка индексирования статьи {article_id}")
            result["failed"] += 1

    logger.info(f"Reindex finished: total={result['total']} updated={result['updated']} failed={result['failed']}")
    return result


async def search_similar_articles(query: str, top_k: int = 5) -> List[Tuple]:
    """Ищет похожие статьи по эмбеддингам.
    Возвращает список кортежей аналогичных output search_wiki:
    (id, title, content, category, tags, author_name, likes, created_at)
    Если модель эмбеддингов недоступна или эмбеддинг для запроса не получен — возвращается пустой список
    (вызов-предоставляющий код должен сделать fallback на LIKE-поиск).
    """
    if not query:
        return []

    # Гарантируем, что модель инициализирована
    _ensure_model()

    if not _model_available or _model is None:
        logger.debug("search_similar_articles: модель эмбеддингов недоступна, возвращаю пустой список")
        return []

    try:
        q_emb = await embed_text(query)
    except Exception:
        logger.exception("Ошибка при генерации эмбеддинга для запроса")
        return []

    if not q_emb:
        logger.debug("search_similar_articles: пустой эмбеддинг для запроса — возвращаю пустой список")
        return []

    q_vec = np.array(q_emb)

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('''
            SELECT id, title, content, category, tags, author_name, likes, created_at, embedding
            FROM wiki
            WHERE is_verified = 1 AND embedding IS NOT NULL
        ''') as cursor:
            rows = await cursor.fetchall()

    scored = []
    for row in rows:
        try:
            emb_json = row[8]
            if not emb_json:
                continue
            emb = np.array(json.loads(emb_json))
            sim = _cosine(q_vec, emb)
            scored.append((sim, row))
        except Exception:
            continue

    scored.sort(key=lambda x: x[0], reverse=True)
    top = [r[1][:8] for r in scored[:top_k]]  # slice off embedding
    return top
