import aiosqlite
from config import DB_NAME

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                name TEXT,
                username TEXT,
                exp INTEGER DEFAULT 0,
                monthly_exp INTEGER DEFAULT 0,
                plan_submitted INTEGER DEFAULT 0,
                last_active DATE DEFAULT CURRENT_DATE,
                agreed_to_tos INTEGER DEFAULT 0
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                task_id INTEGER PRIMARY KEY,
                chat_id INTEGER,
                bot_msg_id INTEGER,
                description TEXT,
                category TEXT DEFAULT 'Other',
                worker_id INTEGER DEFAULT NULL,
                reward INTEGER DEFAULT NULL,
                time INTEGER DEFAULT NULL,
                status TEXT DEFAULT 'open',
                start_time DATETIME,
                postponements_count INTEGER DEFAULT 0
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS vacations (
                user_id INTEGER,
                start_date DATE,
                end_date DATE,
                PRIMARY KEY (user_id, start_date)
            )
        ''')
        # Новая таблица для хранения активных таймаутов
        await db.execute('''
            CREATE TABLE IF NOT EXISTS task_timeouts (
                task_id INTEGER PRIMARY KEY,
                bot_msg_id INTEGER UNIQUE,
                worker_id INTEGER,
                timeout_time DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (task_id) REFERENCES tasks(task_id)
            )
        ''')
        # Новая таблица для хранения сообщений по квестам
        await db.execute('''
            CREATE TABLE IF NOT EXISTS quest_messages (
                message_id INTEGER PRIMARY KEY,
                task_id INTEGER,
                user_id INTEGER,
                user_name TEXT,
                message_text TEXT,
                is_reply_to_quest BOOLEAN DEFAULT 0,
                reply_to_message_id INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (task_id) REFERENCES tasks(task_id)
            )
        ''')
        
        # Таблица для истории изменений EXP
        await db.execute('''
            CREATE TABLE IF NOT EXISTS exp_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                exp_change INTEGER,
                change_date DATE DEFAULT CURRENT_DATE,
                reason TEXT DEFAULT 'quest',
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        ''')
        
        # Таблица для прокси
        await db.execute('''
            CREATE TABLE IF NOT EXISTS proxies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                proxy_url TEXT UNIQUE NOT NULL,
                rating INTEGER DEFAULT 0,
                last_check DATETIME,
                is_working BOOLEAN DEFAULT 0,
                last_error TEXT,
                success_count INTEGER DEFAULT 0,
                fail_count INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Индексы для быстрого поиска
        await db.execute('CREATE INDEX IF NOT EXISTS idx_quest_messages_task_id ON quest_messages(task_id)')
        await db.execute('CREATE INDEX IF NOT EXISTS idx_quest_messages_created_at ON quest_messages(created_at)')
        await db.execute('CREATE INDEX IF NOT EXISTS idx_exp_history_user_date ON exp_history(user_id, change_date)')

        # Индексы для быстрого поиска рабочих прокси
        await db.execute('CREATE INDEX IF NOT EXISTS idx_proxies_rating ON proxies(rating DESC)')
        await db.execute('CREATE INDEX IF NOT EXISTS idx_proxies_working ON proxies(is_working)')
        await db.execute('CREATE INDEX IF NOT EXISTS idx_proxies_last_check ON proxies(last_check)')

        # Миграция: добавляем колонку agreed_to_tos если её нет
        try:
            await db.execute('ALTER TABLE users ADD COLUMN agreed_to_tos INTEGER DEFAULT 0')
        except:
            pass

        # Миграция: добавляем колонку category для квестов если её нет
        try:
            await db.execute('ALTER TABLE tasks ADD COLUMN category TEXT DEFAULT "Other"')
        except:
            pass

        await db.commit()

async def update_exp(user_id: int, amount: int, reason: str = "quest"):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT exp, monthly_exp FROM users WHERE user_id = ?', (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                old_exp, old_monthly = row
                new_exp = max(0, old_exp + amount)
                new_monthly = max(0, old_monthly + amount)

                await db.execute(
                    'UPDATE users SET exp = ?, monthly_exp = ? WHERE user_id = ?',
                    (new_exp, new_monthly, user_id)
                )

                if amount != 0:
                    await db.execute(
                        'INSERT INTO exp_history (user_id, exp_change, reason) VALUES (?, ?, ?)',
                        (user_id, amount, reason)
                    )

                await db.commit()
                return new_exp
    return 0

