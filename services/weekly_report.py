"""
Генератор еженедельных отчётов для "Глаз директора".

Запуск:
  1. Из CLI: python -m services.weekly_report
  2. Из APScheduler: scheduler.add_job(send_weekly_report, 'cron', day_of_week='mon', hour=9, minute=30, args=[bot, GROUP_ID])
  3. По команде: /report (для тимлида)
"""

import asyncio
import html
import logging
from datetime import datetime, timedelta
from typing import Optional
import os
import tempfile
from pathlib import Path

import aiosqlite

from config import DB_NAME, GROUP_ID

logger = logging.getLogger(__name__)


def esc(text: str) -> str:
    """Экранирует HTML-спецсимволы."""
    if not text:
        return ""
    return html.escape(str(text), quote=True)


# ─────────────────────────── helpers ───────────────────────────

def _week_range(ref_date: datetime = None):
    """Возвращает (понедельник, воскресенье) для недели, содержащей ref_date."""
    ref = ref_date or datetime.now()
    monday = ref - timedelta(days=ref.weekday())
    sunday = monday + timedelta(days=6)
    return monday.date(), sunday.date()


def _weekday_name(d):
    return ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][d.weekday()]


# ─────────────────────────── data collectors ───────────────────────────

async def get_leaderboard_changes(db, week_mon, week_sun):
    """
    Топ-10 по EXP за неделю с динамикой.
    Возвращает: [(name, exp_before, exp_after, delta)]
    """
    query = '''
        SELECT u.user_id, u.name,
               COALESCE(SUM(CASE WHEN eh.change_date >= ? THEN eh.exp_change ELSE 0 END), 0) AS delta
        FROM users u
        LEFT JOIN exp_history eh ON u.user_id = eh.user_id
        WHERE u.agreed_to_tos = 1
        GROUP BY u.user_id
        HAVING delta != 0
        ORDER BY delta DESC
        LIMIT 10
    '''
    async with db.execute(query, (week_mon.isoformat(),)) as cursor:
        rows = await cursor.fetchall()

    results = []
    for uid, name, delta in rows:
        async with db.execute('SELECT exp FROM users WHERE user_id = ?', (uid,)) as c:
            cur_exp = (await c.fetchone())[0]
        before = cur_exp - delta
        results.append((name, before, cur_exp, delta))

    return results


async def get_engineer_dashboard(db, week_mon, week_sun):
    """
    Дашборд: Имя | Квесты | Инциденты | Штрафы.
    Возвращает: [(name, quests, incidents, penalties)]
    """
    query = '''
        SELECT
            u.name,
            COUNT(CASE WHEN t.reward = 5 THEN 1 END) AS quests,
            COUNT(CASE WHEN t.reward = 15 THEN 1 END) AS incidents,
            COALESCE(SUM(CASE WHEN eh.exp_change < 0 THEN eh.exp_change END), 0) AS penalties
        FROM users u
        LEFT JOIN tasks t ON u.user_id = t.worker_id AND t.status = 'completed' AND t.start_time >= ?
        LEFT JOIN exp_history eh ON u.user_id = eh.user_id
            AND eh.change_date >= ? AND eh.reason IN ('timeout', 'rejected', 'no_plan', 'afk', 'smite')
        WHERE u.agreed_to_tos = 1
        GROUP BY u.user_id
        HAVING quests + incidents + ABS(COALESCE(penalties, 0)) > 0
        ORDER BY quests + incidents DESC
    '''
    async with db.execute(query, (week_mon.isoformat(), week_mon.isoformat())) as cursor:
        return await cursor.fetchall()


async def get_overdue_analysis(db, week_mon, week_sun):
    """
    Анализ просрочек: задачи, которые вернулись (timeout).
    Возвращает: [(task_id, description, worker_name, timeout_date)]
    """
    # Просроченные квесты возвращаются в status='open' с worker_id=NULL (см. quest_timeout_check)
    # Запрашиваем историю через exp_history по причине 'timeout'
    query = '''
        SELECT t.task_id, t.description, u.name, t.start_time
        FROM tasks t
        JOIN users u ON t.worker_id = u.user_id
        JOIN exp_history eh ON t.worker_id = eh.user_id
            AND eh.reason = 'timeout' AND eh.change_date >= ? AND eh.change_date <= ?
        WHERE t.reward = 5
    '''
    async with db.execute(query, (week_mon.isoformat(), week_sun.isoformat())) as cursor:
        rows = await cursor.fetchall()

    # Дедупликация по task_id
    seen = set()
    unique = []
    for row in rows:
        if row[0] not in seen:
            seen.add(row[0])
            unique.append(row)
    return unique


