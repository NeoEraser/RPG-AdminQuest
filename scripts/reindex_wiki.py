import asyncio
import logging
import sys
import pathlib

# Добавляем корень проекта в sys.path чтобы imports работали при запуске скрипта напрямую
project_root = pathlib.Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

logging.basicConfig(level=logging.INFO)

async def main():
    # Убедимся, что в базе есть нужные колонки (миграция)
    try:
        from database import wiki as db_wiki
        await db_wiki.init_wiki_table()
    except Exception:
        logging.exception('Не удалось выполнить миграцию таблицы wiki')

    from services import wiki_embeddings
    
    # Инициализируем модель перед началом индексации
    logging.info('Инициализация модели эмбеддингов...')
    await wiki_embeddings.init_model()
    
    logging.info('Начинаем переиндексацию подтвержденных статей Wiki...')
    result = await wiki_embeddings.reindex_all()
    logging.info(f'Переиндексация завершена: {result}')

    # Проверим, что было проиндексировано
    if result["updated"] == 0 and result["total"] > 0:
        logging.warning("Не удалось проиндексировать ни одной статьи! Проверьте логи выше.")

if __name__ == '__main__':
    asyncio.run(main())
