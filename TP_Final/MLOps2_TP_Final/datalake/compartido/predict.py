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

Clase 7 (seguridad):
  - Antes de cargar el modelo se verifica su hash contra `seguridad_modelo.json` (lo
    registra lake-preparar en el mismo run). Si no coincide, el modelo NO se carga.
  - Si el run no tiene ese archivo: con EXIGIR_INTEGRIDAD=true (por defecto) tampoco
    se carga; con EXIGIR_INTEGRIDAD=false se carga con un warning (desarrollo).
  - `rangos_entrada()` devuelve los rangos de entrenamiento para validar los autos.
"""

import logging
import os
import tempfile

import mlflow
import mlflow.xgboost
from mlflow.tracking import MlflowClient

from app.predict_mlflow import ModelState, _derive_brands_and_features, predict_price  # noqa: F401
from app.seguridad import ARTEFACTO_SEGURIDAD, exigir_integridad, verificar_integridad
from common.constants import MLFLOW_MODEL_NAME

logger = logging.getLogger(__name__)

METADATA_ARTIFACT = "lake_metadata.json"

# Lo que importan las capas desde app.predict (mismas funciones que MLOps1_final).
__all__ = ["ModelState", "load_production_model", "predict_price", "METADATA_ARTIFACT", "rangos_entrada"]

_RANGOS = None


def rangos_entrada():
    """Rangos de entrenamiento del último modelo cargado (None si no hay seguridad_modelo.json)."""
    return _RANGOS


def _cargar_dict(run_id, nombre):
    try:
        return mlflow.artifacts.load_dict(f"runs:/{run_id}/{nombre}")
    except Exception:
        return None


def load_production_model() -> ModelState:
    global _RANGOS
    mlflow.set_tracking_uri(os.environ["MLFLOW_TRACKING_URI"])
    client = MlflowClient()

    versions = client.get_latest_versions(MLFLOW_MODEL_NAME, stages=["Production"])
    if not versions:
        raise RuntimeError(f"No Production version found for model '{MLFLOW_MODEL_NAME}'")
    mv = versions[0]

    # Se baja el modelo a una carpeta local, se verifica su hash y recién ahí se carga
    # (clase 7). Se usa el número de versión (no "Production") para que modelo, metadata
    # y hash salgan siempre del mismo run, aunque el stage cambie en el medio.
    carpeta = mlflow.artifacts.download_artifacts(
        artifact_uri=f"models:/{MLFLOW_MODEL_NAME}/{mv.version}",
        dst_path=tempfile.mkdtemp(prefix="modelo-"))
    seguridad = _cargar_dict(mv.run_id, ARTEFACTO_SEGURIDAD)
    resultado = verificar_integridad(carpeta, seguridad, exigir_integridad())
    if resultado == "ok":
        logger.info("Modelo v%s: integridad verificada (%s)", mv.version, ARTEFACTO_SEGURIDAD)
    else:
        logger.warning("Modelo v%s: SIN verificar integridad (no hay %s y EXIGIR_INTEGRIDAD=false)",
                       mv.version, ARTEFACTO_SEGURIDAD)
    model = mlflow.xgboost.load_model(carpeta)
    _RANGOS = (seguridad or {}).get("rangos_entrada")

    meta = _cargar_dict(mv.run_id, METADATA_ARTIFACT)
    if meta:
        top_brands, all_features = meta["top_brands"], meta["all_features"]
        logger.info("Modelo v%s: metadata leída de MLflow (%s)", mv.version, METADATA_ARTIFACT)
    else:
        logger.warning(
            "Modelo v%s: el run no tiene %s; se calcula desde el dataset crudo como en "
            "MLOps1_final (más lento). Correr 'preparar lake' para agregarla.",
            mv.version, METADATA_ARTIFACT,
        )
        top_brands, all_features = _derive_brands_and_features()

    return ModelState(model=model, top_brands=top_brands, all_features=all_features,
                      model_version=mv.version)
