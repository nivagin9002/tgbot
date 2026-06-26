"""Хранилище дат турниров и кэмпа в Турцию.

• Если задан DATABASE_URL (на Render) — используется PostgreSQL (данные не теряются).
• Если нет (локальный запуск) — резервный JSON-файл, чтобы можно было тестировать на ПК.

Прошедшие даты удаляются автоматически при каждом просмотре (очистка старых дат).
"""
import json
import logging
import os
from datetime import date

DATABASE_URL = os.getenv("DATABASE_URL", "")
JSON_FILE = os.getenv("DATA_FILE", "data.json")

_pool = None  # пул подключений к PostgreSQL (None при работе через JSON)


async def init() -> None:
    """Подключиться к БД и создать таблицы. Без DATABASE_URL — работаем на JSON."""
    global _pool
    if not DATABASE_URL:
        logging.info("DATABASE_URL не задан — даты хранятся в файле %s", JSON_FILE)
        return
    import asyncpg

    _pool = await asyncpg.create_pool(DATABASE_URL)
    async with _pool.acquire() as conn:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS tournaments ("
            "  id SERIAL PRIMARY KEY,"
            "  event_date DATE NOT NULL,"
            "  text TEXT NOT NULL)"
        )
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS settings ("
            "  key TEXT PRIMARY KEY,"
            "  text TEXT,"
            "  end_date DATE)"
        )
    logging.info("PostgreSQL подключён, таблицы готовы.")


# ---------- Резервный JSON ----------
def _jload() -> dict:
    try:
        with open(JSON_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"tournaments": [], "turkey": None}


def _jsave(data: dict) -> None:
    with open(JSON_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ---------- Турниры ----------
async def get_tournaments() -> list[str]:
    """Список строк будущих турниров (прошедшие удаляются)."""
    today = date.today()
    if _pool:
        async with _pool.acquire() as conn:
            await conn.execute("DELETE FROM tournaments WHERE event_date < $1", today)
            rows = await conn.fetch(
                "SELECT text FROM tournaments WHERE event_date >= $1 ORDER BY event_date",
                today,
            )
            return [r["text"] for r in rows]
    data = _jload()
    keep = [t for t in data["tournaments"] if t["date"] >= today.isoformat()]
    if len(keep) != len(data["tournaments"]):
        data["tournaments"] = keep
        _jsave(data)
    keep.sort(key=lambda t: t["date"])
    return [t["text"] for t in keep]


async def set_tournaments(items: list[tuple[date, str]]) -> None:
    """Полностью заменить список турниров. items = [(дата, строка-для-показа), ...]"""
    if _pool:
        async with _pool.acquire() as conn:
            await conn.execute("DELETE FROM tournaments")
            for event_date, text in items:
                await conn.execute(
                    "INSERT INTO tournaments (event_date, text) VALUES ($1, $2)",
                    event_date,
                    text,
                )
        return
    data = _jload()
    data["tournaments"] = [{"date": d.isoformat(), "text": t} for d, t in items]
    _jsave(data)


# ---------- Кэмп в Турцию ----------
async def get_turkey() -> str | None:
    """Текст дат кэмпа (или None, если не задано/дата уже прошла)."""
    today = date.today()
    if _pool:
        async with _pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT text, end_date FROM settings WHERE key = 'turkey'"
            )
            if not row:
                return None
            if row["end_date"] and row["end_date"] < today:
                await conn.execute("DELETE FROM settings WHERE key = 'turkey'")
                return None
            return row["text"]
    data = _jload()
    t = data.get("turkey")
    if not t:
        return None
    if t.get("end") and t["end"] < today.isoformat():
        data["turkey"] = None
        _jsave(data)
        return None
    return t["text"]


async def set_turkey(text: str, end_date: date | None) -> None:
    if _pool:
        async with _pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO settings (key, text, end_date) VALUES ('turkey', $1, $2) "
                "ON CONFLICT (key) DO UPDATE SET text = $1, end_date = $2",
                text,
                end_date,
            )
        return
    data = _jload()
    data["turkey"] = {"text": text, "end": end_date.isoformat() if end_date else None}
    _jsave(data)
