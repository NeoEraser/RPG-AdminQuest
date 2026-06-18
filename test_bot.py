# test_bot.py - исправленный тест

import asyncio
import logging
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import TOKEN
from services.custom_session import DynamicProxySession
from proxy_manager import ProxyManager

# Ваш ID пользователя (из лога - 339286744)
YOUR_USER_ID = 339286744

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def test_bot():
    """Полный тестовый запуск бота"""
    print("\n" + "="*50)
    print("ТЕСТ БОТА")
    print("="*50)
    
    # Инициализация
    proxy_manager = ProxyManager(TOKEN)
    await proxy_manager.initialize()
    
    session = DynamicProxySession(proxy_manager=proxy_manager)
    bot = Bot(token=TOKEN, session=session)
    
    try:
        # Тест 1: getMe
        print("\n=== Тест 1: getMe ===")
        me = await bot.get_me()
        print(f"✅ Бот: @{me.username} (ID: {me.id})")
        
        # Тест 2: getUpdates
        print("\n=== Тест 2: getUpdates ===")
        updates = await bot.get_updates(limit=1, timeout=5)
        print(f"✅ Получено обновлений: {len(updates)}")
        if updates:
            print(f"  Первое обновление: {updates[0]}")
        
        # Тест 3: Отправка сообщения пользователю (не боту!)
        print("\n=== Тест 3: отправка сообщения пользователю ===")
        try:
            # Отправляем сообщение пользователю с YOUR_USER_ID
            msg = await bot.send_message(
                chat_id=YOUR_USER_ID,  # Ваш ID, не ID бота!
                text="✅ Тестовое сообщение от бота"
            )
            print(f"✅ Сообщение отправлено пользователю {YOUR_USER_ID}")
            print(f"   ID сообщения: {msg.message_id}")
        except Exception as e:
            print(f"❌ Ошибка отправки: {e}")
        
        # Тест 4: Отправка сообщения в группу (если GROUP_ID задан)
        print("\n=== Тест 4: отправка сообщения в группу ===")
        from config import GROUP_ID
        if GROUP_ID:
            try:
                msg = await bot.send_message(
                    chat_id=GROUP_ID,
                    text="✅ Тестовое сообщение в группу от бота"
                )
                print(f"✅ Сообщение отправлено в группу {GROUP_ID}")
                print(f"   ID сообщения: {msg.message_id}")
            except Exception as e:
                print(f"❌ Ошибка отправки в группу: {e}")
        else:
            print("ℹ️ GROUP_ID не задан, пропускаем")
        
        print("\n" + "="*50)
        print("✅ ВСЕ ТЕСТЫ ПРОЙДЕНЫ!")
        print("="*50)
        return True
        
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        await session.close()

if __name__ == "__main__":
    asyncio.run(test_bot())