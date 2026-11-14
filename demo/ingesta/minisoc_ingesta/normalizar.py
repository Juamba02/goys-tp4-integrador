"""Normalización: de lo que manda cada sensor al esquema común del MiniSOC-IA.

El esquema de salida es el mismo que el contrato del agente usa para los eventos de
un incidente (`evento_id`, `ts`, `host`, `tipo`, `datos`), más lo que agrega la
ingesta: el segmento del host, el segmento del otro extremo de una conexión y las
IPs que aparecen dentro de una línea de comando.

La regla de fondo: el sensor corre en un host que puede estar comprometido, así que
todo lo que manda es un dato a validar, no una verdad.
"""
from __future__ import annotations

import ipaddress
import re
from datetime import datetime, timezone
from typing import Any

SEGMENTOS_POR_DEFECTO = {
    "gestion": "10.10.0.0/24",
    "servicios": "10.20.0.0/24",
    "soc": "10.30.0.0/24",
    "externo": "10.99.0.0/24",
}

TIPOS = {"proceso", "conexion"}
DIRECCIONES = {"entrante", "saliente"}
ESTADOS = {"establecida", "syn_enviado"}
MAX_TEXTO = 2000  # una línea de comando más larga se trunca
# Sin letras, dígitos ni puntos pegados: así "python3.12.0.1" no cuenta como IP.
IP_EN_TEXTO = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")


class EventoInvalido(ValueError):
    pass


def ahora_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class Segmentos:
    def __init__(self, segmentos: dict[str, str] | None = None) -> None:
        self.redes = [(n, ipaddress.ip_network(r)) for n, r in (segmentos or SEGMENTOS_POR_DEFECTO).items()]

    def de(self, ip: str) -> str:
        try:
            direccion = ipaddress.ip_address(ip)
        except ValueError:
            return "desconocido"
        for nombre, red in self.redes:
            if direccion.version == red.version and direccion in red:
                return nombre
        return "fuera_del_laboratorio"


def _ts(valor: Any, recibido: str) -> str:
    """El ts del sensor si es válido y no está en el futuro; si no, el de recepción."""
    if isinstance(valor, str):
        try:
            ts = datetime.fromisoformat(valor.replace("Z", "+00:00"))
            if ts.tzinfo is not None and ts <= datetime.now(timezone.utc):
                return ts.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        except ValueError:
            pass
    return recibido


def _texto(valor: Any, campo: str) -> str:
    if not isinstance(valor, str):
        raise EventoInvalido(f"'{campo}' debe ser texto")
    # Sin caracteres de control: no se los queremos pasar ni a la consola ni al modelo.
    limpio = "".join(c if c.isprintable() else " " for c in valor)
    return limpio[:MAX_TEXTO]


def _entero(valor: Any, campo: str, minimo: int = 0, maximo: int = 2**31) -> int:
    if not isinstance(valor, int) or isinstance(valor, bool) or not minimo <= valor <= maximo:
        raise EventoInvalido(f"'{campo}' debe ser un entero entre {minimo} y {maximo}")
    return valor


def _ip(valor: Any, campo: str) -> str:
    try:
        return str(ipaddress.ip_address(valor))
    except (ValueError, TypeError):
        raise EventoInvalido(f"'{campo}' debe ser una IP") from None


def ips_en(texto: str) -> list[str]:
    encontradas: list[str] = []
    for candidato in IP_EN_TEXTO.findall(texto):
        try:
            ip = str(ipaddress.ip_address(candidato))
        except ValueError:
            continue
        if ip not in encontradas:
            encontradas.append(ip)
    return encontradas


def normalizar(crudo: Any, host: str, segmentos: Segmentos, recibido: str | None = None) -> dict[str, Any]:
    """Devuelve el evento normalizado (sin evento_id, que lo pone el almacén).

    `host` es el host que la ingesta ya verificó para el lote: un evento no puede
    decir que viene de otro host.
    """
    recibido = recibido or ahora_iso()
    if not isinstance(crudo, dict):
        raise EventoInvalido("el evento debe ser un objeto")
    if crudo.get("host", host) != host:
        raise EventoInvalido(f"el evento dice venir de {crudo.get('host')!r} pero llegó del sensor de {host}")
    tipo = crudo.get("tipo")
    if tipo not in TIPOS:
        raise EventoInvalido(f"'tipo' debe ser uno de {sorted(TIPOS)}")
    d = crudo.get("datos")
    if not isinstance(d, dict):
        raise EventoInvalido("'datos' debe ser un objeto")

    if tipo == "proceso":
        cmdline = _texto(d.get("cmdline"), "cmdline")
        datos: dict[str, Any] = {
            "pid": _entero(d.get("pid"), "pid", 1),
            "ppid": _entero(d.get("ppid"), "ppid", 0),
            "proceso": _texto(d.get("proceso"), "proceso")[:64],
            "padre": _texto(d.get("padre"), "padre")[:64],
            "cmdline": cmdline,
            "usuario": _texto(d.get("usuario"), "usuario")[:64],
        }
        if d.get("exec") is True:
            datos["exec"] = True
        if len(d["cmdline"]) > MAX_TEXTO:
            datos["cmdline_truncada"] = True
        # El contrato del agente solo acepta bloquear una IP que esté sola en un campo:
        # las que aparecen dentro del comando se copian acá.
        ips = ips_en(cmdline)
        if ips:
            datos["ips_mencionadas"] = ips
            datos["segmentos_mencionados"] = sorted({segmentos.de(ip) for ip in ips})
    else:
        direccion = d.get("direccion")
        if direccion not in DIRECCIONES:
            raise EventoInvalido(f"'direccion' debe ser una de {sorted(DIRECCIONES)}")
        estado = d.get("estado")
        if estado not in ESTADOS:
            raise EventoInvalido(f"'estado' debe ser uno de {sorted(ESTADOS)}")
        datos = {
            "direccion": direccion,
            "ip_origen": _ip(d.get("ip_origen"), "ip_origen"),
            "puerto_origen": _entero(d.get("puerto_origen"), "puerto_origen", 0, 65535),
            "ip_destino": _ip(d.get("ip_destino"), "ip_destino"),
            "puerto_destino": _entero(d.get("puerto_destino"), "puerto_destino", 0, 65535),
            "estado": estado,
        }
        remota = datos["ip_destino"] if direccion == "saliente" else datos["ip_origen"]
        datos["segmento_remoto"] = segmentos.de(remota)

    return {
        "ts": _ts(crudo.get("ts"), recibido),
        "ts_recibido": recibido,
        "host": host,
        "segmento": None,  # lo completa el servicio con el segmento del sensor
        "tipo": tipo,
        "datos": datos,
    }
