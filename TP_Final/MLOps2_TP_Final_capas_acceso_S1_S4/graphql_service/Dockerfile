# Contexto de build: MLOps1_final/ (para poder copiar common/ y api/app/predict.py
# sin duplicarlos — ver docker-compose.yml de esta carpeta).
FROM python:3.11-slim
WORKDIR /app

COPY MLOps2_TP_Final_capas_acceso_S1_S4/graphql_service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY MLOps1_final/common /app/common
COPY MLOps1_final/api/app/predict.py /app/app/predict.py
COPY MLOps1_final/api/app/__init__.py /app/app/__init__.py
COPY MLOps2_TP_Final_capas_acceso_S1_S4/graphql_service/app/main.py /app/app/main.py

ENV PYTHONPATH=/app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
