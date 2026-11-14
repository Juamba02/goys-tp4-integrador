#!/usr/bin/env python3
"""Sensor de telemetría del MiniSOC-IA.

Corre dentro de cada servicio monitoreado, como usuario sin privilegios, y mira
solo su propio contenedor:

- **procesos:** recorre /proc y reporta cada proceso nuevo con su padre, su línea
  de comando y su usuario.
- **conexiones:** lee /proc/net/tcp y reporta cada conexión TCP nueva, entrante o
  saliente. Una conexión que el firewall descarta queda en SYN_SENT, y también se
  reporta: un intento bloqueado es tan informativo como uno exitoso.

Los eventos se mandan en lotes a la ingesta (POST $INGESTA_URL). Si la ingesta no
responde, se guardan en memoria (hasta MAX_PENDIENTES) y se reintenta.

Limitación conocida: es un sensor por muestreo. Un proceso que vive menos que el
intervalo (por defecto 50 ms) puede no verse. Un sensor eBPF (Falco, Tetragon) no
tiene ese problema, pero necesita privilegios sobre el kernel del host.
"""
from __future__ import annotations

import http.client
import json
import os
import pwd
import socket
import sys
import time
import urllib.error
import urllib.request
from collections import deque
from datetime import datetime, timezone

HOST = socket.gethostname()
INTERVALO = float(os.environ.get("SENSOR_INTERVALO", "0.05"))
ENVIO_CADA = float(os.environ.get("SENSOR_ENVIO_CADA", "1.0"))
INGESTA_URL = os.environ.get("INGESTA_URL", "http://10.30.0.10:8081/v1/eventos")
TOKEN = os.environ.get("SENSOR_TOKEN", "")
DEBUG = os.environ.get("SENSOR_DEBUG", "") == "1"
MAX_PENDIENTES = 5000
PUERTOS_PROPIOS = {int(p) for p in os.environ.get("PUERTOS", "").split()}
YO = os.getpid()

# Estados de /proc/net/tcp que interesan (el resto son cierres o escucha).
ESTADOS_TCP = {"01": "establecida", "02": "syn_enviado"}


def ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _leer(ruta: str, binario: bool = False):
    try:
        with open(ruta, "rb" if binario else "r") as f:
            return f.read()
    except OSError:
        return None


_usuarios: dict[int, str] = {}


def usuario(uid: int) -> str:
    if uid not in _usuarios:
        try:
            _usuarios[uid] = pwd.getpwuid(uid).pw_name
        except KeyError:
            _usuarios[uid] = str(uid)
    return _usuarios[uid]


def leer_proceso(pid: int) -> dict | None:
    stat = _leer(f"/proc/{pid}/stat")
    if stat is None:
        return None
    # El nombre va entre paréntesis y puede tener espacios: se corta por el último ')'.
    inicio, fin = stat.find("("), stat.rfind(")")
    comm = stat[inicio + 1:fin]
    campos = stat[fin + 2:].split()
    if campos[0] == "Z":
        return None  # zombi: ya terminó, solo espera que el padre lo recoja
    ppid = int(campos[1])
    crudo = _leer(f"/proc/{pid}/cmdline", binario=True) or b""
    cmdline = crudo.rstrip(b"\0").replace(b"\0", b" ").decode(errors="replace")
    uid = None
    for linea in (_leer(f"/proc/{pid}/status") or "").splitlines():
        if linea.startswith("Uid:"):
            uid = int(linea.split()[1])
            break
    return {"pid": pid, "ppid": ppid, "comm": comm, "cmdline": cmdline or f"[{comm}]", "uid": uid}


def _ip_hex(h: str) -> str:
    # /proc/net/tcp guarda la IPv4 en hex little-endian.
    return socket.inet_ntoa(bytes.fromhex(h)[::-1])


def leer_conexiones() -> set[tuple]:
    conexiones = set()
    texto = _leer("/proc/net/tcp") or ""
    for linea in texto.splitlines()[1:]:
        partes = linea.split()
        if len(partes) < 4 or partes[3] not in ESTADOS_TCP:
            continue
        lip, lpuerto = partes[1].split(":")
        rip, rpuerto = partes[2].split(":")
        conexiones.add((_ip_hex(lip), int(lpuerto, 16), _ip_hex(rip), int(rpuerto, 16), ESTADOS_TCP[partes[3]]))
    return conexiones


