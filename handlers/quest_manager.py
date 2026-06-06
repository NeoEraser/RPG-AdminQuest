from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest
import aiosqlite
from datetime import datetime
from config import DB_NAME
from database.db import get_all_quests_with_stats, get_quest_messages, get_task_by_id, get_quests_by_worker, get_all_workers

router = Router()

# Словарь для временного хранения страниц пагинации
user_pages = {}


@router.message(Command("quests_list"))
async def list_all_quests(message: types.Message):
    """Выводит список всех квестов с пагинацией и фильтром по исполнителю"""
    page = 1
    quests = await get_all_quests_with_stats(limit=50)  # Получаем последние 50

    if not quests:
        await message.answer("📭 В базе данных нет квестов.")
        return

    # Сохраняем страницу пользователя
    user_pages[message.from_user.id] = {'quests': quests, 'page': page, 'filter_worker': None}

    # Показываем выбор фильтра
    await show_worker_filter(message)


async def show_worker_filter(message: types.Message):
    """Показывает фильтр по исполнителям"""
    workers = await get_all_workers()

    text = "👥 <b>ФИЛЬТР ПО ИСПОЛНИТЕЛЯМ</b>\n\n"
    text += f"Всего исполнителей: {len(workers)}\n\n"
    text += "Выберите исполнителя или нажмите 'Все квесты':"

    # Создаем кнопки исполнителей (2 в ряду)
    keyboard = []

    # Кнопки исполнителей
    worker_buttons = []
    for i, worker in enumerate(workers):
        worker_buttons.append(
            InlineKeyboardButton(text=f"👤 {worker}", callback_data=f"filter_worker_{worker}")
        )

    # Добавляем кнопки по 2 в ряду
    for i in range(0, len(worker_buttons), 2):
        if i + 1 < len(worker_buttons):
            keyboard.append([worker_buttons[i], worker_buttons[i + 1]])
        else:
            keyboard.append([worker_buttons[i]])

    # Кнопка "Все квесты"
    keyboard.append([InlineKeyboardButton(text="📋 Все квесты", callback_data="filter_worker_all")])

    reply_markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
    await message.answer(text, reply_markup=reply_markup)

@router.callback_query(F.data.startswith("filter_worker_"))
async def handle_worker_filter(callback: types.CallbackQuery):
    """Обрабатывает выбор фильтра по исполнителю"""
    worker_name = callback.data.replace("filter_worker_", "")
    
    if worker_name == "all":
        # Показываем все квесты
        quests = await get_all_quests_with_stats(limit=50)
        user_pages[callback.from_user.id] = {'quests': quests, 'page': 1, 'filter_worker': None}
        await show_quests_page(callback.message, quests, 1)
    else:
        # Фильтруем по исполнителю
        quests = await get_quests_by_worker(worker_name)
        if not quests:
            await callback.answer(f"У исполнителя {worker_name} нет квестов!", show_alert=True)
            return
        user_pages[callback.from_user.id] = {'quests': quests, 'page': 1, 'filter_worker': worker_name}
        await show_quests_page(callback.message, quests, 1)
    
    await callback.answer()

async def show_quests_page(message: types.Message, quests: list, page: int):
    """Отображает страницу со списком квестов"""
    items_per_page = 5
    total_pages = (len(quests) + items_per_page - 1) // items_per_page
    
    if page < 1:
        page = 1
    if page > total_pages:
        page = total_pages
    
    start_idx = (page - 1) * items_per_page
    end_idx = start_idx + items_per_page
    page_quests = quests[start_idx:end_idx]
    
    # Эмодзи для статусов
    status_emoji = {
        'open': '🟢',
        'in_progress': '🟡',
        'completed': '✅'
    }
    
    status_names = {
        'open': 'Доступен',
        'in_progress': 'В работе',
        'completed': 'Завершен'
    }
    
    text = f"📋 <b>СПИСОК КВЕСТОВ</b> (страница {page}/{total_pages})\n\n"
    
    for quest in page_quests:
        (task_id, bot_msg_id, chat_id, description, status, reward, 
         time_hours, start_time, worker_name, messages_count, last_message) = quest
        
        emoji = status_emoji.get(status, '⚪')
        status_text = status_names.get(status, status)
        
        short_desc = description[:40] + "..." if len(description) > 40 else description
        
        if start_time:
            dt = datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S.%f")
            date =dt.strftime("%d.%m.%y %H:%M")
        else:
            date = ''
        text += f"{emoji} <b>Квест #{task_id} {date} {worker_name if worker_name else ''}</b>\n"
        text += f"   📝 {short_desc}\n"
        text += f"   📊 {status_text} | 💬 {messages_count} сообщ.\n"
        
        if status == 'in_progress' and worker_name:
            text += f"   👤 Исполнитель: {worker_name}\n"
        
        text += "\n"
    
    # Клавиатура для пагинации и выбора квеста
    keyboard = []
    
    # Кнопки пагинации
    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"quests_page_{page-1}"))
    if page < total_pages:
        nav_buttons.append(InlineKeyboardButton(text="Вперед ▶️", callback_data=f"quests_page_{page+1}"))
    
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    # Кнопки квестов (5 в одном ряду)
    quest_buttons = []
    for quest in page_quests[:5]:  # Только первые 5 квестов
        task_id = quest[0]
        quest_buttons.append(
            InlineKeyboardButton(text=f"#{task_id}", callback_data=f"view_quest_{task_id}")
        )
    
    if quest_buttons:
        keyboard.append(quest_buttons)  # Все 5 кнопок в одном ряду
    
    # Кнопка обновления
    keyboard.append([InlineKeyboardButton(text="🔄 Обновить", callback_data="refresh_quests")])
    
    reply_markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
    
    # Отправляем или редактируем сообщение
    if hasattr(message, 'message_id') and message.message_id:
        try:
            await message.edit_text(text, reply_markup=reply_markup)
        except TelegramBadRequest:
            await message.answer(text, reply_markup=reply_markup)
    else:
        await message.answer(text, reply_markup=reply_markup)


