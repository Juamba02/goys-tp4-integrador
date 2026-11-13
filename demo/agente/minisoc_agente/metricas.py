"""Métricas en formato de texto de Prometheus, sin dependencias externas."""

from __future__ import annotations

import threading
from typing import Callable

Etiquetas = tuple[tuple[str, str], ...]


def _fmt_etiquetas(etq: Etiquetas, extra: tuple[tuple[str, str], ...] = ()) -> str:
    todas = etq + extra
    if not todas:
        return ""
    partes = []
    for k, v in todas:
        v = str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        partes.append(f'{k}="{v}"')
    return "{" + ",".join(partes) + "}"


def _fmt_num(x: float) -> str:
    x = float(x)
    if x == float("inf"):
        return "+Inf"
    return str(int(x)) if x.is_integer() else repr(x)


class _Metrica:
    tipo = ""

    def __init__(self, nombre: str, ayuda: str) -> None:
        self.nombre = nombre
        self.ayuda = ayuda
        self._lock = threading.Lock()

    def encabezado(self) -> list[str]:
        return [f"# HELP {self.nombre} {self.ayuda}", f"# TYPE {self.nombre} {self.tipo}"]


class Contador(_Metrica):
    tipo = "counter"

    def __init__(self, nombre: str, ayuda: str) -> None:
        super().__init__(nombre, ayuda)
        self._valores: dict[Etiquetas, float] = {}

    def inc(self, valor: float = 1.0, **etiquetas: str) -> None:
        clave = tuple(sorted(etiquetas.items()))
        with self._lock:
            self._valores[clave] = self._valores.get(clave, 0.0) + valor

    def valor(self, **etiquetas: str) -> float:
        return self._valores.get(tuple(sorted(etiquetas.items())), 0.0)

    def exponer(self) -> list[str]:
        with self._lock:
            items = sorted(self._valores.items())
        if not items and not self.con_etiquetas:
            items = [((), 0.0)]
        return self.encabezado() + [f"{self.nombre}{_fmt_etiquetas(k)} {_fmt_num(v)}" for k, v in items]

    con_etiquetas = False


class ContadorConEtiquetas(Contador):
    """Contador que no expone ninguna serie hasta que se incrementa alguna etiqueta."""

    con_etiquetas = True


class Medidor(_Metrica):
    tipo = "gauge"

    def __init__(self, nombre: str, ayuda: str, funcion: Callable[[], float]) -> None:
        super().__init__(nombre, ayuda)
        self._funcion = funcion

    def exponer(self) -> list[str]:
        return self.encabezado() + [f"{self.nombre} {_fmt_num(self._funcion())}"]


class Histograma(_Metrica):
    tipo = "histogram"

    def __init__(self, nombre: str, ayuda: str, limites: list[float]) -> None:
        super().__init__(nombre, ayuda)
        self.limites = sorted(limites) + [float("inf")]
        self._cuentas = [0] * len(self.limites)
        self._suma = 0.0
        self._total = 0

    def observar(self, valor: float) -> None:
        with self._lock:
            for i, lim in enumerate(self.limites):
                if valor <= lim:
                    self._cuentas[i] += 1
            self._suma += valor
            self._total += 1

    def exponer(self) -> list[str]:
        with self._lock:
            lineas = self.encabezado()
            for lim, c in zip(self.limites, self._cuentas):
                lineas.append(f'{self.nombre}_bucket{{le="{_fmt_num(lim)}"}} {c}')
            lineas.append(f"{self.nombre}_sum {_fmt_num(self._suma)}")
            lineas.append(f"{self.nombre}_count {self._total}")
        return lineas


class Registro:
    def __init__(self) -> None:
        self._metricas: list[_Metrica] = []

    def agregar(self, m: _Metrica) -> _Metrica:
        self._metricas.append(m)
        return m

    def exponer(self) -> str:
        lineas: list[str] = []
        for m in self._metricas:
            lineas += m.exponer()
        return "\n".join(lineas) + "\n"


class MetricasAgente:
    def __init__(self, acciones_pendientes: Callable[[], float], ledger_entradas: Callable[[], float],
                 ledger_integro: Callable[[], float]) -> None:
        r = self.registro = Registro()
        self.incidentes = r.agregar(Contador("minisoc_agente_incidentes_total", "Incidentes recibidos y analizados"))
        self.veredictos = r.agregar(ContadorConEtiquetas("minisoc_agente_veredictos_total", "Veredictos emitidos por tipo"))
        self.revision = r.agregar(ContadorConEtiquetas("minisoc_agente_revision_humana_total", "Incidentes derivados a revisión humana, por motivo"))
        self.evaluacion = r.agregar(ContadorConEtiquetas("minisoc_agente_evaluacion_total", "Veredicto contra la etiqueta esperada (VP, FP, VN, FN, indeterminado)"))
        self.latencia = r.agregar(Histograma("minisoc_agente_latencia_veredicto_segundos", "Tiempo que tarda el agente en emitir el veredicto",
                                             [0.1, 0.5, 1, 2, 5, 10, 20, 30, 60, 120]))
        self.evento_a_veredicto = r.agregar(Histograma("minisoc_agente_evento_a_veredicto_segundos", "Tiempo desde el primer evento del incidente hasta el veredicto",
                                                       [1, 5, 10, 30, 60, 120, 300, 600, 1800]))
        self.acciones = r.agregar(ContadorConEtiquetas("minisoc_agente_acciones_total", "Acciones de contención por tipo y estado alcanzado"))
        self.errores_llm = r.agregar(Contador("minisoc_agente_llm_errores_total", "Fallas al consultar el modelo o interpretar su respuesta"))
        r.agregar(Medidor("minisoc_agente_acciones_pendientes", "Acciones esperando aprobación humana", acciones_pendientes))
        r.agregar(Medidor("minisoc_agente_ledger_entradas", "Entradas escritas en el ledger", ledger_entradas))
        r.agregar(Medidor("minisoc_agente_ledger_integro", "1 si la cadena de hashes del ledger verifica, 0 si no", ledger_integro))

    def exponer(self) -> str:
        return self.registro.exponer()
