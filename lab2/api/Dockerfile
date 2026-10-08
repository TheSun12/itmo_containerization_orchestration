FROM python:3.14.7-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY api.py .

EXPOSE 8080

ENV OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeder:4317
ENV SELF_URL=http://api:8080
ENV PORT=8080

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "4", "api:app"]