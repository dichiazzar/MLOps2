"""Acceso al Data Lake (bucket `datalake` en el MinIO de MLOps1_final).

Lo usan el script que prepara el lake, el consumidor de streaming (escribe) y
GraphQL (lee). Zonas:
  raw/      datos tal como llegaron (dataset crudo, eventos de streaming)
  curated/  datos limpios y listos para entrenar (features en Parquet)

Los modelos NO van acá: los guarda MLflow en el bucket `mlflow-artifacts`,
que funciona como la zona de modelos del lake.
"""

import io
import os

import boto3
import pandas as pd
from botocore.client import Config

BUCKET = "datalake"
ZONAS = ["raw", "curated"]


def s3():
    return boto3.client(
        "s3",
        endpoint_url=os.environ["MINIO_ENDPOINT"],
        aws_access_key_id=os.environ["MINIO_ROOT_USER"],
        aws_secret_access_key=os.environ["MINIO_ROOT_PASSWORD"],
        config=Config(signature_version="s3v4"),
        region_name="us-east-1",
    )


def crear_bucket_y_zonas(cliente=None):
    cliente = cliente or s3()
    existentes = [b["Name"] for b in cliente.list_buckets()["Buckets"]]
    if BUCKET not in existentes:
        cliente.create_bucket(Bucket=BUCKET)
    for zona in ZONAS:  # en S3 no hay carpetas: la zona existe al subir un objeto con ese prefijo
        cliente.put_object(Bucket=BUCKET, Key=f"{zona}/.keep", Body=b"")


def subir_bytes(cuerpo: bytes, key: str, cliente=None):
    (cliente or s3()).put_object(Bucket=BUCKET, Key=key, Body=cuerpo)


def subir_parquet(df: pd.DataFrame, key: str, cliente=None):
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    subir_bytes(buf.getvalue(), key, cliente)


def listar(prefijo: str, cliente=None) -> list:
    """Claves bajo un prefijo, sin los '.keep' de las zonas."""
    cliente = cliente or s3()
    claves, token = [], None
    while True:
        args = {"Bucket": BUCKET, "Prefix": prefijo}
        if token:
            args["ContinuationToken"] = token
        resp = cliente.list_objects_v2(**args)
        claves += [o["Key"] for o in resp.get("Contents", []) if not o["Key"].endswith(".keep")]
        if not resp.get("IsTruncated"):
            return claves
        token = resp["NextContinuationToken"]


def leer_parquet(key: str, cliente=None) -> pd.DataFrame:
    obj = (cliente or s3()).get_object(Bucket=BUCKET, Key=key)
    return pd.read_parquet(io.BytesIO(obj["Body"].read()))
