"""
Wiki-бот: активный поиск и ручное добавление статей.

Команды:
  /wiki [запрос] — поиск статей из базы знаний
  /wiki add — добавить новую статью (тимлид)
  /wiki list — список всех категорий
  /wiki stats — статистика wiki
"""

from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import aiosqlite
from datetime import datetime

from config import DB_NAME, TEAMLEAD_ID
from services.wiki import (
    search_wiki,
    get_all_categories,
    get_wiki_by_category,
    like_wiki_article,
    get_wiki_stats,
    suggest_wiki_category,
    suggest_wiki_title,
    save_wiki_article,
    get_wiki_article_by_id,
    get_unverified_articles,
    approve_wiki_article,
    update_wiki_article,
)

router = Router()


# ─────────────────────────── search ───────────────────────────

@router.message(Command("wiki"))
async def cmd_wiki(message: types.Message):
    """Поиск в Wiki: /wiki запрос или /wiki без параметров для списка категорий."""
    cmd_parts = message.text.strip().split(maxsplit=1)
    if len(cmd_parts) == 1:
        # Просто /wiki — показываем категории
        return await cmd_wiki_list(message)

    query = cmd_parts[1].strip()
    if len(query) < 2:
        return await message.answer("🔍 Введите запрос для поиска (минимум 2 символа).\nПример: /wiki принтер замятие")

    results = await search_wiki(query, limit=5)

    if not results:
        return await message.answer(f"🔍 Ничего не найдено по запросу «{query}».\n\n💡 <b>Совет:</b> попробуйте другие ключевые слова или напишите <code>/wiki add</code> чтобы добавить статью (доступно тимлиду).")

    lines = [f"🔍 <b>НАЙДЕНО: {len(results)} статей</b>\n"]

    for i, (aid, title, content, category, tags, author, likes, created) in enumerate(results, 1):
        lines.append(f"#{i} 📚 <b>{title}</b> <i>({category})</i>")
        short = content[:120].replace('\n', ' ')
        lines.append(f"   {short}...")
        lines.append(f"   👤 {author or 'anon'} | ❤️ {likes} | {datetime.fromisoformat(created.replace(' ', '+')).strftime('%d.%m.%Y')}")

        # Кнопки лайка
        lines.append("")

    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for i, (aid, title, content, category, tags, author, likes, created) in enumerate(results, 1):
        kb.inline_keyboard.append([
            InlineKeyboardButton(text=f"#{i} ❤️", callback_data=f"wiki_like_{aid}"),
            InlineKeyboardButton(text="🔗", url=f"tg://resolve?domain={message.from_user.username or 'user'}")
        ])

    # Фрагмент текста для отправки
    text = "\n".join(lines)
    await message.answer(text, parse_mode="HTML", reply_markup=kb)


async def cmd_wiki_list(message: types.Message):
    """Список категорий wiki."""
    categories = await get_all_categories()
    stats = await get_wiki_stats()

    text = f"📚 <b>БАЗА ЗНАНИЙ</b>\n\n"
    text += f"Всего статей: {stats['total']} | Подтверждено: {stats['verified']}\n\n"

    if categories:
        text += "<b>Категории:</b>\n"
        for cat in categories:
            cnt = stats['by_category'].get(cat, 0)
            text += f"  • {cat} ({cnt})\n"
        text += "\n"
        # Кнопки категорий
        kb = InlineKeyboardMarkup(inline_keyboard=[])
        for cat in categories:
            kb.inline_keyboard.append([
                InlineKeyboardButton(text=f"📂 {cat}", callback_data=f"wiki_cat_{cat}")
            ])
        kb.inline_keyboard.append([
            InlineKeyboardButton(text="📊 Статистика", callback_data="wiki_stats")
        ])
        await message.answer(text, parse_mode="HTML", reply_markup=kb)
    else:
        text += "Пока нет подтверждённых статей.\n\n"
        text += "Напишите <code>/wiki add</code> чтобы добавить первое решение!"
        await message.answer(text, parse_mode="HTML")


@router.callback_query(F.data.startswith("wiki_cat_"))
async def callback_wiki_category(callback: types.CallbackQuery):
    """Показывает статьи по категории."""
    cat = callback.data.replace("wiki_cat_", "")
    articles = await get_wiki_by_category(cat, limit=10)

    lines = [f"📂 <b>КАТЕГОРИЯ: {cat}</b>\n"]

    for i, (aid, title, content, category, tags, author, likes, created) in enumerate(articles, 1):
        lines.append(f"#{i} 📚 <b>{title}</b>")
        short = content[:100].replace('\n', ' ')
        lines.append(f"   {short}")
        lines.append(f"   ❤️ {likes} | {datetime.fromisoformat(created.replace(' ', '+')).strftime('%d.%m.%Y')}")
        lines.append("")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад к категориям", callback_data="wiki_list")]
    ])

    await callback.message.edit_text("\n".join(lines), parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "wiki_stats")
