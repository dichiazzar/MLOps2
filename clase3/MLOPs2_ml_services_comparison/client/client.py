import grpc
import requests
import json
import time
import numpy as np
import ml_service_pb2 # Este archivo será generado
import ml_service_pb2_grpc # Este archivo será generado

# Configuración
GRPC_HOST = "localhost:50051"
GRAPHQL_URL = "http://localhost:8000/graphql"
REST_URL = "http://localhost:8001/predict"
NUM_REQUESTS = 1000 # Número de solicitudes para la prueba de rendimiento
EXAMPLE_FEATURES = [5.1, 3.5, 1.4, 0.2] # Ejemplo para el dataset Iris

# --- gRPC Client ---
def run_grpc_client():
    start_time = time.time()
    with grpc.insecure_channel(GRPC_HOST) as channel:
        stub = ml_service_pb2_grpc.MLServiceStub(channel)
        for _ in range(NUM_REQUESTS):
            request = ml_service_pb2.Feature(values=EXAMPLE_FEATURES)
            response = stub.Predict(request)
            # print(f"gRPC Prediction: {response.class_id}")
    end_time = time.time()
    return end_time - start_time

# --- GraphQL Client ---
def run_graphql_client():
    start_time = time.time()
    query = """
    query Predict($features: [Float!]!) {
      predict(features: $features) {
        class_id
      }
    }
    """
    headers = {"Content-Type": "application/json"}
    for _ in range(NUM_REQUESTS):
        payload = {
            "query": query,
            "variables": {"features": EXAMPLE_FEATURES}
        }
        response = requests.post(GRAPHQL_URL, headers=headers, data=json.dumps(payload))
        response.raise_for_status() # Lanza una excepción si la respuesta no es 2xx
        # print(f"GraphQL Prediction: {response.json()['data']['predict']['class_id']}")
    end_time = time.time()
    return end_time - start_time

# --- REST Client ---
def run_rest_client():
    start_time = time.time()
    headers = {"Content-Type": "application/json"}
    for _ in range(NUM_REQUESTS):
        payload = {"values": EXAMPLE_FEATURES}
        response = requests.post(REST_URL, headers=headers, data=json.dumps(payload))
        response.raise_for_status() # Lanza una excepción si la respuesta no es 2xx
        # print(f"REST Prediction: {response.json()['class_id']}")
    end_time = time.time()
    return end_time - start_time

if __name__ == "__main__":
    print(f"Realizando {NUM_REQUESTS} solicitudes a cada servicio con features: {EXAMPLE_FEATURES}")

    print("\n--- Probando gRPC ---")
    grpc_time = run_grpc_client()
    print(f"Tiempo total gRPC: {grpc_time:.4f} segundos")
    print(f"Tiempo promedio por solicitud gRPC: {grpc_time / NUM_REQUESTS * 1000:.4f} ms")

    print("\n--- Probando GraphQL ---")
    graphql_time = run_graphql_client()
    print(f"Tiempo total GraphQL: {graphql_time:.4f} segundos")
    print(f"Tiempo promedio por solicitud GraphQL: {graphql_time / NUM_REQUESTS * 1000:.4f} ms")

    print("\n--- Probando REST ---")
    rest_time = run_rest_client()
    print(f"Tiempo total REST: {rest_time:.4f} segundos")
    print(f"Tiempo promedio por solicitud REST: {rest_time / NUM_REQUESTS * 1000:.4f} ms")

    print("\n--- Resumen de Tiempos ---")
    print(f"gRPC: {grpc_time:.4f} s")
    print(f"GraphQL: {graphql_time:.4f} s")
    print(f"REST: {rest_time:.4f} s")
    
