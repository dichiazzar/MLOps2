# Contexto de build: TP_Final/ (para poder copiar la API de MLOps1_final sin duplicarla).
# Es la misma API REST de MLOps1_final (mismo código, mismas dependencias). Diferencias:
#   - predict.py: versión de MLOps2 (clase 6: metadata desde MLflow; clase 7: integridad).
#   - seguridad (clase 7): la API se sirve envuelta por app/seguro.py (JWT, roles, límites,
#     validación y auditoría), sin modificar su código.
FROM python:3.11-slim
WORKDIR /app

COPY MLOps1_final/api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt pyjwt==2.8.0

COPY MLOps1_final/common /app/common
COPY MLOps1_final/api/app /app/app
COPY MLOps1_final/api/app/predict.py /app/app/predict_mlflow.py
COPY MLOps2_TP_Final/datalake/compartido/predict.py /app/app/predict.py
COPY MLOps2_TP_Final/datalake/compartido/lago.py /app/app/lago.py
COPY MLOps2_TP_Final/seguridad/compartido/seguridad.py /app/app/seguridad.py
COPY MLOps2_TP_Final/rest_service/app/seguridad_rest.py /app/app/seguridad_rest.py
COPY MLOps2_TP_Final/rest_service/app/seguro.py /app/app/seguro.py

ENV PYTHONPATH=/app
CMD ["uvicorn", "app.seguro:app", "--host", "0.0.0.0", "--port", "8000"]
