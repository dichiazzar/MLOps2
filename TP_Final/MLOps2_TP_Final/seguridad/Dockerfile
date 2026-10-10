# Contexto de build: TP_Final/ (para copiar common/ de MLOps1_final sin duplicarlo).
# Imagen de herramientas de seguridad (clase 7): tests, emitir tokens, certificados y demo.
FROM python:3.11-slim
WORKDIR /app

COPY MLOps2_TP_Final/seguridad/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY MLOps1_final/common /app/common
COPY MLOps2_TP_Final/seguridad/app /app/app
COPY MLOps2_TP_Final/seguridad/compartido/seguridad.py /app/app/seguridad.py
COPY MLOps2_TP_Final/rest_service/app/seguridad_rest.py /app/app/seguridad_rest.py
COPY MLOps2_TP_Final/graphql_service/app/costo.py /app/app/costo.py
COPY MLOps2_TP_Final/seguridad/tests /app/tests

ENV PYTHONPATH=/app
CMD ["python", "-m", "pytest", "tests", "-v"]