async def callback_wiki_stats(callback: types.CallbackQuery):
    """Показывает статистику wiki."""
    stats = await get_wiki_stats()

    lines = [f"📊 <b>СТАТИСТИКА WIKI</b>\n\n"]
    lines.append(f"Всего статей: {stats['total']}")
    lines.append(f"Подтверждено: {stats['verified']}")
    lines.append("")
    lines.append("<b>По категориям:</b>")
    for cat, cnt in stats['by_category'].items():
        lines.append(f"  • {cat}: {cnt}")
    lines.append("")
    if stats['top_authors']:
        lines.append("<b>Топ авторы:</b>")
        for author, cnt in stats['top_authors']:
            lines.append(f"  👤 {author}: {cnt} статей")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="wiki_list")]
    ])

    await callback.message.edit_text("\n".join(lines), parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("wiki_like_"))
async def callback_wiki_like(callback: types.CallbackQuery):
    """Лайк статьи."""
    article_id = int(callback.data.replace("wiki_like_", ""))
    ok = await like_wiki_article(article_id, callback.from_user.id)
    if ok:
        await callback.answer("❤️ Лайк добавлен!", show_alert=True)
    else:
        await callback.answer("Статья не найдена", show_alert=True)


@router.callback_query(F.data.startswith("wiki_open_"))
async def callback_wiki_open(callback: types.CallbackQuery):
    """Показать полную статью по ID."""
    article_id = int(callback.data.replace("wiki_open_", ""))
    article = await get_wiki_article_by_id(article_id)
    if not article:
        return await callback.answer("Статья не найдена", show_alert=True)
    aid, title, content, category, tags, author, likes, created = article

    text = f"📚 <b>{title}</b> <i>({category})</i>\n\n{content}\n\n👤 {author or 'anon'} | ❤️ {likes}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❤️ Полезно", callback_data=f"wiki_like_{aid}")],
        [InlineKeyboardButton(text="Использовал это решение", callback_data=f"wiki_use_{aid}")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="wiki_list")]
    ])

    # Отправляем в чат, где нажали кнопку (работает и в личке и в группе)
    await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("wiki_check_"))
async def callback_wiki_check(callback: types.CallbackQuery):
    """Показать чек-лист (первые строки статьи)."""
    article_id = int(callback.data.replace("wiki_check_", ""))
    article = await get_wiki_article_by_id(article_id)
    if not article:
        return await callback.answer("Статья не найдена", show_alert=True)
    aid, title, content, category, tags, author, likes, created = article

    # Берём первые 8 непустых строк как чек-лист
    lines = [l.strip() for l in content.splitlines() if l.strip()]
    checklist = "\n".join(lines[:8]) if lines else content[:400]

    text = f"🗒️ <b>Чек-лист: {title}</b>\n\n{checklist}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Открыть решение", callback_data=f"wiki_open_{aid}" )],
        [InlineKeyboardButton(text="Использовал это решение", callback_data=f"wiki_use_{aid}" )],
        [InlineKeyboardButton(text="❤️ Полезно", callback_data=f"wiki_like_{aid}")]
    ])

    await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


# ─────────────────────────── add article (admin) ───────────────────────────

# HANDLERS: "Использовал это решение" — запись использования статьи
@router.callback_query(F.data.startswith("wiki_use_"))
async def callback_wiki_use(callback: types.CallbackQuery):
    """Пользователь отметил, что использовал статью для решения квеста.

    Ожидаем, что кнопка нажата в ЛС исполнителя (или в контексте квеста). Если вызывается из лички —
    пытаемся определить текущий task_id через reply_to_message или через последний взятый квест в БД.
    """
    from database.db import save_wiki_usage, get_quests_by_worker, get_quest_messages, get_task_by_id

    article_id = int(callback.data.replace("wiki_use_", ""))
    user_id = callback.from_user.id

    # Попробуем определить task_id: если кнопка нажата в ответ на сообщение квеста — используем reply_to
    task_id = None
    try:
        if callback.message and callback.message.reply_to_message:
            # Если есть reply_to_message — пытаемся получить task по bot_msg_id
            bot_msg_id = callback.message.reply_to_message.message_id
            async with aiosqlite.connect(DB_NAME) as db:
                async with db.execute('SELECT task_id FROM tasks WHERE bot_msg_id = ?', (bot_msg_id,)) as c:
                    row = await c.fetchone()
                    if row:
                        task_id = row[0]
    except Exception:
        pass

    # Если не удалось — ищем последний активный квест этого исполнителя
    if not task_id:
        try:
            # Получаем квесты исполнителя и берём самый последний in_progress
            async with aiosqlite.connect(DB_NAME) as db:
                async with db.execute('SELECT task_id FROM tasks WHERE worker_id = ? AND status = "in_progress" ORDER BY task_id DESC LIMIT 1', (user_id,)) as c:
                    row = await c.fetchone()
                    if row:
                        task_id = row[0]
        except Exception:
            pass

    if not task_id:
        await callback.answer("Не удалось определить квест. Откройте квестовое сообщение и нажмите кнопку снова.", show_alert=True)
        return

    # Сохраняем использование
    try:
        await save_wiki_usage(task_id, article_id, user_id)
        # Увеличим счётчик использования в wiki (необязательно) — тут можно увеличить likes или отдельное поле
        await callback.answer("✅ Отмечено: статья использована для решения квеста", show_alert=True)
    except Exception as e:
        print(f"Error saving wiki usage: {e}")
        await callback.answer("Ошибка при сохранении использования. Попробуйте позже.", show_alert=True)


