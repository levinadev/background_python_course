"""Защита от повторного выполнения. Этот файл можно перенести в свой проект как есть.

Модули курса "Ошибки, повторы и надёжность" и "Периодические задачи".
"""
import functools
import logging

import redis

from background.celery_app import REDIS_URL

logger = logging.getLogger(__name__)
store = redis.Redis.from_url(f"{REDIS_URL}/2", decode_responses=True)

FREE, BUSY, DONE = "free", "busy", "done"


def claim(key, ttl=10 * 60):
    """Занимает действие с ключом key.

    FREE, ключ свободен и теперь занят нами, действие можно выполнять.
    DONE, действие уже выполнено, повторять не нужно.
    BUSY, его выполняет другая копия задачи или она упала посередине.
    Занятый ключ сам освободится через ttl секунд, так что повтор задачи потом сможет его занять.
    """
    # SET NX проверяет и записывает за одну команду, две копии не займут ключ одновременно
    if store.set(key, "running", nx=True, ex=ttl):
        return FREE
    return DONE if store.get(key) == "done" else BUSY


def finish(key, ttl=24 * 60 * 60):
    """Отмечает действие выполненным. Повторы в течение ttl секунд его пропустят."""
    store.set(key, "done", ex=ttl)


def release(key):
    """Освобождает ключ после неудачи, чтобы следующая попытка смогла его занять."""
    store.delete(key)


def single_run(name, timeout=10 * 60):
    """Декоратор для периодических задач. Если задача с этим именем уже идёт, вторая копия ничего не делает.

    Ставится под @app.task. timeout должен быть больше самого долгого выполнения задачи.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            lock = store.lock(f"lock:{name}", timeout=timeout, blocking=False)
            if not lock.acquire():
                logger.info("%s уже выполняется в другом воркере", name)
                return None
            try:
                return func(*args, **kwargs)
            finally:
                try:
                    lock.release()
                except redis.exceptions.LockError:
                    logger.warning("Замок %s истёк раньше, чем закончилась задача", name)
        return wrapper
    return decorator
