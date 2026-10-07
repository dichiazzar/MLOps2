"""Piezas compartidas por el servidor, los clientes y el script que reparte los datos.

- Acceso a MinIO (donde vive la parte de datos de cada concesionaria).
- Limpieza de datos: reusa `common/preprocessing.py` de MLOps1_final, sin copiarlo.
- Armado de la matriz de features a partir de un "esquema" (marcas principales,
  media y desvío) que el servidor calcula entre todos los clientes sin ver sus filas.
- El modelo: regresión lineal entrenada con SGD, igual que en mini_tp5.
"""

import io
import json
import logging
import os

import boto3
import numpy as np
import pandas as pd
from botocore.client import Config

from common.constants import BINARY_FEATURES, NUMERIC_FEATURES, OWNER_MAP
from common.preprocessing import (
    drop_km_outliers,
    drop_missing_technical_rows,
    extraer_columnas_tecnicas,
)
from common.schemas import FuelEnum

# --- Configuración (variables de entorno, con valores por defecto) ---
BUCKET = "federado"
NUM_CLIENTES = int(os.environ.get("NUM_CLIENTES", "3"))
RONDAS = int(os.environ.get("RONDAS", "20"))
EPOCAS_LOCALES = int(os.environ.get("EPOCAS_LOCALES", "50"))
LR = float(os.environ.get("LR", "0.01"))
PARTICION = os.environ.get("PARTICION", "iid")        # "iid" o "no_iid"
SIGMA = float(os.environ.get("SIGMA", "0"))           # ruido de privacidad diferencial
SEMILLA = 42

# Categorías de combustible: salen del mismo enum que valida la API (common/schemas.py).
# La primera (orden alfabético) queda como referencia, igual que drop_first=True.
COMBUSTIBLES = sorted(f.value for f in FuelEnum)


def crear_logger(nombre):
    """Logger propio (sin pasar por el logger raíz, que Flower ya usa: evita líneas repetidas)."""
    lg = logging.getLogger(nombre)
    if not lg.handlers:
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter("%(asctime)s [%(name)s] %(message)s"))
        lg.addHandler(h)
        lg.setLevel(logging.INFO)
        lg.propagate = False
    return lg


# ---------------------------------------------------------------- MinIO / S3
def s3():
    return boto3.client(
        "s3",
        endpoint_url=os.environ["MINIO_ENDPOINT"],
        aws_access_key_id=os.environ["MINIO_ROOT_USER"],
        aws_secret_access_key=os.environ["MINIO_ROOT_PASSWORD"],
        config=Config(signature_version="s3v4"),
        region_name="us-east-1",
    )


def crear_bucket(cliente_s3, bucket=BUCKET):
    existentes = [b["Name"] for b in cliente_s3.list_buckets()["Buckets"]]
    if bucket not in existentes:
        cliente_s3.create_bucket(Bucket=bucket)


def leer_csv(key, bucket=BUCKET) -> pd.DataFrame:
    obj = s3().get_object(Bucket=bucket, Key=key)
    return pd.read_csv(io.BytesIO(obj["Body"].read()))


def subir_csv(df: pd.DataFrame, key, bucket=BUCKET):
    s3().put_object(Bucket=bucket, Key=key, Body=df.to_csv(index=False).encode("utf-8"))


def leer_json(key, bucket=BUCKET):
    return json.loads(s3().get_object(Bucket=bucket, Key=key)["Body"].read())


def subir_json(data, key, bucket=BUCKET):
    s3().put_object(Bucket=bucket, Key=key, Body=json.dumps(data, indent=2).encode("utf-8"))


# ---------------------------------------------------------------- Datos
def limpiar(df_raw: pd.DataFrame, quitar_outliers: bool = True) -> pd.DataFrame:
    """Mismos pasos de limpieza que el entrenamiento de xgb_best (common/preprocessing.py)."""
    df = drop_missing_technical_rows(extraer_columnas_tecnicas(df_raw))
    if quitar_outliers:  # en el TP original solo se quitan del set de entrenamiento
        df = drop_km_outliers(df)
    return df.reset_index(drop=True)


def columnas(top_brands: list) -> list:
    marcas = sorted(top_brands + ["Other"])
    return (
        NUMERIC_FEATURES
        + BINARY_FEATURES
        + [f"fuel_{f}" for f in COMBUSTIBLES[1:]]
        + [f"brand_grouped_{m}" for m in marcas[1:]]
    )


def matriz_features(df: pd.DataFrame, top_brands: list) -> np.ndarray:
    """Arma la matriz de features con columnas fijas, iguales en todos los clientes.

    En el TP original las columnas salen de pd.get_dummies sobre todo el dataset.
    En federado cada cliente ve solo sus datos, así que las columnas se definen a
    partir del esquema común (lista de combustibles y marcas principales).
    """
    out = pd.DataFrame(index=df.index)
    for c in NUMERIC_FEATURES:
        if c != "owner_num":
            out[c] = df[c]
    out["owner_num"] = df["owner"].map(OWNER_MAP)
    out["is_manual"] = (df["transmission"] == "Manual").astype(int)
    out["is_individual"] = (df["seller_type"] == "Individual").astype(int)
    for f in COMBUSTIBLES[1:]:
        out[f"fuel_{f}"] = (df["fuel"] == f).astype(int)
    marca = df["brand"].where(df["brand"].isin(top_brands), "Other")
    for m in sorted(top_brands + ["Other"])[1:]:
        out[f"brand_grouped_{m}"] = (marca == m).astype(int)
    return out[columnas(top_brands)].to_numpy(dtype=float)


def target(df: pd.DataFrame) -> np.ndarray:
    """Mismo target que xgb_best: log(1 + precio)."""
    return np.log1p(df["selling_price"].to_numpy(dtype=float))


def estandarizar(X, media, desvio):
    return (X - np.asarray(media)) / np.asarray(desvio)


def media_y_desvio(n, suma, suma_cuad):
    """Media y desvío a partir de totales (lo único que mandan los clientes)."""
    media = np.asarray(suma) / n
    var = np.clip(np.asarray(suma_cuad) / n - media**2, 0, None)
    desvio = np.sqrt(var)
    desvio[desvio == 0] = 1.0   # columnas constantes (ej. fuel_Electric, que no aparece)
    return media, desvio


# ---------------------------------------------------------------- Modelo
# Regresión lineal con SGD sobre MSE: el mismo modelo que se federó en mini_tp5.
def init_modelo(n_feat):
    return np.zeros(n_feat), 0.0


def paso_sgd(w, b, X, y, lr):
    err = X @ w + b - y
    return w - lr * (X.T @ err / len(y)), b - lr * err.mean()


def entrenar(w, b, X, y, epocas, lr):
    for _ in range(epocas):
        w, b = paso_sgd(w, b, X, y, lr)
    return w, b


def rmse(w, b, X, y):
    return float(np.sqrt(np.mean((X @ w + b - y) ** 2)))