# FSM-состояния для добавления статьи (ниже)
# FSM-состояния для добавления статьи
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext


class WikiAddStates(StatesGroup):
    waiting_for_title = State()
    waiting_for_content = State()
    waiting_for_category = State()


wiki_add_states = WikiAddStates()


@router.message(Command("wiki_add"), F.from_user.id == TEAMLEAD_ID)
async def cmd_wiki_add(message: types.Message, state: FSMContext):
    """Тимлид начинает добавление статьи."""
    await state.clear()
    await state.set_state(WikiAddStates.waiting_for_title)
    await message.answer(
        "📝 <b>Добавление статьи в Wiki</b>\n\n"
        "Шаг 1/3: Введите заголовок статьи.\n"
        "Пример: Как починить замятие бумаги в HP LaserJet"
    )


# ─────────────────────────── Review queue (teamlead) ───────────────────────────

@router.message(Command("wiki_review"))
async def cmd_wiki_review(message: types.Message):
    """Команда для тимлида: /wiki_review — показать очередь непроверенных статей."""
    if message.from_user.id != TEAMLEAD_ID:
        return await message.reply("Доступно только тимлиду.")

    articles = await get_unverified_articles(limit=20)
    if not articles:
        return await message.reply("Очередь проверок пуста.")

    lines = ["📝 <b>ОЧЕРЕДЬ НА ПРОВЕРКУ:</b>\n"]
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for (aid, title, content, category, tags, author, likes, created, uses) in articles:
        short = content[:120].replace('\n', ' ')
        lines.append(f"#{aid} 📚 <b>{title}</b> — {short}...")
        # Добавляем кнопки для этой статьи
        kb.inline_keyboard.append([
            InlineKeyboardButton(text=f"✅ Одобрить #{aid}", callback_data=f"wiki_approve_{aid}"),
            InlineKeyboardButton(text=f"❌ Отклонить #{aid}", callback_data=f"wiki_reject_{aid}")
        ])
        kb.inline_keyboard.append([
            InlineKeyboardButton(text=f"✏️ Редактировать #{aid}", callback_data=f"wiki_edit_{aid}")
        ])
        kb.inline_keyboard.append([InlineKeyboardButton(text="—", callback_data="noop")])

    await message.answer("\n".join(lines), parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data == "wiki_review")
async def callback_wiki_review(callback: types.CallbackQuery):
    # Поддержка из callback — просто делегируем к команде
    return await cmd_wiki_review(callback.message)


@router.callback_query(F.data.startswith("wiki_approve_"))
async def callback_wiki_approve(callback: types.CallbackQuery):
    if callback.from_user.id != TEAMLEAD_ID:
        return await callback.answer("Только тимлид может подтверждать статьи.", show_alert=True)
    aid = int(callback.data.replace("wiki_approve_", ""))
    await approve_wiki_article(aid)
    await callback.answer("✅ Статья подтверждена и доступна всем.", show_alert=True)
    try:
        await callback.message.delete()
    except:
        pass


@router.callback_query(F.data.startswith("wiki_reject_"))
async def callback_wiki_reject(callback: types.CallbackQuery):
    if callback.from_user.id != TEAMLEAD_ID:
        return await callback.answer("Только тимлид может отклонять статьи.", show_alert=True)
    aid = int(callback.data.replace("wiki_reject_", ""))
    # Пометим как отклонённую (is_verified = 2)
    await update_wiki_article(aid, is_verified=2)
    await callback.answer("❌ Статья помечена как отклонённая.", show_alert=True)
    try:
        await callback.message.delete()
    except:
        pass


