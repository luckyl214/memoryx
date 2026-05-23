FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir "uvicorn[standard]" prometheus-client

COPY . .

RUN mkdir -p /app/db /app/logs /app/cache /app/data

EXPOSE 8080

CMD ["uvicorn", "memoryx.api.rest_app:app", "--host", "0.0.0.0", "--port", "8080"]
