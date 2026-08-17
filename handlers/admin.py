from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import aiosqlite
from datetime import datetime
from config import TEAMLEAD_ID, DB_NAME
from database.db import update_exp

router = Router()


# ─────────────── admin commands ───────────────

@router.message(Command("smite"), F.from_user.id == TEAMLEAD_ID)
async def divine_smite(message: types.Message):
    try:
        parts = message.text.split(maxsplit=3)
        target_id, penalty = int(parts[1]), int(parts[2])
        reason = parts[3] if len(parts) > 3 else "Неисповедимы пути Тимлида."
        await update_exp(target_id, -penalty, reason="smite")
        await message.answer(f"⚡️ <b>ГНЕВ ТИМЛИДА</b> ⚡️\nГерой <code>{target_id}</code> оштрафован: <b>-{penalty} EXP</b>\n<b>Причина:</b> <i>{reason}</i>")
    except:
        await message.answer("Формат: /smite ID 20 Уронил прод")


@router.message(Command("vacation"), F.from_user.id == TEAMLEAD_ID)
async def set_vacation(message: types.Message):
    try:
        _, target_id, start_str, end_str = message.text.split()
        datetime.strptime(start_str, "%Y-%m-%d")
        datetime.strptime(end_str, "%Y-%m-%d")
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                'INSERT INTO vacations (user_id, start_date, end_date) VALUES (?, ?, ?)',
                (int(target_id), start_str, end_str)
            )
            await db.commit()
        await message.answer(f"🌴 <b>Отпуск активирован!</b>\nГерой <code>{target_id}</code> отдыхает. Штрафы отключены.")
    except:
        await message.answer("Формат: /vacation ID YYYY-MM-DD YYYY-MM-DD")


@router.message(Command("dashboard"))
async def cmd_dashboard(message: types.Message):
    """Live Status — кто чем занят прямо сейчас."""
    if not TEAMLEAD_ID:
        return await message.answer("⚠️ Dashboard не настроен (GROUP_ID не указан).")

    from services.weekly_report import get_live_status

    async with aiosqlite.connect(DB_NAME) as db:
        status_text = await get_live_status(db)

    # Если пользователей много, показываем кнопку "Подробный отчёт"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Недельный отчёт", callback_data="weekly_report")]
    ])
    await message.answer(status_text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data == "weekly_report")
async def callback_weekly_report(callback: types.CallbackQuery):
    """Ручная генерация еженедельного отчёта по кнопке."""
    from services.weekly_report import generate_weekly_report
    await callback.answer("⏳ Генерирую отчёт...", show_alert=False)
    try:
        report = await generate_weekly_report(
            bot=callback.bot,
            chat_id=callback.message.chat.id
        )
    except Exception as e:
        await callback.answer(f"❌ Ошибка: {e}", show_alert=True)
        logger = __import__('logging').getLogger(__name__)
        logger.error(f"Ошибка генерации отчёта: {e}", exc_info=True)


@router.message(Command("reindex_now"), F.from_user.id == TEAMLEAD_ID)
async def cmd_reindex_now(message: types.Message):
    """Ручной запуск переиндексации Wiki — доступен только тимлиду."""
    try:
        # Предпочитаем запуск внешнего reindex в отдельном venv
        from services import external_reindex
    except Exception:
        await message.answer("❌ Модуль external_reindex недоступен на сервере. Переиндексация невозможна.")
        return

    await message.answer("⏳ Запускаю внешнюю переиндексацию Wiki (в отдельном venv). Это может занять время. Уведомлю, когда закончу.")
    try:
        res = await external_reindex.run_reindex_external(bot=message.bot, notify_chat_id=message.from_user.id)
        rc = res.get('rc', -1)
        if rc == 0:
            await message.answer("✅ Внешняя переиндексация запущена и завершилась успешно (см уведомление).")
        else:
            await message.answer(f"❌ Внешняя переиндексация завершилась с кодом {rc}. См логи для деталей.")
    except Exception as e:
        await message.answer(f"❌ Ошибка при запуске внешней переиндексации: {e}")
        logger = __import__('logging').getLogger(__name__)
        logger.exception(f"Ошибка ручной внешней переиндексации: {e}")
