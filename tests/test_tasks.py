"""Тесты задач без Redis, брокера и почтового сервера.

Запуск в контейнере
    docker compose run --rm --no-deps web pytest -q
"""
import json
import os
import smtplib
import time

import pytest
from celery.exceptions import Retry

from background import once, tasks


class FakeStore:
    """Заменяет Redis в тестах, только те команды, которые нужны модулю once."""

    def __init__(self):
        self.data = {}

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.data:
            return None
        self.data[key] = value
        return True

    def get(self, key):
        return self.data.get(key)

    def delete(self, key):
        self.data.pop(key, None)


@pytest.fixture
def store(monkeypatch):
    fake = FakeStore()
    monkeypatch.setattr(once, "store", fake)
    return fake


@pytest.fixture
def outbox(monkeypatch):
    sent = []
    monkeypatch.setattr(tasks, "send_email", lambda to, subject, body: sent.append(to))
    return sent


def test_email_is_sent_only_once(store, outbox):
    assert tasks.send_email_once("m1", "user@example.com", "Тема", "Текст") == "sent"
    assert tasks.send_email_once("m1", "user@example.com", "Тема", "Текст") == "skipped"
    assert outbox == ["user@example.com"]


def test_email_waits_while_other_copy_is_sending(store, outbox):
    store.set("email:m1", "running")
    with pytest.raises(Retry):
        tasks.send_email_once("m1", "user@example.com", "Тема", "Текст")
    assert outbox == []


def test_email_frees_key_when_mail_server_fails(store, monkeypatch):
    def broken(to, subject, body):
        raise smtplib.SMTPServerDisconnected("почтовый сервер недоступен")

    monkeypatch.setattr(tasks, "send_email", broken)
    with pytest.raises(smtplib.SMTPServerDisconnected):
        tasks.send_email_once("m1", "user@example.com", "Тема", "Текст")
    assert store.get("email:m1") is None


def test_build_report_writes_file(tmp_path, monkeypatch):
    monkeypatch.setattr(tasks, "OUTPUT", tmp_path)
    result = tasks.build_report.apply(args=("r1",), kwargs={"seconds": 0})
    assert result.get() == {"id": "r1", "file": "r1.json"}
    assert json.loads((tmp_path / "r1.json").read_text(encoding="utf-8"))["id"] == "r1"


def test_cleanup_removes_only_old_files(tmp_path, monkeypatch):
    monkeypatch.setattr(tasks, "OUTPUT", tmp_path)

    class FreeLock:
        def acquire(self):
            return True

        def release(self):
            pass

    monkeypatch.setattr(once.store, "lock", lambda *args, **kwargs: FreeLock())
    old, new = tmp_path / "old.json", tmp_path / "new.json"
    old.write_text("{}")
    new.write_text("{}")
    week_ago = time.time() - 8 * 24 * 60 * 60
    os.utime(old, (week_ago, week_ago))
    assert tasks.cleanup() == 1
    assert not old.exists() and new.exists()


def test_cleanup_skips_when_already_running(tmp_path, monkeypatch):
    monkeypatch.setattr(tasks, "OUTPUT", tmp_path)

    class BusyLock:
        def acquire(self):
            return False

    monkeypatch.setattr(once.store, "lock", lambda *args, **kwargs: BusyLock())
    assert tasks.cleanup() is None


@pytest.fixture
def report(tmp_path, monkeypatch):
    monkeypatch.setattr(tasks, "OUTPUT", tmp_path)
    (tmp_path / "r1.json").write_text('{"id": "r1"}', encoding="utf-8")
    return {"id": "r1", "file": "r1.json"}


def test_second_summary_comes_from_cache(store, report, monkeypatch):
    calls = []
    monkeypatch.setattr(tasks.ai, "ask", lambda prompt: calls.append(prompt) or {"text": "пересказ", "tokens": 10})
    assert tasks.summarize_report(report)["summary"] == "пересказ"
    assert tasks.summarize_report(report)["summary"] == "пересказ"
    assert len(calls) == 1


def test_busy_model_retries_after_pause_from_service(store, report, monkeypatch):
    def busy(prompt):
        raise tasks.ai.AIBusy("429 Too Many Requests", retry_after=7)

    monkeypatch.setattr(tasks.ai, "ask", busy)
    pauses = []
    monkeypatch.setattr(tasks.summarize_report, "retry",
                        lambda exc, countdown: pauses.append(countdown) or Retry())
    with pytest.raises(Retry):
        tasks.summarize_report(report)
    assert pauses == [7]
