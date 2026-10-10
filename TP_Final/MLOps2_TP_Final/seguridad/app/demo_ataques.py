"""Prueba de punta a punta de la seguridad del TP (clase 7): la versión del Mini-TP 7
contra los servicios reales. Imprime 'esperado vs obtenido' por capa y termina con
código 1 si algo no da lo esperado.

    docker compose --profile manual run --rm demo-ataques [--integridad]
"""

import argparse
import io
import json
import os
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import boto3
import grpc
import requests
from botocore.client import Config
from botocore.exceptions import ClientError
from kafka import KafkaProducer

import car_price_pb2 as pb
import car_price_pb2_grpc as pbg
from app.seguridad import claves_hmac, emitir_token, firmar, hash_modelo

REST = "http://rest:8000"
GQL = "http://graphql:8001/graphql"
GRPC = "grpc:50051"
AUTO = {
    "name": "Maruti Swift Dzire VDI", "year": 2014, "km_driven": 145500,
    "fuel": "Diesel", "seller_type": "Individual", "transmission": "Manual",
    "owner": "First Owner", "mileage": "23.4 kmpl", "engine": "1248 CC",
    "max_power": "74 bhp", "torque": "190Nm@ 2000rpm", "seats": 5,
}
GQL_AUTO = ('{name: "Maruti Swift Dzire VDI", year: 2014, kmDriven: 145500, fuel: diesel, '
            'sellerType: individual, transmission: manual, owner: first, mileage: "23.4 kmpl", '
            'engine: "1248 CC", maxPower: "74 bhp", torque: "190Nm@ 2000rpm", seats: 5}')
FALLAS = []


def chequear(capa, prueba, esperado, obtenido):
    # números: igualdad exacta; textos: el esperado tiene que aparecer en lo obtenido
    ok = obtenido == esperado if isinstance(esperado, int) else str(esperado) in str(obtenido)
    if not ok:
        FALLAS.append(f"{capa}: {prueba}")
    print(f"  {'OK   ' if ok else 'FALLA'} {capa:9s} {prueba:46s} esperado={esperado!s:20s} obtenido={str(obtenido)[:60]}")


def tokens():
    return {"analista": emitir_token("demo-analista", "analista"), "admin": emitir_token("demo-admin", "admin"),
            "invitado": emitir_token("demo-invitado", "invitado"),
            "vencido": emitir_token("demo-analista", "analista", minutos=-1)}


def h(tok):
    return {"Authorization": f"Bearer {tok}"}


def probar_rest(t):
    print("\nREST")
    post = lambda **kw: requests.post(f"{REST}/predict", timeout=10, **kw).status_code  # noqa: E731
    chequear("REST", "sin token", 401, post(json=AUTO))
    chequear("REST", "token vencido", 401, post(json=AUTO, headers=h(t["vencido"])))
    chequear("REST", "rol invitado", 403, post(json=AUTO, headers=h(t["invitado"])))
    chequear("REST", "analista", 200, post(json=AUTO, headers=h(t["analista"])))
    chequear("REST", "año 3000", 422, post(json={**AUTO, "year": 3000}, headers=h(t["analista"])))
    chequear("REST", "analista en /predictions/recent", 403,
             requests.get(f"{REST}/predictions/recent", headers=h(t["analista"]), timeout=10).status_code)
    limite = int(os.environ.get("LIMITE_POR_MINUTO", "60"))
    tok = emitir_token(f"demo-rafaga-{uuid.uuid4().hex[:6]}", "analista")
    codigos = [post(json=AUTO, headers=h(tok)) for _ in range(limite + 1)]
    chequear("REST", f"ráfaga de {limite + 1} pedidos", 429, codigos[-1])


def gql(query, tok=None):
    """'OK' si no hubo errores; si no, todos los mensajes de error juntos."""
    r = requests.post(GQL, json={"query": query}, headers=h(tok) if tok else {}, timeout=20).json()
    return " | ".join(e.get("message", "") for e in r["errors"]) if r.get("errors") else "OK"