async def get_client_activity_map(db, week_mon, week_sun):
    """
    Карта клиентов по завершённым задачам (по описанию).
    Это упрощённый вариант — можно расширить парсингом названий клиентов.
    Возвращает: [(description, worker_name, created_at)]
    """
    query = '''
        SELECT t.description, u.name, t.start_time
        FROM tasks t
        JOIN users u ON t.worker_id = u.user_id
        WHERE t.status = 'completed'
          AND t.start_time >= ? AND t.start_time <= ?
        ORDER BY t.start_time DESC
    '''
    async with db.execute(query, (week_mon.isoformat(), week_sun.isoformat())) as cursor:
        return await cursor.fetchall()


# ─────────────────────────── report builder ───────────────────────────

def build_weekly_report(week_mon, week_sun, leaderboard, dashboard, overdue, client_map):

    """Формирует Markdown-отчёт."""
    lines = []

    # ── Заголовок ──
    lines.append(f"📊 <b>НЕДЕЛЬНЫЙ ОТЧЁТ: {_weekday_name(week_mon)}, {week_mon.strftime('%d.%m')} — {_weekday_name(week_sun)}, {week_sun.strftime('%d.%m.%Y')}</b>")
    lines.append("")

    # ── Leaderboard ──
    lines.append(f"🏆 <b>ТОП АКТИВНОСТИ ({len(leaderboard)} героев с движением)</b>")
    if leaderboard:
        for i, (name, before, after, delta) in enumerate(leaderboard[:10], 1):
            arrow = "📈" if delta > 0 else "📉"
            lines.append(f"  {i}. {arrow} <b>{esc(name)}</b>: {before}→{after} EXP ({delta:+d})")
    else:
        lines.append("  Нет активности за неделю.")
    lines.append("")

    # ── Dashboard ──
    lines.append(f"👥 <b>ДАШБОРД ИНЖЕНЕРОВ</b>")
    if dashboard:
        lines.append("  <code>Имя                          | Квесты | Инц. | Штрафы</code>")
        lines.append("  " + "─" * 50)
        for name, quests, incidents, penalties in dashboard:
            penalty_str = str(penalties) if penalties < 0 else "0"
            lines.append(f"  {esc(name)[:24]:<24}| {quests:>4} | {incidents:>4} | {penalty_str:>6}")
    else:
        lines.append("  Нет завершённых задач за неделю.")
    lines.append("")

    # ── Просрочки ──
    lines.append(f"⚠️ <b>ПРОСРОЧКИ (вернулись в open)</b>")
    if overdue:
        for tid, desc, worker, start_time in overdue[:10]:
            dt = datetime.fromisoformat(start_time.replace(' ', '+'))
            lines.append(f"  🔴 Квест #{tid} — <b>{esc(worker)}</b> — {dt.strftime('%d.%m %H:%M')}")
            short = esc(desc)[:60] + "..." if len(esc(desc)) > 60 else esc(desc)
            lines.append(f"     {short}")
        lines.append(f"  ... всего: {len(overdue)}")
    else:
        lines.append("  ✅ Просрочек нет!")
    lines.append("")

    # ── Карта клиентов ──
    lines.append(f"📋 <b>ВЫПОЛНЕННЫЕ ЗАДАЧИ ({len(client_map)})</b>")
    if client_map:
        by_worker = {}
        for desc, worker, created in client_map:
            by_worker.setdefault(worker, []).append((desc, created))

        for worker, tasks in sorted(by_worker.items()):
            lines.append(f"  👤 <b>{esc(worker)}</b> — {len(tasks)} задач(и)")
            for desc, created in tasks[:5]:
                dt = datetime.fromisoformat(created.replace(' ', '+'))
                short = esc(desc)[:70] + "..." if len(esc(desc)) > 70 else esc(desc)
                lines.append(f"     {dt.strftime('%d.%m %H:%M')} — {short}")
            if len(tasks) > 5:
                lines.append(f"     ... и ещё {len(tasks) - 5}")
    else:
        lines.append("  Нет завершённых задач за неделю.")
    lines.append("")

    # ── Footer ──
    lines.append(f"📅 Сгенерировано: {datetime.now().strftime('%d.%m.%Y %H:%M')} | 🤖 RPG-AdminQuest Bot")

    return "\n".join(lines)


