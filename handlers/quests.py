from aiogram import Router, F, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import aiosqlite
from datetime import datetime, timedelta
from config import DB_NAME
from database.db import update_exp, update_activity, save_timeout, remove_timeout, save_quest_message, increment_postponements, update_timeout
from services.scheduler import scheduler, quest_timeout_check
from services.api import update_telegram_tag
from services.rpg import calculate_level, get_tag_title
from services.category_detector import detect_category, format_category_tag

router = Router()

# Функция для очистки описания от команд
def clean_description(text: str) -> str:
    """Очищает описание квеста от ключевых слов команд"""
    keywords = ["НоваяЗадача", "НовыйКвест", "инцидент"]
    text = text.strip()
    
    for keyword in keywords:
        # Перебираем возможные варианты регистра
        text = text.replace(keyword, "")
        text = text.replace(keyword.lower(), "")
        text = text.replace(keyword.title(), "")
        text = text.replace(keyword.upper(), "")
    
    return " ".join(text.split())

@router.message(F.text.lower().contains("новаязадача") | F.text.lower().contains("новыйквест"))
async def create_task(message: types.Message):
    # Очищаем описание от команд
    task_text = clean_description(message.text)
    reward = 5
    time_hours = 4

    # Определяем категорию автоматически
    category = detect_category(task_text)
    category_tag = format_category_tag(category)

    if len(task_text) < 15:
        return await message.reply("Описание задачи слишком короткое!")
    try:
        await message.delete()
    except:
        pass

    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⚔️ Взять квест", callback_data="take_quest")]])
    sent_msg = await message.answer(
        f"📜 <b>НОВЫЙ КВЕСТ</b> {category_tag}\n\n<b>От:</b> {message.from_user.first_name}\n<b>Суть:</b> {task_text}\n\n<b>Награда:</b> +{reward} EXP\n<b>Время:</b> {time_hours} часа",
        reply_markup=kb
    )

    # Закрепляем сообщение с квестом (тихое закрепление)
    try:
        await message.chat.pin_message(
            message_id=sent_msg.message_id,
            disable_notification=True  # Закрепление без уведомления
        )
    except Exception as e:
        print(f"Не удалось закрепить сообщение: {e}")

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            'INSERT INTO tasks (chat_id, bot_msg_id, description, category, reward, time) VALUES (?, ?, ?, ?, ?, ?)',
            (sent_msg.chat.id, sent_msg.message_id, task_text, category, reward, time_hours)
        ) as cursor:
            task_id = cursor.lastrowid
        await db.commit()

        # Сохраняем сообщение с созданием квеста
        await save_quest_message(
            task_id=task_id,
            user_id=message.from_user.id,
            user_name=message.from_user.first_name,
            message_text=f"Создал(а) квест: {task_text}",
            is_reply_to_quest=True
        )

@router.callback_query(F.data == "take_quest")
async def process_take_quest(callback: types.CallbackQuery):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT exp, agreed_to_tos FROM users WHERE user_id = ?', (callback.from_user.id,)) as cursor:
            row = await cursor.fetchone()
            if not row: return await callback.reply("Сначала напиши /start")
            if row[1] == 0: return await callback.reply("Сначала согласись с условиями через /start")
            
            user_id = callback.from_user.id
            msg_id = callback.message.message_id

            async with aiosqlite.connect(DB_NAME) as db:
                async with db.execute('SELECT task_id, worker_id, status, time, description, chat_id FROM tasks WHERE bot_msg_id = ?', (msg_id,)) as cursor:
                    task = await cursor.fetchone()

                    if not task or task[2] != 'open': 
                        return await callback.answer("Уже занято!", show_alert=True)

                    task_id, worker_id, status, time_hours, description, chat_id = task

                    # Обновляем задачу
                    start_time = datetime.now()
                    timeout_time = start_time + timedelta(hours=time_hours)
                    
                    await db.execute(
                        'UPDATE tasks SET worker_id = ?, status = "in_progress", start_time = ? WHERE task_id = ?',
                        (user_id, start_time, task_id)
                    )
                    await db.commit()
                    
                    # Сохраняем таймаут в БД
                    await save_timeout(task_id, msg_id, user_id, timeout_time.isoformat())
                    
                    
            # Сохраняем сообщение о взятии квеста
            await save_quest_message(
                task_id=task_id,
                user_id=user_id,
                user_name=callback.from_user.first_name,
                message_text=f"Взял(а) квест в работу",
                is_reply_to_quest=True
            )

                # Добавляем задачу в планировщик
            scheduler.add_job(
                quest_timeout_check,
                'date',
                run_date=timeout_time,
                args=[callback.bot, task_id, msg_id, user_id],
                id=f"quest_timeout_{msg_id}",
                replace_existing=True
            )

            await update_activity(user_id) # Сброс АФК таймера

            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="⏸ Отсрочка", callback_data=f"postpone_quest")
            ]])

            await callback.message.edit_text(
                f"{callback.message.text}\n\n👣 <b>Взял на себя:</b> {callback.from_user.first_name}\n⏳ Время пошло!\n\nУдачи, герой!", reply_markup=kb
            )

