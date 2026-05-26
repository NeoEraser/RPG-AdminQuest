import aiosqlite
import logging
from datetime import datetime, timedelta, date
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from config import DB_NAME, GROUP_ID
from database.db import update_exp
from database.db import remove_timeout, get_all_timeouts, cleanup_expired_timeouts

scheduler = AsyncIOScheduler(timezone="Asia/Yekaterinburg")

async def monthly_results_check(bot: Bot, group_id: int):
    """Подведение итогов месяца, объявление премий и сброс"""
    today = datetime.now().date().isoformat()
    
    async with aiosqlite.connect(DB_NAME) as db:
        # Берем только активных (не в отпуске)
        query = '''
            SELECT u.user_id, u.name, u.monthly_exp FROM users u
            LEFT JOIN vacations v ON u.user_id = v.user_id AND ? BETWEEN v.start_date AND v.end_date
            WHERE v.user_id IS NULL
            ORDER BY u.monthly_exp DESC
        '''
        async with db.execute(query, (today,)) as cursor:
            active_users = await cursor.fetchall()

        if not active_users or len(active_users) < 2:
            return # Недостаточно людей для турнира

        # Находим максимальное и минимальное значение monthly_exp
        max_exp = active_users[0][2]
        min_exp = active_users[-1][2]
        
        # Собираем всех лидеров (с максимальным exp)
        top_winners = [user for user in active_users if user[2] == max_exp]
        
        # Собираем всех замыкающих (с минимальным exp)
        bottom_losers = [user for user in active_users if user[2] == min_exp]
        
        diff = max_exp - min_exp

        text = "🏁 <b>ИТОГИ ТУРНИРА МЕСЯЦА</b> 🏁\n\n"
        
        # Составляем список топа для сообщения
        for i, (u_id, name, m_exp) in enumerate(active_users[:10]):
            medal = ["🥇", "🥈", "🥉"][i] if i < 3 else f"{i+1}."
            text += f"{medal} {name} — <code>{m_exp} EXP</code>\n"

        text += f"\n📊 Разрыв между лидером и замыкающим: <b>{diff} EXP</b>\n"

        if diff >= 20:
            text += "\n💰 <b>Вердикт:</b> Победитель определен!\n"
            
            # Обрабатываем победителей
            if len(top_winners) == 1:
                text += f"🏆 {top_winners[0][1]} получает дополнительную премию!\n"
            else:
                winners_names = ", ".join([winner[1] for winner in top_winners])
                text += f"🏆 Победители: {winners_names}\n"
                text += "Каждый получает дополнительную премию!\n"
            
            # Обрабатываем проигравших
            if len(bottom_losers) == 1:
                text += f"🧨 {bottom_losers[0][1]} оплачивает банкет (списание из ЗП)."
            else:
                losers_names = ", ".join([loser[1] for loser in bottom_losers])
                text += f"🧨 Замыкающие: {losers_names}\n"
                text += "Каждый скидывается на банкет (списание из ЗП)."
        else:
            text += "\n🤝 <b>Вердикт:</b> Плотный строй! Разрыв менее 20 EXP. Все молодцы, премия остается у всех при себе."

        await bot.send_message(group_id, text)
        
        # Сбрасываем месячный опыт у ВСЕХ
        await db.execute('UPDATE users SET monthly_exp = 0')
        await db.commit()
        
async def reset_monthly_exp(bot: Bot):
    """Сброс месячного рейтинга и подведение итогов"""
    async with aiosqlite.connect(DB_NAME) as db:
        # Здесь можно вставить логику проверки разрыва в 20 EXP перед обнулением!
        # ... логика подведения итогов ...
        
        await db.execute('UPDATE users SET monthly_exp = 0')
        await db.commit()
    
    # Можно отправить уведомление в чат
    await bot.send_message(GROUP_ID, "📅 Новый месяц начался! Месячный опыт обнулен, гонка за премию стартует заново!")
    
async def quest_timeout_check(bot: Bot, task_id: int, bot_msg_id: int, user_id: int):
    """Проверка таймаута квеста"""
    async with aiosqlite.connect(DB_NAME) as db:
        # Удаляем таймаут из БД
        await remove_timeout(bot_msg_id)
        
        # Проверяем статус задачи
        async with db.execute('SELECT status, description, chat_id, reward, time FROM tasks WHERE task_id = ?', (task_id,)) as cursor:
            row = await cursor.fetchone()
            if row and row[0] == 'in_progress':
                status, description, chat_id, reward, time = row
                
                # Штрафуем пользователя
                await update_exp(user_id, -2, reason="timeout")
                
                # Возвращаем задачу в открытый статус
                await db.execute(
                    'UPDATE tasks SET status = "open", worker_id = NULL, start_time = NULL WHERE task_id = ?', 
                    (task_id,)
                )
                await db.commit()
                
                # Уведомляем пользователя
                try:
                    await bot.send_message(
                        user_id, 
                        "💀 <b>Время вышло!</b> Квест провален. Штраф: -2 EXP.\nЗадача снова доступна."
                    )
                except:
                    pass

                # Обновляем сообщение в чате
                if reward == 5: # Обычный квест
                    kb = InlineKeyboardMarkup(
                        inline_keyboard=[[InlineKeyboardButton(text="⚔️ Взять квест", callback_data=f"take_quest")]]
                    )
                    try:
                        await bot.edit_message_text(
                            chat_id=chat_id, 
                            message_id=bot_msg_id,
                            text=f"📜 <b>НОВЫЙ КВЕСТ (ПОВТОРНО)</b>\n\n<b>Суть:</b> {description}\n\n⚠️ <i>Исполнитель не справился.</i>\n<b>Награда:</b> +{reward} EXP\n<b>Время:</b> {time} часа",
                            reply_markup=kb
                        )
                    except Exception as e: 
                        logging.error(f"Ошибка при обновлении сообщения: {e}")
                
                elif reward == 15: # Инцидент
                    kb = InlineKeyboardMarkup(
                        inline_keyboard=[[InlineKeyboardButton(text="🔥 Спасти мир", callback_data=f"take_quest")]]
                    )
                    try:
                        await bot.edit_message_text(
                            chat_id=chat_id, 
                            message_id=bot_msg_id,
                            text=f"🚨 <b>КРИТИЧЕСКИЙ ИНЦИДЕНТ (ПОВТОРНО)</b> 🚨\n\n<b>Суть:</b> {description}\n\n⚠️ <i>Исполнитель не справился.</i>\n<b>Награда:</b> +{reward} EXP\n<b>Время:</b> {time} час",
                            reply_markup=kb
                        )
                    except Exception as e: 
                        logging.error(f"Ошибка при обновлении сообщения: {e}")

