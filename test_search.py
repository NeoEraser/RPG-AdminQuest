#!/usr/bin/env python3
"""Тестовый скрипт — НЕ трогает файлы проекта."""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import asyncio

# Убедимся, что корень проекта в path


async def main():
    from database.db import init_db
    from database.wiki import init_wiki_table
    from services.wiki import search_wiki

    await init_db()
    await init_wiki_table()

    from services import wiki_embeddings as wemb
    await wemb.init_model()

    descriptions = [
        "настройка почты",
    ]

    for desc in descriptions:
        print(f"\n{'='*60}")
        print(f"Поиск по: {desc}")
        print(f"{'='*60}")
        results = await search_wiki(desc, limit=3)
        if results:
            lines = [f"💡 <b>Похожие решения по задаче:</b>\n"]
            kb_suggestions = InlineKeyboardMarkup(inline_keyboard=[])
            for i, (aid, title, content, category, tags, author, likes, created) in enumerate(results, 1):
                short = content[:120].replace('\n', ' ')
                lines.append(f"#{i} 📚 <b>{title}</b> <i>({category})</i>\n   {short}...")
                kb_suggestions.inline_keyboard.append([
                    InlineKeyboardButton(text=f"Открыть #{i}", callback_data=f"wiki_open_{aid}"),
                    InlineKeyboardButton(text=f"Чек-лист #{i}", callback_data=f"wiki_check_{aid}")
                ])
            text = "\n".join(lines)
            try:
                #await bot.send_message(user_id, text, parse_mode="HTML", reply_markup=kb_suggestions)
                print(text)
            except Exception:
                # если не удалось отправить в ЛС — уведомим исполнителя в чате (без содержимого)
                print("Не удалось отправить ЛС. Откройте диалог с ботом, чтобы получать подсказки.")
                #await callback.answer("Не удалось отправить ЛС. Откройте диалог с ботом, чтобы получать подсказки.", show_alert=True)

asyncio.run(main())