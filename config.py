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
EMBEDDING_PYTHON = os.getenv(
    "EMBEDDING_PYTHON", 
    os.path.join(os.getcwd(), "Desktop", "python project", "uralaiti_gamebot_rpg", ".venv", "Scripts", "python.exe")
)


# ══════════════════════════════════════════════════════════
# AI-анализ задач
# ══════════════════════════════════════════════════════════

import json as _json
import logging

AI_BASE_URL = os.getenv("AI_BASE_URL")
AI_MODEL = os.getenv("AI_MODEL")
AI_TEMPERATURE = float(os.getenv("AI_TEMPERATURE"))
AI_MAX_TOKENS=int(os.getenv("AI_MAX_TOKENS"))
AI_ENABLED = os.getenv("AI_ENABLED")

COMPANIES_FILE = os.getenv(
    "COMPANIES_FILE",
    os.path.join(os.getcwd(), "Desktop", "python project", "uralaiti_gamebot_rpg", "config", "companies.json")
)

try:
    with open(COMPANIES_FILE, "r", encoding="utf-8") as f:
        COMPANIES = _json.load(f)
    logging.info(f"✅ AI-анализ: загружено {len(COMPANIES)} компаний")
except Exception:
    COMPANIES = []
    logging.warning("⚠️ AI-анализ: файл companies.json не найден — анализ компаний отключён")