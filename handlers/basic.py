from aiogram import Router, F, types
from aiogram.filters import Command
import aiosqlite
from config import DB_NAME
from services.rpg import calculate_level, exp_for_next_level, get_tag_title
from database.db import get_month_activity
from datetime import datetime
import calendar

router = Router()

def build_activity_calendar(daily_changes: dict, year: int, month: int) -> str:
    """Генерирует GitHub-style календарик активности"""
    days_in_month = calendar.monthrange(year, month)[1]
    first_weekday = calendar.monthrange(year, month)[0]

    cal_lines = []
    week_emojis = []

    for day in range(1, days_in_month + 1):
        if day == 1:
            week_emojis.extend(['◼️'] * first_weekday)

        exp_change = daily_changes.get(day, 0)
        if exp_change < 0:
            emoji = '🔴'
        elif exp_change == 0:
            emoji = '⬜'
        else:
            emoji = '🟩'

        week_emojis.append(emoji)

        if len(week_emojis) == 7:
            cal_lines.append(' '.join(week_emojis))
            week_emojis = []

    if week_emojis:
        cal_lines.append(' '.join(week_emojis))

    calendar_text = '\n'.join(cal_lines)
    # legend = '\n🟩 плюс | ⬜ ноль | 🔴 минус'

    return calendar_text #+ legend

@router.message(Command("start"))
async def cmd_start(message: types.Message):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT user_id FROM users WHERE user_id = ?', (message.from_user.id,)) as cursor:
            user = await cursor.fetchone()
        if not user:
            await db.execute('INSERT INTO users (user_id, name) VALUES (?, ?)', (message.from_user.id, message.from_user.first_name))
            await db.commit()
            await message.answer("🎮 Ты зарегистрирован в системе <b>RPG-админов</b>! Теперь ты можешь брать квесты.")
        else:
            await message.answer("⚔️ Ты уже в строю, боец!")

@router.message(Command("profile"))
async def show_profile(message: types.Message):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT exp FROM users WHERE user_id = ?', (message.from_user.id,)) as cursor:
            row = await cursor.fetchone()
            if not row: return await message.reply("Сначала напиши /start")

            exp = row[0]
            lvl = calculate_level(exp)
            title = get_tag_title(lvl)
            next_lvl_exp = exp_for_next_level(lvl)

            prev_lvl_exp = exp_for_next_level(lvl - 1) if lvl > 1 else 0
            needed_for_lvl = next_lvl_exp - prev_lvl_exp
            current_progress = exp - prev_lvl_exp
            filled_units = int((current_progress / needed_for_lvl) * 10) if needed_for_lvl > 0 else 0

            progress_bar = "▓" * filled_units + "░" * (10 - filled_units)
            diff = next_lvl_exp - exp

            text = (
                f"👤 <b>Герой:</b> {message.from_user.first_name}\n"
                f"🎖 <b>Титул:</b> <i>{title}</i>\n"
                f"📊 <b>Уровень:</b> <code>{lvl}</code>\n"
                f"✨ <b>Опыт:</b> <code>{exp} EXP</code>\n"
                f"📈 <b>До Level Up:</b> <code>{max(0, diff)} EXP</code>\n\n"
                f"💪 <code>{progress_bar}</code>\n\n"
            )

            today = datetime.now()
            daily_changes = await get_month_activity(message.from_user.id, today.year, today.month)
            calendar_view = build_activity_calendar(daily_changes, today.year, today.month)

            text += f"📅 <b>АКТИВНОСТЬ {today.strftime('%B %Y').capitalize()}</b>\n"
            text += f"<code>{calendar_view}</code>"

            await message.reply(text)

