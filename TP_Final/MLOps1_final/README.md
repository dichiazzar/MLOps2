# TP Final - Operaciones de Aprendizaje de Maquina 1 (MLOps 1)
## Prediccion del Precio de Venta de Autos Usados con Machine Learning implementado con herramientas de MLOps

**Integrantes:** Cristhian Pettico — Rodolfo Di Chiazza  
**Curso:** Operaciones Aprendizaje de Maquina 1 | CEIA — FIUBA  
**Fecha:** Agosto 2026

Utilizando el modelo XGBoost implementado en la materia Aprendizaje de Máquina 1 por los mismos integrantes de equipo (ver archivo "TP Final AdM.ipynb" como referencia), se construye un servicio de orquestación en Docker para el ciclo de vida del modelo.

El stack implementado en Docker sirve el modelo XGBoost `xgb_best` (entrenado con el dataset de autos usados "Car Dekho") mediante una API REST, con el entrenamiento orquestado por Airflow y registrado en MLflow (metadata en Postgres, artefactos en MinIO).

## Servicios

| Servicio   | URL                     | Credenciales          |
|------------|-------------------------|-----------------------|
| Airflow UI | http://localhost:8080   | admin / admin         |
| MLflow UI  | http://localhost:5000   | -                      |
| MinIO UI   | http://localhost:9001   | minioadmin / minioadmin123 |
| API docs   | http://localhost:8000/docs | -                   |

## Inicio rápido

```bash
docker compose up -d --build
```

Esperar a que todos los servicios reporten estar 'healthy' (`docker compose ps`), y luego disparar el entrenamiento:

```bash
docker compose exec airflow-webserver airflow dags unpause train_xgb_pipeline
docker compose exec airflow-webserver airflow dags trigger train_xgb_pipeline
```

Una vez que el DAG termine (verificalo en la Airflow UI), reiniciar la API para que tome el nuevo modelo `Production` registrado:

```bash
docker compose restart api
```

Luego se puede llamar al endpoint de predicción:

Bash Linux:
```bash
curl -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Maruti Swift Dzire VDI",
    "year": 2014,
    "km_driven": 145500,
    "fuel": "Diesel",
    "seller_type": "Individual",
    "transmission": "Manual",
    "owner": "First Owner",
    "mileage": "23.4 kmpl",
    "engine": "1248 CC",
    "max_power": "74 bhp",
    "torque": "190Nm@ 2000rpm",
    "seats": 5
  }'
```

CMD Windows (no powershell):
```bash
curl -X POST http://localhost:8000/predict -H "Content-Type: application/json" -d "{\"name\": \"Maruti Swift Dzire VDI\", \"year\": 2014, \"km_driven\": 145500, \"fuel\": \"Diesel\", \"seller_type\": \"Individual\", \"transmission\": \"Manual\", \"owner\": \"First Owner\", \"mileage\": \"23.4 kmpl\", \"engine\": \"1248 CC\", \"max_power\": \"74 bhp\", \"torque\": \"190Nm@ 2000rpm\", \"seats\": 5}"
```

O ejecutar `scripts/smoke_test.sh` para hacer todo lo anterior automáticamente.

Otros endpoints disponibles:

- `GET /health` — estado de la API e informacion acerca de modelo cargado.
- `GET /model/info` — metadata sobre el modelo actualmente cargado (versión, cantidad de features, marcas principales).
- `GET /predictions/recent?limit=N` — las últimas N predicciones servidas, de la más reciente a la más antigua (logueadas en Postgres).

La documentación interactiva completa (Swagger UI) está disponible en `http://localhost:8000/docs`.

## El diseño realizado y luego implementado incluye:

1. **Airflow**: un DAG de entrenamiento (`train_xgb_pipeline`) que va desde la carga de datos hasta el registro del modelo en MLflow. El trigger es manual, sin reentrenamiento periódico automático en esta fase. Es importante mencionar que el paso de datos entre las tareas del pipeline se hace a través del directorio /tmp en la instancia docker que ejecuta Airflow. Esto podría mejorarse en futuras versiones subiendo los datos intermedios a MinIO.
2. **MLflow**: Tracking Server con PostgreSQL como backend store (params/metrics/registry) y **MinIO como artifact store** (modelo serializado vía `mlflow.xgboost.log_model`).
3. **Model loading en FastAPI**: al iniciar, la API descarga la versión marcada `Production` desde el **MLflow Model Registry**. Cierra el ciclo Airflow → MLflow → FastAPI.
4. **Preprocesamiento compartido**: paquete Python `common/` con toda la lógica de parsing/feature engineering extraída del notebook, usado tanto por el DAG de Airflow como por FastAPI.
5. **Formato de entrada de la API**: campos crudos idénticos al dataset original (`name`, `year`, `km_driven`, `fuel`, `seller_type`, `transmission`, `owner`, `mileage`, `engine`, `max_power`, `torque`, `seats`). La API aplica el pipeline completo de parsing internamente.
6. **Alcance del DAG**: reproduce fielmente el preprocesamiento y feature engineering del notebook, pero entrena XGBoost directamente con los hiperparámetros ya encontrados por Optuna (hardcodeados en `common/constants.py`), sin re-ejecutar la búsqueda de parámetros óptimos.
7. **PostgreSQL**: cumple doble rol — (a) backend de metadata para MLflow y Airflow (bases separadas `mlflow_db`, `airflow_db`), y (b) base `predictions_db` donde FastAPI loguea cada predicción servida (input, output, timestamp, versión de modelo usada) para trazabilidad.
8. **Origen de datos crudos**: el CSV se sube a MinIO (bucket `raw-data`) como "data lake" vía un script de setup inicial; el DAG de Airflow lo descarga desde ahí.
9. **Versiones**: se usan versiones recientes, estables y compatibles entre sí (Python 3.11, Airflow 2.9/2.10, Postgres 16, MinIO y MLflow recientes).


## Ejecutar los tests unitarios de `common` localmente

```bash
pip install -r requirements-dev.txt
python -m pytest common/tests/ -v
```
