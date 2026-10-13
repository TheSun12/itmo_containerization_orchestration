FROM python:3.14.7-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY worker.py .

ENV WORKER_INTERVAL=5
ENV WORKER_BATCH_SIZE=10
ENV DB_HOST=shop-postgres-rw
ENV DB_PORT=5432
ENV DB_NAME=shop
ENV DB_USER=shop

CMD ["python3", "-u", "worker.py"]