@router.message(Command("top"))
async def show_top(message: types.Message):
    async with aiosqlite.connect(DB_NAME) as db:
        # Получаем активных игроков (не в отпуске)
        today = datetime.now().date().isoformat()
        
        # Топ за МЕСЯЦ (для премий)
        query_monthly = '''
            SELECT u.name, u.monthly_exp FROM users u
            LEFT JOIN vacations v ON u.user_id = v.user_id AND ? BETWEEN v.start_date AND v.end_date
            WHERE v.user_id IS NULL
            ORDER BY u.monthly_exp DESC LIMIT 10
        '''
        
        # Топ за ВСЁ ВРЕМЯ (для статуса)
        query_all_time = 'SELECT name, exp FROM users ORDER BY exp DESC LIMIT 5'

        async with db.execute(query_monthly, (today,)) as c:
            monthly_top = await c.fetchall()
        async with db.execute(query_all_time) as c:
            all_time_top = await c.fetchall()

    if not monthly_top:
        return await message.answer("📭 В гильдии пока нет активных героев.")

    text = "🏆 <b>ТУРНИР МЕСЯЦА</b> (на кону премия)\n"
    for i, (name, m_exp) in enumerate(monthly_top):
        medal = ["🥇", "🥈", "🥉"][i] if i < 3 else f"{i+1}."
        text += f"{medal} {name} — <code>{m_exp} EXP</code>\n"

    text += "\n📜 <b>ЛЕГЕНДЫ ГИЛЬДИИ</b> (весь опыт)\n"
    for i, (name, exp) in enumerate(all_time_top):
        text += f"• {name}: {exp} EXP\n"

    await message.answer(text)

@router.message(Command("quests"))
async def list_active_quests(message: types.Message):
    """Выводит список активных квестов (доступные и в работе)"""
    async with aiosqlite.connect(DB_NAME) as db:
        # Получаем доступные квесты (open)
        async with db.execute('''
            SELECT bot_msg_id, chat_id, description 
            FROM tasks 
            WHERE status = 'open'
            ORDER BY task_id DESC
        ''') as cursor:
            open_quests = await cursor.fetchall()
        
        # Получаем квесты в работе с именами исполнителей
        async with db.execute('''
            SELECT t.bot_msg_id, t.chat_id, t.description, u.name, u.user_id
            FROM tasks t
            LEFT JOIN users u ON t.worker_id = u.user_id
            WHERE t.status = 'in_progress'
            ORDER BY t.start_time DESC
        ''') as cursor:
            in_progress_quests = await cursor.fetchall()
    
    if not open_quests and not in_progress_quests:
        await message.answer("📭 В данный момент нет активных квестов.")
        return
    
    text = "📋 <b>АКТИВНЫЕ КВЕСТЫ</b>\n\n"
    
    # Доступные квесты
    if open_quests:
        text += "🟢 <b>ДОСТУПНЫЕ КВЕСТЫ (open)</b>\n"
        for bot_msg_id, chat_id, description in open_quests:
            chat_link = f"https://t.me/c/{abs(int(str(chat_id)[2:]))}/52/{bot_msg_id}"
            short_desc = description[:100] + "..." if len(description) > 40 else description
            text += f"• <a href='{chat_link}'>{short_desc}</a>\n"
        text += "\n"
    
    # Квесты в работе
    if in_progress_quests:
        text += "🟡 <b>КВЕСТЫ В РАБОТЕ (in_progress)</b>\n"
        for bot_msg_id, chat_id, description, worker_name, worker_id in in_progress_quests:
            chat_link = f"https://t.me/c/{abs(int(str(chat_id)[2:]))}/52/{bot_msg_id}"
            short_desc = description[:100] + "..." if len(description) > 40 else description
            worker_display = worker_name or f"ID:{worker_id}"
            text += f"• <a href='{chat_link}'>{short_desc}</a> — <i>исп. {worker_display}</i>\n"
    
    await message.answer(text, disable_web_page_preview=True)

