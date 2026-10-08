import json
import time
import random
import logging
import os
from concurrent.futures import ThreadPoolExecutor

import requests
from flask import Flask, Response, request
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.instrumentation.flask import FlaskInstrumentor

# ── Config ──────────────────────────────────────────────────────────────
# gRPC endpoint — Jaeger all-in-one слушает 4317 из коробки
OTEL_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "jaeger:4317")
SERVICE_NAME  = os.getenv("OTEL_SERVICE_NAME", "api")
SERVICE_PORT  = int(os.getenv("PORT", "8080"))
SELF_URL      = os.getenv("SELF_URL", f"http://localhost:{SERVICE_PORT}")

# ── OpenTelemetry setup ─────────────────────────────────────────────────
resource = Resource.create({"service.name": SERVICE_NAME})
provider = TracerProvider(resource=resource)
provider.add_span_processor(
    BatchSpanProcessor(
        OTLPSpanExporter(endpoint=OTEL_ENDPOINT, insecure=True)
    )
)
trace.set_tracer_provider(provider)
tracer = trace.get_tracer(__name__)

# ── Logging (structured JSON with trace_id) ─────────────────────────────
class JSONFormatter(logging.Formatter):
    def format(self, record):
        span = trace.get_current_span()
        ctx = span.get_span_context()
        trace_id = f"{ctx.trace_id:032x}" if ctx and ctx.is_valid else "-"
        span_id  = f"{ctx.span_id:016x}"  if ctx and ctx.is_valid else "-"

        # request доступен только внутри контекста запроса — защищаемся
        try:
            path   = request.path
            method = request.method
        except RuntimeError:
            path, method = "-", "-"

        log_entry = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "level":     record.levelname,
            "message":   record.getMessage(),
            "trace_id":  trace_id,
            "span_id":   span_id,
            "service":   SERVICE_NAME,
            "path":      path,
            "method":    method,
        }
        return json.dumps(log_entry)

logger = logging.getLogger("api")
logger.setLevel(logging.INFO)
logger.propagate = False  # не дублировать в root logger
handler = logging.StreamHandler()
handler.setFormatter(JSONFormatter())
logger.addHandler(handler)

# ── Flask app ────────────────────────────────────────────────────────────
app = Flask(__name__)
FlaskInstrumentor().instrument_app(app)

# ── Prometheus metrics ──────────────────────────────────────────────────
REQUEST_COUNT = Counter(
    "api_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"],
)
ERROR_COUNT = Counter(
    "api_errors_total",
    "Total 5xx errors",
    ["endpoint"],
)
REQUEST_LATENCY = Histogram(
    "api_request_duration_seconds",
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
    # request.path — реальный путь (/health, /fail, ...), не имя функции
    endpoint = request.path
    REQUEST_COUNT.labels(request.method, endpoint, resp.status_code).inc()
    REQUEST_LATENCY.labels(endpoint).observe(latency)
    if resp.status_code >= 500:
        ERROR_COUNT.labels(endpoint).inc()
    return resp


# ── Endpoints ────────────────────────────────────────────────────────────
@app.route("/health")
def health():
    logger.info("health check ok")
    return Response("ok", status=200, mimetype="text/plain")


@app.route("/fail")
def fail():
    """Return 500 and mark the span as error."""
    span = trace.get_current_span()
    span.set_status(trace.Status(trace.StatusCode.ERROR, "intentional failure"))
    span.record_exception(ValueError("intentional 500"))
    logger.error("intentional failure on /fail")
    return Response("internal server error", status=500, mimetype="text/plain")


@app.route("/slow")
def slow():
    """Sleep 1–3 s, wrapped in a child span so Jaeger waterfall shows it."""
    delay = random.uniform(1, 3)
    with tracer.start_as_current_span("slow-op") as child:
        child.set_attribute("delay_seconds", delay)
        logger.info(f"sleeping for {delay:.2f}s")
        time.sleep(delay)
    logger.info("slow request completed")
    return Response(f"slept {delay:.2f}s", status=200, mimetype="text/plain")


@app.route("/load")
def load():
    """Fire a burst of internal requests to spike RPS (parallel)."""
    count = int(request.args.get("n", "20"))
    logger.info(f"generating {count} internal requests")

    paths = [random.choice(["/health", "/slow", "/fail"]) for _ in range(count)]

    def fetch(path):
        try:
            r = requests.get(f"{SELF_URL}{path}", timeout=10)
            return r.status_code
        except Exception:
            return 0

    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(fetch, paths))

    ok = sum(1 for c in results if c == 200)
    return Response(
        json.dumps({"total": count, "ok": ok, "statuses": results}),
        status=200,
        mimetype="application/json",
    )


@app.route("/metrics")
def metrics():
    return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=SERVICE_PORT)