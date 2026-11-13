import json

from minisoc_agente.ledger import Ledger


def _llenar(ledger, n=3):
    for i in range(n):
        ledger.registrar("prueba", f"INC-{i}", {"i": i})


def test_cadena_valida(tmp_path):
    led = Ledger(tmp_path / "l.jsonl")
    _llenar(led)
    res = led.verificar()
    assert res.integro and res.entradas == 3


def test_ledger_vacio_es_integro(tmp_path):
    assert Ledger(tmp_path / "l.jsonl").verificar().integro


def test_modificar_contenido_rompe_la_cadena(tmp_path):
    ruta = tmp_path / "l.jsonl"
    led = Ledger(ruta)
    _llenar(led)
    lineas = ruta.read_text(encoding="utf-8").splitlines()
    entrada = json.loads(lineas[1])
    entrada["datos"]["i"] = 999
    lineas[1] = json.dumps(entrada)
    ruta.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    res = Ledger(ruta).verificar()
    assert not res.integro and res.error_en_seq == 2


def test_borrar_una_linea_rompe_la_cadena(tmp_path):
    ruta = tmp_path / "l.jsonl"
    _llenar(Ledger(ruta))
    lineas = ruta.read_text(encoding="utf-8").splitlines()
    del lineas[1]
    ruta.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    assert not Ledger(ruta).verificar().integro


def test_recalcular_hashes_sin_la_clave_no_alcanza(tmp_path):
    ruta = tmp_path / "l.jsonl"
    _llenar(Ledger(ruta, clave="secreta"))
    # Un atacante sin la clave reescribe el ledger con SHA-256 "válido".
    falso = tmp_path / "falso.jsonl"
    _llenar(Ledger(falso))
    ruta.write_text(falso.read_text(encoding="utf-8"), encoding="utf-8")
    assert not Ledger(ruta, clave="secreta").verificar().integro


def test_reabrir_continua_la_cadena(tmp_path):
    ruta = tmp_path / "l.jsonl"
    _llenar(Ledger(ruta), 2)
    led = Ledger(ruta)
    assert led.cantidad == 2
    e = led.registrar("prueba", None, {})
    assert e["seq"] == 3
    assert led.verificar().integro


def test_filtrar_por_incidente(tmp_path):
    led = Ledger(tmp_path / "l.jsonl")
    _llenar(led)
    assert [e["seq"] for e in led.entradas("INC-1")] == [2]
