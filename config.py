import os
from dotenv import load_dotenv

# Загружаем переменные из .env
load_dotenv()

# Читаем переменные
TOKEN = str(os.getenv("BOT_TOKEN"))
TEAMLEAD_ID = int(os.getenv("TEAMLEAD_ID", 0)) # Преобразуем в int для проверок
DB_NAME = str(os.getenv("DB_NAME"))
GROUP_ID = int(os.getenv("GROUP_ID", 0)) # Тот самый ID чата для квестов

# Читаем список прокси из переменной окружения
# Формат: PROXY_LIST=http://user:pass@proxy1:port,http://proxy2:port,socks5://proxy3:port
PROXY_LIST_RAW = os.getenv("PROXY_LIST", "")
PROXY_LIST = [p.strip() for p in PROXY_LIST_RAW.split(",") if p.strip()]