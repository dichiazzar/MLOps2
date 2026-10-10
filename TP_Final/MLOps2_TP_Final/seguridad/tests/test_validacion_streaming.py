import uuid
from datetime import datetime, timedelta, timezone

from app import seguridad as s
from app.validacion import validar_evento

CLAVES = {"concesionaria-norte": "clave-n"}
AUTO = {
    "name": "Maruti Swift Dzire VDI", "year": 2014, "km_driven": 145500,
    "fuel": "Diesel", "seller_type": "Individual", "transmission": "Manual",
    "owner": "First Owner", "mileage": "23.4 kmpl", "engine": "1248 CC",
    "max_power": "74 bhp", "torque": "190Nm@ 2000rpm", "seats": 5.0,
}


def ev(**cambios):
    e = {**AUTO, "_event_time": 1.0, "_productor": "concesionaria-norte", "_id": uuid.uuid4().hex,
         "_ts": datetime.now(timezone.utc).isoformat()}
    e.update(cambios)
    e["_firma"] = s.firmar(e, CLAVES.get(e["_productor"], "otra"))
    return e


def test_ok():
    car, destino, motivo = validar_evento(ev(), CLAVES, s.VistosRecientes(), None)
    assert destino == "ok" and car.km_driven == 145500 and motivo is None


def test_firma_y_productor():
    alterado = ev()
    alterado["km_driven"] = 1
    assert validar_evento(alterado, CLAVES, s.VistosRecientes(), None)[1] == "dlq_firma"
    assert validar_evento(ev(_productor="trucha"), CLAVES, s.VistosRecientes(), None)[1] == "dlq_firma"


def test_replay():
    vistos = s.VistosRecientes()
    e = ev()
    assert validar_evento(e, CLAVES, vistos, None)[1] == "ok"
    assert validar_evento(e, CLAVES, vistos, None)[1] == "dlq_replay"
    viejo = ev(_ts=(datetime.now(timezone.utc) - timedelta(days=2)).isoformat())
    assert validar_evento(viejo, CLAVES, vistos, None)[1] == "dlq_replay"


def test_evento_sin_id():
    e = ev()
    del e["_id"]
    e["_firma"] = s.firmar(e, "clave-n")
    assert validar_evento(e, CLAVES, s.VistosRecientes(), None)[1] == "dlq_replay"


def test_esquema():
    car, destino, motivo = validar_evento(ev(year=3000), CLAVES, s.VistosRecientes(), None)
    assert car is None and destino == "dlq_esquema" and "year" in motivo


def test_no_es_dict():
    assert validar_evento("basura", CLAVES, s.VistosRecientes(), None)[1] == "dlq_esquema"