@router.callback_query(F.data.startswith("quests_page_"))
async def handle_quests_page(callback: types.CallbackQuery):
    """Обрабатывает переключение страниц списка квестов"""
    page = int(callback.data.split("_")[-1])
    
    user_data = user_pages.get(callback.from_user.id)
    if not user_data:
        quests = await get_all_quests_with_stats(limit=50)
        user_pages[callback.from_user.id] = {'quests': quests, 'page': page}
    else:
        quests = user_data['quests']
        user_data['page'] = page
    
    await show_quests_page(callback.message, quests, page)
    await callback.answer()


@router.callback_query(F.data.startswith("view_quest_"))
async def view_quest_details(callback: types.CallbackQuery):
    """Показывает детали квеста и всю переписку"""
    task_id = int(callback.data.split("_")[-1])
    
    # Получаем информацию о квесте
    task = await get_task_by_id(task_id)
    if not task:
        await callback.answer("Квест не найден!", show_alert=True)
        return
    
    # Получаем все сообщения по квесту
    messages = await get_quest_messages(task_id)
    
    # Формируем текст с информацией о квесте
    (task_id, chat_id, bot_msg_id, description, worker_id, reward, 
     time_hours, status, start_time, worker_name) = task[:10]
    
    status_emoji = {
        'open': '🟢',
        'in_progress': '🟡',
        'completed': '✅'
    }.get(status, '⚪')
    
    status_names = {
        'open': 'Доступен',
        'in_progress': 'В работе',
        'completed': 'Завершен'
    }.get(status, status)
    
    # Ссылка на сообщение с квестом
    quest_link = f"https://t.me/c/{abs(int(str(chat_id)[2:]))}/52/{bot_msg_id}" if chat_id and bot_msg_id else "Нет ссылки"
    
    text = f"📋 <b>ДЕТАЛИ КВЕСТА #{task_id}</b>\n\n"
    text += f"{status_emoji} <b>Статус:</b> {status_names}\n"
    text += f"📝 <b>Описание:</b>\n<code>{description}</code>\n\n"
    text += f"💰 <b>Награда:</b> +{reward} EXP\n"
    text += f"⏱ <b>Время на выполнение:</b> {time_hours} часа\n"
    
    if start_time:
        start_time_str = datetime.fromisoformat(start_time.replace(' ', '+')).strftime("%d.%m.%Y %H:%M")
        text += f"🕐 <b>Время старта:</b> {start_time_str}\n"
    
    if worker_name:
        text += f"👤 <b>Исполнитель:</b> {worker_name}\n"
    
    text += f"🔗 <b>Ссылка на квест:</b> <a href='{quest_link}'>Перейти</a>\n\n"
    
    if messages:
        text += f"💬 <b>ПЕРЕПИСКА ПО КВЕСТУ</b> ({len(messages)} сообщ.)\n"
        text += "─" * 30 + "\n"
        
        # Показываем последние 20 сообщений
        for msg in messages[-20:]:
            msg_id, user_id, user_name, msg_text, created_at, is_reply = msg
            created_time = datetime.fromisoformat(created_at.replace(' ', '+')).strftime("%d.%m %H:%M")
            prefix = "📌" if is_reply else "💬"
            text += f"{prefix} <b>{user_name}</b> [{created_time}]:\n   {msg_text[:100]}\n\n"
        
        if len(messages) > 20:
            text += f"<i>... и еще {len(messages) - 20} сообщений</i>\n"
    else:
        text += "💬 <b>Переписка по квесту отсутствует.</b>"
    
    # Клавиатура для действий
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔗 Открыть квест в Telegram", url=quest_link)],
        [InlineKeyboardButton(text="◀️ Назад к списку", callback_data="back_to_quests_list")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard, disable_web_page_preview=True)
    await callback.answer()


@router.callback_query(F.data == "refresh_quests")
async def refresh_quests_list(callback: types.CallbackQuery):
    """Обновляет список квестов с учетом текущего фильтра"""
    user_data = user_pages.get(callback.from_user.id)
    filter_worker = user_data.get('filter_worker') if user_data else None
    
    if filter_worker:
        quests = await get_quests_by_worker(filter_worker)
    else:
        quests = await get_all_quests_with_stats(limit=50)
    
    user_pages[callback.from_user.id] = {'quests': quests, 'page': 1, 'filter_worker': filter_worker}
    await show_quests_page(callback.message, quests, 1)
    await callback.answer("Список обновлен!", show_alert=True)


@router.callback_query(F.data == "back_to_quests_list")
async def back_to_quests_list(callback: types.CallbackQuery):
    """Возвращает к списку квестов"""
    user_data = user_pages.get(callback.from_user.id)
    if user_data:
        await show_quests_page(callback.message, user_data['quests'], user_data.get('page', 1))
    else:
        quests = await get_all_quests_with_stats(limit=50)
        await show_quests_page(callback.message, quests, 1)
    await callback.answer()