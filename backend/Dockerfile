# Backend image. Build context is the PROJECT ROOT (see docker-compose.yml) so
# the `backend` package and requirements.txt are both available and imports use
# the `backend.*` namespace, matching the test suite.
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend ./backend

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "backend.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
