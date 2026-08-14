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


@router.callback_query(F.data == "wiki_list")
async def callback_wiki_list(callback: types.CallbackQuery):
    """Показывает список категорий — обработчик для кнопок "Назад" и "Назад к категориям"."""
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
    else:
        text += "Пока нет подтверждённых статей.\n\n"
        text += "Напишите <code>/wiki_add</code> чтобы добавить первое решение!"
        kb = None

    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
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


# ─────────────────────────── add article (admin) ───────────────────────────

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
    await update_exp(message.from_user.id, 5, reason="wiki_add")

    await message.answer(
        f"✅ Статья добавлена в Wiki!\n\n"
        f"📚 <b>{title}</b>\n"
        f"📂 Категория: {category}\n"
        f"💰 Награда: +5 EXP (Звание Архивариуса)\n\n"
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