def build_weekly_report_html(week_mon, week_sun, leaderboard, dashboard, overdue, client_map) -> str:
    """Формирует HTML-версию отчёта."""
    
    html = f"""
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Недельный отчёт RPG-AdminQuest</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif;
            max-width: 900px;
            margin: 20px auto;
            padding: 30px;
            background: #f8f9fa;
            color: #2c3e50;
            line-height: 1.6;
        }}
        .container {{
            background: white;
            border-radius: 16px;
            padding: 40px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.08);
        }}
        h1 {{
            font-size: 26px;
            color: #2c3e50;
            border-bottom: 3px solid #3498db;
            padding-bottom: 15px;
            margin-bottom: 30px;
        }}
        h2 {{
            font-size: 22px;
            color: #34495e;
            margin-top: 30px;
            margin-bottom: 15px;
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        .badge {{
            background: #e9ecef;
            padding: 2px 10px;
            border-radius: 12px;
            font-size: 14px;
            font-weight: normal;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 15px 0;
            font-size: 15px;
        }}
        th, td {{
            padding: 10px 12px;
            text-align: left;
            border-bottom: 1px solid #dee2e6;
        }}
        th {{
            background: #f1f3f5;
            font-weight: 600;
            color: #495057;
        }}
        tr:hover {{
            background: #f8f9fa;
        }}
        .leaderboard-item {{
            padding: 8px 0;
            display: flex;
            justify-content: space-between;
            border-bottom: 1px solid #f1f3f5;
        }}
        .leaderboard-item .name {{
            font-weight: 500;
        }}
        .leaderboard-item .exp {{
            font-weight: 600;
        }}
        .exp-positive {{ color: #27ae60; }}
        .exp-negative {{ color: #e74c3c; }}
        .task-item {{
            padding: 6px 0 6px 20px;
            border-left: 3px solid #3498db;
            margin: 5px 0;
            font-size: 14px;
        }}
        .task-item .time {{
            color: #6c757d;
            font-weight: 500;
        }}
        .overdue-item {{
            padding: 10px 15px;
            margin: 8px 0;
            background: #fff5f5;
            border-left: 4px solid #e74c3c;
            border-radius: 4px;
        }}
        .overdue-item .worker {{
            font-weight: 600;
            color: #c0392b;
        }}
        .footer {{
            margin-top: 40px;
            padding-top: 20px;
            border-top: 2px solid #e9ecef;
            color: #6c757d;
            font-size: 13px;
            text-align: center;
        }}
        .empty-state {{
            color: #6c757d;
            font-style: italic;
            padding: 15px 0;
        }}
        .worker-group {{
            margin: 10px 0 15px 0;
            background: #f8f9fa;
            padding: 12px 16px;
            border-radius: 8px;
        }}
        .worker-group .worker-name {{
            font-weight: 600;
            color: #2c3e50;
            font-size: 16px;
        }}
        .worker-group .task-count {{
            color: #6c757d;
            font-size: 14px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 НЕДЕЛЬНЫЙ ОТЧЁТ</h1>
        <p style="font-size: 18px; color: #34495e; margin-bottom: 30px;">
            {_weekday_name(week_mon)}, {week_mon.strftime('%d.%m')} — {_weekday_name(week_sun)}, {week_sun.strftime('%d.%m.%Y')}
        </p>
"""

    # ── Leaderboard ──
    html += f"""
        <h2>🏆 ТОП АКТИВНОСТИ <span class="badge">{len(leaderboard)} героев</span></h2>
"""
    if leaderboard:
        html += '<div style="margin: 15px 0;">'
        for i, (name, before, after, delta) in enumerate(leaderboard[:10], 1):
            emoji = "📈" if delta > 0 else "📉"
            color_class = "exp-positive" if delta > 0 else "exp-negative"
            html += f"""
            <div class="leaderboard-item">
                <span class="name">{i}. {emoji} {esc(name)}</span>
                <span class="exp">{before} → {after} EXP <span class="{color_class}">({delta:+d})</span></span>
            </div>
"""
        if len(leaderboard) > 10:
            html += f'<div style="color: #6c757d; text-align: center; margin-top: 8px;">... и ещё {len(leaderboard) - 10} участников</div>'
        html += '</div>'
    else:
        html += '<div class="empty-state">Нет активности за неделю.</div>'

    # ── Dashboard ──
    html += f"""
        <h2>👥 ДАШБОРД ИНЖЕНЕРОВ</h2>
"""
    if dashboard:
        html += """
        <table>
            <thead>
                <tr>
                    <th>Имя</th>
                    <th style="text-align: center;">Квесты</th>
                    <th style="text-align: center;">Инциденты</th>
                    <th style="text-align: center;">Штрафы</th>
                </tr>
            </thead>
            <tbody>
"""
        for name, quests, incidents, penalties in dashboard:
            penalty_str = str(penalties) if penalties < 0 else "0"
            html += f"""
                <tr>
                    <td><strong>{esc(name)}</strong></td>
                    <td style="text-align: center;">{quests}</td>
                    <td style="text-align: center;">{incidents}</td>
                    <td style="text-align: center; color: {'#e74c3c' if penalties < 0 else '#27ae60'};">{penalty_str}</td>
                </tr>
"""
        html += """
            </tbody>
        </table>
"""
    else:
        html += '<div class="empty-state">Нет завершённых задач за неделю.</div>'

    # ── Просрочки ──
    html += f"""
        <h2>⚠️ ПРОСРОЧКИ (вернулись в open)</h2>
"""
    if overdue:
        for tid, desc, worker, start_time in overdue[:10]:
            dt = datetime.fromisoformat(start_time.replace(' ', '+'))
            short_desc = esc(desc)[:60] + "..." if len(esc(desc)) > 60 else esc(desc)
            html += f"""
            <div class="overdue-item">
                <div>
                    <span class="worker">🔴 {esc(worker)}</span>
                    <span style="color: #6c757d; font-size: 13px;">— Квест #{tid}</span>
                    <span style="color: #6c757d; font-size: 13px; float: right;">{dt.strftime('%d.%m %H:%M')}</span>
                </div>
                <div style="font-size: 14px; margin-top: 4px;">{short_desc}</div>
            </div>
"""
        if len(overdue) > 10:
            html += f'<div style="color: #6c757d; text-align: center; margin-top: 10px;">... всего: {len(overdue)} просрочек</div>'
    else:
        html += '<div class="empty-state">✅ Просрочек нет!</div>'

    # ── Карта клиентов ──
    html += f"""
        <h2>📋 ВЫПОЛНЕННЫЕ ЗАДАЧИ <span class="badge">{len(client_map)}</span></h2>
"""
    if client_map:
        by_worker = {}
        for desc, worker, created in client_map:
            by_worker.setdefault(worker, []).append((desc, created))

        for worker, tasks in sorted(by_worker.items()):
            html += f"""
            <div class="worker-group">
                <div style="display: flex; justify-content: space-between; margin-bottom: 8px;">
                    <span class="worker-name">👤 {esc(worker)}</span>
                    <span class="task-count">{len(tasks)} задач(и)</span>
                </div>
"""
            for desc, created in tasks[:5]:
                dt = datetime.fromisoformat(created.replace(' ', '+'))
                short = esc(desc)[:70] + "..." if len(esc(desc)) > 70 else esc(desc)
                html += f"""
                <div class="task-item">
                    <span class="time">{dt.strftime('%d.%m %H:%M')}</span> — {short}
                </div>
"""
            if len(tasks) > 5:
                html += f'<div style="color: #6c757d; font-size: 13px; padding-left: 20px;">... и ещё {len(tasks) - 5}</div>'
            html += '</div>'
    else:
        html += '<div class="empty-state">Нет завершённых задач за неделю.</div>'

    # ── Footer ──
    html += f"""
        <div class="footer">
            📅 Сгенерировано: {datetime.now().strftime('%d.%m.%Y %H:%M')} &nbsp;|&nbsp; 🤖 RPG-AdminQuest Bot
        </div>
    </div>
</body>
</html>
"""
    return html


