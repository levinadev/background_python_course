FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

# Воркер не работает от root
RUN useradd --create-home app && mkdir -p /app/output && chown app /app/output
USER app
