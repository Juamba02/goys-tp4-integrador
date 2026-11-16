"""Ledger auditable: registro append-only encadenado por hash.

Cada entrada es una línea JSON en un archivo. El hash de cada entrada cubre su
contenido y el hash de la anterior, así que cambiar o borrar una línea rompe la
cadena desde ese punto. Con una clave (``LEDGER_CLAVE``) el hash es un HMAC: sin
la clave no se puede recalcular la cadena para tapar una modificación.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

HASH_INICIAL = "0" * 64


def ahora_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _canonico(entrada: dict[str, Any]) -> bytes:
    return json.dumps(entrada, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


@dataclass
class ResultadoVerificacion:
    integro: bool
    entradas: int
    error_en_seq: int | None = None
    detalle: str = ""

    def a_dict(self) -> dict[str, Any]:
        return {
            "integro": self.integro,
            "entradas": self.entradas,
            "error_en_seq": self.error_en_seq,
            "detalle": self.detalle,
        }


class Ledger:
    def __init__(self, ruta: str | Path, clave: str | None = None) -> None:
        self.ruta = Path(ruta)
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        self._clave = clave.encode() if clave else None
        self._lock = threading.Lock()
        self._seq = 0
        self._ultimo_hash = HASH_INICIAL
        # Líneas que no son una entrada válida (por ejemplo, una escritura cortada si el
        # proceso murió a mitad). No impiden arrancar: se saltean al leer, la cadena queda
        # sin verificar (integro=0) y se reportan acá para investigarlas.
        self.lineas_invalidas: list[int] = []
        for entrada in self._leer_crudo():
            self._seq = entrada.get("seq", self._seq)
            self._ultimo_hash = entrada.get("hash", self._ultimo_hash)
        # Si el archivo quedó sin salto de línea final (escritura cortada), la próxima
        # entrada tiene que empezar en una línea nueva para no pegarse a la cortada.
        self._falta_salto = False
        if self.ruta.exists() and self.ruta.stat().st_size > 0:
            with self.ruta.open("rb") as f:
                f.seek(-1, 2)
                self._falta_salto = f.read(1) != b"\n"

    def _hash(self, entrada_sin_hash: dict[str, Any]) -> str:
        datos = _canonico(entrada_sin_hash)
        if self._clave:
            return hmac.new(self._clave, datos, hashlib.sha256).hexdigest()
        return hashlib.sha256(datos).hexdigest()

    def registrar(self, tipo: str, incidente_id: str | None, datos: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            entrada = {
                "seq": self._seq + 1,
                "ts": ahora_iso(),
                "incidente_id": incidente_id,
                "tipo": tipo,
                "datos": datos,
                "hash_anterior": self._ultimo_hash,
            }
            entrada["hash"] = self._hash(entrada)
            with self.ruta.open("a", encoding="utf-8") as f:
                f.write(("\n" if self._falta_salto else "") + json.dumps(entrada, ensure_ascii=False) + "\n")
            self._falta_salto = False
            self._seq = entrada["seq"]
            self._ultimo_hash = entrada["hash"]
            return entrada

    def _leer_lineas(self) -> Iterator[tuple[int, dict[str, Any] | None, str]]:
        """(número de línea, entrada o None si no es válida, error)."""
        if not self.ruta.exists():
            return
        with self.ruta.open(encoding="utf-8", errors="replace") as f:
            for nro, linea in enumerate(f, start=1):
                linea = linea.strip()
                if not linea:
                    continue
                try:
                    entrada = json.loads(linea)
                except json.JSONDecodeError as e:
                    yield nro, None, f"no es JSON válido: {e}"
                    continue
                if not isinstance(entrada, dict):
                    yield nro, None, "no es un objeto JSON"
                    continue
                yield nro, entrada, ""

    def _leer_crudo(self) -> Iterator[dict[str, Any]]:
        """Entradas válidas, salteando (y anotando) las líneas que no lo son."""
        invalidas = []
        for nro, entrada, _ in self._leer_lineas():
            if entrada is None:
                invalidas.append(nro)
            else:
                yield entrada
        self.lineas_invalidas = invalidas

    def entradas(self, incidente_id: str | None = None) -> list[dict[str, Any]]:
        return [e for e in self._leer_crudo() if incidente_id is None or e.get("incidente_id") == incidente_id]

    @property
    def cantidad(self) -> int:
        return self._seq

    @property
    def ultimo_hash(self) -> str:
        return self._ultimo_hash

    def verificar(self) -> ResultadoVerificacion:
        anterior = HASH_INICIAL
        esperado_seq = 1
        n = 0
        for nro, entrada, error in self._leer_lineas():
            n += 1
            if entrada is None:
                return ResultadoVerificacion(False, n, None, f"la línea {nro} {error}")
            seq = entrada.get("seq")
            if seq != esperado_seq:
                return ResultadoVerificacion(False, n, seq, f"se esperaba seq {esperado_seq} y hay {seq}")
            if entrada.get("hash_anterior") != anterior:
                return ResultadoVerificacion(False, n, seq, "hash_anterior no coincide: falta o cambió una entrada previa")
            sin_hash = {k: v for k, v in entrada.items() if k != "hash"}
            if self._hash(sin_hash) != entrada.get("hash"):
                return ResultadoVerificacion(False, n, seq, "el contenido de la entrada fue modificado")
            anterior = entrada["hash"]
            esperado_seq += 1
        return ResultadoVerificacion(True, n)

    def huella_archivo(self) -> tuple[int, int, int]:
        """(entradas escritas por este proceso, mtime en ns, tamaño) del archivo. Cambia
        también si alguien edita una línea por fuera del agente."""
        try:
            st = self.ruta.stat()
        except FileNotFoundError:
            return (self._seq, 0, 0)
        return (self._seq, st.st_mtime_ns, st.st_size)


def _main() -> None:
    import argparse
    import os
    import sys

    p = argparse.ArgumentParser(description="Verifica la integridad de un ledger del agente.")
    p.add_argument("ruta", nargs="?", default=os.environ.get("LEDGER_RUTA", "datos/ledger.jsonl"))
    args = p.parse_args()
    res = Ledger(args.ruta, os.environ.get("LEDGER_CLAVE")).verificar()
    print(json.dumps(res.a_dict(), ensure_ascii=False, indent=2))
    sys.exit(0 if res.integro else 1)


if __name__ == "__main__":
    _main()