@router.callback_query(F.data == "postpone_quest")
async def process_postpone_quest(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    msg_id = callback.message.message_id

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT task_id, worker_id, status, time FROM tasks WHERE bot_msg_id = ?', (msg_id,)) as cursor:
            task = await cursor.fetchone()

            if not task:
                return await callback.answer("Квест не найден!", show_alert=True)

            task_id, worker_id, status, time_hours = task

            if status != 'in_progress':
                return await callback.answer("Квест не в работе!", show_alert=True)

            if worker_id != user_id:
                return await callback.answer("Это не твой квест!", show_alert=True)

            # Вытягиваем текущее время таймера из БД
            async with db.execute('SELECT timeout_time FROM task_timeouts WHERE bot_msg_id = ?', (msg_id,)) as cursor:
                timeout_row = await cursor.fetchone()
                if not timeout_row:
                    return await callback.answer("Таймер не найден!", show_alert=True)

                current_timeout = datetime.fromisoformat(timeout_row[0])

            # Добавляем 2 часа к существующему времени таймера
            new_timeout_time = current_timeout + timedelta(hours=4)

            # Удаляем старый таймер из планировщика
            try:
                scheduler.remove_job(f"quest_timeout_{msg_id}")
            except:
                pass

            # Обновляем таймер в БД
            await update_timeout(msg_id, new_timeout_time.isoformat())

            # Добавляем новую задачу в планировщик
            scheduler.add_job(
                quest_timeout_check,
                'date',
                run_date=new_timeout_time,
                args=[callback.bot, task_id, msg_id, user_id],
                id=f"quest_timeout_{msg_id}",
                replace_existing=True
            )

            # Увеличиваем счетчик отсрочек
            await increment_postponements(task_id)

    # Сохраняем сообщение об отсрочке
    await save_quest_message(
        task_id=task_id,
        user_id=user_id,
        user_name=callback.from_user.first_name,
        message_text=f"Взял отсрочку (+4 часа)",
        is_reply_to_quest=True
    )

    await callback.answer("⏸ Отсрочка активирована! +4 часа к времени", show_alert=False)

    # Обновляем сообщение с информацией об отсрочке
    await callback.message.edit_text(
        f"{callback.message.text}\n\n✋ <b>Отсрочка активирована:</b> {callback.from_user.first_name}\n⏳ Добавлено 4 часа",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="⏸ Отсрочка", callback_data="postpone_quest")
        ]])
    )

    await update_activity(user_id)
    
