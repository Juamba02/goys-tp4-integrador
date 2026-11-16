#!/usr/bin/env python3
"""probar IP PUERTO: intenta una conexión TCP e informa qué pasó.

Distingue tres resultados, porque no es lo mismo que la red bloquee el paquete
a que llegue y nadie escuche:

  abierto    la conexión se estableció                       (salida 0)
  rechazado  llegó al host pero el puerto está cerrado (RST) (salida 1)
  bloqueado  no hubo respuesta: el firewall lo descartó      (salida 2)
"""
import socket
import sys


def probar(ip: str, puerto: int, timeout: float = 2.0) -> str:
    try:
        with socket.create_connection((ip, puerto), timeout=timeout):
            return "abierto"
    except ConnectionRefusedError:
        return "rechazado"
    except (socket.timeout, TimeoutError, OSError):
        return "bloqueado"


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        return 64
    resultado = probar(sys.argv[1], int(sys.argv[2]))
    print(resultado)
    return {"abierto": 0, "rechazado": 1, "bloqueado": 2}[resultado]


if __name__ == "__main__":
    sys.exit(main())
