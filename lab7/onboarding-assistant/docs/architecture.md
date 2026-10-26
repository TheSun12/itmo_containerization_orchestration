# Архитектура

Клиент → API (FastAPI) → Очередь (Redis) → Воркер → ClickHouse.

Воркеры масштабируются горизонтально. API stateless.