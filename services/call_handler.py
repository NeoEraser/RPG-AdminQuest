"""
Модуль обработки звонков Insis Webhook.
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
from pathlib import Path

import requests
import whisper
import torch
import numpy as np
import soundfile as sf
from functools import lru_cache
from dotenv import load_dotenv

from flask import Flask, request
from services.ai_analyzer import analyze_task_with_ai

MAX_AUDIO_SECONDS = int(os.getenv("MAX_AUDIO_SECONDS", "180"))

# --- ЗАГРУЗКА .env ДО ВСЕГО ОСТАЛЬНОГО ---
PROJECT_DIR = Path(__file__).resolve().parent
ENV_PATH = PROJECT_DIR.parent / ".env"   # или PROJECT_DIR / ".env" — где лежит у тебя
load_dotenv(ENV_PATH)

# Фиксируем кэш HF, чтобы predownload и рантайм смотрели в одну папку
if os.getenv("HF_HOME"):
    os.environ["HF_HOME"] = os.environ["HF_HOME"]

# Оффлайн-режим (1 = не лезть в интернет)
if os.getenv("HF_HUB_OFFLINE", "0") == "1":
    os.environ["HF_HUB_OFFLINE"] = "1"

logger = logging.getLogger(__name__)

# --- НАСТРОЙКИ ---
# FFmpeg path fix для Windows
ffmpeg_path = r'C:\ffmpeg\bin'
if os.path.exists(ffmpeg_path):
    os.environ['PATH'] = ffmpeg_path + os.pathsep + os.environ.get('PATH', '')

# Папка для записей
RECORDINGS_DIR = str(PROJECT_DIR.parent / "recordings")
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
    "9804": "Алексей", "9805": "Александр", "9806": "Егор",
    "9807": "None", "9808": "Лев", "9809": "Кирилл", "9810": "Владимир"
}

def _load_model():
    global _model
    if _model is None:
        print("[WHISPER] Загрузка модели large-v3...")
        #_model = whisper.load_model("large-v3-turbo")
        _model = whisper.load_model("large-v3")
        print("[WHISPER] Модель загружена")
    return _model

def _load_audio_for_diarization(file_path):
    """Загружает аудио через soundfile — без torchcodec и torchaudio."""
    data, sample_rate = sf.read(file_path, always_2d=True, dtype="float32")
    # soundfile: (samples, channels) → torch/pyannote: (channels, samples)
    waveform = torch.from_numpy(data.T).contiguous()
    return {"waveform": waveform, "sample_rate": sample_rate}

@lru_cache(maxsize=1)
def _load_diarization_pipeline():
    """Загружает pyannote один раз. На 3GB VRAM держим на CPU."""
    from pyannote.audio import Pipeline
    print("[DIARIZATION] Загрузка pyannote/speaker-diarization-3.1...")
    pipe = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-3.1",
        token=os.getenv("HF_TOKEN"),  # None, если кэш уже есть
    )
    # Всегда CPU: не влезает в 3 ГБ вместе с whisper.
    pipe.to(torch.device("cpu"))
    print("[DIARIZATION] Модель загружена (CPU)")
    return pipe


def _assign_speakers(segments, diarization_output):
    """Размечает сегменты Whisper спикерами по максимальному пересечению."""
    # pyannote 4.x возвращает DiarizeOutput — внутри нужный Annotation в .speaker_diarization.
    # pyannote 3.x возвращает сам Annotation. getattr покрывает оба случая.
    diarization = getattr(
        diarization_output, "speaker_diarization", diarization_output
    )

    turns = [
        (turn.start, turn.end, spk)
        for turn, _, spk in diarization.itertracks(yield_label=True)
    ]

    def speaker_for(start, end):
        best_spk, best_ov = None, 0.0
        for t_start, t_end, spk in turns:
            ov = min(end, t_end) - max(start, t_start)
            if ov > best_ov:
                best_ov, best_spk = ov, spk
        return best_spk

    for seg in segments:
        seg["speaker"] = speaker_for(seg["start"], seg["end"])
    return segments


def _format_segments(segments):
    """Схлопывает подряд идущие сегменты одного спикера в строку."""
    lines, buf, cur = [], [], None
    for seg in segments:
        spk = seg.get("speaker") or "UNKNOWN"
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        if spk != cur:
            if buf:
                lines.append(f"[{cur}]: {' '.join(buf)}")
            buf, cur = [], spk
        buf.append(text)
    if buf:
        lines.append(f"[{cur}]: {' '.join(buf)}")
    return "\n".join(lines)

def _prepare_audio(file_path, max_seconds=MAX_AUDIO_SECONDS):
    """
    Обрезает аудио до max_seconds и приводит к mono 16kHz через ffmpeg.
    Возвращает (путь_для_работы, путь_временного_файла_или_None).
    Если обрезка не нужна — вернёт исходный путь и None.
    """
    if not max_seconds or max_seconds <= 0:
        return file_path, None

    import subprocess
    import tempfile

    # Узнаём длительность
    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", file_path],
            capture_output=True, text=True, check=True,
        )
        duration = float(probe.stdout.strip())
    except Exception as e:
        logger.warning(f"[AUDIO] Не удалось определить длительность: {e}")
        return file_path, None

    if duration <= max_seconds:
        return file_path, None

    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".wav", dir=RECORDINGS_DIR)
    os.close(tmp_fd)
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", file_path, "-t", str(max_seconds),
             "-ar", "16000", "-ac", "1", tmp_path],
            capture_output=True, check=True,
        )
    except Exception as e:
        logger.error(f"[AUDIO] Ошибка ffmpeg при обрезке: {e}")
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        return file_path, None

    logger.info(f"[AUDIO] Обрезано {duration:.1f}s → {max_seconds}s: {tmp_path}")
    return tmp_path, tmp_path

def _transcribe_audio(file_path, with_speakers=True):
    if not file_path or not os.path.exists(file_path):
        return ""

    work_path, tmp_to_clean = _prepare_audio(file_path)
    try:
        model = _load_model()
        result = model.transcribe(work_path, language="ru", fp16=False)
        segments = result.get("segments") or []

        if not with_speakers or not segments:
            return result.get("text", "")

        try:
            audio_input = _load_audio_for_diarization(work_path)
            diarization_output = _load_diarization_pipeline()(
                audio_input, num_speakers=2
            )
            _assign_speakers(segments, diarization_output)
            return _format_segments(segments)
        except Exception as e:
            logger.error(f"[DIARIZATION] Ошибка: {e}. Возвращаю без спикеров")
            return result.get("text", "")
    except Exception as e:
        logger.error(f"[WHISPER] Ошибка расшифровки: {e}")
        return ""
    finally:
        if tmp_to_clean:
            try:
                os.remove(tmp_to_clean)
            except OSError:
                pass

def _download_recording(record_name, service_id):
    """Скачивает MP3 с сервера АТС. Реализована защита от таймаутов."""
    if not record_name:
        return None
    
    url = f"https://vats-records.profintel.ru/{service_id}/{record_name}.mp3"
    filepath = os.path.join(RECORDINGS_DIR, f"{record_name}.mp3")
    
    if os.path.exists(filepath):
        return filepath
        
    max_retries = 5
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
        self.answered = False          # <-- НОВОЕ: был ли Answer по этому звонку
        self.hangup_timer = None       # <-- НОВОЕ: таймер пропущенного

def process_call_group(state, immediate=False):
    print(f"!!! >>> PROCESS_CALL_GROUP START: {state.linkedid} (immediate={immediate}) <<< !!!")
    
    if state.timer:
        try:
            state.timer.cancel()
        except Exception:
            pass
        state.timer = None
    if state.hangup_timer:
        try:
            state.hangup_timer.cancel()
        except Exception:
            pass
        state.hangup_timer = None

    if state.is_finalized:
        print(f"DEBUG: process_call_group skipped — already finalized.")
        return

    state.is_finalized = True
    
    if state.answered_user:        
        # Пытаемся получить запись
        recording_path = None
        if state.recording and state.service_id:
            recording_path = _download_recording(state.recording, state.service_id)
        
        # Если записи нет — НЕ отправляем сообщение вообще
        if not recording_path:
            print(f"!!! >>> RECORDING NOT AVAILABLE, SKIPPING MESSAGE: {state.recording} <<< !!!")
            # Тихо завершаем, сообщение не отправляем
            def cleanup():
                if state.linkedid in _active_calls:
                    del _active_calls[state.linkedid]
                    print(f"!!! >>> CLEANUP STATE (no recording): {state.linkedid} <<< !!!")
            threading.Timer(5.0, cleanup).start()
            return
        
        # Запись есть — формируем сообщение
        final_msg = f"📞 **ВХОДЯЩИЙ** от {state.caller_number}\n"
        final_msg += f"✅ Ответил: {state.answered_user}\n"
        
        text = _transcribe_audio(recording_path)
        if text:
            analysis = asyncio.run(analyze_task_with_ai(text))
            if analysis.summary:
                final_msg += f"\n📝 <b>Выжимка из разговора:</b>\n{analysis.summary}\n"
            elif analysis.company or analysis.address:
                lines = []
                if analysis.company:
                    vip_tag = " ⭐VIP" if analysis.is_vip else ""
                    lines.append(f"🏢 Компания: <b>{analysis.company}</b>{vip_tag}")
                if analysis.address:
                    lines.append(f"📍 Локация: {analysis.address}")
                em = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}
                lines.append(f"{em.get(analysis.priority, '🟡')} Приоритет: <b>{analysis.priority.upper()}</b>")
                final_msg += f"\n📋 <b>АНАЛИЗ ЗАДАЧИ</b>\n" + "\n".join(lines) + "\n"
            else:
                final_msg += f"\n🎤 Расшифровка: {text[:300]}\n"
        else:
            # Расшифровка не удалась, но запись есть — можно отправить без текста
            final_msg += f"\n⚠️ Расшифровка не удалась.\n"
        
        print(f"[GROUP] Итог (Входящий):\n{final_msg}")
        call_queue.put(final_msg)

    else:
        # Никто не ответил — пропущенный
        if state.caller_number:
            final_msg = f"📞 **ПРОПУЩЕННЫЙ** от {state.caller_number}\n"
            print(f"[GROUP] Итог (Пропущенный):\n{final_msg}")
            call_queue.put(final_msg)
    
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
        
        state.answered = True

        print(f"DEBUG: Answer detected! User: {state.answered_user}, Rec: {state.recording}")
        
        # Отменяем таймер пропущенного (звонок взят)
        if state.hangup_timer:
            print("DEBUG: Cancelling hangup timer.")
            state.hangup_timer.cancel()
            state.hangup_timer = None

        # НЕ финализируем здесь — ждём Hangup, чтобы получить запись
        # Но ставим страховочный таймер на случай, если Hangup не придёт
        if state.timer:
            state.timer.cancel()
        state.timer = threading.Timer(120.0, process_call_group, args=[state])
        state.timer.start()
        return

    # 6. Конец звонка
    if event_type == 'Hangup':
        print(f"DEBUG: Hangup detected.")
        
        # Если уже знаем, что ответили — финализируем (запись уже должна быть готова)
        if state.answered:
            print(f"DEBUG: Answered call hangup, finalizing.")
            if state.timer:
                state.timer.cancel()
                state.timer = None
            if state.hangup_timer:
                state.hangup_timer.cancel()
                state.hangup_timer = None
            process_call_group(state, immediate=True)
            return

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
            else:
                state.answered_user = "Система (неизвестно)"

            state.answered = True

        if state.answered:
            print(f"DEBUG: Someone answered. Finalizing.")
            if state.timer:
                state.timer.cancel()
                state.timer = None
            if state.hangup_timer:
                state.hangup_timer.cancel()
                state.hangup_timer = None
            process_call_group(state, immediate=True)
            return
        
        # Пропущенный — таймер 15 сек тишины
        if state.hangup_timer:
            print(f"DEBUG: Restarting hangup timer (15s).")
            state.hangup_timer.cancel()
        else:
            print(f"DEBUG: Starting 15s timer for Hangup.")

        state.hangup_timer = threading.Timer(15.0, process_call_group, args=[state])
        state.hangup_timer.start()
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