def probar_graphql(t):
    print("\nGraphQL")
    chequear("GraphQL", "modelInfo sin token", "no autorizado", gql("{ modelInfo { modelVersion } }"))
    chequear("GraphQL", "modelInfo analista", "OK", gql("{ modelInfo { modelVersion } }", t["analista"]))
    chequear("GraphQL", "introspección", "introspection has been disabled",
             gql("{ __schema { types { name } } }", t["admin"]))
    # El esquema real no tiene consultas válidas de profundidad > 5: se arma una con campos
    # inexistentes; el limitador reporta su error junto con el de campo desconocido.
    profunda = "{ modelInfo { a { b { c { d { e { f } } } } } } }"
    chequear("GraphQL", "profundidad 7", "exceeds maximum operation depth", gql(profunda, t["analista"]))
    alias = "mutation { " + " ".join(f"p{i}: predict(car: {GQL_AUTO}) {{ predictedPrice }}" for i in range(25)) + " }"
    chequear("GraphQL", "25 alias de predict", "consulta demasiado costosa", gql(alias, t["analista"]))
    # cadena de fragmentos repetidos: sin el control previo, la validación tardaba un tiempo exponencial
    frags = " ".join(f"fragment F{i} on Query {{ ...F{i + 1} ...F{i + 1} }}" for i in range(30))
    bomba = "{ ...F0 } " + frags + " fragment F30 on Query { modelInfo { modelName } }"
    t0 = time.time()
    r = requests.post(GQL, json={"query": bomba}, timeout=20)
    chequear("GraphQL", "bomba de fragmentos (sin token)", "400 rápido",
             f"{r.status_code} {'rápido' if time.time() - t0 < 2 else 'lento'}")
    chequear("GraphQL", "auditoria con analista", "no autorizado",
             gql('{ auditoria(capa: "rest") { total } }', t["analista"]))
    chequear("GraphQL", "auditoria con admin", "OK", gql('{ auditoria(capa: "rest") { total } }', t["admin"]))


def probar_grpc(t):
    print("\ngRPC")
    with open("/certs/ca.crt", "rb") as f:
        creds = grpc.ssl_channel_credentials(root_certificates=f.read())

    def llamar(seguro=True, tok=None, car=AUTO):
        canal = grpc.secure_channel(GRPC, creds) if seguro else grpc.insecure_channel(GRPC)
        try:
            md = [("authorization", f"Bearer {tok}")] if tok else None
            pbg.CarPriceServiceStub(canal).Predict(pb.Car(**car), metadata=md, timeout=10)
            return "OK"
        except grpc.RpcError as e:
            return e.code().name
        finally:
            canal.close()

    chequear("gRPC", "canal sin TLS", "UNAVAILABLE", llamar(seguro=False, tok=t["analista"]))
    chequear("gRPC", "TLS sin token", "UNAUTHENTICATED", llamar())
    chequear("gRPC", "TLS rol invitado", "PERMISSION_DENIED", llamar(tok=t["invitado"]))
    chequear("gRPC", "TLS mensaje de 2 MB", "RESOURCE_EXHAUSTED",
             llamar(tok=t["analista"], car={**AUTO, "name": "A" * 2_000_000}))
    chequear("gRPC", "TLS año 3000", "INVALID_ARGUMENT", llamar(tok=t["analista"], car={**AUTO, "year": 3000}))
    chequear("gRPC", "TLS + token analista", "OK", llamar(tok=t["analista"]))


def s3(usuario_env, clave_env):
    return boto3.client("s3", endpoint_url=os.environ["MINIO_ENDPOINT"],
                        aws_access_key_id=os.environ[usuario_env], aws_secret_access_key=os.environ[clave_env],
                        config=Config(signature_version="s3v4"), region_name="us-east-1")


def codigo_s3(f):
    try:
        f()
        return "OK"
    except ClientError as e:
        return e.response["Error"]["Code"]