# FSM для редактирования статьи (тимлид)
class WikiEditStates(StatesGroup):
    waiting_for_content = State()


_wiki_edit_state: dict = {}


@router.callback_query(F.data.startswith("wiki_edit_"))
async def callback_wiki_edit(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != TEAMLEAD_ID:
        return await callback.answer("Только тимлид может редактировать статьи.", show_alert=True)
    aid = int(callback.data.replace("wiki_edit_", ""))
    # Сохраняем в память
    _wiki_edit_state[callback.from_user.id] = aid
    await callback.answer("✏️ Отправьте новый полный текст статьи в этом чате.", show_alert=True)
    await state.set_state(WikiEditStates.waiting_for_content)


@router.message(WikiEditStates.waiting_for_content, F.from_user.id == TEAMLEAD_ID)
async def wiki_edit_receive(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id not in _wiki_edit_state:
        await state.clear()
        return await message.reply("Нет выбранной статьи для редактирования.")
    aid = _wiki_edit_state[user_id]
    new_content = message.text.strip()
    if len(new_content) < 5:
        return await message.reply("Текст слишком короткий. Отправьте более развёрнутый текст.")
    # Обновляем статью и помечаем как подтверждённую
    await update_wiki_article(aid, content=new_content, is_verified=1)
    await message.reply(f"✅ Статья #{aid} обновлена и подтверждена.")
    del _wiki_edit_state[user_id]
    await state.clear()


@router.message(WikiAddStates.waiting_for_title)
async def wiki_add_title(message: types.Message, state: FSMContext):
    title = message.text.strip()
    if len(title) < 3:
        return await message.answer("Заголовок слишком короткий. Введите заново.")
    await state.update_data(title=title)
    await state.set_state(WikiAddStates.waiting_for_content)
    await message.answer(
        "Шаг 2/3: Введите содержание статьи.\n"
        "Опишите решение пошагово. Можно использовать Markdown.\n"
        "Напишите <code>/wiki_cancel</code> для отмены."
    )


@router.message(WikiAddStates.waiting_for_content)
async def wiki_add_content(message: types.Message, state: FSMContext):
    content = message.text.strip()
    if len(content) < 10:
        return await message.answer("Слишком короткое описание. Напишите подробнее.")

    data = await state.get_data()
    title = data.get('title', '')

    # Авто-определение категории
    category = suggest_wiki_category(content + " " + title)

    await state.clear()

    article_id = await save_wiki_article(
        title=title,
        content=content,
        category=category,
        author_id=message.from_user.id,
        author_name=message.from_user.first_name,
        is_verified=1
    )

    # Награда автору
    from database.db import update_exp
    await update_exp(message.from_user.id, 20, reason="wiki_add")

    await message.answer(
        f"✅ Статья добавлена в Wiki!\n\n"
        f"📚 <b>{title}</b>\n"
        f"📂 Категория: {category}\n"
        f"💰 Награда: +20 EXP (Звание Архивариуса)\n\n"
        f"Теперь инженеры могут найти это решение через /wiki"
    )


@router.message(Command("wiki_cancel"))
async def wiki_add_cancel(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Добавление статьи отменено.")


@router.message(F.text.lower().in_({"помощь", "help", "подсказка", "совет"}))
async def cmd_wiki_help(message: types.Message):
    """Быстрый поиск: если пользователь пишет "помощь принтер" — ищем в wiki."""
    # Проверяем, есть ли запрос длиннее одного слова
    parts = message.text.strip().split()
    if len(parts) >= 2:
        query = " ".join(parts[1:])
        results = await search_wiki(query, limit=3)

        if results:
            lines = [f"💡 <b>НАЙДЕНО В БАЗЕ ЗНАНИЙ:</b>\n"]
            for i, (aid, title, content, category, tags, author, likes, created) in enumerate(results, 1):
                lines.append(f"#{i} 📚 <b>{title}</b>")
                short = content[:150].replace('\n', ' ')
                lines.append(f"   {short}...")
            await message.answer("\n".join(lines), parse_mode="HTML")
            return

    # Если просто "помощь" или "help" — показываем справку по wiki
    text = (
        "📚 <b>База знаний Wiki</b>\n\n"
        "Ищите решения в базе знаний:\n"
        "• <code>/wiki принтер замятие</code> — поиск по ключевым словам\n"
        "• <code>/wiki</code> — список категорий\n"
        "• <code>/wiki stats</code> — статистика\n\n"
        "💡 Совет: пишите конкретные запросы, например:\n"
        "  <code>/wiki windows обновление ошибка</code>\n"
        "  <code>/wiki 1с отчет</code>\n"
        "  <code>/wiki hp замятие бумаги</code>"
    )
    await message.answer(text, parse_mode="HTML")
