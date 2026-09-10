"""
Модуль обработки звонков Inis Webhook.
Исправлена проблема с отсутствующим номером входящего (обход пустых событий АТС).
"""
import asyncio
import datetime
import logging
import os
import queue
import re
import threading
import time
import requests
import whisper

from flask import Flask, request
from services.ai_analyzer import analyze_task_with_ai

logger = logging.getLogger(__name__)

# --- НАСТРОЙКИ ---
# FFmpeg path fix для Windows
ffmpeg_path = r'C:\ffmpeg\bin'
if os.path.exists(ffmpeg_path):
    os.environ['PATH'] = ffmpeg_path + os.pathsep + os.environ.get('PATH', '')

# Папка для записей
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
RECORDINGS_DIR = os.path.join(PROJECT_DIR, '..', 'recordings')
os.makedirs(RECORDINGS_DIR, exist_ok=True)

# Очередь сообщений для бота
call_queue = queue.Queue()

# Временное хранилище активных групповых звонков
_active_calls = {}

# Глобальная модель Whisper
_model = None

# База сотрудников
STAFF = {
    "9801": "Евгения", "9802": "Дима", "9803": "Евгений",
    "9804": "Алексей Бархатов", "9805": "Александр", "9806": "Егор",
    "9807": "Иван", "9808": "Лев", "9809": "Кирилл", "9810": "Владимир"
}

def _load_model():
    global _model
    if _model is None:
        print("[WHISPER] Загрузка модели large-v3-turbo...")
        #_model = whisper.load_model("large-v3-turbo")
        _model = whisper.load_model("large-v3")
        print("[WHISPER] Модель загружена")
    return _model

def _transcribe_audio(file_path):
    if not file_path or not os.path.exists(file_path):
        return ""
    try:
        model = _load_model()
        result = model.transcribe(file_path, language="ru", fp16=False)
        return result.get("text", "")
    except Exception as e:
        logger.error(f"[WHISPER] Ошибка расшифровки: {e}")
        return ""

def _download_recording(record_name, service_id):
    """Скачивает MP3 с сервера АТС. Реализована защита от таймаутов."""
    if not record_name:
        return None
    
    url = f"https://vats-records.profintel.ru/{service_id}/{record_name}.mp3"
    filepath = os.path.join(RECORDINGS_DIR, f"{record_name}.mp3")
    
    if os.path.exists(filepath):
        return filepath
        
    max_retries = 3
    timeout = 60
    
    for attempt in range(max_retries):
        try:
            logger.info(f"[CALL] Попытка скачать запись (#{attempt + 1}): {record_name}")
            resp = requests.get(url, timeout=timeout)
            if resp.status_code == 200:
                with open(filepath, 'wb') as f:
                    f.write(resp.content)
                logger.info(f"[CALL] Успешно скачана запись: {record_name}")
                return filepath
            else:
                logger.warning(f"[CALL] Неверный статус при скачивании: {resp.status_code}")
        except requests.exceptions.Timeout:
            logger.warning(f"[CALL] Таймаут при скачивании (#{attempt + 1}). Повтор через 5 сек...")
            time.sleep(5)
        except requests.exceptions.ConnectionError:
            logger.warning(f"[CALL] Ошибка соединения при скачивании (#{attempt + 1}). Повтор через 5 сек...")
            time.sleep(5)
        except Exception as e:
            logger.error(f"[CALL] Критическая ошибка при скачивании: {e}")
            break
            
    logger.error(f"[CALL] Не удалось скачать запись {record_name} после {max_retries} попыток.")
    return None

class CallState:
    def __init__(self, linkedid, caller_name, caller_number):
        self.linkedid = linkedid
        self.caller_name = caller_name 
        self.caller_number = caller_number 
        self.answered_user = None      
        self.recording = None          
        self.timer = None              
        self.service_id = None 
        self.is_finalized = False

def process_call_group(state, immediate=False):
    """
    Формирует итоговое сообщение.
    immediate=True -> отправляем сразу, не дожидаясь всех Hangup.
    """
    print(f"!!! >>> PROCESS_CALL_GROUP START: {state.linkedid} (immediate={immediate}) <<< !!!")
    
    state.is_finalized = True
    
    if state.answered_user:
        final_msg = f"📞 **ВХОДЯЩИЙ** от {state.caller_number}\n"
        final_msg += f"✅ Ответил: {state.answered_user}\n"
        
        if state.recording and state.service_id:
            recording_path = _download_recording(state.recording, state.service_id)
            if recording_path:
                text = _transcribe_audio(recording_path)
                if text:
                    text = analyze_task_with_ai(text)
                    final_msg += f"\n🎤 Расшифровка:\n{text}\n"
                else:
                    final_msg += f"\n⚠️ Расшифровка не удалась.\n"
        
        print(f"[GROUP] Итог (Входящий):\n{final_msg}")
        call_queue.put(final_msg)

    else:
        # Никто не ответил
        if state.caller_number:
            final_msg = f"📞 **ПРОПУЩЕННЫЙ** от {state.caller_number}\n"
            print(f"[GROUP] Итог (Пропущенный):\n{final_msg}")
            call_queue.put(final_msg)
    
    # Вместо немедленного удаления, ставим таймер очистки на 5 секунд.
    # Это нужно, чтобы дождаться всех "хвостовых" Hangup и не создать дубликат состояния.
    def cleanup():
        if state.linkedid in _active_calls:
            del _active_calls[state.linkedid]
            print(f"!!! >>> CLEANUP STATE: {state.linkedid} <<< !!!")
            
    threading.Timer(5.0, cleanup).start()

