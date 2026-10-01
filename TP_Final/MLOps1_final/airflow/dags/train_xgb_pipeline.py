"""Entrenamiento del pipeline para xgb_best: MinIO -> preprocess -> train -> MLflow -> Registry."""
import io
import os
from datetime import datetime

import boto3
import mlflow
import mlflow.xgboost
import numpy as np
import pandas as pd
from airflow.decorators import dag, task
from botocore.client import Config
from mlflow.tracking import MlflowClient
from sklearn.metrics import (
    mean_absolute_error,
    mean_absolute_percentage_error,
    r2_score,
    root_mean_squared_error,
)
from sklearn.model_selection import train_test_split
from xgboost import XGBRegressor

from common.constants import (
    MLFLOW_MODEL_NAME,
    TRAIN_TEST_SIZE,
    TRAIN_TEST_SPLIT_SEED,
    XGB_PARAMS,
)
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

MINIO_ENDPOINT = os.environ["MINIO_ENDPOINT"]
MINIO_ACCESS_KEY = os.environ["MINIO_ROOT_USER"]
MINIO_SECRET_KEY = os.environ["MINIO_ROOT_PASSWORD"]
RAW_BUCKET = "raw-data"
OBJECT_KEY = "car_details_v3.csv"

TMP_DIR = "/tmp/xgb_pipeline"


def _s3_client():
    return boto3.client(
        "s3",
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_ACCESS_KEY,
        aws_secret_access_key=MINIO_SECRET_KEY,
        config=Config(signature_version="s3v4"),
        region_name="us-east-1",
    )


@dag(
    dag_id="train_xgb_pipeline",
    schedule=None,
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["mlops", "xgboost", "car-price"],
)
def train_xgb_pipeline():

    @task(retries=1)
    def extract_data() -> str:
        os.makedirs(TMP_DIR, exist_ok=True)
        client = _s3_client()
        buffer = io.BytesIO()
        client.download_fileobj(RAW_BUCKET, OBJECT_KEY, buffer)
        buffer.seek(0)
        df_raw = pd.read_csv(buffer)
        path = f"{TMP_DIR}/raw.parquet"
        df_raw.to_parquet(path)
        return path

    @task
    def preprocess(raw_path: str) -> dict:
        df_raw = pd.read_parquet(raw_path)
        df_raw = df_raw.drop_duplicates().reset_index(drop=True)

        price_bins = pd.qcut(
            df_raw["selling_price"],
            q=5,
            labels=["muy_barato", "barato", "intermedio", "caro", "muy_caro"],
        )
        df_train, df_test = train_test_split(
            df_raw,
            test_size=TRAIN_TEST_SIZE,
            stratify=price_bins,
            random_state=TRAIN_TEST_SPLIT_SEED,
        )

        df_train = extraer_columnas_tecnicas(df_train)
        df_test = extraer_columnas_tecnicas(df_test)

        df_train = drop_missing_technical_rows(df_train)
        df_test = drop_missing_technical_rows(df_test)

        df_train = drop_km_outliers(df_train)

        top_brands = compute_top_brands(df_train)
        df_train_enc, df_test_enc = encode_categoricals(df_train, df_test, top_brands)

        all_features = get_all_feature_columns(df_train_enc)
        df_train_enc, df_test_enc = align_columns(df_train_enc, df_test_enc, all_features)

        X_train = build_feature_matrix(df_train_enc, all_features)
        X_test = build_feature_matrix(df_test_enc, all_features)

        y_train = np.log1p(df_train["selling_price"].values)
        y_test_orig = df_test["selling_price"].values

        X_train.to_parquet(f"{TMP_DIR}/X_train.parquet")
        X_test.to_parquet(f"{TMP_DIR}/X_test.parquet")
        np.save(f"{TMP_DIR}/y_train.npy", y_train)
        np.save(f"{TMP_DIR}/y_test_orig.npy", y_test_orig)

        with open(f"{TMP_DIR}/top_brands.txt", "w") as f:
            f.write("\n".join(top_brands))
        with open(f"{TMP_DIR}/all_features.txt", "w") as f:
            f.write("\n".join(all_features))

        return {
            "x_train_path": f"{TMP_DIR}/X_train.parquet",
            "x_test_path": f"{TMP_DIR}/X_test.parquet",
            "y_train_path": f"{TMP_DIR}/y_train.npy",
            "y_test_orig_path": f"{TMP_DIR}/y_test_orig.npy",
        }

    @task
    def train_model(paths: dict) -> str:
        X_train = pd.read_parquet(paths["x_train_path"])
        y_train = np.load(paths["y_train_path"])

        model = XGBRegressor(**XGB_PARAMS)
        model.fit(X_train, y_train)

        model_path = f"{TMP_DIR}/xgb_model.json"
        model.save_model(model_path)
        return model_path

    @task
    def evaluate_and_log_mlflow(model_path: str, paths: dict) -> str:
        mlflow.set_tracking_uri(os.environ["MLFLOW_TRACKING_URI"])
        mlflow.set_experiment("car_price_xgb")

        X_test = pd.read_parquet(paths["x_test_path"])
        y_test_orig = np.load(paths["y_test_orig_path"])

        model = XGBRegressor()
        model.load_model(model_path)

        y_pred_log = model.predict(X_test)
        y_pred = np.expm1(y_pred_log)

        mae = mean_absolute_error(y_test_orig, y_pred)
        rmse = root_mean_squared_error(y_test_orig, y_pred)
        mape = mean_absolute_percentage_error(y_test_orig, y_pred)
        r2 = r2_score(y_test_orig, y_pred)

        with mlflow.start_run(run_name="xgb_best_training") as run:
            mlflow.log_params(XGB_PARAMS)
            mlflow.log_metrics({"mae": mae, "rmse": rmse, "mape": mape, "r2": r2})
            mlflow.xgboost.log_model(model, "model")
            run_id = run.info.run_id

        return run_id

    @task
    def register_model(mlflow_run_id: str):
        mlflow.set_tracking_uri(os.environ["MLFLOW_TRACKING_URI"])
        client = MlflowClient()
        model_uri = f"runs:/{mlflow_run_id}/model"

        result = mlflow.register_model(model_uri=model_uri, name=MLFLOW_MODEL_NAME)

        for mv in client.search_model_versions(f"name='{MLFLOW_MODEL_NAME}'"):
            if mv.current_stage == "Production" and mv.version != result.version:
                client.transition_model_version_stage(
                    name=MLFLOW_MODEL_NAME, version=mv.version, stage="Archived"
                )

        client.transition_model_version_stage(
            name=MLFLOW_MODEL_NAME, version=result.version, stage="Production"
        )

    raw_path = extract_data()
    paths = preprocess(raw_path)
    model_path = train_model(paths)
    mlflow_run_id = evaluate_and_log_mlflow(model_path, paths)
    register_model(mlflow_run_id)


train_xgb_pipeline()
