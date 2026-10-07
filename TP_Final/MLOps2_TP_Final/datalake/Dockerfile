# Contexto de build: TP_Final/ (para poder copiar common/ y api/app/predict.py
# de MLOps1_final sin duplicarlos, ver docker-compose.yml de esta carpeta).
# Imagen del paso "preparar lake" (clase 6): se corre a mano.
FROM python:3.11-slim
WORKDIR /app

COPY MLOps2_TP_Final/datalake/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY MLOps1_final/common /app/common
COPY MLOps1_final/api/app/__init__.py /app/app/__init__.py
COPY MLOps1_final/api/app/predict.py /app/app/predict_mlflow.py
COPY MLOps2_TP_Final/datalake/compartido/predict.py /app/app/predict.py
COPY MLOps2_TP_Final/datalake/compartido/lago.py /app/app/lago.py
COPY MLOps2_TP_Final/datalake/app/preparar.py /app/app/preparar.py

ENV PYTHONPATH=/app
CMD ["python", "-m", "app.preparar"]
