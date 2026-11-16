"""Almacén de incidentes de la correlación (SQLite, archivo propio)."""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

ESQUEMA = """
CREATE TABLE IF NOT EXISTS incidentes (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    host             TEXT NOT NULL,
    segmento         TEXT NOT NULL,
    -- abierto: recibe alertas · pendiente: cerrado, falta enviarlo (o reintentarlo)
    -- enviado: el agente respondió con un veredicto · rechazado: el agente no lo aceptó
    estado           TEXT NOT NULL,
    creado           REAL NOT NULL,
    ultima_alerta    REAL NOT NULL,
    cerrado          REAL,
    intentos         INTEGER NOT NULL DEFAULT 0,
    proximo_intento  REAL,
    enviado          TEXT,
    respuesta        TEXT,
    error            TEXT
);
CREATE INDEX IF NOT EXISTS incidentes_estado ON incidentes (estado);
CREATE TABLE IF NOT EXISTS incidente_alertas (
    incidente   INTEGER NOT NULL,
    alerta      TEXT NOT NULL,
    datos       TEXT NOT NULL,
    PRIMARY KEY (incidente, alerta)
);
CREATE TABLE IF NOT EXISTS estado (clave TEXT PRIMARY KEY, valor TEXT NOT NULL);
"""


def incidente_id(n: int) -> str:
    return f"INC-{n:06d}"


class AlmacenIncidentes:
    def __init__(self, ruta: str | Path) -> None:
        if str(ruta) != ":memory:":
            Path(ruta).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(ruta), check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(ESQUEMA)
        self._lock = threading.Lock()

    # ---------------------------------------------------------------- cursor
    def cursor(self) -> int:
        with self._lock:
            fila = self._db.execute("SELECT valor FROM estado WHERE clave = 'cursor_alertas'").fetchone()
        return int(fila[0]) if fila else 0

    def agregar_alertas(self, alertas: list[dict[str, Any]], cursor: int, ahora: float) -> list[int]:
        """Suma cada alerta al incidente abierto de su host (o abre uno) y avanza el
        cursor, todo en una transacción. Devuelve los ids de incidentes tocados."""
        tocados: list[int] = []
        with self._lock, self._db:
            for a in alertas:
                fila = self._db.execute(
                    "SELECT id FROM incidentes WHERE host = ? AND estado = 'abierto'", (a["host"],)).fetchone()
                if fila:
                    iid = fila[0]
                    self._db.execute("UPDATE incidentes SET ultima_alerta = ? WHERE id = ?", (ahora, iid))
                else:
                    iid = self._db.execute(
                        "INSERT INTO incidentes (host, segmento, estado, creado, ultima_alerta)"
                        " VALUES (?, ?, 'abierto', ?, ?)", (a["host"], a["segmento"], ahora, ahora)).lastrowid
                self._db.execute(
                    "INSERT OR IGNORE INTO incidente_alertas (incidente, alerta, datos) VALUES (?, ?, ?)",
                    (iid, a["alerta_id"], json.dumps(a, ensure_ascii=False, sort_keys=True)))
                if iid not in tocados:
                    tocados.append(iid)
            self._db.execute("INSERT OR REPLACE INTO estado (clave, valor) VALUES ('cursor_alertas', ?)", (str(cursor),))
        return tocados

    # ----------------------------------------------------------- ciclo de vida
    def cerrar_inactivos(self, ahora: float, inactividad: float, duracion_max: float) -> list[int]:
        with self._lock, self._db:
            ids = [f[0] for f in self._db.execute(
                "SELECT id FROM incidentes WHERE estado = 'abierto' AND (ultima_alerta <= ? OR creado <= ?)",
                (ahora - inactividad, ahora - duracion_max))]
            for iid in ids:
                self._db.execute("UPDATE incidentes SET estado = 'pendiente', cerrado = ?, proximo_intento = ?"
                                 " WHERE id = ?", (ahora, ahora, iid))
        return ids

    def para_enviar(self, ahora: float) -> list[int]:
        with self._lock:
            return [f[0] for f in self._db.execute(
                "SELECT id FROM incidentes WHERE estado = 'pendiente' AND proximo_intento <= ? ORDER BY id", (ahora,))]

    def alertas_de(self, iid: int) -> list[dict[str, Any]]:
        with self._lock:
            filas = self._db.execute(
                "SELECT datos FROM incidente_alertas WHERE incidente = ? ORDER BY alerta", (iid,)).fetchall()
        return [json.loads(f[0]) for f in filas]

    def marcar(self, iid: int, estado: str, *, enviado: dict | None = None, respuesta: Any = None,
               error: str | None = None, reintentar_en: float | None = None) -> None:
        with self._lock, self._db:
            self._db.execute(
                "UPDATE incidentes SET estado = ?, intentos = intentos + 1, proximo_intento = ?,"
                " enviado = COALESCE(?, enviado), respuesta = COALESCE(?, respuesta), error = ? WHERE id = ?",
                (estado, reintentar_en,
                 json.dumps(enviado, ensure_ascii=False) if enviado is not None else None,
                 json.dumps(respuesta, ensure_ascii=False) if respuesta is not None else None,
                 error, iid))

    # ---------------------------------------------------------------- lectura
    def listar(self, desde: int = 0, limite: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            filas = self._db.execute(
                "SELECT id, host, segmento, estado, intentos, respuesta, error,"
                " (SELECT COUNT(*) FROM incidente_alertas WHERE incidente = incidentes.id)"
                " FROM incidentes WHERE id > ? ORDER BY id LIMIT ?", (desde, max(1, min(limite, 1000)))).fetchall()
        salida = []
        for f in filas:
            respuesta = json.loads(f[5]) if f[5] else None
            salida.append({
                "incidente_id": incidente_id(f[0]), "host": f[1], "segmento": f[2], "estado": f[3],
                "alertas": f[7], "intentos": f[4], "error": f[6],
                "veredicto": respuesta.get("veredicto") if isinstance(respuesta, dict) else None,
                "respuesta": respuesta,
            })
        return salida

    def enviado(self, iid: int) -> dict[str, Any] | None:
        with self._lock:
            fila = self._db.execute("SELECT enviado FROM incidentes WHERE id = ?", (iid,)).fetchone()
        return json.loads(fila[0]) if fila and fila[0] else None

    def contar(self) -> dict[str, int]:
        with self._lock:
            return dict(self._db.execute("SELECT estado, COUNT(*) FROM incidentes GROUP BY estado").fetchall())
