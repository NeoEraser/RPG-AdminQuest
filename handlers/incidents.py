from aiogram import Router, F, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import aiosqlite
from config import DB_NAME
from database.db import update_exp, save_quest_message
from datetime import datetime

router = Router()

def clean_incident_description(text: str) -> str:
    """Очищает описание инцидента от ключевых слов"""
    text = text.strip()
    text = text.replace("инцидент", "").replace("Инцидент", "")
    text = text.strip()
    return text

@router.message(F.text.lower().contains("инцидент"))
async def create_incident(message: types.Message):
    task_text = clean_incident_description(message.text)
    reward = 15
    time_hours = 1
    if not task_text: 
        return
    try: 
        await message.delete()
    except: 
        pass

    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔥 Спасти мир", callback_data="take_quest")]])
    sent_msg = await message.answer(
        f"🚨 <b>КРИТИЧЕСКИЙ ИНЦИДЕНТ</b> 🚨\n<b>Проблема:</b> {task_text}\n\n<b>Награда: +{reward} EXP</b>\n<b>Время: {time_hours} час</b>", reply_markup=kb
    )
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            'INSERT INTO tasks (chat_id, bot_msg_id, description, reward, time) VALUES (?, ?, ?, ?, ?)',
            (sent_msg.chat.id, sent_msg.message_id, task_text, reward, time_hours)
        ) as cursor:
            task_id = cursor.lastrowid  # Теперь cursor определен
        await db.commit()

        # Сохраняем сообщение о создании инцидента
        await save_quest_message(
            task_id=task_id,
            user_id=message.from_user.id,
            user_name=message.from_user.first_name,
            message_text=f"Создал(а) критический инцидент: {task_text}",
            is_reply_to_quest=True
        )
        
    # Закрепляем сообщение с квестом (тихое закрепление)
    try:
        await message.chat.pin_message(
            message_id=sent_msg.message_id,
            disable_notification=True  # Закрепление без уведомления
        )
    except Exception as e:
        print(f"Не удалось закрепить сообщение: {e}")

@router.message(F.reply_to_message, F.text.lower().in_({"брак", "доделать", "переделать"}))
async def reject_task(message: types.Message):
    reply_msg = message.reply_to_message
    
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT worker_id, status, description, reward, time FROM tasks WHERE bot_msg_id = ?', (reply_msg.message_id,)) as cursor:
            task = await cursor.fetchone()
            if not task or task[1] != "completed": 
                return await message.reply("❌ Эту задачу нельзя отклонить. Она либо не завершена, либо не найдена.")
            
            worker_id, status, description, reward, time = task
            
            # Штрафуем исполнителя
            await update_exp(worker_id, -5, reason="rejected")
            
            # Возвращаем задачу в работу тому же исполнителю
            await db.execute(
                'UPDATE tasks SET status = "in_progress", start_time = ? WHERE bot_msg_id = ?',
                (datetime.now(), reply_msg.message_id)
            )
            await db.commit()
    
    # Обновляем сообщение с задачей
    await reply_msg.edit_text(f"{reply_msg.text}\n\n<b>⚠️ <b>Отклонено проверяющим!</b> Необходимо исправить.</b>", reply_markup=None)

    # Закрепляем сообщение с квестом (тихое закрепление)
    try:
        await message.chat.pin_message(
            message_id=reply_msg.message_id,
            disable_notification=True  # Закрепление без уведомления
        )
    except Exception as e:
        print(f"Не удалось закрепить сообщение: {e}")

    await message.answer(
        f"❌ <b>ЗАДАЧА ОТКЛОНЕНА</b>\n\n"
        f"Исполнитель получает штраф <b>-5 EXP</b>.\n"
        f"Задача возвращена на доработку. Исправляй и сдавай заново."
    )