import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import seguridad as s
from app.seguridad_rest import SeguridadREST

AUTO = {
    "name": "Maruti Swift Dzire VDI", "year": 2014, "km_driven": 145500,
    "fuel": "Diesel", "seller_type": "Individual", "transmission": "Manual",
    "owner": "First Owner", "mileage": "23.4 kmpl", "engine": "1248 CC",
    "max_power": "74 bhp", "torque": "190Nm@ 2000rpm", "seats": 5,
}


def _api():
    api = FastAPI()

    @api.get("/health")
    def health():
        return {"status": "ok"}

    @api.post("/predict")
    def predict(car: dict):
        return {"predicted_price": 1.0, "model_version": "1", "eco": car["name"]}

    @api.get("/model/info")
    def info():
        return {"model_name": "xgb_best"}

    @api.get("/predictions/recent")
    def recent():
        return []

    return api


@pytest.fixture
def entorno():
    eventos = []

    class AuditorFalso:
        def registrar(self, identidad, accion, resultado, **kw):
            eventos.append((identidad.usuario if identidad else None, accion, str(resultado)))

    app = SeguridadREST(_api(), auditor=AuditorFalso(), limite=s.LimiteDeTasa(n=3))
    return TestClient(app), eventos


def h(rol="analista", usuario="jaime"):
    return {"Authorization": f"Bearer {s.emitir_token(usuario, rol)}"}


def test_health_publico(entorno):
    cli, eventos = entorno
    assert cli.get("/health").status_code == 200
    assert eventos == []                                   # lo público no se audita


def test_sin_token_401(entorno):
    cli, eventos = entorno
    r = cli.post("/predict", json=AUTO)
    assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"
    assert eventos == [(None, "predecir", "401")]


def test_roles(entorno):
    cli, _ = entorno
    assert cli.post("/predict", json=AUTO, headers=h("invitado")).status_code == 403
    assert cli.post("/predict", json=AUTO, headers=h()).status_code == 200
    assert cli.get("/model/info", headers=h()).status_code == 200
    assert cli.get("/predictions/recent", headers=h()).status_code == 403
    assert cli.get("/predictions/recent", headers=h("admin")).status_code == 200


def test_validacion_422(entorno):
    cli, _ = entorno
    r = cli.post("/predict", json={**AUTO, "year": 3000}, headers=h())
    assert r.status_code == 422 and "year" in r.json()["detail"]


def test_body_no_json_422(entorno):
    cli, _ = entorno
    for cuerpo in (b"no es json", b"[1, 2]", b""):
        r = cli.post("/predict", content=cuerpo, headers={**h(), "Content-Type": "application/json"})
        assert r.status_code == 422, cuerpo


def test_body_grande_413(entorno):
    cli, _ = entorno
    r = cli.post("/predict", json={**AUTO, "name": "A" * 20_000}, headers=h())
    assert r.status_code == 413


def test_body_llega_intacto_a_la_api(entorno):
    cli, _ = entorno
    assert cli.post("/predict", json=AUTO, headers=h()).json()["eco"] == AUTO["name"]


def test_limite_429_por_usuario(entorno):
    cli, eventos = entorno
    codigos = [cli.post("/predict", json=AUTO, headers=h(usuario="jaime")).status_code for _ in range(4)]
    assert codigos == [200, 200, 200, 429]
    assert cli.post("/predict", json=AUTO, headers=h(usuario="ana")).status_code == 200
    assert ("jaime", "predecir", "429") in eventos


def test_ruta_desconocida_pide_token(entorno):
    cli, _ = entorno
    assert cli.get("/no-existe").status_code == 401
    assert cli.get("/no-existe", headers=h()).status_code == 404
