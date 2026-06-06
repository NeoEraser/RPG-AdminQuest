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

        # Индексы для быстрого поиска
        await db.execute('CREATE INDEX IF NOT EXISTS idx_quest_messages_task_id ON quest_messages(task_id)')
        await db.execute('CREATE INDEX IF NOT EXISTS idx_quest_messages_created_at ON quest_messages(created_at)')
        await db.execute('CREATE INDEX IF NOT EXISTS idx_exp_history_user_date ON exp_history(user_id, change_date)')

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