"""Alertas y cursor de lectura en SQLite."""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

ESQUEMA = """
CREATE TABLE IF NOT EXISTS alertas (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    regla_id    TEXT NOT NULL,
    tecnica     TEXT NOT NULL,
    tactica     TEXT NOT NULL,
    severidad   TEXT NOT NULL,
    descripcion TEXT NOT NULL,
    host        TEXT NOT NULL,
    segmento    TEXT NOT NULL,
    ts          TEXT NOT NULL,
    evento_id   TEXT NOT NULL,
    evento      TEXT NOT NULL,
    UNIQUE (regla_id, evento_id)
);
CREATE INDEX IF NOT EXISTS alertas_host_ts ON alertas (host, ts);
CREATE TABLE IF NOT EXISTS estado (clave TEXT PRIMARY KEY, valor TEXT NOT NULL);
"""


def alerta_id(n: int) -> str:
    return f"ALR-{n:06d}"


class Almacen:
    def __init__(self, ruta: str | Path) -> None:
        if str(ruta) != ":memory:":
            Path(ruta).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(ruta), check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(ESQUEMA)
        self._lock = threading.Lock()

    def cursor(self) -> int:
        with self._lock:
            fila = self._db.execute("SELECT valor FROM estado WHERE clave = 'cursor_ingesta'").fetchone()
        return int(fila[0]) if fila else 0

    def guardar(self, alertas: list[dict[str, Any]], cursor: int) -> list[dict[str, Any]]:
        """Guarda las alertas y avanza el cursor en la misma transacción: si el proceso
        se corta a la mitad, al volver relee esos eventos y no pierde ni duplica nada."""
        nuevas = []
        with self._lock, self._db:
            for a in alertas:
                cur = self._db.execute(
                    "INSERT OR IGNORE INTO alertas (regla_id, tecnica, tactica, severidad, descripcion,"
                    " host, segmento, ts, evento_id, evento) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (a["regla_id"], a["tecnica"], a["tactica"], a["severidad"], a["descripcion"],
                     a["host"], a["segmento"], a["ts"], a["eventos"][0],
                     json.dumps(a["evento"], ensure_ascii=False, sort_keys=True)))
                if cur.rowcount:
                    a["alerta_id"] = alerta_id(cur.lastrowid)
                    nuevas.append(a)
            self._db.execute("INSERT OR REPLACE INTO estado (clave, valor) VALUES ('cursor_ingesta', ?)", (str(cursor),))
        return nuevas

    def leer(self, desde: int = 0, limite: int = 500, host: str | None = None) -> tuple[list[dict[str, Any]], int]:
        sql = ("SELECT id, regla_id, tecnica, tactica, severidad, descripcion, host, segmento, ts, evento_id, evento"
               " FROM alertas WHERE id > ?")
        args: list[Any] = [desde]
        if host:
            sql += " AND host = ?"
            args.append(host)
        sql += " ORDER BY id LIMIT ?"
        args.append(max(1, min(limite, 5000)))
        with self._lock:
            filas = self._db.execute(sql, args).fetchall()
        alertas = [{
            "alerta_id": alerta_id(f[0]), "regla_id": f[1], "tecnica": f[2], "tactica": f[3],
            "severidad": f[4], "descripcion": f[5], "host": f[6], "segmento": f[7], "ts": f[8],
            "eventos": [f[9]], "evento": json.loads(f[10]),
        } for f in filas]
        return alertas, (filas[-1][0] if filas else desde)

    def cantidad(self) -> int:
        with self._lock:
            return self._db.execute("SELECT COUNT(*) FROM alertas").fetchone()[0]