async def update_activity(user_id: int):
    """Обновляет дату последней активности пользователя"""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('UPDATE users SET last_active = CURRENT_DATE WHERE user_id = ?', (user_id,))
        await db.commit()

async def update_username(user_id: int, username: str):
    """Обновляет username пользователя"""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('UPDATE users SET username = ? WHERE user_id = ?', (username, user_id))
        await db.commit()

async def check_tos_agreed(user_id: int) -> bool:
    """Проверяет, согласился ли пользователь с условиями"""
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT agreed_to_tos FROM users WHERE user_id = ?', (user_id,)) as cursor:
            row = await cursor.fetchone()
            return row[0] == 1 if row else False

async def set_tos_agreed(user_id: int):
    """Отмечает, что пользователь согласился с условиями"""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('UPDATE users SET agreed_to_tos = 1 WHERE user_id = ?', (user_id,))
        await db.commit()

# Новая функция для сохранения таймаута
async def save_timeout(task_id: int, bot_msg_id: int, worker_id: int, timeout_time: str):
    """Сохраняет информацию о таймауте в БД"""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('''
            INSERT OR REPLACE INTO task_timeouts (task_id, bot_msg_id, worker_id, timeout_time)
            VALUES (?, ?, ?, ?)
        ''', (task_id, bot_msg_id, worker_id, timeout_time))
        await db.commit()

# Функция для удаления таймаута
async def remove_timeout(bot_msg_id: int):
    """Удаляет таймаут из БД"""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('DELETE FROM task_timeouts WHERE bot_msg_id = ?', (bot_msg_id,))
        await db.commit()

# Функция для получения всех активных таймаутов
async def get_all_timeouts() -> list:
    """Возвращает все активные таймауты"""
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('''
            SELECT t.task_id, t.bot_msg_id, t.worker_id, t.timeout_time,
                   tasks.chat_id, tasks.description
            FROM task_timeouts t
            JOIN tasks ON t.task_id = tasks.task_id
            WHERE t.timeout_time > datetime('now')
            ORDER BY t.timeout_time ASC
        ''') as cursor:
            return await cursor.fetchall()

# Функция для обновления таймаута отсрочки
async def update_timeout(bot_msg_id: int, new_timeout_time: str):
    """Обновляет время таймаута для отсрочки"""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            'UPDATE task_timeouts SET timeout_time = ? WHERE bot_msg_id = ?',
            (new_timeout_time, bot_msg_id)
        )
        await db.commit()

# Функция для увеличения счетчика отсрочек
async def increment_postponements(task_id: int):
    """Увеличивает счетчик использованных отсрочек"""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            'UPDATE tasks SET postponements_count = postponements_count + 1 WHERE task_id = ?',
            (task_id,)
        )
        await db.commit()


# Функция для очистки просроченных таймаутов
async def cleanup_expired_timeouts():
    """Удаляет из БД просроченные таймауты"""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('DELETE FROM task_timeouts WHERE timeout_time <= datetime("now")')
        await db.commit()
        
