#!/usr/bin/env python3
"""Servicio de contención del router: la única forma de que el SOC cambie la red.

Escucha solo en la IP del router en el segmento SOC y solo acepta pedidos del
respondedor, con token. No ejecuta comandos arbitrarios: cada acción se traduce a un
conjunto fijo de reglas en la cadena MINISOC-CONTENCION, que se evalúa antes que
cualquier otra regla de FORWARD.

    bloquear_ip  X  ->  DROP todo lo que va hacia X o viene de X
    aislar_host  H  ->  DROP todo lo que va hacia H o viene de H, salvo SSH desde gestión
                        (para entrar a investigar) y la telemetría hacia la ingesta

Cada regla lleva un comentario "minisoc ACC-0001", así se puede revertir exactamente
lo que aplicó una acción. Aplicar dos veces la misma acción no duplica reglas.

Aunque el pedido venga autenticado, este servicio también rechaza bloquear redes
protegidas o aislar hosts protegidos: es la última capa y no confía en las anteriores.

| Método y ruta     | Cuerpo |
|-------------------|--------|
| POST /v1/aplicar  | {"accion_id": "ACC-0001", "tipo": "bloquear_ip", "objetivo": "10.99.0.66"} |
| POST /v1/revertir | {"accion_id": "ACC-0001"} |
| GET  /v1/contencion | reglas aplicadas, agrupadas por acción |
"""
from __future__ import annotations

import hmac
import ipaddress
import json
import logging
import os
import re
import shlex
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

log = logging.getLogger("contencion")

CADENA = "MINISOC-CONTENCION"
ACCION_ID = re.compile(r"^ACC-\d{1,8}$")
GESTION = "10.10.0.0/24"
INGESTA = "10.30.0.10"
REDES_PROTEGIDAS = ("10.10.0.0/24", "10.20.0.0/24", "10.30.0.0/24")
# Hosts que se pueden aislar: nombre del contenedor -> IP. El resto no se aísla.
HOSTS_AISLABLES = {"web-01": "10.20.0.11", "api-01": "10.20.0.12", "db-01": "10.20.0.13"}
HOSTS_PROTEGIDOS = ("router", "ansible", "espejo", "ingesta", "deteccion", "agente", "respondedor", "analista")

Ejecutar = Callable[[list[str]], str]


class Rechazo(ValueError):
    pass


