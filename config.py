import os
from dotenv import load_dotenv

# Загружаем переменные из .env
load_dotenv()

# Читаем переменные
TOKEN = str(os.getenv("BOT_TOKEN"))
# Преобразуем в int для проверок
TEAMLEAD_ID = int(os.getenv("TEAMLEAD_ID", 0)) 
DB_NAME = str(os.getenv("DB_NAME"))
PROXY_URL = os.getenv("PROXY_URL")
# Тот самый ID чата для квестов
GROUP_ID = int(os.getenv("GROUP_ID", 0)) 
# Путь к python интерпретатору для отдельного venv с эмбеддингами (если используете отдельный venv)
EMBEDDING_PYTHON = os.getenv("EMBEDDING_PYTHON", os.path.join(os.getcwd(), "Desktop", "python project", "uralaiti_gamebot_rpg", ".venv", "Scripts", "python.exe"))
