# Contexto de build: TP_Final/ (para poder copiar la API de MLOps1_final sin duplicarla).
# Es la misma API REST de MLOps1_final (mismo código, mismas dependencias). La única
# diferencia es predict.py: se usa la versión de MLOps2 (clase 6), que lee la
# metadata del modelo desde MLflow en vez de recalcularla al arrancar.
FROM python:3.11-slim
WORKDIR /app

COPY MLOps1_final/api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY MLOps1_final/common /app/common
COPY MLOps1_final/api/app /app/app
COPY MLOps1_final/api/app/predict.py /app/app/predict_mlflow.py
COPY MLOps2_TP_Final/datalake/compartido/predict.py /app/app/predict.py

ENV PYTHONPATH=/app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
