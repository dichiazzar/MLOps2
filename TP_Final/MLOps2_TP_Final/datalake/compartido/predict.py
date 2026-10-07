"""Versión MLOps2 de `api/app/predict.py` (MLOps1_final), con las mismas funciones.

Al construir cada imagen (REST, GraphQL, gRPC, streaming):
  - el `predict.py` original de MLOps1_final se copia como `app/predict_mlflow.py`;
  - este archivo se copia como `app/predict.py`.
Así el código de las capas no cambia: siguen importando `load_production_model`
y `predict_price` desde `app.predict`.

Qué cambia respecto de MLOps1_final:
  - El modelo se sigue bajando de MLflow (versión en Production), igual que antes.
  - Las marcas principales y el orden de las columnas se leen de `lake_metadata.json`,
    un archivo que el paso "preparar lake" agrega al mismo run de MLflow del modelo.
    Antes, cada capa bajaba el dataset crudo y rehacía parte del preprocesamiento
    al arrancar para calcularlos.
  - Si ese archivo no está (por ejemplo, Airflow entrenó una versión nueva y todavía
    no se corrió "preparar lake"), se calculan como antes y se avisa en el log.
"""

import logging
import os

import mlflow
import mlflow.xgboost
from mlflow.tracking import MlflowClient

from app.predict_mlflow import ModelState, _derive_brands_and_features, predict_price  # noqa: F401
from common.constants import MLFLOW_MODEL_NAME

logger = logging.getLogger(__name__)

METADATA_ARTIFACT = "lake_metadata.json"


def load_production_model() -> ModelState:
    mlflow.set_tracking_uri(os.environ["MLFLOW_TRACKING_URI"])
    client = MlflowClient()

    versions = client.get_latest_versions(MLFLOW_MODEL_NAME, stages=["Production"])
    if not versions:
        raise RuntimeError(f"No Production version found for model '{MLFLOW_MODEL_NAME}'")
    mv = versions[0]

    # Se carga por número de versión (no por "Production") para que modelo y
    # metadata salgan siempre del mismo run, aunque el stage cambie en el medio.
    model = mlflow.xgboost.load_model(f"models:/{MLFLOW_MODEL_NAME}/{mv.version}")

    try:
        meta = mlflow.artifacts.load_dict(f"runs:/{mv.run_id}/{METADATA_ARTIFACT}")
        top_brands, all_features = meta["top_brands"], meta["all_features"]
        logger.info("Modelo v%s: metadata leída de MLflow (%s)", mv.version, METADATA_ARTIFACT)
    except Exception:
        logger.warning(
            "Modelo v%s: el run no tiene %s; se calcula desde el dataset crudo como en "
            "MLOps1_final (más lento). Correr 'preparar lake' para agregarla.",
            mv.version, METADATA_ARTIFACT,
        )
        top_brands, all_features = _derive_brands_and_features()

    return ModelState(
        model=model,
        top_brands=top_brands,
        all_features=all_features,
        model_version=mv.version,
    )
