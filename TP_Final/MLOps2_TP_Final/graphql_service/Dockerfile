# Contexto de build: TP_Final/ (para poder copiar common/ y api/app/predict.py
# de MLOps1_final sin duplicarlos, ver docker-compose.yml de esta carpeta).
FROM python:3.11-slim
WORKDIR /app

COPY MLOps2_TP_Final/graphql_service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY MLOps1_final/common /app/common
# predict.py de MLOps1_final se copia como predict_mlflow.py y se reemplaza por la
# versión de MLOps2 (clase 6), que lee la metadata del modelo desde MLflow.
COPY MLOps1_final/api/app/predict.py /app/app/predict_mlflow.py
COPY MLOps2_TP_Final/datalake/compartido/predict.py /app/app/predict.py
COPY MLOps2_TP_Final/datalake/compartido/lago.py /app/app/lago.py
COPY MLOps1_final/api/app/__init__.py /app/app/__init__.py
COPY MLOps2_TP_Final/graphql_service/app/main.py /app/app/main.py

ENV PYTHONPATH=/app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
