import io
import os
from dataclasses import dataclass

import boto3
import mlflow
import mlflow.xgboost
import pandas as pd
from botocore.client import Config
from mlflow.tracking import MlflowClient

from common.constants import MLFLOW_MODEL_NAME
from common.preprocessing import (
    build_feature_matrix,
    build_inference_features,
    compute_top_brands,
    drop_km_outliers,
    drop_missing_technical_rows,
    encode_categoricals,
    extraer_columnas_tecnicas,
    get_all_feature_columns,
)
from common.schemas import CarRawInput

RAW_BUCKET = "raw-data"
OBJECT_KEY = "car_details_v3.csv"


@dataclass
class ModelState:
    model: object
    top_brands: list
    all_features: list
    model_version: str


def _download_raw_dataset() -> pd.DataFrame:
    client = boto3.client(
        "s3",
        endpoint_url=os.environ["MINIO_ENDPOINT"],
        aws_access_key_id=os.environ["MINIO_ROOT_USER"],
        aws_secret_access_key=os.environ["MINIO_ROOT_PASSWORD"],
        config=Config(signature_version="s3v4"),
        region_name="us-east-1",
    )
    buffer = io.BytesIO()
    client.download_fileobj(RAW_BUCKET, OBJECT_KEY, buffer)
    buffer.seek(0)
    return pd.read_csv(buffer)


def _derive_brands_and_features() -> tuple[list, list]:
    from sklearn.model_selection import train_test_split

    df_raw = _download_raw_dataset().drop_duplicates().reset_index(drop=True)
    price_bins = pd.qcut(
        df_raw["selling_price"], q=5,
        labels=["muy_barato", "barato", "intermedio", "caro", "muy_caro"],
    )
    df_train, df_test = train_test_split(
        df_raw, test_size=0.25, stratify=price_bins, random_state=42
    )
    df_train = extraer_columnas_tecnicas(df_train)
    df_test = extraer_columnas_tecnicas(df_test)
    df_train = drop_missing_technical_rows(df_train)
    df_test = drop_missing_technical_rows(df_test)
    df_train = drop_km_outliers(df_train)

    top_brands = compute_top_brands(df_train)
    df_train_enc, _ = encode_categoricals(df_train, df_test, top_brands)
    all_features = get_all_feature_columns(df_train_enc)
    return top_brands, all_features


def load_production_model() -> ModelState:
    mlflow.set_tracking_uri(os.environ["MLFLOW_TRACKING_URI"])
    client = MlflowClient()

    versions = client.get_latest_versions(MLFLOW_MODEL_NAME, stages=["Production"])
    if not versions:
        raise RuntimeError(f"No Production version found for model '{MLFLOW_MODEL_NAME}'")

    mv = versions[0]
    model = mlflow.xgboost.load_model(f"models:/{MLFLOW_MODEL_NAME}/Production")
    top_brands, all_features = _derive_brands_and_features()

    return ModelState(
        model=model,
        top_brands=top_brands,
        all_features=all_features,
        model_version=mv.version,
    )


def predict_price(state: ModelState, car: CarRawInput) -> float:
    import numpy as np

    row = build_inference_features(car, state.top_brands, state.all_features)
    pred_log = state.model.predict(row)[0]
    return float(np.expm1(pred_log))
