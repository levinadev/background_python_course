"""Клиент нейросети. Модуль курса "Нейросети в фоновых задачах".

AI_BACKEND=fake (по умолчанию) включает учебную модель. Она отвечает с задержкой и иногда
возвращает 429 с заголовком Retry-After, как настоящие сервисы с лимитом запросов.
AI_BACKEND=ollama включает настоящую модель в Ollama, смотрите compose.ollama.yaml.
Для платного сервиса напишите свою функцию по образцу ask_ollama и вызовите её в ask.
"""
import json
import os
import random
import time
import urllib.error
import urllib.request

BACKEND = os.environ.get("AI_BACKEND", "fake")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:0.6b")
FAIL_RATE = float(os.environ.get("AI_FAIL_RATE", "0.3"))  # доля ответов 429 у учебной модели
DELAY = float(os.environ.get("AI_DELAY", "2"))


class AIBusy(Exception):
    """Сервис перегружен или лимит запросов исчерпан (429, 503). Стоит повторить позже."""

    def __init__(self, message, retry_after=None):
        super().__init__(message)
        self.retry_after = retry_after


class AIError(Exception):
    """Ошибка в самом запросе (400, 404). Повтор не поможет."""


def ask_fake(prompt):
    time.sleep(DELAY)
    if random.random() < FAIL_RATE:
        raise AIBusy("429 Too Many Requests", retry_after=random.randint(5, 20))
    words = len(prompt.split())
    return {"text": f"Пересказ от учебной модели. Запрос из {words} слов обработан.", "tokens": words * 2}


def ask_ollama(prompt, timeout):
    body = json.dumps({"model": MODEL, "prompt": prompt, "stream": False, "think": False}).encode()
    req = urllib.request.Request(f"{OLLAMA_URL}/api/generate", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as exc:
        if exc.code in (429, 503):
            retry_after = exc.headers.get("Retry-After")
            raise AIBusy(f"{exc.code} {exc.reason}", int(retry_after) if retry_after and retry_after.isdigit() else None)
        if 400 <= exc.code < 500:
            raise AIError(f"{exc.code} {exc.read().decode(errors='replace')}")
        raise AIBusy(f"{exc.code} {exc.reason}")
    except (urllib.error.URLError, TimeoutError) as exc:
        raise AIBusy(f"Ollama не ответила, {exc}")
    return {"text": data["response"].strip(),
            "tokens": data.get("prompt_eval_count", 0) + data.get("eval_count", 0)}


def ask(prompt, timeout=100):
    if BACKEND == "ollama":
        return ask_ollama(prompt, timeout)
    return ask_fake(prompt)
