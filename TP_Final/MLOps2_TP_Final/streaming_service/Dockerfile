# Contexto de build: MLOps1_final/ (para poder copiar common/ y api/app/predict.py
# sin duplicarlos — ver docker-compose.yml de esta carpeta).
FROM python:3.11-slim
WORKDIR /app

COPY MLOps2_TP_Final/streaming_service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY MLOps1_final/common /app/common
COPY MLOps1_final/api/app/predict.py /app/app/predict.py
COPY MLOps1_final/api/app/__init__.py /app/app/__init__.py
COPY MLOps2_TP_Final/streaming_service/app/consumer.py /app/app/consumer.py
COPY MLOps2_TP_Final/streaming_service/app/producer.py /app/app/producer.py

ENV PYTHONPATH=/app
# El comando real (consumer o producer) lo define el servicio en docker-compose.yml
CMD ["python", "-m", "app.consumer"]
