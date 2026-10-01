FROM python:3.9-slim-buster

WORKDIR /app

# Install Poetry
RUN pip install poetry

# Copy pyproject.toml and poetry.lock to the working directory
COPY pyproject.toml poetry.lock ./

# Install dependencies using Poetry
RUN poetry install --no-root

# Copy the proto directory
COPY proto ./proto/

# Para gRPC, necesitamos generar el código proto dentro del contenedor
RUN poetry run python -m grpc_tools.protoc -I./proto --python_out=. --grpc_python_out=. ./proto/ml_service.proto

# Copy the rest of the application code
COPY . .
