import os
from dotenv import load_dotenv

# Загружаем переменные из .env
load_dotenv()

# Читаем переменные
TOKEN = str(os.getenv("BOT_TOKEN"))
TEAMLEAD_ID = int(os.getenv("TEAMLEAD_ID", 0)) # Преобразуем в int для проверок
DB_NAME = str(os.getenv("DB_NAME"))
PROXY_URL = os.getenv("PROXY_URL")
GROUP_ID = int(os.getenv("GROUP_ID", 0)) # Тот самый ID чата для квестов