"""Almacén de eventos en SQLite (biblioteca estándar, un solo archivo)."""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

ESQUEMA = """
CREATE TABLE IF NOT EXISTS eventos (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           TEXT NOT NULL,
    ts_recibido  TEXT NOT NULL,
    host         TEXT NOT NULL,
    segmento     TEXT NOT NULL,
    tipo         TEXT NOT NULL,
    datos        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS eventos_host_ts ON eventos (host, ts);
"""


def evento_id(n: int) -> str:
    return f"EVT-{n:06d}"


class Almacen:
    def __init__(self, ruta: str | Path) -> None:
        if str(ruta) != ":memory:":
            Path(ruta).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(ruta), check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(ESQUEMA)
        self._lock = threading.Lock()

    def guardar(self, eventos: list[dict[str, Any]]) -> list[str]:
        """Guarda los eventos en una sola transacción y devuelve sus evento_id."""
        ids = []
        with self._lock, self._db:
            for e in eventos:
                cur = self._db.execute(
                    "INSERT INTO eventos (ts, ts_recibido, host, segmento, tipo, datos) VALUES (?, ?, ?, ?, ?, ?)",
                    (e["ts"], e["ts_recibido"], e["host"], e["segmento"], e["tipo"],
                     json.dumps(e["datos"], ensure_ascii=False, sort_keys=True)),
                )
                e["evento_id"] = evento_id(cur.lastrowid)
                ids.append(e["evento_id"])
        return ids

    def leer(self, desde: int = 0, limite: int = 500, host: str | None = None,
             tipo: str | None = None) -> tuple[list[dict[str, Any]], int]:
        """Eventos con id > desde, en orden. Devuelve (eventos, último id leído)."""
        sql = "SELECT id, ts, ts_recibido, host, segmento, tipo, datos FROM eventos WHERE id > ?"
        args: list[Any] = [desde]
        if host:
            sql += " AND host = ?"
            args.append(host)
        if tipo:
            sql += " AND tipo = ?"
            args.append(tipo)
        sql += " ORDER BY id LIMIT ?"
        args.append(max(1, min(limite, 5000)))
        with self._lock:
            filas = self._db.execute(sql, args).fetchall()
        eventos = [{
            "evento_id": evento_id(f[0]), "ts": f[1], "ts_recibido": f[2], "host": f[3],
            "segmento": f[4], "tipo": f[5], "datos": json.loads(f[6]),
        } for f in filas]
        return eventos, (filas[-1][0] if filas else desde)

    def cantidad(self) -> int:
        with self._lock:
            return self._db.execute("SELECT COUNT(*) FROM eventos").fetchone()[0]
