FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=8080
# workers=1 keeps a single writer for SQLite; threads handle concurrency
CMD ["gunicorn", "app:app", "--workers", "1", "--threads", "8", "--bind", "0.0.0.0:8080"]
