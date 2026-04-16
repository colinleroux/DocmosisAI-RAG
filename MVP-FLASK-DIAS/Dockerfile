FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY static ./static

EXPOSE 8081

CMD ["gunicorn", "-b", "0.0.0.0:8081", "--workers", "1", "--timeout", "1800", "app:app"]
