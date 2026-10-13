import json
import os
import time
import logging
import threading
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

from flask import Flask, Response, request
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.instrumentation.flask import FlaskInstrumentor


# ── Config ──────────────────────────────────────────────────────────────
OTEL_ENDPOINT   = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")   # пустой = OTel не шлём
SERVICE_NAME    = os.getenv("OTEL_SERVICE_NAME", "shop-api")
SERVICE_PORT    = int(os.getenv("PORT", "8080"))

DB_HOST         = os.getenv("DB_HOST", "shop-postgres-rw")
DB_PORT         = int(os.getenv("DB_PORT", "5432"))
DB_NAME         = os.getenv("DB_NAME", "shop")
DB_USER         = os.getenv("DB_USER", "shop")
DB_PASSWORD     = os.getenv("DB_PASSWORD", "")

HEALTH_FAIL     = os.getenv("HEALTH_FAIL", "false").lower() == "true"


# ── OpenTelemetry (опционально) ─────────────────────────────────────────
resource = Resource.create({"service.name": SERVICE_NAME})
provider = TracerProvider(resource=resource)

if OTEL_ENDPOINT:
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=OTEL_ENDPOINT, insecure=True))
    )

trace.set_tracer_provider(provider)
tracer = trace.get_tracer(__name__)


# ── Logging: JSON с trace_id ────────────────────────────────────────────
class JSONFormatter(logging.Formatter):
    def format(self, record):
        span = trace.get_current_span()
        ctx = span.get_span_context()
        trace_id = f"{ctx.trace_id:032x}" if ctx and ctx.is_valid else "-"
        span_id  = f"{ctx.span_id:016x}"  if ctx and ctx.is_valid else "-"

        try:
            path   = request.path
            method = request.method
        except RuntimeError:
            path, method = "-", "-"

        return json.dumps({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "level":     record.levelname,
            "message":   record.getMessage(),
            "trace_id":  trace_id,
            "span_id":   span_id,
            "service":   SERVICE_NAME,
            "path":      path,
            "method":    method,
        })


logger = logging.getLogger("shop-api")
logger.setLevel(logging.INFO)
logger.propagate = False
handler = logging.StreamHandler()
handler.setFormatter(JSONFormatter())
logger.addHandler(handler)


# ── Flask ───────────────────────────────────────────────────────────────
app = Flask(__name__)
FlaskInstrumentor().instrument_app(app)


# ── Prometheus metrics (RED) ────────────────────────────────────────────
REQUEST_COUNT = Counter(
    "shop_api_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"],
)
ERROR_COUNT = Counter(
    "shop_api_errors_total",
    "Total 5xx errors",
    ["endpoint"],
)
REQUEST_LATENCY = Histogram(
    "shop_api_request_duration_seconds",
    "Request latency in seconds",
    ["endpoint"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10],
)


@app.before_request
def before():
    request._start_time = time.time()


@app.after_request
def after(resp):
    latency = time.time() - getattr(request, "_start_time", time.time())
    endpoint = request.path
    REQUEST_COUNT.labels(request.method, endpoint, resp.status_code).inc()
    REQUEST_LATENCY.labels(endpoint).observe(latency)
    if resp.status_code >= 500:
        ERROR_COUNT.labels(endpoint).inc()
    return resp


# ── Работа с БД ─────────────────────────────────────────────────────────
def get_conn():
    """Открыть новое соединение с БД (на каждый запрос — свой)."""
    return psycopg.connect(
        host=DB_HOST, port=DB_PORT,
        dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD,
        row_factory=dict_row,
        connect_timeout=5,
    )


def init_schema(retries: int = 30, delay: float = 2.0):
    """Создать таблицу orders. Пробуем несколько раз — БД может ещё не подняться."""
    ddl = """
    CREATE TABLE IF NOT EXISTS orders (
        id           SERIAL PRIMARY KEY,
        item         TEXT NOT NULL,
        status       TEXT NOT NULL DEFAULT 'pending',
        created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        processed_at TIMESTAMPTZ
    );
    """
    for attempt in range(1, retries + 1):
        try:
            with get_conn() as conn, conn.cursor() as cur:
                cur.execute(ddl)
                conn.commit()
            logger.info("schema ready")
            return
        except Exception as e:
            logger.warning(f"schema init attempt {attempt}/{retries} failed: {e}")
            time.sleep(delay)
    raise RuntimeError("could not init schema")


# ── Endpoints ───────────────────────────────────────────────────────────
@app.route("/health")
def health():
    if HEALTH_FAIL:
        logger.error("health check failing (HEALTH_FAIL=true)")
        return Response("unhealthy", status=500, mimetype="text/plain")
    logger.info("health check ok")
    return Response("ok", status=200, mimetype="text/plain")


@app.route("/order", methods=["POST"])
def create_order():
    payload = request.get_json(silent=True) or {}
    item = payload.get("item")
    if not item:
        return Response(
            json.dumps({"error": "field 'item' is required"}),
            status=400, mimetype="application/json",
        )

    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO orders (item) VALUES (%s) RETURNING id, item, status, created_at",
                (item,),
            )
            row = cur.fetchone()
            conn.commit()
        logger.info(f"order created id={row['id']} item={item!r}")
        return Response(
            json.dumps({
                "id": row["id"],
                "item": row["item"],
                "status": row["status"],
                "created_at": row["created_at"].isoformat(),
            }),
            status=201, mimetype="application/json",
        )
    except Exception as e:
        logger.exception(f"failed to create order: {e}")
        return Response(
            json.dumps({"error": "internal error"}),
            status=500, mimetype="application/json",
        )


@app.route("/orders", methods=["GET"])
def list_orders():
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT id, item, status, created_at, processed_at FROM orders ORDER BY id DESC LIMIT 100")
            rows = cur.fetchall()
        # datetime → isoformat для JSON
        out = [{
            "id": r["id"],
            "item": r["item"],
            "status": r["status"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "processed_at": r["processed_at"].isoformat() if r["processed_at"] else None,
        } for r in rows]
        return Response(json.dumps({"orders": out, "count": len(out)}),
                        status=200, mimetype="application/json")
    except Exception as e:
        logger.exception(f"failed to list orders: {e}")
        return Response(
            json.dumps({"error": "internal error"}),
            status=500, mimetype="application/json",
        )


@app.route("/metrics")
def metrics():
    return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)

if os.getenv("STARTUP_DB_CHECK", "true").lower() == "true":
    try:
        init_schema(retries=30, delay=2.0)
    except Exception as e:
        logger.error(f"schema init failed permanently: {e}")
else:
    logger.info("STARTUP_DB_CHECK == false - skipping schema init (running without DB)")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=SERVICE_PORT)