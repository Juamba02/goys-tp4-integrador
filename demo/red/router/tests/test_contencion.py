"""Servicio de contención del router, con un iptables falso que imita la salida real
de `iptables -S` (agrega /32 a las IPs y pone el comentario entre comillas)."""
import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import contencion as c  # noqa: E402


class IptablesFalso:
    def __init__(self, fallar_en=None):
        self.reglas = []          # cada regla: lista de args después de la cadena
        self.llamadas = []
        self.fallar_en = fallar_en

    @staticmethod
    def _norm(args):
        return [a[:-3] if a.endswith("/32") else a for a in args]

    def __call__(self, args):
        self.llamadas.append(args)
        accion, cadena, resto = args[0], args[1], args[2:]
        if accion == "-S":
            lineas = [f"-N {cadena}"]
            for r in self.reglas:
                partes = []
                for i, a in enumerate(r):
                    if i > 0 and r[i - 1] == "--comment":
                        partes.append(f'"{a}"')
                    elif i > 0 and r[i - 1] in ("-s", "-d") and "/" not in a:
                        partes.append(a + "/32")
                    else:
                        partes.append(a)
                lineas.append(f"-A {cadena} " + " ".join(partes))
            return "\n".join(lineas) + "\n"
        if (accion == "-A" and self.fallar_en is not None
                and len([x for x in self.llamadas if x[0] == "-A"]) == self.fallar_en):
            raise RuntimeError("iptables: falla simulada")
        if accion == "-A":
            self.reglas.append(resto)
        elif accion == "-D":
            # Como el real: borra la primera regla igual, y si no hay ninguna, falla.
            objetivo = self._norm(resto)
            for i, r in enumerate(self.reglas):
                if self._norm(r) == objetivo:
                    del self.reglas[i]
                    break
            else:
                raise RuntimeError("iptables: Bad rule (does a matching rule exist in that chain?)")
        return ""


@pytest.fixture
def ipt():
    return IptablesFalso()


@pytest.fixture
def cont(ipt):
    return c.Contencion(ipt)


def test_bloquear_ip_corta_los_dos_sentidos(cont, ipt):
    assert cont.aplicar("ACC-0001", "bloquear_ip", "10.99.0.66") == {"accion_id": "ACC-0001", "estado": "aplicada", "reglas": 2}
    assert [r[:2] for r in ipt.reglas] == [["-s", "10.99.0.66"], ["-d", "10.99.0.66"]]
    assert all(r[-2:] == ["-j", "DROP"] for r in ipt.reglas)
    assert list(cont.listar()) == ["ACC-0001"]


def test_aplicar_dos_veces_no_duplica(cont, ipt):
    cont.aplicar("ACC-0001", "bloquear_ip", "10.99.0.66")
    assert cont.aplicar("ACC-0001", "bloquear_ip", "10.99.0.66")["estado"] == "ya_aplicada"
    assert len(ipt.reglas) == 2


def test_aislar_deja_entrar_a_gestion_y_salir_la_telemetria(cont, ipt):
    cont.aplicar("ACC-0002", "aislar_host", "web-01")
    assert len(ipt.reglas) == 6
    retorno = [r[:8] for r in ipt.reglas if r[-1] == "RETURN"]
    assert ["-s", "10.10.0.0/24", "-d", "10.20.0.11", "-p", "tcp", "--dport", "22"] in retorno
    assert ["-s", "10.20.0.11", "-d", "10.30.0.10", "-p", "tcp", "--dport", "8081"] in retorno
    # Las RETURN van antes que las DROP: si no, también quedarían afuera.
    assert [r[-1] for r in ipt.reglas] == ["RETURN"] * 4 + ["DROP", "DROP"]


def test_revertir_saca_exactamente_lo_de_esa_accion(cont, ipt):
    cont.aplicar("ACC-0001", "bloquear_ip", "10.99.0.66")
    cont.aplicar("ACC-0002", "aislar_host", "api-01")
    assert cont.revertir("ACC-0002") == {"accion_id": "ACC-0002", "estado": "revertida", "reglas": 6}
    assert list(cont.listar()) == ["ACC-0001"]
    assert cont.revertir("ACC-0002")["estado"] == "no_estaba"


@pytest.mark.parametrize("tipo, objetivo, mensaje", [
    ("bloquear_ip", "10.20.0.11", "red protegida"),      # un servicio interno se aísla, no se bloquea
    ("bloquear_ip", "10.10.0.5", "red protegida"),       # el espejo de gestión
    ("bloquear_ip", "10.99.0.66; reboot", "no es una IP"),
    ("bloquear_ip", "::1", "IPv4"),
    ("aislar_host", "ansible", "protegido"),
    ("aislar_host", "router", "protegido"),
    ("aislar_host", "agente", "protegido"),
    ("aislar_host", "web-02", "desconocido"),
    ("borrar_todo", "x", "no permitida"),
])
def test_rechaza_aunque_venga_autenticado(cont, ipt, tipo, objetivo, mensaje):
    with pytest.raises(c.Rechazo, match=mensaje):
        cont.aplicar("ACC-0003", tipo, objetivo)
    assert ipt.reglas == []


@pytest.mark.parametrize("accion_id", ["ACC-1; iptables -F", "acc-1", "", None, "ACC-123456789"])
def test_accion_id_invalido(cont, accion_id):
    with pytest.raises(c.Rechazo):
        cont.aplicar(accion_id, "bloquear_ip", "10.99.0.66")


def test_todo_o_nada_si_iptables_falla_a_la_mitad():
    ipt = IptablesFalso(fallar_en=2)  # falla en la segunda regla
    cont = c.Contencion(ipt)
    with pytest.raises(RuntimeError):
        cont.aplicar("ACC-0004", "bloquear_ip", "10.99.0.66")
    assert ipt.reglas == []


def test_api_solo_respondedor_con_token(cont):
    srv = c.crear_servidor(cont, "127.0.0.1", 0, "secreto", "127.0.0.1")
    otro = c.crear_servidor(cont, "127.0.0.1", 0, "secreto", "10.30.0.30")
    for s in (srv, otro):
        threading.Thread(target=s.serve_forever, daemon=True).start()

    def post(servidor, cuerpo, token="secreto"):
        pedido = urllib.request.Request(f"http://127.0.0.1:{servidor.server_address[1]}/v1/aplicar",
                                        json.dumps(cuerpo).encode(),
                                        {"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(pedido) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    try:
        ok = {"accion_id": "ACC-0001", "tipo": "bloquear_ip", "objetivo": "10.99.0.66"}
        assert post(srv, ok)[0] == 200
        assert post(srv, ok, token="otro")[0] == 401
        assert post(otro, ok)[0] == 403                 # no viene de la IP del respondedor
        assert post(srv, {**ok, "objetivo": "10.30.0.20"})[0] == 422
    finally:
        for s in (srv, otro):
            s.shutdown()
            s.server_close()


def test_sin_token_configurado_rechaza_todo(cont):
    srv = c.crear_servidor(cont, "127.0.0.1", 0, "", "127.0.0.1")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    pedido = urllib.request.Request(f"http://127.0.0.1:{srv.server_address[1]}/v1/aplicar", b"{}",
                                    {"Authorization": "Bearer "})
    try:
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(pedido)
        assert e.value.code == 401
    finally:
        srv.shutdown()
        srv.server_close()