def ejecutar_iptables(args: list[str]) -> str:
    # Lista de argumentos, nunca un shell: el objetivo no puede inyectar nada.
    r = subprocess.run(["iptables", *args], capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        raise RuntimeError(f"iptables {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout


class Contencion:
    def __init__(self, ejecutar: Ejecutar = ejecutar_iptables,
                 hosts: dict[str, str] | None = None,
                 redes_protegidas: tuple[str, ...] = REDES_PROTEGIDAS,
                 hosts_protegidos: tuple[str, ...] = HOSTS_PROTEGIDOS) -> None:
        self.ejecutar = ejecutar
        self.hosts = dict(HOSTS_AISLABLES if hosts is None else hosts)
        self.redes = [ipaddress.ip_network(r) for r in redes_protegidas]
        self.hosts_protegidos = set(hosts_protegidos)
        self._lock = threading.Lock()

    # ------------------------------------------------------------ validación
    def _reglas(self, accion_id: str, tipo: str, objetivo: Any) -> list[list[str]]:
        if not isinstance(accion_id, str) or not ACCION_ID.match(accion_id):
            raise Rechazo("accion_id inválido")
        etiqueta = ["-m", "comment", "--comment", f"minisoc {accion_id} {tipo}"]
        if tipo == "bloquear_ip":
            try:
                ip = ipaddress.ip_address(objetivo)
            except (ValueError, TypeError):
                raise Rechazo(f"objetivo no es una IP: {objetivo!r}") from None
            if ip.version != 4:
                raise Rechazo("solo IPv4")
            if any(ip in r for r in self.redes):
                raise Rechazo(f"{ip} es de una red protegida: un host interno se aísla, no se bloquea")
            return [["-s", str(ip), *etiqueta, "-j", "DROP"],
                    ["-d", str(ip), *etiqueta, "-j", "DROP"]]
        if tipo == "aislar_host":
            if objetivo in self.hosts_protegidos:
                raise Rechazo(f"{objetivo} es un host protegido: aislarlo cortaría la gestión o el SOC")
            if objetivo not in self.hosts:
                raise Rechazo(f"host desconocido: {objetivo!r}")
            ip = self.hosts[objetivo]
            # RETURN deja que las reglas normales decidan. Se mantienen dos cosas:
            # - gestión puede seguir entrando por SSH para investigar;
            # - el sensor sigue mandando telemetría: un host aislado es justo el que
            #   más interesa seguir viendo.
            # Todo lo demás se corta.
            return [["-s", GESTION, "-d", ip, "-p", "tcp", "--dport", "22", *etiqueta, "-j", "RETURN"],
                    ["-s", ip, "-d", GESTION, "-p", "tcp", "--sport", "22", *etiqueta, "-j", "RETURN"],
                    ["-s", ip, "-d", INGESTA, "-p", "tcp", "--dport", "8081", *etiqueta, "-j", "RETURN"],
                    ["-s", INGESTA, "-d", ip, "-p", "tcp", "--sport", "8081", *etiqueta, "-j", "RETURN"],
                    ["-s", ip, *etiqueta, "-j", "DROP"],
                    ["-d", ip, *etiqueta, "-j", "DROP"]]
        raise Rechazo(f"acción no permitida: {tipo!r}")

    # --------------------------------------------------------------- estado
    def listar(self) -> dict[str, list[str]]:
        """Reglas actuales de la cadena, agrupadas por accion_id."""
        por_accion: dict[str, list[str]] = {}
        for linea in self.ejecutar(["-S", CADENA]).splitlines():
            if not linea.startswith(f"-A {CADENA} "):
                continue
            partes = shlex.split(linea)
            if "--comment" in partes:
                comentario = partes[partes.index("--comment") + 1].split()
                if len(comentario) >= 2 and comentario[0] == "minisoc":
                    por_accion.setdefault(comentario[1], []).append(linea)
        return por_accion

    # ------------------------------------------------------------- acciones
    def aplicar(self, accion_id: str, tipo: str, objetivo: Any) -> dict[str, Any]:
        reglas = self._reglas(accion_id, tipo, objetivo)
        with self._lock:
            if accion_id in self.listar():
                return {"accion_id": accion_id, "estado": "ya_aplicada"}
            aplicadas = []
            try:
                for r in reglas:
                    self.ejecutar(["-A", CADENA, *r])
                    aplicadas.append(r)
            except RuntimeError:
                # Todo o nada: una acción a medias es peor que ninguna.
                for r in aplicadas:
                    try:
                        self.ejecutar(["-D", CADENA, *r])
                    except RuntimeError:
                        log.exception("no se pudo deshacer una regla parcial de %s", accion_id)
                raise
        log.info("%s aplicada: %s %s (%d reglas)", accion_id, tipo, objetivo, len(reglas))
        return {"accion_id": accion_id, "estado": "aplicada", "reglas": len(reglas)}

    def revertir(self, accion_id: str) -> dict[str, Any]:
        if not isinstance(accion_id, str) or not ACCION_ID.match(accion_id):
            raise Rechazo("accion_id inválido")
        with self._lock:
            lineas = self.listar().get(accion_id, [])
            for linea in lineas:
                partes = shlex.split(linea)
                self.ejecutar(["-D", *partes[1:]])
        log.info("%s revertida (%d reglas)", accion_id, len(lineas))
        return {"accion_id": accion_id, "estado": "revertida" if lineas else "no_estaba", "reglas": len(lineas)}


def crear_servidor(contencion: Contencion, host: str, puerto: int, token: str, ip_respondedor: str) -> ThreadingHTTPServer:
    class Manejador(BaseHTTPRequestHandler):
        server_version = "minisoc-contencion/0.1"

        def log_message(self, fmt: str, *args: Any) -> None:
            log.debug("%s %s", self.address_string(), fmt % args)

        def _responder(self, codigo: int, cuerpo: Any) -> None:
            datos = json.dumps(cuerpo, ensure_ascii=False).encode()
            self.send_response(codigo)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(datos)))
            self.end_headers()
            self.wfile.write(datos)

        def _autorizado(self) -> bool:
            if self.client_address[0] != ip_respondedor:
                self._responder(403, {"error": "solo el respondedor puede pedir contención"})
                return False
            recibido = self.headers.get("Authorization", "")
            if not token or not hmac.compare_digest(recibido.encode(), f"Bearer {token}".encode()):
                self._responder(401, {"error": "token inválido o ausente"})
                return False
            return True

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/salud":
                return self._responder(200, {"estado": "ok"})
            if self.path != "/v1/contencion":
                return self._responder(404, {"error": "ruta no encontrada"})
            if self._autorizado():
                self._responder(200, contencion.listar())

        def do_POST(self) -> None:  # noqa: N802
            if self.path not in ("/v1/aplicar", "/v1/revertir"):
                return self._responder(404, {"error": "ruta no encontrada"})
            if not self._autorizado():
                return
            try:
                largo = min(int(self.headers.get("Content-Length") or 0), 10_000)
                pedido = json.loads(self.rfile.read(largo) or b"{}")
                if not isinstance(pedido, dict):
                    raise Rechazo("se esperaba un objeto JSON")
                if self.path == "/v1/aplicar":
                    r = contencion.aplicar(pedido.get("accion_id"), pedido.get("tipo"), pedido.get("objetivo"))
                else:
                    r = contencion.revertir(pedido.get("accion_id"))
                self._responder(200, r)
            except (Rechazo, json.JSONDecodeError) as e:
                log.warning("pedido rechazado: %s", e)
                self._responder(422, {"error": str(e)})
            except RuntimeError as e:
                log.error("falló iptables: %s", e)
                self._responder(500, {"error": str(e)})

    return ThreadingHTTPServer((host, puerto), Manejador)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    token = os.environ.get("CONTENCION_TOKEN", "")
    if not token:
        # Sin token no hay contención: es la única puerta para cambiar la red.
        log.error("CONTENCION_TOKEN vacío: el servicio de contención rechaza todo (correr ./preparar.sh)")
    host = os.environ.get("CONTENCION_HOST", "10.30.0.254")
    puerto = int(os.environ.get("CONTENCION_PUERTO", "9000"))
    ip_respondedor = os.environ.get("RESPONDEDOR_IP", "10.30.0.30")
    servidor = crear_servidor(Contencion(), host, puerto, token, ip_respondedor)
    log.info("contención escuchando en %s:%d, solo para %s", host, puerto, ip_respondedor)
    servidor.serve_forever()


if __name__ == "__main__":
    main()