class Sensor:
    def __init__(self) -> None:
        self.procesos: dict[int, dict] = {}
        self.conexiones: set[tuple] = set()
        self.pendientes: deque = deque(maxlen=MAX_PENDIENTES)
        self.descartados = 0
        self.ingesta_ok = True
        destino = urllib.request.urlparse(INGESTA_URL)
        self.ingesta = (socket.gethostbyname(destino.hostname), destino.port or 80)

    def _evento(self, tipo: str, datos: dict) -> None:
        if len(self.pendientes) == self.pendientes.maxlen:
            self.descartados += 1
        ev = {"ts": ahora(), "host": HOST, "tipo": tipo, "datos": datos}
        self.pendientes.append(ev)
        if DEBUG:
            print(json.dumps(ev, ensure_ascii=False), flush=True)

    def inicializar(self) -> None:
        """Lo que ya existe al arrancar es la línea de base: no se reporta."""
        for pid in self._pids():
            p = leer_proceso(pid)
            if p:
                p.update(vistas=2, reportado=True)
                self.procesos[pid] = p
        self.conexiones = leer_conexiones()

    @staticmethod
    def _pids() -> list[int]:
        return [int(d) for d in os.listdir("/proc") if d.isdigit()]

    def _padre(self, ppid: int) -> dict | None:
        return leer_proceso(ppid) or self.procesos.get(ppid)

    def _reportar(self, p: dict, exec_: bool = False) -> None:
        padre = self._padre(p["ppid"])
        datos = {
            "pid": p["pid"],
            "ppid": p["ppid"],
            "proceso": p["comm"],
            "padre": padre["comm"] if padre else "?",
            "cmdline": p["cmdline"],
            "usuario": usuario(p["uid"]) if p["uid"] is not None else "?",
        }
        if exec_:
            datos["exec"] = True  # el mismo pid pasó a ejecutar otro programa
        self._evento("proceso", datos)
        p["reportado"] = True

    def _excluido(self, p: dict) -> bool:
        # - `runc init` es la plomería de `docker exec`: todavía no es el programa real.
        # - Lo que se lanza con `docker exec` (padre fuera del contenedor, ppid 0) es el
        #   canal de administración del laboratorio y queda fuera del alcance del
        #   sensor. Sus hijos sí se reportan.
        return p["comm"].startswith("runc:") or p["ppid"] == 0

    def _copia_de_fork(self, p: dict) -> bool:
        # Entre el fork y el exec, el hijo todavía tiene el nombre y la línea de
        # comando del padre: hay que esperar a ver qué programa termina ejecutando.
        padre = self._padre(p["ppid"])
        return bool(padre) and (p["comm"], p["cmdline"]) == (padre["comm"], padre["cmdline"])

    def muestrear(self) -> None:
        vivos = set()
        for pid in self._pids():
            if pid == YO:
                continue
            p = leer_proceso(pid)
            if p is None:
                continue
            vivos.add(pid)
            previo = self.procesos.get(pid)
            cambio = previo is not None and (p["comm"], p["cmdline"]) != (previo["comm"], previo["cmdline"])
            p.update(vistas=(previo["vistas"] + 1) if previo else 1,
                     reportado=previo["reportado"] if previo else False)
            self.procesos[pid] = p
            if self._excluido(p):
                continue
            if not p["reportado"]:
                # Se reporta en cuanto ejecuta su propio programa. Una copia de fork
                # que nunca hace exec (un worker) se reporta a la segunda muestra.
                if not self._copia_de_fork(p) or p["vistas"] >= 2:
                    self._reportar(p)
            elif cambio:
                self._reportar(p, exec_=True)

        for pid in set(self.procesos) - vivos:
            p = self.procesos.pop(pid)
            if not p["reportado"] and not self._excluido(p):
                self._reportar(p)  # vivió una sola muestra: se reporta igual

        actuales = leer_conexiones()
        for lip, lpuerto, rip, rpuerto, estado in actuales - self.conexiones:
            if (rip, rpuerto) == self.ingesta:
                continue  # el propio envío de telemetría
            if estado == "establecida" and (lip, lpuerto, rip, rpuerto, "syn_enviado") in self.conexiones:
                continue  # ya se reportó cuando salió el SYN
            entrante = lpuerto in PUERTOS_PROPIOS
            self._evento("conexion", {
                "direccion": "entrante" if entrante else "saliente",
                "ip_origen": rip if entrante else lip,
                "puerto_origen": rpuerto if entrante else lpuerto,
                "ip_destino": lip if entrante else rip,
                "puerto_destino": lpuerto if entrante else rpuerto,
                "estado": estado,
            })
        self.conexiones = actuales

    def enviar(self) -> None:
        if not self.pendientes:
            return
        lote = list(self.pendientes)
        cuerpo = json.dumps({"sensor": HOST, "descartados": self.descartados, "eventos": lote}).encode()
        pedido = urllib.request.Request(INGESTA_URL, cuerpo, {"Content-Type": "application/json"})
        if TOKEN:
            pedido.add_header("Authorization", f"Bearer {TOKEN}")
        try:
            with urllib.request.urlopen(pedido, timeout=3):
                pass
        except (urllib.error.URLError, OSError, http.client.HTTPException, ValueError) as e:
            if self.ingesta_ok:
                print(f"sensor: ingesta no disponible ({e}); los eventos quedan en espera", file=sys.stderr, flush=True)
                self.ingesta_ok = False
            return
        if not self.ingesta_ok:
            print("sensor: ingesta disponible otra vez", file=sys.stderr, flush=True)
            self.ingesta_ok = True
        for _ in lote:
            self.pendientes.popleft()
        self.descartados = 0


def main() -> None:
    # Espera a que el servicio termine de arrancar (y tome su nombre) antes de
    # sacar la línea de base, para no reportar su propio arranque.
    time.sleep(float(os.environ.get("SENSOR_ESPERA", "2")))
    sensor = Sensor()
    sensor.inicializar()
    print(f"sensor de {HOST}: {len(sensor.procesos)} procesos en la línea de base, enviando a {INGESTA_URL}", flush=True)
    ultimo_envio = time.monotonic()
    while True:
        # Un error puntual (un proceso que desaparece a mitad de la lectura, una
        # respuesta rara de la ingesta) no puede apagar el sensor.
        try:
            sensor.muestrear()
            if time.monotonic() - ultimo_envio >= ENVIO_CADA:
                sensor.enviar()
                ultimo_envio = time.monotonic()
        except Exception as e:  # noqa: BLE001
            print(f"sensor: error {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        time.sleep(INTERVALO)


if __name__ == "__main__":
    main()
