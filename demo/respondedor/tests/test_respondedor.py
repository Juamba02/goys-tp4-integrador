"""Ciclo del respondedor con un agente y un router falsos."""
from minisoc_respondedor.clientes import SinRespuesta
from minisoc_respondedor.servicio import MAX_INTENTOS, Respondedor


class AgenteFalso:
    def __init__(self, acciones):
        self.acciones = {a["accion_id"]: dict(a, estado="aprobada") for a in acciones}
        self.marcadas = []
        self.caido = False

    def aprobadas(self):
        if self.caido:
            raise SinRespuesta("agente caído")
        return [a for a in self.acciones.values() if a["estado"] == "aprobada"]

    def ejecutada(self, aid, ok, detalle=""):
        if self.caido:
            raise SinRespuesta("agente caído")
        a = self.acciones[aid]
        if a["estado"] != "aprobada":
            return 409, {"error": "ya no está aprobada"}
        a["estado"] = "ejecutada" if ok else "fallida"
        self.marcadas.append((aid, ok, detalle))
        return 200, a


class RouterFalso:
    def __init__(self, respuestas=None):
        self.aplicadas = {}
        self.respuestas = list(respuestas or [])
        self.pedidos = 0

    def aplicar(self, aid, tipo, objetivo):
        self.pedidos += 1
        if self.respuestas:
            r = self.respuestas.pop(0)
            if isinstance(r, Exception):
                raise r
            return r
        if aid in self.aplicadas:
            return 200, {"accion_id": aid, "estado": "ya_aplicada"}
        self.aplicadas[aid] = (tipo, objetivo)
        return 200, {"accion_id": aid, "estado": "aplicada", "reglas": 2}

    def revertir(self, aid):
        estado = "revertida" if self.aplicadas.pop(aid, None) else "no_estaba"
        return 200, {"accion_id": aid, "estado": estado}


BLOQUEO = {"accion_id": "ACC-0001", "tipo": "bloquear_ip", "objetivo": "10.99.0.66"}


def test_aplica_y_avisa():
    agente, router = AgenteFalso([BLOQUEO]), RouterFalso()
    r = Respondedor(agente, router)
    assert r.ciclo() == 1
    assert router.aplicadas == {"ACC-0001": ("bloquear_ip", "10.99.0.66")}
    assert agente.marcadas == [("ACC-0001", True, "aplicada en el router")]
    assert r.ciclo() == 0  # ya no está aprobada


def test_solo_toma_las_aprobadas():
    agente = AgenteFalso([BLOQUEO])
    agente.acciones["ACC-0001"]["estado"] = "pendiente"  # el analista todavía no decidió
    router = RouterFalso()
    assert Respondedor(agente, router).ciclo() == 0
    assert router.pedidos == 0


def test_rechazo_del_router_se_informa_como_fallida():
    agente = AgenteFalso([BLOQUEO])
    router = RouterFalso([(422, {"error": "10.20.0.11 es de una red protegida"})])
    Respondedor(agente, router).ciclo()
    aid, ok, detalle = agente.marcadas[0]
    assert (aid, ok) == ("ACC-0001", False) and "red protegida" in detalle


def test_router_caido_no_marca_nada_y_reintenta():
    agente = AgenteFalso([BLOQUEO])
    router = RouterFalso([SinRespuesta("timeout")])
    r = Respondedor(agente, router)
    assert r.ciclo() == 0
    assert agente.marcadas == []
    assert r.ciclo() == 1  # el router volvió
    assert agente.marcadas[0][1] is True


def test_corte_entre_aplicar_y_avisar_no_duplica():
    agente, router = AgenteFalso([BLOQUEO]), RouterFalso()
    r = Respondedor(agente, router)
    # El agente se cae justo después de que el router aplicó.
    original = agente.ejecutada

    def caerse(*a, **k):
        agente.ejecutada = original
        raise SinRespuesta("agente caído")
    agente.ejecutada = caerse
    assert r.ciclo() == 0
    assert router.aplicadas  # quedó aplicada
    assert r.ciclo() == 1    # siguiente ciclo: el router dice ya_aplicada y se avisa
    assert agente.marcadas == [("ACC-0001", True, "ya_aplicada en el router")]


def test_iptables_falla_varias_veces_y_se_da_por_fallida():
    agente = AgenteFalso([BLOQUEO])
    router = RouterFalso([(500, {"error": "iptables: falla"})] * MAX_INTENTOS)
    r = Respondedor(agente, router)
    for _ in range(MAX_INTENTOS - 1):
        assert r.ciclo() == 0
    assert r.ciclo() == 1
    assert agente.marcadas[0][1] is False


def test_token_mal_configurado_no_marca_fallida():
    # 401 no es culpa de la acción: no se la marca como fallida, se espera a que se arregle.
    agente = AgenteFalso([BLOQUEO])
    router = RouterFalso([(401, {"error": "token"})])
    r = Respondedor(agente, router)
    assert r.ciclo() == 0
    assert agente.marcadas == []


def test_agente_caido():
    agente = AgenteFalso([BLOQUEO])
    agente.caido = True
    r = Respondedor(agente, RouterFalso())
    assert r.ciclo() == 0
    assert "minisoc_respondedor_errores_total 1" in r.metricas()


def test_revertir_y_metricas():
    agente, router = AgenteFalso([BLOQUEO]), RouterFalso()
    r = Respondedor(agente, router)
    r.ciclo()
    assert r.revertir("ACC-0001")["estado"] == "revertida"
    m = r.metricas()
    assert 'minisoc_respondedor_acciones_total{tipo="bloquear_ip",resultado="ok"} 1' in m
    assert 'minisoc_respondedor_acciones_total{tipo="reversion",resultado="revertida"} 1' in m
