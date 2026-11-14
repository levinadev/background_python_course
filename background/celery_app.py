"""Приложение Celery и настройки, с которыми задачи не теряются и не выполняются дважды.

Рядом с настройками написано, в каком модуле курса они разобраны.
"""
import os

from celery import Celery
from celery.schedules import crontab

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
# Брокер можно сменить на RabbitMQ одной переменной, модуль "Redis или RabbitMQ", Redis останется для результатов
BROKER_URL = os.environ.get("BROKER_URL", f"{REDIS_URL}/0")

app = Celery(
    "background",
    broker=BROKER_URL,
    backend=f"{REDIS_URL}/1",  # результаты в отдельной базе Redis, данные приложения в базе 2
    include=["background.tasks"],
)

app.conf.update(
    timezone=os.environ.get("CELERY_TIMEZONE", "Europe/Moscow"),
    # Модуль "Первая задача"
    task_track_started=True,  # кроме PENDING и SUCCESS видно STARTED
    result_expires=60 * 60 * 24,  # результаты живут сутки, Redis не разрастается
    # Модуль "Ошибки, повторы и надёжность"
    task_acks_late=True,  # подтверждение после выполнения, упавшая задача вернётся в очередь
    task_reject_on_worker_lost=True,  # то же, если процесс-исполнитель убит
    broker_transport_options={
        # Через сколько неподтверждённая задача вернётся в очередь при Redis.
        # Должно быть больше самой долгой задачи, иначе её выполнит второй воркер
        "visibility_timeout": 60 * 60,
    },
    task_soft_time_limit=5 * 60,  # общий предохранитель от зависших задач,
    task_time_limit=6 * 60,  # у долгих задач лимиты задаются отдельно
    # Модуль "Воркеры, очереди и масштабирование"
    worker_prefetch_multiplier=1,  # воркер не набирает задач впрок, длинные не задерживают короткие
    task_default_queue="default",
    task_routes={
        "background.tasks.build_report": {"queue": "heavy"},
        # Модуль "Нейросети в фоновых задачах". Медленные платные запросы не занимают общие воркеры
        "background.tasks.summarize_report": {"queue": "ai"},
        "background.tasks.*": {"queue": "default"},
    },
    broker_connection_retry_on_startup=True,  # воркер дождётся брокера при старте
    # Модуль "Периодические задачи". Celery beat запускается ровно в одном экземпляре
    beat_schedule={
        "cleanup-every-night": {
            "task": "background.tasks.cleanup",
            "schedule": crontab(minute=0, hour=3),
        },
    },
)

if BROKER_URL.startswith("amqp"):
    app.conf.update(
        # RabbitMQ 4 не разрешает временные неэксклюзивные очереди,
        # а именно такие Celery по умолчанию создаёт для служебных сообщений
        control_queue_exclusive=True,
        event_queue_exclusive=True,
    )
