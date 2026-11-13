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
        for entrada in self._leer_crudo():
            self._seq = entrada.get("seq", self._seq)
            self._ultimo_hash = entrada.get("hash", self._ultimo_hash)

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
                f.write(json.dumps(entrada, ensure_ascii=False) + "\n")
            self._seq = entrada["seq"]
            self._ultimo_hash = entrada["hash"]
            return entrada

    def _leer_crudo(self) -> Iterator[dict[str, Any]]:
        if not self.ruta.exists():
            return
        with self.ruta.open(encoding="utf-8") as f:
            for linea in f:
                linea = linea.strip()
                if linea:
                    yield json.loads(linea)

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
        try:
            for entrada in self._leer_crudo():
                n += 1
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
        except json.JSONDecodeError as e:
            return ResultadoVerificacion(False, n + 1, None, f"línea no es JSON válido: {e}")
        return ResultadoVerificacion(True, n)


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
