# RPG AdminQuest

Telegram бот с системой RPG квестов и управлением админом.

## Функционал

- 🎮 RPG система с квестами
- 👨‍💼 Панель администратора
- 📋 Управление квестами
- 🎯 Система инцидентов
- ⏰ Планировщик событий
- 🌐 API интеграции

## Требования

- Python 3.8+
- pip

## Установка

1. Клонируйте репозиторий:
```bash
git clone https://github.com/NeoEraser/RPG-AdminQuest.git
cd RPG-AdminQuest
```

2. Установите зависимости:
```bash
pip install -r requirements.txt
```

3. Создайте файл `.env` с переменными окружения:
```
BOT_TOKEN=your_telegram_token
TEAMLEAD_ID = Telegram ID Тимлида
DB_NAME = путь до базы данных
PROXY_URL = если используется прокси для телеграмма
GROUP_ID = группа в которой работает бот
```

4. Запустите бот:
```bash
python main.py
```

## Структура проекта

```
├── main.py                 # Точка входа приложения
├── config.py              # Конфигурация и константы
├── handlers/              # Обработчики команд
│   ├── basic.py           # Базовые команды
│   ├── admin.py           # Админ команды
│   ├── quests.py          # Системы квестов
│   ├── quest_manager.py   # Управление квестами
│   └── incidents.py       # Управление инцидентами
├── services/              # Бизнес-логика
│   ├── rpg.py             # RPG система
│   ├── api.py             # API интеграции
│   └── scheduler.py       # Планировщик событий
├── database/              # Работа с БД
│   └── db.py              # ORM модели
└── gamebot_rpg.db        # SQLite база данных
```

## Использование

### Запуск бота
```bash
python main.py
```

## Переменные окружения

Создайте файл `.env` в корне проекта:

```env
BOT_TOKEN=your_telegram_token
TEAMLEAD_ID = Telegram ID Тимлида
DB_NAME = путь до базы данных
PROXY_URL = если используется прокси для телеграмма
GROUP_ID = группа в которой работает бот
```

## Лицензия

MIT

## Автор

NeoEraser