def handle_call_event(event_type, data):
    linkedid = data.get('linkedid')
    src = data.get('src')
    dst = data.get('dst')
    direction = data.get('direction')
    src_name = data.get('src_name', 'Неизвестно') # Определяем переменную здесь, чтобы избежать NameError
    service_id = data.get('service_id')
    
    print(f"DEBUG: Received event {event_type} for linkedid={linkedid} (dir={direction}, src={src}, dst={dst})")

    # 1. ИГНОРИРУЕМ ВСЕ ИСХОДЯЩИЕ
    if direction == 'Out':
        print(f"DEBUG: IGNORED - Outgoing call {linkedid} from {src}")
        return

    # 2. Инициализация или обновление звонка
    if linkedid not in _active_calls:
        # Создаем новое состояние
        caller_number = src
        if not caller_number or len(str(caller_number)) < 6:
            caller_number = dst
        if not caller_number or len(str(caller_number)) < 6:
            match = re.search(r'(\+?[0-9]{10,12})', str(src_name))
            if match:
                caller_number = match.group(1)
        
        if not caller_number or len(str(caller_number)) < 6:
            caller_number = "Неизвестно"
        
        print(f"DEBUG: Created new CallState for {linkedid}. Caller: {caller_number}")
        _active_calls[linkedid] = CallState(linkedid, src_name, caller_number)
    else:
        # Состояние уже есть. Если номер не определен (например, из-за "мусорного" события), а здесь есть данные — обновляем!
        state = _active_calls[linkedid]
        if (not state.caller_number or state.caller_number == "Неизвестно") and src and len(str(src)) > 5:
            state.caller_number = src
            state.caller_name = data.get('src_name', '')
            print(f"DEBUG: Updated caller number for {linkedid} to {src}")

    state = _active_calls[linkedid]
    state.service_id = service_id

    # 3. ЖЕСТКАЯ ПРОВЕРКА: если звонок уже обработан (finalized), игнорируем ВСЁ
    if state.is_finalized:
        print(f"DEBUG: IGNORED - Call {linkedid} already finalized.")
        return

    # 4. Начало звонка
    if event_type == 'Initialize':
        print(f"DEBUG: Initialized {linkedid} from {src_name}")
        return

    # 5. Взятие трубки
    if event_type == 'Answer':
        state.recording = data.get('record_name')
        answered_ext = src 
        if answered_ext in STAFF:
            state.answered_user = STAFF[answered_ext]
        else:
            state.answered_user = src_name 
        
        print(f"DEBUG: Answer detected! User: {state.answered_user}, Rec: {state.recording}")
        
        # Если ответили, сразу отправляем сообщение и отменяем таймер ожидания
        if state.timer:
            print("DEBUG: Cancelling timer.")
            state.timer.cancel()
        process_call_group(state, immediate=True)
        return

    # 6. Конец звонка
    if event_type == 'Hangup':
        print(f"DEBUG: Hangup detected.")
        
        # === ПРОВЕРКА ЗАПИСИ В Hangup ===
        hangup_rec = data.get('record_name')
        hangup_src = data.get('src')
        hangup_src_name = data.get('src_name')

        # Если мы не видели события Answer, но в Hangup есть имя записи,
        # значит звонок всё же был взят.
        if hangup_rec and not state.answered_user:
            print(f"DEBUG: Answer detected via Hangup recording!")
            state.recording = hangup_rec
            if hangup_src and str(hangup_src) in STAFF:
                state.answered_user = STAFF[str(hangup_src)]
            elif hangup_src_name:
                state.answered_user = hangup_src_name
            elif hangup_rec:
                 state.answered_user = "Система (неизвестно)" 

        if state.answered_user:
            print(f"DEBUG: Someone answered. Cancelling timer if any.")
            if state.timer:
                state.timer.cancel()
            process_call_group(state, immediate=True)
            return
        
        # Если ответа нет, запускаем таймер (Пропущенный)
        if state.timer is None:
            print(f"DEBUG: Starting 3s timer for Hangup.")
            state.timer = threading.Timer(3.0, process_call_group, args=[state])
            state.timer.start()
            return


class CallHandler:
    def __init__(self, port=5000):
        self.port = port
        self._thread = None

    def start(self):
        from flask import Flask
        app = Flask(__name__)

        @app.route('/incoming', methods=['POST'])
        def webhook():
            try:
                data = request.json
                handle_call_event(data.get('event'), data)
                return "OK", 200
            except Exception as e:
                logger.error(f"[CALL] Error: {e}", exc_info=True)
                return "Error", 500

        def run_flask():
            app.run(host='0.0.0.0', port=self.port, debug=False, use_reloader=False)

        self._thread = threading.Thread(target=run_flask, daemon=True)
        self._thread.start()
        logger.info(f"✅ CallHandler запущен на порту {self.port}")

    async def stop(self):
        self._thread = None
        logger.info("📞 CallHandler остановлен")