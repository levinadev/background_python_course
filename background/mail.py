"""Отправка письма по SMTP.

Локально письма ловит Mailpit, их видно в браузере на http://localhost:8025.
На сервере задайте SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD и SMTP_STARTTLS=1 своего почтового сервиса.
"""
import os
import smtplib
from email.message import EmailMessage

SMTP_HOST = os.environ.get("SMTP_HOST", "localhost")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "1025"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_STARTTLS = os.environ.get("SMTP_STARTTLS", "0") == "1"
MAIL_FROM = os.environ.get("MAIL_FROM", "noreply@example.com")

# Ошибки, после которых письмо стоит отправить ещё раз. Сервер недоступен, обрыв связи или таймаут
MAIL_ERRORS = (smtplib.SMTPException, OSError)


def send_email(to, subject, body):
    message = EmailMessage()
    message["From"] = MAIL_FROM
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as smtp:
        if SMTP_STARTTLS:
            smtp.starttls()
        if SMTP_USER:
            smtp.login(SMTP_USER, SMTP_PASSWORD)
        smtp.send_message(message)
