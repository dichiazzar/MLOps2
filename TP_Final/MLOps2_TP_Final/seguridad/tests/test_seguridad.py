import json
from datetime import datetime, timedelta, timezone

import jwt
import pandas as pd
import pytest

from app import seguridad as s

AUTO = {
    "name": "Maruti Swift Dzire VDI", "year": 2014, "km_driven": 145500,
    "fuel": "Diesel", "seller_type": "Individual", "transmission": "Manual",
    "owner": "First Owner", "mileage": "23.4 kmpl", "engine": "1248 CC",
    "max_power": "74 bhp", "torque": "190Nm@ 2000rpm", "seats": 5,
}


# ---------- tokens ----------
def test_token_valido():
    ident = s.verificar_token(s.emitir_token("jaime", "analista"))
    assert ident == s.Identidad("jaime", "analista")


def test_token_con_y_sin_prefijo():
    tok = s.emitir_token("ana", "admin")
    for variante in (tok, f"Bearer {tok}", f"bearer {tok}", f"  Bearer   {tok}  "):
        assert s.verificar_token(variante).usuario == "ana"
    for malo in ("Bearer", "Bearer ", "basura", "Basic abc"):
        with pytest.raises(s.TokenInvalido):
            s.verificar_token(malo)


def test_token_falta():
    for vacio in (None, ""):
        with pytest.raises(s.TokenInvalido, match="falta"):
            s.verificar_token(vacio)


def test_token_vencido():
    with pytest.raises(s.TokenInvalido, match="vencido"):
        s.verificar_token(s.emitir_token("jaime", "analista", minutos=-1))


def test_token_otro_secreto():
    tok = s.emitir_token("hacker", "admin", secreto="y" * 40)
    with pytest.raises(s.TokenInvalido, match="InvalidSignatureError"):
        s.verificar_token(tok)


def test_token_alg_none_rechazado():
    tok = jwt.encode({"sub": "hacker", "rol": "admin",
                      "exp": datetime.now(timezone.utc) + timedelta(minutes=5)}, None, algorithm="none")
    with pytest.raises(s.TokenInvalido):
        s.verificar_token(tok)