def probar_streaming():
    print("\nStreaming")
    claves = claves_hmac()
    productor, clave = next(iter(claves.items()))
    prod = KafkaProducer(bootstrap_servers="redpanda:9092", value_serializer=lambda v: json.dumps(v).encode())
    marca = f"demo-{uuid.uuid4().hex[:8]}"

    def firmado(**cambios):
        ev = {**AUTO, "name": f"Maruti {marca}", "seats": 5.0, "_event_time": time.time(),
              "_productor": productor, "_id": uuid.uuid4().hex, "_ts": datetime.now(timezone.utc).isoformat()}
        ev.update(cambios)
        ev["_firma"] = firmar(ev, clave)
        return ev

    legitimos = [firmado() for _ in range(5)]
    alterado = firmado()
    alterado["km_driven"] = 1
    ataque = [{**firmado(), "_firma": "x" * 64}, alterado, legitimos[0], firmado(year=3000)]
    # mensaje que ni siquiera es JSON: antes dejaba al consumidor reiniciándose para siempre
    crudo = KafkaProducer(bootstrap_servers="redpanda:9092")
    crudo.send("autos", b"\xff\xfe esto no es JSON")
    crudo.flush()
    for e in legitimos + ataque:      # los legítimos van DESPUÉS de la basura: prueban que sigue vivo
        prod.send("autos", e)
    prod.flush()
    print("  publicados 1 mensaje basura, 5 legítimos y 4 de ataque; esperando los lotes (25 s)...")
    time.sleep(25)
    admin = s3("MINIO_ROOT_USER", "MINIO_ROOT_PASSWORD")
    hoy = datetime.now(timezone.utc).date().isoformat()

    def contar(prefijo, parquet):
        n = 0
        for o in admin.list_objects_v2(Bucket="datalake", Prefix=prefijo).get("Contents", []):
            cuerpo = admin.get_object(Bucket="datalake", Key=o["Key"])["Body"].read()
            if parquet:
                import pandas as pd
                n += int((pd.read_parquet(io.BytesIO(cuerpo))["name"] == f"Maruti {marca}").sum())
            else:
                n += sum(marca in linea for linea in cuerpo.decode().splitlines())
        return n

    chequear("Streaming", "legítimos puntuados en raw/streaming", 5,
             contar(f"raw/streaming/fecha={hoy}/", parquet=True))
    chequear("Streaming", "ataque en raw/dlq", 4, contar(f"raw/dlq/fecha={hoy}/", parquet=False))


def probar_lake():
    print("\nLake")
    rest = s3("MINIO_CAPA_REST_USER", "MINIO_CAPA_REST_PASSWORD")
    chequear("Lake", "capa-rest escribe en mlflow-artifacts", "AccessDenied",
             codigo_s3(lambda: rest.put_object(Bucket="mlflow-artifacts", Key="demo/hack.txt", Body=b"x")))
    chequear("Lake", "capa-rest lee curated/", "AccessDenied",
             codigo_s3(lambda: rest.get_object(Bucket="datalake", Key="curated/car_dekho/car_features.parquet")))
    chequear("Lake", "capa-rest borra auditoría", "AccessDenied",
             codigo_s3(lambda: rest.delete_object(Bucket="datalake", Key="raw/auditoria/capa=rest/x")))


def probar_integridad():
    print("\nIntegridad (copia local del modelo; no toca el modelo en Production)")
    mlflow_url = os.environ["MLFLOW_TRACKING_URI"]
    mv = requests.get(f"{mlflow_url}/api/2.0/mlflow/registered-models/get-latest-versions",
                      params={"name": "xgb_best", "stages": "Production"}, timeout=10).json()["model_versions"][0]
    rest = s3("MINIO_CAPA_REST_USER", "MINIO_CAPA_REST_PASSWORD")
    bucket, prefijo = mv["source"].removeprefix("s3://").split("/", 1)
    carpeta = Path(tempfile.mkdtemp())
    for o in rest.list_objects_v2(Bucket=bucket, Prefix=prefijo + "/")["Contents"]:
        destino = carpeta / o["Key"][len(prefijo) + 1:]
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(rest.get_object(Bucket=bucket, Key=o["Key"])["Body"].read())
    run_prefijo = prefijo.rsplit("/", 1)[0]
    seg = json.loads(rest.get_object(Bucket=bucket, Key=f"{run_prefijo}/seguridad_modelo.json")["Body"].read())
    chequear("Integr.", "hash del modelo registrado", seg["sha256_total"][:12], hash_modelo(carpeta)["sha256_total"][:12])
    archivo = next(p for p in carpeta.rglob("*") if p.is_file() and p.name != "MLmodel")
    archivo.write_bytes(archivo.read_bytes() + b" ")
    chequear("Integr.", "modelo alterado detectado", "distinto",
             "distinto" if hash_modelo(carpeta)["sha256_total"] != seg["sha256_total"] else "igual")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--integridad", action="store_true")
    a = p.parse_args()
    t = tokens()
    probar_rest(t)
    probar_graphql(t)
    probar_grpc(t)
    probar_streaming()
    probar_lake()
    if a.integridad:
        probar_integridad()
    print("\n" + ("TODO OK" if not FALLAS else f"{len(FALLAS)} FALLAS: {FALLAS}"))
    sys.exit(1 if FALLAS else 0)


if __name__ == "__main__":
    main()
