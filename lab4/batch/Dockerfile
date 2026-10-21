FROM python:3.14.7-slim

WORKDIR /app

COPY batch.py .

ENV SERVICE_NAME=batch
ENV CPU_WORKERS=1
ENV MEM_STEP_MB=10
ENV MEM_INTERVAL_S=5
ENV MEM_MAX_MB=0

CMD ["python3", "-u", "batch.py"]