# ─────────────────────────── main function ───────────────────────────

async def generate_weekly_report(bot=None, chat_id: int = None, ref_date: datetime = None, send_html: bool = True, send_txt: bool = True):
    """
    Генерирует и (если bot+chat_id) отправляет еженедельный отчёт.

    Args:
        bot: aiogram Bot instance (для отправки). None = только генерация.
        chat_id: куда отправить.
        ref_date: дата референса (по умолчанию — сейчас).

    Returns:
        str — текст отчёта.
    """

    # Set default value if None
    if ref_date is None:
        ref_date = datetime.now()  # or datetime.utcnow() depending on your needs

    week_mon, week_sun = _week_range(ref_date - timedelta(days=7))

    logger.info(f"📊 Генерация отчёта за неделю {week_mon.isoformat()} — {week_sun.isoformat()}")

    async with aiosqlite.connect(DB_NAME) as db:
        leaderboard = await get_leaderboard_changes(db, week_mon, week_sun)
        dashboard = await get_engineer_dashboard(db, week_mon, week_sun)
        overdue = await get_overdue_analysis(db, week_mon, week_sun)
        client_map = await get_client_activity_map(db, week_mon, week_sun)

    report_text = None
    html_content = None
    
    if bot and chat_id:
        # ── Текстовая версия ──
        if send_txt:
            report_text = build_weekly_report(week_mon, week_sun, leaderboard, dashboard, overdue, client_map)
            # Разбиваем если длиннее 4096 символов
            max_len = 4096
            if len(report_text) <= max_len:
                await bot.send_message(chat_id, report_text, parse_mode="HTML")
            else:
                parts = [report_text[i:i+max_len] for i in range(0, len(report_text), max_len)]
                for i, part in enumerate(parts):
                    suffix = f"\n\n*(часть {i+1}/{len(parts)})" if len(parts) > 1 else ""
                    await bot.send_message(chat_id, part + suffix, parse_mode="HTML")
            logger.info("✅ Текстовая версия отправлена")
        
        # ── HTML-версия как файл ──
        if send_html:
            html_content = build_weekly_report_html(week_mon, week_sun, leaderboard, dashboard, overdue, client_map)
            try:
                # Создаём директорию для отчётов, если её нет
                reports_dir = Path("reports")
                reports_dir.mkdir(exist_ok=True)
                
                # Формируем имя файла с датами
                file_name = f"weekly_report_{week_mon.strftime('%Y%m%d')}_{week_sun.strftime('%Y%m%d')}.html"
                file_path = reports_dir / file_name
                
                # Сохраняем HTML в файл
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(html_content)
                
                logger.info(f"✅ HTML-файл сохранён: {file_path}")
                
                # Если есть bot и chat_id, отправляем сообщение о сохранении
                if bot and chat_id:
                    await bot.send_message(
                        chat_id,
                        f"✅ HTML-версия отчёта сохранена локально:\n<code>{file_path}</code>",
                        parse_mode="HTML",
                        disable_notification=True
                    )
                    
            except Exception as e:
                logger.error(f"❌ Ошибка при сохранении HTML: {e}", exc_info=True)
                if bot and chat_id:
                    await bot.send_message(
                        chat_id,
                        f"⚠️ Ошибка при сохранении HTML: {e}",
                        disable_notification=True
                    )

    # Если только генерация без отправки
    if not report_text:
        report_text = build_weekly_report(week_mon, week_sun, leaderboard, dashboard, overdue, client_map)
    if not html_content:
        html_content = build_weekly_report_html(week_mon, week_sun, leaderboard, dashboard, overdue, client_map)

    return report_text, html_content


