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
        await update_exp(target_id, -penalty, reason="smite")
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


@router.message(Command("add_proxy"))
async def add_proxy_command(message: types.Message):
    """Добавляет новый прокси в базу"""
    if not is_admin(message.from_user.id):
        return
    
    if not command.args:
        await message.reply("❌ Укажите прокси: /add_proxy http://user:pass@ip:port")
        return
    
    proxy_url = command.args.strip()
    await proxy_manager.add_proxy_manual(proxy_url)
    await message.reply(f"✅ Прокси добавлен: {proxy_url}")

@router.message(Command("proxies"))
async def list_proxies_command(message: types.Message):
    """Показывает список прокси"""
    if not is_admin(message.from_user.id):
        return
    
    proxies = await db.get_all_proxies()
    if not proxies:
        await message.reply("ℹ️ Нет прокси в базе")
        return
    
    text = "📋 **Список прокси:**\n\n"
    for proxy_id, proxy_url, rating, is_working, last_check, success_count, fail_count in proxies[:20]:
        status = "✅" if is_working else "❌"
        text += f"{status} `{proxy_url}`\n"
        text += f"   Рейтинг: {rating} | Успешно: {success_count} | Ошибок: {fail_count}\n"
        if last_check:
            text += f"   Последняя проверка: {last_check}\n"
        text += "\n"
    
    await message.reply(text, parse_mode="Markdown")

@router.message(Command("proxy_stats"))
async def proxy_stats_command(message: types.Message):
    """Показывает статистику прокси"""
    if not is_admin(message.from_user.id):
        return
    
    stats = await proxy_manager.get_stats()
    text = f"""
📊 **Статистика прокси:**

• Всего: {stats['total']}
• Рабочих: {stats['working']}
• Средний рейтинг: {stats['avg_rating']:.1f}
• Максимальный рейтинг: {stats['max_rating']}
"""
    await message.reply(text, parse_mode="Markdown")

@router.message(Command("refresh_proxies"))
async def refresh_proxies_command(message: types.Message):
    """Принудительно проверяет все прокси"""
    if not is_admin(message.from_user.id):
        return
    
    await message.reply("🔄 Начинаю проверку всех прокси...")
    
    proxies = await db.get_all_proxies()
    checked = 0
    working = 0
    
    for proxy_id, proxy_url, rating, is_working, last_check, success_count, fail_count in proxies:
        result = await proxy_manager._check_proxy(proxy_url)
        await db.update_proxy_rating(proxy_url, result)
        checked += 1
        if result:
            working += 1
        await asyncio.sleep(0.1)  # Небольшая задержка
    
    await message.reply(f"✅ Проверено {checked} прокси, рабочих: {working}")