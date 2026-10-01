import grpc
from concurrent import futures
import joblib
import ml_service_pb2
import ml_service_pb2_grpc
import numpy as np
import os

MODEL_PATH = os.path.join(os.path.dirname(__file__), 'model.pkl')

class MLServiceServicer(ml_service_pb2_grpc.MLServiceServicer):
    def __init__(self):
        try:
            self.model = joblib.load(MODEL_PATH)
            print(f"Modelo cargado desde {MODEL_PATH}")
        except FileNotFoundError:
            print(f"Error: No se encontró el modelo en {MODEL_PATH}. Asegúrate de haberlo entrenado y guardado.")
            self.model = None

    def Predict(self, request, context):
        if self.model is None:
            context.set_details("Modelo no cargado")
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            return ml_service_pb2.Prediction()

        features = np.array(request.values).reshape(1, -1)
        prediction = self.model.predict(features)[0]
        return ml_service_pb2.Prediction(class_id=int(prediction))

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    ml_service_pb2_grpc.add_MLServiceServicer_to_server(MLServiceServicer(), server)
    server.add_insecure_port('[::]:50051')
    server.start()
    print("Servidor gRPC escuchando en el puerto 50051...")
    server.wait_for_termination()

if __name__ == '__main__':
    serve()
