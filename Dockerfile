FROM python:3.11-slim

WORKDIR /app

# Instalar dependencias del sistema requeridas
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    ca-certificates \
    libpq-dev \
    && rm -rf /var/lib/apt-get/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Variables de entorno por defecto
ENV PORT=8001
EXPOSE 8001

CMD ["sh", "-c", "arq app.worker.WorkerSettings & uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8001}"]
