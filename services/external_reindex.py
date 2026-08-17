import asyncio
import logging
import shlex
import os
from config import GROUP_ID, DB_NAME, EMBEDDING_PYTHON

logger = logging.getLogger(__name__)


async def _run_subprocess(cmd, cwd=None):
    """Run subprocess and capture stdout/stderr asynchronously."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd
    )
    stdout, stderr = await proc.communicate()
    out = stdout.decode(errors='replace') if stdout else ''
    err = stderr.decode(errors='replace') if stderr else ''
    return proc.returncode, out, err


async def run_reindex_external(bot=None, notify_chat_id=None, python_exe=None):
    """Run scripts/reindex_wiki.py using external python executable (embedding venv).
    If bot and notify_chat_id provided, sends start/finish messages.
    Returns a dict: {"rc": int, "stdout": str, "stderr": str}
    """
    python_exe = EMBEDDING_PYTHON
    if not python_exe or not os.path.exists(python_exe):
        msg = f"Embedding python not found: {python_exe}"
        logger.error(msg)
        if bot and notify_chat_id:
            try:
                await bot.send_message(notify_chat_id, f"❌ {msg}")
            except: pass
        return {"rc": -1, "stdout": "", "stderr": msg}

    script = os.path.join(os.getcwd(), 'Desktop', 'python project', 'uralaiti_gamebot_rpg', 'scripts', 'reindex_wiki.py')
    if not os.path.exists(script):
        msg = f"reindex script not found: {script}"
        logger.error(msg)
        if bot and notify_chat_id:
            try:
                await bot.send_message(notify_chat_id, f"❌ {msg}")
            except: pass
        return {"rc": -1, "stdout": "", "stderr": msg}

    if bot and notify_chat_id:
        try:
            await bot.send_message(notify_chat_id, "⏳ Запускаю внешнюю переиндексацию Wiki (в отдельном venv)...")
        except: pass

    cmd = [python_exe, script]
    logger.info(f"Running external reindex: {cmd}")
    rc, out, err = await _run_subprocess(cmd, cwd=os.getcwd())

    logger.info(f"External reindex finished rc={rc}")
    logger.debug("stdout:\n%s", out)
    logger.debug("stderr:\n%s", err)

    # try to parse standard result line printed by scripts/reindex_wiki.py or check_embeddings
    # scripts/reindex_wiki.py prints logs; scripts/check_embeddings can be used to verify separately
    if bot and notify_chat_id:
        try:
            if rc == 0:
                # attempt to find summary in stdout
                summary = None
                for line in out.splitlines()[::-1]:
                    if 'Reindex finished' in line or 'Reindex finished' in line:
                        summary = line
                        break
                if not summary:
                    # fallback: send brief success
                    await bot.send_message(notify_chat_id, "✅ Внешняя переиндексация завершена (см логи).")
                else:
                    await bot.send_message(notify_chat_id, f"✅ {summary}")
            else:
                await bot.send_message(notify_chat_id, f"❌ Внешняя переиндексация завершилась с ошибкой (rc={rc}). См логи.")
        except Exception:
            pass

    return {"rc": rc, "stdout": out, "stderr": err}


async def run_reindex_job(bot):
    """Helper scheduled job for APScheduler: runs external reindex and notifies GROUP_ID."""
    await run_reindex_external(bot=bot, notify_chat_id=GROUP_ID)
