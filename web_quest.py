"""
Модуль веб-формы подачи заявок на квесты.
Flask-сервер на порту 5001, публичная форма без аутентификации.
Заявка отправляется как сообщение в Telegram-чат (GROUP_ID)
через call_queue — тот же путь, что у телефонии.
"""
import logging
import os
import threading
from datetime import datetime

logger = logging.getLogger(__name__)

# Форматированное сообщение заявки для Telegram
QUEST_TEMPLATE = """
📋 <b>НОВАЯ ЗАЯВКА НА КВЕСТ</b>

👤 <b>Имя:</b> {name}
📱 <b>Телефон:</b> {phone}
🏢 <b>Компания:</b> {company}
📝 <b>Проблема:</b> {description}

🕐 <b>Дата:</b> {date}
"""


def format_quest_message(name: str, phone: str, company: str, description: str) -> str:
    """Формирует сообщение для Telegram из данных формы."""
    from datetime import datetime
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")

    return QUEST_TEMPLATE.format(
        name=name,
        phone=phone,
        company=company,
        description=description,
        date=now,
    ).strip()


# Импорт очереди вызовов — тот же call_queue, что и у телефонии
from services.call_handler import call_queue

# Форматированное сообщение заявки для Telegram
QUEST_TEMPLATE = """
📋 <b>НОВАЯ ЗАЯВКА НА КВЕСТ</b>

👤 <b>Имя:</b> {name}
📱 <b>Телефон:</b> {phone}
🏢 <b>Компания:</b> {company}
📝 <b>Проблема:</b> {description}

🕐 <b>Дата:</b> {date}
"""


def format_quest_message(name: str, phone: str, company: str, description: str) -> str:
    """Формирует сообщение для Telegram из данных формы."""
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")

    return QUEST_TEMPLATE.format(
        name=name,
        phone=phone,
        company=company,
        description=description,
        date=now,
    ).strip()


