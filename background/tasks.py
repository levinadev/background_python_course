"""Образцы задач. Скопируйте подходящий и замените тело на свою работу.

В задачи передавайте id и простые значения (строки, числа, списки, словари), а не объекты ORM:
аргументы превращаются в JSON, а объект к моменту выполнения мог уже измениться.
"""
import hashlib
import json
import os
import time
import urllib.request
from pathlib import Path

from celery.exceptions import SoftTimeLimitExceeded
from celery.utils.log import get_task_logger

from background import ai, once
from background.celery_app import app
from background.mail import MAIL_ERRORS, send_email

logger = get_task_logger(__name__)
OUTPUT = Path(os.environ.get("OUTPUT_DIR", "output"))
KEEP_DAYS = 7


# 1. Запрос во внешний сервис, который иногда не отвечает.
# Повторы с растущей случайной паузой, чтобы тысяча упавших задач не повторилась одновременно
@app.task(
    autoretry_for=(OSError,),  # сюда входят URLError, обрыв связи и таймаут
    retry_backoff=2,  # пауза 2, 4, 8, 16 секунд
    retry_backoff_max=60,
    retry_jitter=True,
    max_retries=5,
)
def fetch_json(url):
    with urllib.request.urlopen(url, timeout=10) as response:
        return json.loads(response.read())


# 2. Письмо, которое должно уйти один раз, даже если задача повторилась или запущена дважды
@app.task(bind=True, max_retries=5, default_retry_delay=60)
def send_email_once(self, message_id, to, subject, body):
    key = f"email:{message_id}"
    state = once.claim(key)
    if state == once.DONE:
        logger.info("Письмо %s уже отправлено", message_id)
        return "skipped"
    if state == once.BUSY:
        raise self.retry()  # другая копия отправляет прямо сейчас или упала, проверим позже
    try:
        send_email(to, subject, body)
    except MAIL_ERRORS as exc:
        once.release(key)
        raise self.retry(exc=exc)  # почтовый сервер недоступен, повторим через минуту
    once.finish(key)
    logger.info("Письмо %s отправлено", message_id)
    return "sent"


# 3. Долгая работа. Отдельная очередь heavy и свои лимиты времени
@app.task(bind=True, soft_time_limit=10 * 60, time_limit=11 * 60)
def build_report(self, report_id, seconds=3):
    path = OUTPUT / f"{report_id}.json"
    try:
        time.sleep(seconds)  # здесь ваша долгая работа
        OUTPUT.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"id": report_id, "task_id": self.request.id}), encoding="utf-8")
    except SoftTimeLimitExceeded:
        path.unlink(missing_ok=True)  # мягкий лимит даёт время убрать недоделанный результат
        raise
    return {"id": report_id, "file": path.name}


# 4. Периодическая задача. Если прошлый запуск ещё идёт, новый ничего не делает
@app.task
@once.single_run("cleanup", timeout=30 * 60)
def cleanup():
    border = time.time() - KEEP_DAYS * 24 * 60 * 60
    removed = 0
    for path in OUTPUT.glob("*.json"):
        if path.stat().st_mtime < border:
            path.unlink()
            removed += 1
    logger.info("Удалено старых файлов: %s", removed)
    return removed


# 5. Запрос к нейросети. Своя очередь ai, лимит запросов, пауза из Retry-After и кэш ответов.
# Получает результат build_report, поэтому её удобно ставить в цепочку после отчёта, смотрите web.py
@app.task(bind=True, max_retries=5, rate_limit="10/m", soft_time_limit=120, time_limit=150)
def summarize_report(self, report):
    text = (OUTPUT / report["file"]).read_text(encoding="utf-8")
    prompt = f"Перескажи отчёт в двух предложениях. {text}"
    # одинаковый запрос даёт одинаковый ответ, второй раз за него не платим
    key = "summary:" + hashlib.sha256(prompt.encode()).hexdigest()
    cached = once.store.get(key)
    if cached:
        logger.info("Пересказ отчёта %s взят из кэша", report["id"])
        return {"id": report["id"], "summary": cached}
    try:
        answer = ai.ask(prompt)
    except (ai.AIBusy, SoftTimeLimitExceeded) as exc:
        if self.request.retries >= self.max_retries:
            logger.warning("Модель так и не ответила, отчёт %s остаётся без пересказа", report["id"])
            return {"id": report["id"], "summary": None}
        # пауза, которую назвал сервис, а если не назвал, то растущая
        countdown = getattr(exc, "retry_after", None) or min(60, 5 * 2 ** self.request.retries)
        raise self.retry(exc=exc, countdown=countdown)
    once.store.set(key, answer["text"], ex=7 * 24 * 60 * 60)
    logger.info("Пересказ отчёта %s готов, токенов %s", report["id"], answer["tokens"])
    return {"id": report["id"], "summary": answer["text"]}
