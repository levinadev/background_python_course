"""Веб-часть на Flask. Запрос сразу получает id задачи, а работа идёт в фоне.

Модуль курса "Celery в веб-приложении и тесты". Для Django смотрите README.
"""
import uuid

from celery import chain
from celery.result import AsyncResult
from flask import Flask, jsonify, request

from background.celery_app import app as celery_app
from background.tasks import build_report, send_email_once, summarize_report

app = Flask(__name__)
app.json.ensure_ascii = False  # кириллица в ответах без \uXXXX


@app.post("/emails")
def create_email():
    data = request.get_json(silent=True) or {}
    to = data.get("to", "")
    if "@" not in to:
        return jsonify(error="нужно поле to с адресом"), 400
    # id письма создаётся один раз здесь, поэтому повтор задачи не отправит второе письмо
    message_id = data.get("message_id") or str(uuid.uuid4())
    result = send_email_once.delay(message_id, to, data.get("subject", "Привет"), data.get("body", "Письмо из фоновой задачи"))
    return jsonify(task_id=result.id, message_id=message_id), 202


@app.post("/reports")
def create_report():
    report_id = str(uuid.uuid4())
    result = build_report.delay(report_id)
    return jsonify(task_id=result.id, report_id=report_id), 202


@app.post("/reports/summary")
def create_report_with_summary():
    # Модуль "Цепочки и группы задач". Результат build_report сам уходит первым аргументом в summarize_report,
    # и каждая задача идёт в свою очередь, отчёт в heavy, пересказ в ai
    report_id = str(uuid.uuid4())
    result = chain(build_report.s(report_id), summarize_report.s()).apply_async()
    return jsonify(task_id=result.id, report_task_id=result.parent.id, report_id=report_id), 202


@app.get("/tasks/<task_id>")
def task_status(task_id):
    # id задачи не секрет, в настоящем проекте проверяйте, что пользователь имеет право видеть результат
    result = AsyncResult(task_id, app=celery_app)
    body = {"task_id": task_id, "state": result.state}
    if result.successful():
        body["result"] = result.result
    elif result.failed():
        body["error"] = str(result.result)
    return jsonify(body)


@app.get("/health")
def health():
    return jsonify(status="ok")
