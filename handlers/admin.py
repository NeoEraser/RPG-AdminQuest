from aiogram import Router, F, types
from aiogram.filters import Command
import aiosqlite
from datetime import datetime
from config import TEAMLEAD_ID, DB_NAME
from database.db import update_exp

router = Router()

@router.message(Command("smite"), F.from_user.id == TEAMLEAD_ID)
async def divine_smite(message: types.Message):
    try:
        parts = message.text.split(maxsplit=3)
        target_id, penalty = int(parts[1]), int(parts[2])
        reason = parts[3] if len(parts) > 3 else "Неисповедимы пути Тимлида."
        new_exp = await update_exp(target_id, -penalty, reason="smite")
        await message.answer(f"⚡️ <b>ГНЕВ ТИМЛИДА</b> ⚡️\nГерой <code>{target_id}</code> оштрафован: <b>-{penalty} EXP</b>\n<b>Причина:</b> <i>{reason}</i>")
    except: 
        await message.answer("Формат: /smite ID 20 Уронил прод")

@router.message(Command("vacation"), F.from_user.id == TEAMLEAD_ID)
async def set_vacation(message: types.Message):
    try:
        _, target_id, start_str, end_str = message.text.split()
        datetime.strptime(start_str, "%Y-%m-%d") # Валидация
        datetime.strptime(end_str, "%Y-%m-%d")
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute('INSERT INTO vacations (user_id, start_date, end_date) VALUES (?, ?, ?)', (int(target_id), start_str, end_str))
            await db.commit()
        await message.answer(f"🌴 <b>Отпуск активирован!</b>\nГерой <code>{target_id}</code> отдыхает. Штрафы отключены.")
    except: 
        await message.answer("Формат: /vacation ID 2024-06-01 2024-06-14")