# Функции для работы с сообщениями квестов
async def save_quest_message(task_id: int, user_id: int, user_name: str, message_text: str, 
                            is_reply_to_quest: bool = False, reply_to_message_id: int = None):
    """Сохраняет сообщение по квесту"""
    async with aiosqlite.connect(DB_NAME) as db:
        # Получаем следующий message_id (используем auto increment)
        async with db.execute('SELECT MAX(message_id) FROM quest_messages') as cursor:
            max_id = await cursor.fetchone()
            new_id = (max_id[0] or 0) + 1
        
        await db.execute('''
            INSERT INTO quest_messages (message_id, task_id, user_id, user_name, message_text, 
                                       is_reply_to_quest, reply_to_message_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (new_id, task_id, user_id, user_name, message_text, is_reply_to_quest, reply_to_message_id))
        await db.commit()
        return new_id

async def get_quest_messages(task_id: int) -> list:
    """Получает все сообщения по квесту"""
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('''
            SELECT message_id, user_id, user_name, message_text, created_at, is_reply_to_quest
            FROM quest_messages 
            WHERE task_id = ? 
            ORDER BY created_at ASC
        ''', (task_id,)) as cursor:
            return await cursor.fetchall()

async def get_all_quests_with_stats(limit: int = 50) -> list:
    """Получает список всех квестов со статистикой"""
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('''
            SELECT
                t.task_id,
                t.bot_msg_id,
                t.chat_id,
                t.description,
                t.status,
                t.reward,
                t.time,
                t.start_time,
                u.name as worker_name,
                COUNT(qm.message_id) as messages_count,
                MAX(qm.created_at) as last_message
            FROM tasks t
            LEFT JOIN users u ON t.worker_id = u.user_id
            LEFT JOIN quest_messages qm ON t.task_id = qm.task_id
            GROUP BY t.task_id
            ORDER BY t.task_id DESC
            LIMIT ?
        ''', (limit,)) as cursor:
            return await cursor.fetchall()


async def get_quests_by_worker(worker_name: str, limit: int = 50) -> list:
    """Получает квесты конкретного исполнителя"""
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('''
            SELECT
                t.task_id,
                t.bot_msg_id,
                t.chat_id,
                t.description,
                t.status,
                t.reward,
                t.time,
                t.start_time,
                u.name as worker_name,
                COUNT(qm.message_id) as messages_count,
                MAX(qm.created_at) as last_message
            FROM tasks t
            LEFT JOIN users u ON t.worker_id = u.user_id
            LEFT JOIN quest_messages qm ON t.task_id = qm.task_id
            WHERE u.name = ?
            GROUP BY t.task_id
            ORDER BY t.task_id DESC
            LIMIT ?
        ''', (worker_name, limit)) as cursor:
            return await cursor.fetchall()


async def get_all_workers() -> list:
    """Получает список всех исполнителей (у кого есть завершённые квесты)"""
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('''
            SELECT DISTINCT u.name
            FROM tasks t
            JOIN users u ON t.worker_id = u.user_id
            WHERE t.status IN ('in_progress', 'completed')
            ORDER BY u.name ASC
        ''') as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows if row[0]]

async def get_task_by_id(task_id: int):
    """Получает информацию о квесте по ID"""
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('''
            SELECT t.*, u.name as worker_name
            FROM tasks t
            LEFT JOIN users u ON t.worker_id = u.user_id
            WHERE t.task_id = ?
        ''', (task_id,)) as cursor:
            return await cursor.fetchone()

async def get_month_activity(user_id: int, year: int = None, month: int = None) -> dict:
    """Получает активность пользователя за месяц {день: сумма_exp_change}"""
    from datetime import datetime
    if year is None or month is None:
        today = datetime.now()
        year = today.year
        month = today.month

    month_str = f"{year}-{month:02d}"

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('''
            SELECT CAST(strftime('%d', change_date) AS INTEGER) as day, SUM(exp_change) as total
            FROM exp_history
            WHERE user_id = ? AND strftime('%Y-%m', change_date) = ?
            GROUP BY day
            ORDER BY day
        ''', (user_id, month_str)) as cursor:
            rows = await cursor.fetchall()

    daily_changes = {}
    for day, total in rows:
        daily_changes[day] = total

    return daily_changes


async def add_proxy(proxy_url: str) -> bool:
    """Добавляет новый прокси в базу данных"""
    try:
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute('''
                INSERT OR IGNORE INTO proxies (proxy_url, is_working, created_at, updated_at)
                VALUES (?, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ''', (proxy_url,))
            await db.commit()
            return True
    except Exception as e:
        logger.error(f"Ошибка добавления прокси {proxy_url}: {e}")
        return False

async def add_proxies_batch(proxy_urls: list) -> int:
    """Добавляет несколько прокси в базу данных"""
    added = 0
    try:
        async with aiosqlite.connect(DB_NAME) as db:
            for proxy_url in proxy_urls:
                try:
                    await db.execute('''
                        INSERT OR IGNORE INTO proxies (proxy_url, is_working, created_at, updated_at)
                        VALUES (?, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    ''', (proxy_url,))
                    added += 1
                except:
                    pass
            await db.commit()
    except Exception as e:
        logger.error(f"Ошибка добавления прокси: {e}")
    return added

async def get_working_proxies(limit: int = 10) -> list:
    """Получает список рабочих прокси с наивысшим рейтингом"""
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('''
            SELECT proxy_url, rating, success_count, fail_count
            FROM proxies
            WHERE is_working = 1
            ORDER BY rating DESC, success_count DESC
            LIMIT ?
        ''', (limit,)) as cursor:
            rows = await cursor.fetchall()
            return rows

async def get_all_proxies() -> list:
    """Получает все прокси из базы"""
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('''
            SELECT id, proxy_url, rating, is_working, last_check, success_count, fail_count
            FROM proxies
            ORDER BY rating DESC
        ''') as cursor:
            return await cursor.fetchall()

async def get_proxy_for_check() -> list:
    """Получает прокси для проверки (не проверенные более часа или с низким рейтингом)"""
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('''
            SELECT id, proxy_url
            FROM proxies
            WHERE last_check IS NULL 
               OR last_check < datetime('now', '-1 hour')
               OR rating < 0
            ORDER BY rating ASC
            LIMIT 20
        ''') as cursor:
            return await cursor.fetchall()

async def update_proxy_rating(proxy_url: str, is_working: bool, error: str = None):
    """Обновляет рейтинг прокси после проверки"""
    try:
        async with aiosqlite.connect(DB_NAME) as db:
            # Получаем текущий рейтинг
            async with db.execute('SELECT rating FROM proxies WHERE proxy_url = ?', (proxy_url,)) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return
                
                current_rating = row[0]
                
                # Обновляем рейтинг
                if is_working:
                    new_rating = min(10, current_rating + 1)
                    success_count_inc = 1
                    fail_count_inc = 0
                else:
                    new_rating = max(-10, current_rating - 1)
                    success_count_inc = 0
                    fail_count_inc = 1
                
                await db.execute('''
                    UPDATE proxies 
                    SET rating = ?,
                        is_working = ?,
                        last_check = CURRENT_TIMESTAMP,
                        last_error = ?,
                        success_count = success_count + ?,
                        fail_count = fail_count + ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE proxy_url = ?
                ''', (new_rating, 1 if is_working else 0, error, success_count_inc, fail_count_inc, proxy_url))
                await db.commit()
    except Exception as e:
        logger.error(f"Ошибка обновления рейтинга прокси {proxy_url}: {e}")

async def reset_proxy_ratings():
    """Сбрасывает рейтинги всех прокси (для перепроверки)"""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('UPDATE proxies SET rating = 0, is_working = 0, last_check = NULL')
        await db.commit()

async def get_best_proxy() -> str:
    """Получает лучший рабочий прокси"""
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('''
            SELECT proxy_url
            FROM proxies
            WHERE is_working = 1
            ORDER BY rating DESC, success_count DESC
            LIMIT 1
        ''') as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None

async def cleanup_bad_proxies():
    """Удаляет прокси с очень низким рейтингом"""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('DELETE FROM proxies WHERE rating < -5 AND fail_count > 10')
        await db.commit()

async def get_proxy_stats() -> dict:
    """Получает статистику по прокси"""
    async with aiosqlite.connect(DB_NAME) as db:
        stats = {}
        
        # Общее количество
        async with db.execute('SELECT COUNT(*) FROM proxies') as cursor:
            stats['total'] = (await cursor.fetchone())[0]
        
        # Рабочие
        async with db.execute('SELECT COUNT(*) FROM proxies WHERE is_working = 1') as cursor:
            stats['working'] = (await cursor.fetchone())[0]
        
        # Средний рейтинг
        async with db.execute('SELECT AVG(rating) FROM proxies') as cursor:
            stats['avg_rating'] = (await cursor.fetchone())[0] or 0
        
        # Самый высокий рейтинг
        async with db.execute('SELECT MAX(rating) FROM proxies') as cursor:
            stats['max_rating'] = (await cursor.fetchone())[0] or 0
        
        return stats