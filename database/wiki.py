"""
Wiki database layer — table creation and queries.
"""
import aiosqlite
import logging
from config import DB_NAME

logger = logging.getLogger(__name__)


async def init_wiki_table():
    """Создаёт таблицу wiki при старте и выполняет простые миграции """
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

        # Миграция: добавить колонку uses для подсчёта использований статей
        try:
            await db.execute('ALTER TABLE wiki ADD COLUMN uses INTEGER DEFAULT 0')
        except:
            pass
        # Миграция: добавить колонку embedding для хранения JSON-эмбеддинга
        try:
            await db.execute('ALTER TABLE wiki ADD COLUMN embedding TEXT')
        except:
            pass
        await db.commit()
