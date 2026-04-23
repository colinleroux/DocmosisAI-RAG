FROM node:20-slim AS frontend-builder

WORKDIR /frontend

COPY frontend/package*.json ./
RUN npm install

COPY frontend/ ./
RUN npm run build


FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY dais_app ./dais_app

# Copy built frontend bundle into Flask static directory.
COPY --from=frontend-builder /frontend/dist ./dais_app/static/dist

EXPOSE 8081

CMD ["gunicorn", "-b", "0.0.0.0:8081", "--workers", "1", "--timeout", "1800", "app:app"]