# ─────────────────────────── live dashboard ───────────────────────────

async def get_live_status(db) -> str:
    """
    Текущий статус всех активных пользователей.
    Возвращает строку для /dashboard.
    """
    query = '''
        SELECT
            u.user_id, u.name, u.last_active,
            t.task_id, t.description, t.start_time,
            t.status AS task_status
        FROM users u
        LEFT JOIN tasks t ON u.user_id = t.worker_id AND t.status = 'in_progress'
        WHERE u.agreed_to_tos = 1
        ORDER BY t.start_time DESC NULLS LAST, u.name
    '''
    async with db.execute(query) as cursor:
        rows = await cursor.fetchall()

    now = datetime.now()
    lines = ["🔴 <b>ТЕКУЩИЙ СТАТУС</b>\n"]

    by_user = {}
    for uid, name, last_active, tid, desc, start_time, task_status in rows:
        if name not in by_user:
            by_user[name] = {"task": None, "last_active": last_active}
        if task_status == 'in_progress' and tid:
            by_user[name]["task"] = {"id": tid, "desc": desc, "start": start_time}

    for name, data in by_user.items():
        task = data["task"]
        if task:
            st = datetime.fromisoformat(task["start"].replace(' ', '+'))
            elapsed = (now - st).total_seconds() / 60
            status_emoji = "🟡"
            status_text = f"Квест #{task['id']} ({int(elapsed)} мин)"
            short = task["desc"][:45] + "..." if len(task["desc"]) > 45 else task["desc"]
            lines.append(f"  {status_emoji} <b>{name}</b> — {status_text}")
            lines.append(f"     {short}")
        else:
            lines.append(f"  🟢 <b>{name}</b> — свободен")
        lines.append("")

    return "\n".join(lines)


# ─────────────────────────── CLI entry point ───────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import sys

    chat_id = int(sys.argv[1]) if len(sys.argv) > 1 else None
    report = asyncio.run(generate_weekly_report(chat_id=chat_id))
    if not chat_id:
        print(report)
