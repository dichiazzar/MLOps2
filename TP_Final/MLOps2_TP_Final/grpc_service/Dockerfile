# Contexto de build: TP_Final/ (para poder copiar common/ y api/app/predict.py
# de MLOps1_final sin duplicarlos, ver docker-compose.yml de esta carpeta).
FROM python:3.11-slim
WORKDIR /app

COPY MLOps2_TP_Final/grpc_service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY MLOps1_final/common /app/common
COPY MLOps1_final/api/app/predict.py /app/app/predict.py
COPY MLOps1_final/api/app/__init__.py /app/app/__init__.py
COPY MLOps2_TP_Final/grpc_service/proto ./proto
COPY MLOps2_TP_Final/grpc_service/app/server.py /app/app/server.py
COPY MLOps2_TP_Final/grpc_service/app/client_example.py /app/app/client_example.py

# Generar los stubs como módulos top-level en /app (no dentro de app/, porque
# el código que grpc_tools genera para car_price_pb2_grpc.py hace
# `import car_price_pb2` absoluto, no relativo al paquete).
# Tampoco se generan en un volume montado en runtime: un bind mount de dev
# pisaría estos archivos — ver grpc_service de ml_services_comparison, clase3,
# para el bug que esto evita.
RUN python -m grpc_tools.protoc -I./proto --python_out=. --grpc_python_out=. ./proto/car_price.proto

ENV PYTHONPATH=/app

CMD ["python", "-m", "app.server"]