async def restore_timeouts(bot: Bot):
    """Восстанавливает все таймауты после перезапуска"""
    logging.info("🔄 Восстановление таймаутов после перезапуска...")
    
    # Очищаем просроченные
    await cleanup_expired_timeouts()
    
    # Получаем активные таймауты
    timeouts = await get_all_timeouts()
    
    if not timeouts:
        logging.info("✅ Активных таймаутов не найдено")
        return
    
    restored_count = 0
    for task_id, bot_msg_id, worker_id, timeout_time_str, chat_id, description in timeouts:
        try:
            timeout_time = datetime.fromisoformat(timeout_time_str.replace(' ', '+'))
            now = datetime.now(timeout_time.tzinfo)
            
            # Вычисляем оставшееся время
            if timeout_time > now:
                remaining = (timeout_time - now).total_seconds()
                
                # Добавляем задачу с оставшимся временем
                scheduler.add_job(
                    quest_timeout_check, 
                    'date', 
                    run_date=timeout_time,
                    args=[bot, task_id, bot_msg_id, worker_id],
                    id=f"quest_timeout_{bot_msg_id}",
                    replace_existing=True
                )
                restored_count += 1
                logging.info(f"🔄 Восстановлен таймаут для квеста {bot_msg_id}, осталось {remaining/60:.1f} мин")
            else:
                # Если время уже прошло, выполняем проверку немедленно
                await quest_timeout_check(bot, task_id, bot_msg_id, worker_id)
                logging.info(f"⚡ Немедленное выполнение просроченного квеста {bot_msg_id}")
                
        except Exception as e:
            logging.error(f"❌ Ошибка восстановления таймаута для квеста {bot_msg_id}: {e}")
    
    logging.info(f"✅ Восстановлено {restored_count} активных таймаутов")

async def daily_plan_check(bot: Bot):
    today = datetime.now().date().isoformat()
    async with aiosqlite.connect(DB_NAME) as db:
        query = '''
            SELECT u.user_id FROM users u
            LEFT JOIN vacations v ON u.user_id = v.user_id AND ? BETWEEN v.start_date AND v.end_date
            WHERE u.plan_submitted = 0 AND v.user_id IS NULL
        '''
        async with db.execute(query, (today,)) as cursor:
            users = await cursor.fetchall()
            for (u_id,) in users:
                await update_exp(u_id, -1, reason="no_plan")
                try: 
                    await bot.send_message(u_id, "📉 Штраф -1 EXP: Нет плана на завтра до 18:00.")
                except: 
                    pass
        await db.execute('UPDATE users SET plan_submitted = 0')
        await db.commit()

def count_weekdays_since(last_date: date, today_date: date) -> int:
    """Количество рабочих дней (пн-пт) от last_date до today_date (не включая last_date)"""
    if last_date >= today_date:
        return 0
    days = 0
    current = last_date + timedelta(days=1)
    while current <= today_date:
        if current.weekday() < 5:  # 0=пн, 4=пт, 5=сб, 6=вс
            days += 1
        current += timedelta(days=1)
    return days

async def skill_decay_check(bot: Bot):
    """Деградация навыков за АФК (2 дня)"""
    today = datetime.now().date()
    async with aiosqlite.connect(DB_NAME) as db:
        query = '''
            SELECT u.user_id FROM users u
            LEFT JOIN vacations v ON u.user_id = v.user_id AND ? BETWEEN v.start_date AND v.end_date
            WHERE u.last_active <= ? AND v.user_id IS NULL AND u.exp > 0
        '''
        async with db.execute(query, (today.isoformat(),)) as cursor:
            users = await cursor.fetchall()
        
        for u_id, last_active_str in users:
            last_active = datetime.fromisoformat(last_active_str).date()
            # Считаем только рабочие дни
            weekday_diff = count_weekdays_since(last_active, today)
            
            if weekday_diff >= 2:  # 2 и более рабочих дня без активности
                await update_exp(u_id, -2, reason="afk")
                try:
                    await bot.send_message(u_id, "🕸 <b>Скиллы ржавеют!</b>\nТы не брал квесты больше 2 рабочих дней. Штраф за АФК: <b>-2 EXP</b>.")
                except:
                    pass