# Contexto de build: TP_Final/ (para poder copiar common/ de MLOps1_final
# sin duplicarlo, ver docker-compose.yml de esta carpeta).
# Una sola imagen para el servidor, los clientes y el script que reparte los datos:
# el comando de cada uno lo define su servicio en docker-compose.yml.
FROM python:3.11-slim
WORKDIR /app

COPY MLOps2_TP_Final/federated_service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY MLOps1_final/common /app/common
COPY MLOps2_TP_Final/federated_service/app /app/app

ENV PYTHONPATH=/app
CMD ["python", "-m", "app.servidor"]
