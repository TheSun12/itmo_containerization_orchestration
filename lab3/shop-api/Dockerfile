FROM python:3.14.7-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY api.py .

EXPOSE 8080

ENV PORT=8080
ENV DB_HOST=shop-postgres-rw
ENV DB_PORT=5432
ENV DB_NAME=shop
ENV DB_USER=shop
ENV HEALTH_FAIL=false

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "--access-logfile", "-", "api:app"]