@router.message(Command("help"))
async def cmd_help(message: types.Message):
    help_text = (
        "⚔️ <b>ГИЛЬДИЯ АДМИНОВ: СПРАВОЧНИК ГЕРОЯ</b> 📜\n\n"

        "<b>📊 ОСНОВНЫЕ КОМАНДЫ:</b>\n"
        "👤 /profile — Посмотреть свой уровень, опыт и прогресс до next level-up\n"
        "🏆 /top — Доска почета (топ месяца и легенды гильдии)\n"
        "📋 /quests — Все активные квесты (открытые и в работе)\n"
        "🆘 /help — Вызвать это справочное меню\n\n"

        "<b>⚔️ РАБОТА С КВЕСТАМИ:</b>\n"
        "📝 <code>НоваяЗадача</code> или <code>НовыйКвест</code>\n"
        "   → Создает обычный квест, награда <b>+5 EXP</b>\n"
        "🚨 <code>инцидент</code> [проблема]\n"
        "   → Срочный инцидент, время: <b>1 час</b>, награда <b>+15 EXP</b>\n"
        "⚔️ <b>Кнопка «Взять квест»</b> — Забронировать квест на <b>4 часа</b>\n"
        "✅ <b>Reply на квест: Готово [отчет]</b> — Сдать выполненный квест\n"
        "   → Короткий отчет: +1 EXP | Развернутый отчет: +5 EXP\n\n"

        "<b>📋 СИСТЕМА КВЕСТОВ:</b>\n"
        "🟢 <b>OPEN</b> — Свободный квест, ждет исполнителя\n"
        "🟡 <b>IN PROGRESS</b> — Квест в работе с таймаутом 4ч\n"
        "✅ <b>COMPLETED</b> — Выполненный квест\n"
        "🔴 <b>EXPIRED</b> — Просрочено (штраф -2 EXP)\n\n"

        "<b>📅 ДОПОЛНИТЕЛЬНЫЕ КОМАНДЫ:</b>\n"
        "📝 <code>План на завтра</code> — Отправить план на день\n"
        "   → Можно отправить 12:00–18:00 по будням\n"
        "   → Отказ: <b>-1 EXP</b> (проверка в 18:00 пн–чт)\n"
        "⚠️ <code>брак</code>, <code>доделать</code>, <code>переделать</code> — Отклонить выполненный квест\n"
        "   → Исполнитель получает штраф <b>-5 EXP</b>, квест возвращается\n\n"

        "<b>⚖️ СИСТЕМА УРОВНЕЙ И СТАТУСОВ:</b>\n"
        "📈 Каждый новый уровень требует больше опыта\n"
        "🎖 Титул зависит от уровня (смотри /profile)\n"
        "🏅 Топ месяца = премии для лучших героев\n\n"

        "<b>⚠️ ПРАВИЛА И ШТРАФЫ:</b>\n"
        "📉 Просроченный квест (не сдал за 4ч): <b>-2 EXP</b>\n"
        "📉 Отказ планировать (пропуск плана): <b>-1 EXP</b> (18:00 пн–чт)\n"
        "🕸 АФК штраф (3+ дня без квестов): <b>-2 EXP</b>\n"
        "🔥 Отклоненный квест (брак): <b>-5 EXP</b>\n\n"

        "<b>🎁 СИСТЕМА ВОЗНАГРАЖДЕНИЙ:</b>\n"
        "⭐ Развернутый отчет (+5 EXP > +1 EXP)\n"
        "🚨 Критические инциденты: <b>+15 EXP</b>\n"
        "🌙 Ежемесячный конкурс: <b>премии</b> за топ 1\n\n"

        "<b>💡 СОВЕТЫ:</b>\n"
        "• Пиши развернутые отчеты для максимальной награды\n"
        "• Планируй дни для избежания штрафов\n"
        "• Не тянешь с квестами — 4 часа на выполнение\n"
        "• Следи за уровнем — чем выше, тем круче титул!\n\n"

        "<b>🆘 ПОМОЩЬ:</b>\n"
        "Если что-то не работает, напиши /help еще раз или спроси тимлида."
    )
    await message.answer(help_text)