@router.message(F.reply_to_message, F.text.lower().startswith("готово"))
async def finish_quest(message: types.Message):
    reply_msg = message.reply_to_message
    user_id = message.from_user.id
    report_text = message.text[6:].strip()

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT task_id, worker_id, status, description, reward, category FROM tasks WHERE bot_msg_id = ?', (reply_msg.message_id,)) as cursor:
            task = await cursor.fetchone()
            if not task:
                return

            task_id, worker_id, status, description, reward, category = task

            if status == 'completed':
                return await message.reply("🏁 Квест уже сдан.")
            if worker_id != user_id:
                return await message.reply("🧙‍♂️ Это не твой квест.")

            # Сохраняем отчет в переписку
            await save_quest_message(
                task_id=task_id,
                user_id=user_id,
                user_name=message.from_user.first_name,
                message_text=f"Отчет: {report_text}",
                is_reply_to_quest=True,
                reply_to_message_id=reply_msg.message_id
            )

            is_detailed = len(report_text) >= 15
            reward = reward if is_detailed else 1

            # Удаляем таймаут из БД
            await remove_timeout(reply_msg.message_id)

            # Удаляем задачу из планировщика
            try:
                scheduler.remove_job(f"quest_timeout_{reply_msg.message_id}")
            except:
                pass

            await db.execute('UPDATE tasks SET status = "completed" WHERE task_id = ?', (task_id,))
            await db.commit()

    new_exp = await update_exp(user_id, reward, reason="quest")
    await update_activity(user_id)
    new_lvl = calculate_level(new_exp)
    await update_telegram_tag(message.chat.id, user_id, new_lvl)

    title = get_tag_title(new_lvl)
    if is_detailed:
        await message.answer(f"🌟 <b>Квест выполнен!</b>\nГерой: {message.from_user.full_name} ({title})\nНаграда: +{reward} EXP")
    else:
        await message.answer(f"🤨 <b>Сухой отчет.</b>\nНаграда: +{reward} EXP")

    # Снимаем с закрепа при выполнении квеста
    try:
        await reply_msg.unpin()
    except Exception as e:
        print(f"Не удалось открепить сообщение: {e}")

    await reply_msg.edit_text(f"{reply_msg.text}\n\n<b>✅ Квест сдан</b>", reply_markup=None)

    # ── Промпт: сохранить решение в Wiki ──
    kb_wiki = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💾 Сохранить в Wiki", callback_data=f"save_wiki_{task_id}"),
            InlineKeyboardButton(text="🙅 Нет, не нужно", callback_data=f"no_wiki_{task_id}")
        ]
    ])
    await message.answer(
        f"📚 <b>Сохранить решение в базу знаний?</b>\n\n"
        f"Это поможет другим инженерам быстрее решать похожие задачи.\n"
        f"За +20 EXP и звание «Архивариус» тимлид добавит статью.\n"
        f"Нажмите кнопку — и тимлид получит уведомление.",
        reply_markup=kb_wiki
    )

@router.message(F.text.lower().startswith("план на завтра") | F.text.lower().startswith("планы на завтра"))
async def set_daily_plan(message: types.Message):
    current_hour = datetime.now().hour
    
    if current_hour >= 18:  # с 18:00 до 24:00
        await message.reply("🌙 Лучше поздно, чем никогда!")
    elif current_hour < 12:  # с 00:01 до 12:00
        await message.reply("☀️ Боец, так дело не пойдет, завтра уже наступило!")
    else:  # с 12:00 до 18:00
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute('UPDATE users SET plan_submitted = 1 WHERE user_id = ?', (message.from_user.id,))
            await db.commit()
        await message.reply("✅ План зафиксирован.")
        
        
        
        
        
@router.message(F.reply_to_message, F.text.lower().startswith("передать"))
async def transfer_quest(message: types.Message):
    reply_msg = message.reply_to_message
    user_id = message.from_user.id

    # Извлекаем ник целевого игрока из команды
    transfer_text = message.text[8:].strip()  # Убираем "передать"

    # Если начинается с @, убираем его
    if transfer_text.startswith("@"):
        target_username = transfer_text[1:].strip()
    else:
        target_username = transfer_text.strip()

    if not target_username:
        return await message.reply("❌ Укажите ник игрока: передать @nickname")

    # Ищем пользователя в БД по username
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT user_id, name FROM users WHERE LOWER(username) = LOWER(?)', (target_username,)) as cursor:
            result = await cursor.fetchone()
            if not result:
                return await message.reply(f"❌ Игрок <b>@{target_username}</b> не найден в системе.\n\nУбедитесь, что он вызвал /profile хотя бы один раз.")

            target_user_id, target_user_name = result

        # Получаем информацию о квесте
        async with db.execute('SELECT task_id, worker_id, status, description, reward FROM tasks WHERE bot_msg_id = ?', (reply_msg.message_id,)) as cursor:
            task = await cursor.fetchone()
            if not task:
                return

            task_id, worker_id, status, description, reward = task

            # Проверяем, что текущий пользователь является исполнителем квеста
            if worker_id != user_id:
                return await message.reply("🧙‍♂️ Это не твой квест, ты не можешь его передать!")

            # Обновляем исполнителя квеста
            await db.execute(
                'UPDATE tasks SET worker_id = ? WHERE task_id = ?',
                (target_user_id, task_id)
            )
            await db.commit()

            # Сохраняем действие в переписку
            await save_quest_message(
                task_id=task_id,
                user_id=user_id,
                user_name=message.from_user.first_name,
                message_text=f"Передал квест игроку {target_user_name}",
                is_reply_to_quest=True
            )

    await message.answer(
        f"✅ <b>КВЕСТ ПЕРЕДАН</b>\n\n"
        f"От: {message.from_user.first_name}\n"
        f"Кому: <b>{target_user_name}</b>\n\n"
        f"Квест #{task_id} теперь в руках нового исполнителя."
    )

    # Обновляем исходное сообщение квеста
    await reply_msg.edit_text(f"{reply_msg.text}\n\n👤 <b>Квест передан:</b> {target_user_name}", reply_markup=None)


