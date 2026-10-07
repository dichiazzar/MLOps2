"""Prepara el Data Lake (clase 6). Se corre a mano, una vez y después de cada
entrenamiento nuevo en Airflow. Se puede repetir sin problemas.

1. Crea el bucket `datalake` con las zonas `raw` y `curated`.
2. Copia el dataset crudo a raw/car_dekho/.
3. Calcula las features con el mismo preprocesamiento y el mismo split que el DAG
   de Airflow, y las guarda en Parquet en curated/car_dekho/.
4. Agrega `lake_metadata.json` (marcas principales y orden de columnas) al run de
   MLflow del modelo en Production, para que las capas no tengan que recalcularla
   al arrancar. Si ya está, no la vuelve a subir.
"""

import io
import logging
import os
from datetime import datetime, timezone

import mlflow
import numpy as np
import pandas as pd
from mlflow.tracking import MlflowClient
from sklearn.model_selection import train_test_split

from app import lago
from app.predict import METADATA_ARTIFACT
from app.predict_mlflow import OBJECT_KEY, RAW_BUCKET, _derive_brands_and_features
from common.constants import MLFLOW_MODEL_NAME, TRAIN_TEST_SIZE, TRAIN_TEST_SPLIT_SEED
from common.preprocessing import (
    align_columns,
    build_feature_matrix,
    compute_top_brands,
    drop_km_outliers,
    drop_missing_technical_rows,
    encode_categoricals,
    extraer_columnas_tecnicas,
    get_all_feature_columns,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [preparar] %(message)s")
log = logging.getLogger("preparar")

DATASET = "car_dekho"


def features_curadas(df_raw: pd.DataFrame) -> pd.DataFrame:
    """Mismos pasos que la tarea `preprocess` del DAG train_xgb_pipeline."""
    df = df_raw.drop_duplicates().reset_index(drop=True)
    bins = pd.qcut(df["selling_price"], q=5,
                   labels=["muy_barato", "barato", "intermedio", "caro", "muy_caro"])
    df_train, df_test = train_test_split(
        df, test_size=TRAIN_TEST_SIZE, stratify=bins, random_state=TRAIN_TEST_SPLIT_SEED
    )
    df_train = drop_km_outliers(drop_missing_technical_rows(extraer_columnas_tecnicas(df_train)))
    df_test = drop_missing_technical_rows(extraer_columnas_tecnicas(df_test))
    top_brands = compute_top_brands(df_train)
    train_enc, test_enc = encode_categoricals(df_train, df_test, top_brands)
    all_features = get_all_feature_columns(train_enc)
    train_enc, test_enc = align_columns(train_enc, test_enc, all_features)
    partes = []
    for nombre, enc, orig in [("train", train_enc, df_train), ("test", test_enc, df_test)]:
        X = build_feature_matrix(enc, all_features)
        X["selling_price"] = orig["selling_price"].values
        X["log_selling_price"] = np.log1p(X["selling_price"])
        X["split"] = nombre
        partes.append(X)
    return pd.concat(partes, ignore_index=True)


def main():
    s3 = lago.s3()
    lago.crear_bucket_y_zonas(s3)
    log.info("Bucket '%s' con zonas %s listo.", lago.BUCKET, lago.ZONAS)

    # 1. raw: el dataset tal cual está en el bucket de MLOps1_final
    crudo = s3.get_object(Bucket=RAW_BUCKET, Key=OBJECT_KEY)["Body"].read()
    key_raw = f"raw/{DATASET}/{OBJECT_KEY}"
    lago.subir_bytes(crudo, key_raw, s3)
    df_raw = pd.read_csv(io.BytesIO(crudo))
    log.info("raw     -> s3://%s/%s (%d filas)", lago.BUCKET, key_raw, len(df_raw))

    # 2. curated: features listas para entrenar
    df_cur = features_curadas(df_raw)
    key_cur = f"curated/{DATASET}/car_features.parquet"
    lago.subir_parquet(df_cur, key_cur, s3)
    log.info("curated -> s3://%s/%s (%d filas, %d columnas)",
             lago.BUCKET, key_cur, len(df_cur), df_cur.shape[1])

    # 3. metadata del modelo en Production, guardada en su run de MLflow
    mlflow.set_tracking_uri(os.environ["MLFLOW_TRACKING_URI"])
    client = MlflowClient()
    versions = client.get_latest_versions(MLFLOW_MODEL_NAME, stages=["Production"])
    if not versions:
        log.warning("No hay versión de '%s' en Production: no se agrega metadata.", MLFLOW_MODEL_NAME)
        return
    mv = versions[0]
    existentes = [a.path for a in client.list_artifacts(mv.run_id)]
    if METADATA_ARTIFACT in existentes:
        log.info("El run del modelo v%s ya tiene %s: no se vuelve a subir.", mv.version, METADATA_ARTIFACT)
    else:
        # Misma función que usaban las capas al arrancar: el resultado es idéntico.
        top_brands, all_features = _derive_brands_and_features()
        metadata = {
            "model_name": MLFLOW_MODEL_NAME,
            "model_version": mv.version,
            "run_id": mv.run_id,
            "top_brands": top_brands,
            "all_features": all_features,
            "dataset_raw": f"s3://{lago.BUCKET}/{key_raw}",
            "dataset_curated": f"s3://{lago.BUCKET}/{key_cur}",
            "creado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        client.log_dict(mv.run_id, metadata, METADATA_ARTIFACT)
        log.info("Metadata agregada al run %s del modelo v%s (%s).",
                 mv.run_id, mv.version, METADATA_ARTIFACT)
    log.info("Listo.")


if __name__ == "__main__":
    main()
