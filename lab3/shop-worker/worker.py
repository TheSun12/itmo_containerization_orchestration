import json
import os
import time
import signal
import logging
import sys

import psycopg
from psycopg.rows import dict_row


# ── Config ──────────────────────────────────────────────────────────────
SERVICE_NAME    = os.getenv("SERVICE_NAME", "shop-worker")
WORKER_INTERVAL = int(os.getenv("WORKER_INTERVAL", "5"))
BATCH_SIZE      = int(os.getenv("WORKER_BATCH_SIZE", "10"))

DB_HOST         = os.getenv("DB_HOST", "shop-postgres-rw")
DB_PORT         = int(os.getenv("DB_PORT", "5432"))
DB_NAME         = os.getenv("DB_NAME", "shop")
DB_USER         = os.getenv("DB_USER", "shop")
DB_PASSWORD     = os.getenv("DB_PASSWORD", "")


# ── Logging: JSON ───────────────────────────────────────────────────────
class JSONFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "level":     record.levelname,
            "message":   record.getMessage(),
            "service":   SERVICE_NAME,
        })


logger = logging.getLogger("shop-worker")
logger.setLevel(logging.INFO)
logger.propagate = False
handler = logging.StreamHandler()
handler.setFormatter(JSONFormatter())
logger.addHandler(handler)


# ── БД ──────────────────────────────────────────────────────────────────
def get_conn():
    return psycopg.connect(
        host=DB_HOST, port=DB_PORT,
        dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD,
        row_factory=dict_row,
        connect_timeout=5,
    )


def process_batch() -> int:
    """Обработать одну пачку pending-заказов. Возвращает количество обработанных."""
    with get_conn() as conn, conn.cursor() as cur:
        # SELECT ... FOR UPDATE SKIP LOCKED — атомарный захват пачки,
        # чтобы несколько реплик worker не брали одни и те же заказы.
        cur.execute(
            """
            WITH batch AS (
                SELECT id FROM orders
                WHERE status = 'pending'
                ORDER BY id
                LIMIT %s
                FOR UPDATE SKIP LOCKED
            )
            UPDATE orders o
            SET status = 'processed', processed_at = NOW()
            FROM batch
            WHERE o.id = batch.id
            RETURNING o.id
            """,
            (BATCH_SIZE,),
        )
        rows = cur.fetchall()
        conn.commit()
    return len(rows)


def wait_for_db(retries: int = 30, delay: float = 2.0) -> bool:
    for attempt in range(1, retries + 1):
        try:
            with get_conn() as conn:
                conn.execute("SELECT 1")
            logger.info("db ready")
            return True
        except Exception as e:
            logger.warning(f"wait_for_db attempt {attempt}/{retries}: {e}")
            time.sleep(delay)
    return False


# ── Main loop ───────────────────────────────────────────────────────────
shutdown = False

def handle_sigterm(signum, frame):
    global shutdown
    shutdown = True
    logger.info("received SIGTERM, shutting down gracefully")

signal.signal(signal.SIGTERM, handle_sigterm)
signal.signal(signal.SIGINT, handle_sigterm)


def main():
    if os.getenv("STARTUP_DB_CHECK", "true").lower() == "true":
        if not wait_for_db():
            logger.error("db not reachable, exiting")
            sys.exit(1)
    else:
        logger.info("STARTUP_DB_CHECK == false - skipping schema init (running without DB)")

    logger.info(f"worker started, interval={WORKER_INTERVAL}s, batch={BATCH_SIZE}")
    while not shutdown:
        try:
            n = process_batch()
            if n:
                logger.info(f"processed {n} orders")
        except Exception as e:
            logger.exception(f"process_batch failed: {e}")
        # спим интервалами по 1 сек, чтобы быстро реагировать на SIGTERM
        for _ in range(WORKER_INTERVAL):
            if shutdown:
                break
            time.sleep(1)

    logger.info("worker stopped")


if __name__ == "__main__":
    main()