def test_token_sin_sub_rechazado():
    tok = jwt.encode({"rol": "admin", "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
                     "x" * 40, algorithm="HS256")
    with pytest.raises(s.TokenInvalido):
        s.verificar_token(tok)


def test_secreto_corto_falla(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "corto")
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        s.emitir_token("a", "admin")


# ---------- permisos ----------
@pytest.mark.parametrize("rol,accion,esperado", [
    ("analista", "predecir", True), ("admin", "predecir", True), ("invitado", "predecir", False),
    ("analista", "ver_predicciones_de_otros", False), ("admin", "ver_predicciones_de_otros", True),
    ("analista", "ver_auditoria", False), ("admin", "ver_auditoria", True),
    ("admin", "accion_inexistente", False),
])
def test_permisos(rol, accion, esperado):
    assert s.autorizado(s.Identidad("u", rol), accion) is esperado


def test_permisos_anonimo():
    assert s.autorizado(None, "predecir") is False


# ---------- límite de tasa ----------
def test_limite_de_tasa():
    t = [0.0]
    lim = s.LimiteDeTasa(n=3, segundos=60, reloj=lambda: t[0])
    assert [lim.permitir("jaime") for _ in range(4)] == [True, True, True, False]
    assert lim.permitir("ana") is True          # otro usuario, cupo propio
    t[0] = 61
    assert lim.permitir("jaime") is True        # la ventana se liberó


def test_limite_de_tasa_lee_entorno(monkeypatch):
    monkeypatch.setenv("LIMITE_POR_MINUTO", "2")
    lim = s.LimiteDeTasa()
    assert [lim.permitir("x") for _ in range(3)] == [True, True, False]


# ---------- HMAC ----------
CLAVES = {"concesionaria-norte": "clave-n", "concesionaria-sur": "clave-s"}


def _evento_firmado(productor="concesionaria-norte"):
    ev = {**AUTO, "_productor": productor, "_id": "abc123", "_ts": datetime.now(timezone.utc).isoformat()}
    ev["_firma"] = s.firmar(ev, CLAVES[productor])
    return ev


def test_firma_valida():
    assert s.verificar_firma(_evento_firmado(), CLAVES) is None


def test_firma_cuerpo_alterado():
    ev = _evento_firmado()
    ev["km_driven"] = 10
    assert s.verificar_firma(ev, CLAVES) == "firma inválida"


def test_firma_con_clave_de_otro_productor():
    ev = _evento_firmado("concesionaria-norte")
    ev["_productor"] = "concesionaria-sur"          # se hace pasar por otro
    assert s.verificar_firma(ev, CLAVES) == "firma inválida"


def test_firma_productor_desconocido_o_sin_firma():
    ev = _evento_firmado()
    ev["_productor"] = "concesionaria-trucha"
    assert s.verificar_firma(ev, CLAVES) == "productor desconocido"
    ev2 = _evento_firmado()
    del ev2["_firma"]
    assert s.verificar_firma(ev2, CLAVES) == "firma inválida"


def test_canonico_ignora_orden_y_firma():
    a = {"b": 1, "a": 2, "_firma": "x"}
    b = {"a": 2, "b": 1}
    assert s.canonico(a) == s.canonico(b)


def test_claves_hmac_desde_entorno(monkeypatch):
    monkeypatch.setenv("HMAC_CLAVES", json.dumps(CLAVES))
    assert s.claves_hmac() == CLAVES


# ---------- anti-replay ----------
def test_vistos_recientes():
    t = [0.0]
    v = s.VistosRecientes(ttl_segundos=10, reloj=lambda: t[0])
    assert v.ya_visto("a") is False
    assert v.ya_visto("a") is True
    t[0] = 11
    assert v.ya_visto("a") is False             # venció el TTL


def test_ts_en_ventana():
    ahora = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
    assert s.ts_en_ventana(ahora.isoformat(), ahora) is True
    assert s.ts_en_ventana((ahora - timedelta(hours=2)).isoformat(), ahora) is False
    assert s.ts_en_ventana((ahora + timedelta(minutes=10)).isoformat(), ahora) is False


def test_ts_invalido_fuera_de_ventana():
    for malo in (None, "", "ayer", 12345, "2026-13-45T00:00:00"):
        assert s.ts_en_ventana(malo) is False


# ---------- alerta de DLQ ----------
def test_alerta_por_ventana_inicio_y_fin():
    a = s.AlertaPorVentana(n=10, umbral=0.2)
    eventos = [a.registrar(False) for _ in range(10)]
    assert all(e is None for e in eventos)
    inicio = [a.registrar(True, "dlq_firma", "x") for _ in range(3)]
    assert [e["tipo"] for e in inicio if e] == ["INICIO"]
    fin = [a.registrar(False) for _ in range(10)]
    assert [e["tipo"] for e in fin if e] == ["FIN"]


# ---------- validación del auto ----------
def test_validar_auto_ok():
    car = s.validar_auto(AUTO)
    assert car.km_driven == 145500


@pytest.mark.parametrize("cambio,texto", [
    ({"year": 3000}, "year"),
    ({"fuel": "Nafta"}, "fuel"),
    ({"km_driven": 50_000_000}, "km_driven"),
    ({"mileage": "mucho"}, "no se pudieron leer"),
    ({"engine": "<script>"}, "no se pudieron leer"),
    ({"es_admin": True}, "campos no permitidos"),
])
def test_validar_auto_rechaza(cambio, texto):
    with pytest.raises(s.EntradaInvalida, match=texto):
        s.validar_auto({**AUTO, **cambio})


def test_validar_auto_no_dict():
    for malo in (None, [], "texto", 5):
        with pytest.raises(s.EntradaInvalida):
            s.validar_auto(malo)


def test_validar_auto_rangos():
    rangos = {"engine_value": [600.0, 5000.0]}
    s.validar_auto(AUTO, rangos)
    with pytest.raises(s.EntradaInvalida, match="engine_value"):
        s.validar_auto({**AUTO, "engine": "9000 CC"}, rangos)


def test_rangos_de_train_aceptan_todos_los_autos_de_test(dataset_csv):
    # Split 75/25 con pandas y la semilla del proyecto (sklearn no está en la imagen de tests).
    from common.preprocessing import drop_missing_technical_rows, extraer_columnas_tecnicas
    df = pd.read_csv(dataset_csv).drop_duplicates().reset_index(drop=True)
    tecnico = drop_missing_technical_rows(extraer_columnas_tecnicas(df))
    train = tecnico.sample(frac=0.75, random_state=42)
    test = tecnico.drop(train.index)
    rangos = s.calcular_rangos(train)
    cols = ["name", "year", "km_driven", "fuel", "seller_type", "transmission", "owner",
            "mileage", "engine", "max_power", "torque", "seats"]
    rechazados = []
    for fila in test[cols].to_dict("records"):
        try:
            s.validar_auto(fila, rangos)
        except s.EntradaInvalida as e:
            rechazados.append(str(e))
    assert len(rechazados) / len(test) < 0.01, rechazados[:5]


def test_calcular_rangos():
    df = pd.DataFrame({c: [10.0, 20.0] for c in s.COLUMNAS_RANGO})
    r = s.calcular_rangos(df, margen=0.2)
    assert r["engine_value"] == [8.0, 22.0]
    df.loc[0, "km_driven"] = 0.0
    assert s.calcular_rangos(df)["km_driven"][0] == 0.0    # no baja de 0


# ---------- hash e integridad ----------
def _modelo(tmp_path):
    (tmp_path / "model.json").write_text('{"arbol": 1}')
    (tmp_path / "MLmodel").write_text("flavors: xgboost")
    return tmp_path


def test_hash_modelo_estable(tmp_path):
    h1 = s.hash_modelo(_modelo(tmp_path))
    h2 = s.hash_modelo(tmp_path)
    assert h1 == h2 and set(h1["archivos"]) == {"model.json", "MLmodel"}


def test_verificar_integridad(tmp_path):
    carpeta = _modelo(tmp_path)
    seg = {"sha256_total": s.hash_modelo(carpeta)["sha256_total"]}
    assert s.verificar_integridad(carpeta, seg, exigir=True) == "ok"
    (carpeta / "model.json").write_text('{"arbol": 2}')        # alguien cambió el modelo
    with pytest.raises(s.IntegridadRota, match="no coincide"):
        s.verificar_integridad(carpeta, seg, exigir=False)


def test_verificar_integridad_sin_artefacto(tmp_path):
    carpeta = _modelo(tmp_path)
    assert s.verificar_integridad(carpeta, None, exigir=False) == "sin_verificar"
    with pytest.raises(s.IntegridadRota, match="seguridad_modelo.json"):
        s.verificar_integridad(carpeta, None, exigir=True)


@pytest.mark.parametrize("valor,esperado", [
    (None, True), ("true", True), ("1", True), ("false", False), ("FALSE", False), ("0", False), ("no", False),
])
def test_exigir_integridad(monkeypatch, valor, esperado):
    if valor is None:
        monkeypatch.delenv("EXIGIR_INTEGRIDAD", raising=False)
    else:
        monkeypatch.setenv("EXIGIR_INTEGRIDAD", valor)
    assert s.exigir_integridad() is esperado


# ---------- auditoría ----------
def test_hash_entrada():
    assert s.hash_entrada(None) is None
    assert s.hash_entrada({"b": 1, "a": 2}) == s.hash_entrada({"a": 2, "b": 1})
    assert len(s.hash_entrada(b"hola")) == 16


def test_auditor_formato_y_lote():
    subidos = []
    aud = s.Auditor("rest", lambda cuerpo, key: subidos.append((cuerpo, key)), cada_n=2, iniciar_hilo=False)
    ev = aud.registrar(s.Identidad("jaime", "analista"), "predecir", 200, entrada=AUTO, model_version="1")
    assert set(ev) == {"ts", "capa", "usuario", "rol", "accion", "resultado", "detalle",
                       "hash_entrada", "model_version"}
    assert ev["resultado"] == "200" and "Maruti" not in json.dumps(ev)   # nunca datos crudos
    aud.registrar(None, "predecir", 401, detalle="falta el token")       # completa el lote
    assert len(subidos) == 1
    cuerpo, key = subidos[0]
    assert key.startswith("raw/auditoria/capa=rest/fecha=") and key.endswith(".jsonl")
    filas = [json.loads(linea) for linea in cuerpo.decode().splitlines()]
    assert [f["usuario"] for f in filas] == ["jaime", None]


def test_escritor_lake_caido_no_rompe(caplog):
    def falla(cuerpo, key):
        raise ConnectionError("minio caído")
    esc = s.EscritorPorLotes("raw/x", falla, cada_n=1, iniciar_hilo=False)
    esc.agregar({"a": 1})                        # no levanta excepción
    assert "no se pudo subir" in caplog.text


def test_escritor_vaciar_sin_filas():
    esc = s.EscritorPorLotes("raw/x", lambda c, k: None, iniciar_hilo=False)
    assert esc.vaciar() is None