# ─────────────────────────── Wiki save callbacks ───────────────────────────

@router.callback_query(F.data.startswith("save_wiki_"))
async def callback_save_wiki(callback: types.CallbackQuery):
    """Пользователь хочет сохранить решение в Wiki."""
    from services.wiki import suggest_wiki_category, suggest_wiki_title, save_wiki_article
    from aiogram.fsm.state import State, StatesGroup
    from aiogram.fsm.context import FSMContext

    task_id = int(callback.data.split("_")[-1])

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('''
            SELECT description, category FROM tasks WHERE task_id = ?
        ''', (task_id,)) as cursor:
            task = await cursor.fetchone()

    if not task:
        return await callback.answer("Квест не найден", show_alert=True)

    description, category = task

    await callback.message.edit_reply_markup()  # убираем кнопки
    await callback.answer("✍️ Отправьте текст решения в чат", show_alert=False)

    # Сохраняем task_id в FSM
    state = callback.bot.user  # это не FSM, используем временное хранилище
    # Для простоты используем callback data - но нам нужно FSM
    # Используем простую структуру: сохраняем данные и ждём ввод

    # Сохраняем task_id и описание в "временную память" через callback
    # Используем подход: запоминаем task_id в user_pages (уже есть в quest_manager)
    # Или просто используем отдельный словарь
    global _wiki_input_state
    _wiki_input_state[callback.from_user.id] = {
        "task_id": task_id,
        "description": description,
        "category": category
    }

    await callback.message.answer(
        f"📚 <b>Добавление в Wiki</b>\n\n"
        f"Квест #{task_id}: {description[:80]}\n"
        f"Категория (предложенная): {category}\n\n"
        f"✍️ Напишите текст решения:\n"
        f"1. Опишите проблему\n"
        f"2. Опишите решение пошагово\n"
        f"3. Укажите важные нюансы\n\n"
        f"Напишите <code>/wiki_skip</code> чтобы пропустить."
    )


@router.callback_query(F.data.startswith("no_wiki_"))
async def callback_no_wiki(callback: types.CallbackQuery):
    """Пользователь отказался сохранять в Wiki."""
    task_id = int(callback.data.split("_")[-1])
    await callback.message.edit_reply_markup()
    await callback.answer("OK, решение не сохранено", show_alert=False)
    await callback.message.answer("👍 Если передумаете — напишите <code>/wiki</code> в любой момент.")


def _clean_description(text: str) -> str:
    """Очищает описание квеста от команд"""
    text = text.strip()
    text = text.replace("НоваяЗадача", "").replace("новаязадача", "")
    text = text.replace("НовыйКвест", "").replace("новыйквест", "")
    text = text.replace("инцидент", "")
    text = text.strip()
    return text

# Глобальное состояние для ввода Wiki
_wiki_input_state: dict = {}


@router.message(F.text)
async def wiki_input_handler(message: types.Message):
    """Обработчик ввода текста для Wiki."""
    user_id = message.from_user.id

    if user_id not in _wiki_input_state:
        return

    state_data = _wiki_input_state[user_id]

    # Проверяем команду отмены
    if message.text.strip().lower() in ("/wiki_skip", "/wiki_cancel", "/отмена"):
        del _wiki_input_state[user_id]
        await message.answer("❌ Добавление статьи отменено.")
        return

    text = message.text.strip()
    if len(text) < 15:
        await message.answer("Слишком короткий текст. Напишите подробнее (минимум 15 символов).")
        return

    # Сохраняем статью
    from services.wiki import save_wiki_article, suggest_wiki_category
    from database.db import update_exp

    title = suggest_wiki_title(state_data["description"])
    category = state_data.get("category", "Other")

    article_id = await save_wiki_article(
        title=title,
        content=text,
        category=category,
        author_id=user_id,
        author_name=message.from_user.first_name,
        is_verified=0  # требует проверки тимлида
    )

    # Награда за сохранение решения
    await update_exp(user_id, 20, reason="wiki_add")

    del _wiki_input_state[user_id]

    await message.answer(
        f"✅ <b>Решение сохранено в базу знаний!</b>\n\n"
        f"📚 <b>{title}</b>\n"
        f"📂 Категория: {category}\n"
        f"⏳ Статус: на проверке у тимлида\n"
        f"💰 Награда: +20 EXP\n\n"
        f"После проверки тимлида статья появится для всех через <code>/wiki</code>"
    )