# Простая HTML-шаблон формы
FORM_HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Заявка на квест</title>
    <style>
        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #0f0c29, #302b63, #24243e);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }
        .container {
            background: rgba(255, 255, 255, 0.05);
            backdrop-filter: blur(20px);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 20px;
            padding: 40px;
            max-width: 500px;
            width: 100%;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
        }
        h1 {
            color: #fff;
            text-align: center;
            margin-bottom: 10px;
            font-size: 1.8em;
        }
        .subtitle {
            color: rgba(255, 255, 255, 0.5);
            text-align: center;
            margin-bottom: 30px;
            font-size: 0.9em;
        }
        .form-group {
            margin-bottom: 20px;
        }
        label {
            display: block;
            color: rgba(255, 255, 255, 0.7);
            margin-bottom: 8px;
            font-size: 0.9em;
            font-weight: 500;
        }
        label .required {
            color: #ff6b6b;
        }
        input[type="text"],
        input[type="tel"],
        textarea {
            width: 100%;
            padding: 14px 16px;
            background: rgba(255, 255, 255, 0.08);
            border: 1px solid rgba(255, 255, 255, 0.15);
            border-radius: 10px;
            color: #fff;
            font-size: 1em;
            transition: all 0.3s ease;
            outline: none;
        }
        input[type="text"]:focus,
        input[type="tel"]:focus,
        textarea:focus {
            border-color: #7c5cfc;
            background: rgba(124, 92, 252, 0.1);
            box-shadow: 0 0 0 3px rgba(124, 92, 252, 0.2);
        }
        input::placeholder,
        textarea::placeholder {
            color: rgba(255, 255, 255, 0.3);
        }
        textarea {
            min-height: 120px;
            resize: vertical;
        }
        .btn-submit {
            width: 100%;
            padding: 16px;
            background: linear-gradient(135deg, #7c5cfc, #a855f7);
            color: #fff;
            border: none;
            border-radius: 10px;
            font-size: 1.1em;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
            margin-top: 10px;
        }
        .btn-submit:hover {
            transform: translateY(-2px);
            box-shadow: 0 10px 30px rgba(124, 92, 252, 0.4);
        }
        .btn-submit:active {
            transform: translateY(0);
        }
        .btn-submit:disabled {
            opacity: 0.5;
            cursor: not-allowed;
            transform: none;
            box-shadow: none;
        }
        .success-msg {
            display: none;
            text-align: center;
            padding: 30px;
        }
        .success-msg .icon {
            font-size: 3em;
            margin-bottom: 15px;
        }
        .success-msg h2 {
            color: #fff;
            margin-bottom: 10px;
        }
        .success-msg p {
            color: rgba(255, 255, 255, 0.6);
        }
        .error-msg {
            display: none;
            background: rgba(255, 107, 107, 0.15);
            border: 1px solid rgba(255, 107, 107, 0.3);
            border-radius: 10px;
            padding: 12px 16px;
            color: #ff6b6b;
            margin-bottom: 20px;
            font-size: 0.9em;
        }
    </style>
</head>
<body>
    <div class="container">
        <div id="form-section">
            <h1>📋 Заявка на квест</h1>
            <p class="subtitle">Заполните форму — мы свяжемся с вами</p>

            <div class="error-msg" id="error-msg"></div>

            <form id="quest-form">
                <div class="form-group">
                    <label>Имя <span class="required">*</span></label>
                    <input type="text" id="name" name="name"
                           placeholder="Как вас зовут?" required>
                </div>

                <div class="form-group">
                    <label>Телефон <span class="required">*</span></label>
                    <input type="tel" id="phone" name="phone"
                           placeholder="+7 (999) 123-45-67" required>
                </div>

                <div class="form-group">
                    <label>Компания</label>
                    <input type="text" id="company" name="company"
                           placeholder="Название вашей компании">
                </div>

                <div class="form-group">
                    <label>Описание проблемы <span class="required">*</span></label>
                    <textarea id="description" name="description"
                              placeholder="Опишите, что случилось..." required></textarea>
                </div>

                <button type="submit" class="btn-submit" id="submit-btn">
                    Отправить заявку
                </button>
            </form>
        </div>

        <div class="success-msg" id="success-section">
            <div class="icon">✅</div>
            <h2>Заявка отправлена!</h2>
            <p>Мы свяжемся с вами в ближайшее время.</p>
        </div>
    </div>

    <script>
        const form = document.getElementById('quest-form');
        const errorMsg = document.getElementById('error-msg');
        const submitBtn = document.getElementById('submit-btn');
        const formSection = document.getElementById('form-section');
        const successSection = document.getElementById('success-section');

        // Маска телефона
        const phoneInput = document.getElementById('phone');
        phoneInput.addEventListener('input', function(e) {
            let x = e.target.value.replace(/\\D/g, '').match(/(\\d{0,1})(\\d{0,3})(\\d{0,3})(\\d{0,2})(\\d{0,2})/);
            if (!x) return;
            e.target.value = !x[2] ? (x[1] === '8' ? '+7' : x[1])
                : '+7 (' + x[2] + (x[3] ? ') ' + x[3] : '')
                + (x[4] ? '-' + x[4] : '')
                + (x[5] ? '-' + x[5] : '');
        });

        form.addEventListener('submit', async function(e) {
            e.preventDefault();
            errorMsg.style.display = 'none';

            const data = {
                name: document.getElementById('name').value.trim(),
                phone: document.getElementById('phone').value.trim(),
                company: document.getElementById('company').value.trim(),
                description: document.getElementById('description').value.trim(),
            };

            // Валидация
            if (!data.name || !data.phone || !data.description) {
                showError('Заполните все обязательные поля');
                return;
            }
            if (data.description.length > 5000) {
                showError('Описание слишком длинное (макс. 5000 символов)');
                return;
            }

            // Отправка
            submitBtn.disabled = true;
            submitBtn.textContent = 'Отправка...';

            try {
                const resp = await fetch('/submit', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data),
                });
                const result = await resp.json();

                if (result.status === 'ok') {
                    formSection.style.display = 'none';
                    successSection.style.display = 'block';
                } else {
                    showError(result.message || 'Ошибка отправки');
                }
            } catch (err) {
                showError('Не удалось подключиться к серверу');
            } finally {
                submitBtn.disabled = false;
                submitBtn.textContent = 'Отправить заявку';
            }
        });

        function showError(msg) {
            errorMsg.textContent = msg;
            errorMsg.style.display = 'block';
        }
    </script>
</body>
</html>
"""


class WebQuestHandler:
    """Flask-сервер для веб-формы заявок на квесты (порт 5001)."""

    def __init__(self, bot_token: str, group_id: int, proxy_manager, port: int = 5001):
        self.bot_token = bot_token
        self.group_id = group_id
        self.proxy_manager = proxy_manager
        self.port = port
        self._thread = None

    def start(self):
        from flask import Flask, request, jsonify

        app = Flask(__name__)

        @app.route("/", methods=["GET"])
        def index():
            return FORM_HTML

        @app.route("/submit", methods=["POST"])
        def submit():
            data = request.get_json()
            if not data:
                return jsonify({"status": "error", "message": "Нет данных"}), 400

            name = str(data.get("name", "")).strip()
            phone = str(data.get("phone", "")).strip()
            company = str(data.get("company", "")).strip()
            description = str(data.get("description", "")).strip()

            # Валидация
            if not name or not phone or not description:
                return jsonify({"status": "error", "message": "Заполните все обязательные поля"}), 400

            if len(description) > 5000:
                return jsonify({"status": "error", "message": "Описание слишком длинное"}), 400

            # Формируем сообщение
            message_text = format_quest_message(name, phone, company, description)

            # Добавляем в очередь — тот же call_queue, что и у телефонии
            call_queue.put(message_text)
            logger.info(f"✅ Заявка от {name} добавлена в queue")

            return jsonify({"status": "ok"}), 200

        def run_flask():
            app.run(host="0.0.0.0", port=self.port, debug=False, use_reloader=False)

        self._thread = threading.Thread(target=run_flask, daemon=True)
        self._thread.start()
        logger.info(f"✅ WebQuestHandler запущен на порту {self.port}")

    async def stop(self):
        self._thread = None
        logger.info("📋 WebQuestHandler остановлен")