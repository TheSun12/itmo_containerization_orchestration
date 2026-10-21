import os
import time
import logging
import json
import sys
import threading

# ── Config ──────────────────────────────────────────────────────────────
SERVICE_NAME    = os.getenv("SERVICE_NAME", "batch")
CPU_WORKERS     = int(os.getenv("CPU_WORKERS", "1"))         # сколько потоков жрут CPU
MEM_STEP_MB     = int(os.getenv("MEM_STEP_MB", "10"))        # сколько МБ за раз
MEM_INTERVAL_S  = float(os.getenv("MEM_INTERVAL_S", "5"))    # как часто
MEM_MAX_MB      = int(os.getenv("MEM_MAX_MB", "0"))          # 0 = без лимита, иначе не расти выше


# ── Logging ─────────────────────────────────────────────────────────────
class JSONFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "level":     record.levelname,
            "message":   record.getMessage(),
            "service":   SERVICE_NAME,
        })


logger = logging.getLogger("batch")
logger.setLevel(logging.INFO)
logger.propagate = False
handler = logging.StreamHandler()
handler.setFormatter(JSONFormatter())
logger.addHandler(handler)


# ── CPU-burner ──────────────────────────────────────────────────────────
def cpu_burner(worker_id: int):
    """
    Бесконечно грузит CPU: считает сумму квадратов в цикле.
    Поток — один. Можно запустить несколько.
    """
    logger.info(f"cpu-burner {worker_id} started")
    x = 0
    while True:
        x = (x + 1) % 1000000
        y = x * x            # бесполезная нагрузка
        _ = y % 7            # чтобы компилятор не выкинул вычисление


# ── Memory-burner ───────────────────────────────────────────────────────
def memory_burner():
    """
    Бесконечно выделяет память — по MEM_STEP_MB каждые MEM_INTERVAL_S секунд.
    Если MEM_MAX_MB > 0 — останавливается на этом пороге.
    """
    logger.info(f"memory-burner started (step={MEM_STEP_MB}MB, interval={MEM_INTERVAL_S}s, max={MEM_MAX_MB}MB)")
    chunks = []
    total_mb = 0

    while True:
        if MEM_MAX_MB > 0 and total_mb >= MEM_MAX_MB:
            logger.info(f"memory-burner reached cap ({MEM_MAX_MB}MB), holding")
            time.sleep(MEM_INTERVAL_S)
            continue

        # Выделяем список из ~MEM_STEP_MB мегабайт
        # Каждый int в Python — примерно 28 байт, но для гарантии берём bytes
        chunk = bytearray(MEM_STEP_MB * 1024 * 1024)
        chunks.append(chunk)   # держим ссылку, чтобы не собрал GC
        total_mb += MEM_STEP_MB
        logger.info(f"allocated ~{total_mb}MB total")
        time.sleep(MEM_INTERVAL_S)


# ── Main ────────────────────────────────────────────────────────────────
def main():
    logger.info(f"batch starting: cpu_workers={CPU_WORKERS}, mem_step={MEM_STEP_MB}MB, mem_interval={MEM_INTERVAL_S}s, mem_max={MEM_MAX_MB}MB")

    # Запускаем CPU-потоки
    for i in range(CPU_WORKERS):
        t = threading.Thread(target=cpu_burner, args=(i,), daemon=True)
        t.start()

    # Запускаем memory-поток
    t = threading.Thread(target=memory_burner, daemon=True)
    t.start()

    # Главный поток просто спит — все потоки daemon, процесс работает
    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()