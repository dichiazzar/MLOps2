"""Servidor gRPC sobre el mismo modelo xgb_best (mini_tp3_actividad.ipynb aplicado al TP integrador).

Reusa `load_production_model` y `predict_price` de api/app/predict.py — mismo
modelo, mismo scoring que REST y GraphQL. Lo que cambia acá es el transporte:
contrato .proto tipado, payload binario, canal persistente, y un método de
server-streaming para puntuar un lote de autos de una sola llamada.

Clase 7 (seguridad): interceptor con JWT y rol (app/interceptor.py), validación estricta
del auto, mensajes de 1 MB como máximo, lotes de 100 autos como máximo y solo TLS (certificado
del volumen `certs`, ver seguridad-certs). Cada llamada queda en la auditoría.
"""

import logging
import os
import sys
from concurrent import futures

import grpc

import car_price_pb2
import car_price_pb2_grpc
from app import lago
from app.interceptor import InterceptorJWT
from app.predict import ModelState, load_production_model, predict_price, rangos_entrada
from app.seguridad import Auditor, EntradaInvalida, validar_auto

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


MAX_MENSAJE = 1024 * 1024
MAX_LOTE = 100
CERTS = os.environ.get("CERTS_DIR", "/certs")


def _dict_from_proto(car: "car_price_pb2.Car") -> dict:
    campos = ["name", "year", "km_driven", "fuel", "seller_type", "transmission", "owner",
              "mileage", "engine", "max_power", "torque", "seats"]
    return {c: getattr(car, c) for c in campos}


class CarPriceServicer(car_price_pb2_grpc.CarPriceServiceServicer):
    def __init__(self):
        self.state: ModelState = load_production_model()
        logger.info("Modelo cargado (versión %s)", self.state.model_version)

    def _predict_one(self, car_proto, context):
        try:
            car_raw = validar_auto(_dict_from_proto(car_proto), rangos_entrada())
        except EntradaInvalida as exc:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details(str(exc))
            return None
        try:
            return predict_price(self.state, car_raw)
        except Exception:
            logger.exception("Error al predecir")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details("error interno")   # sin detalles internos al cliente
            return None

    def Predict(self, request, context):
        price = self._predict_one(request, context)
        if price is None:
            return car_price_pb2.Prediction()
        return car_price_pb2.Prediction(predicted_price=price, model_version=self.state.model_version)

    def PredictStream(self, request, context):
        if len(request.items) > MAX_LOTE:
            context.abort(grpc.StatusCode.RESOURCE_EXHAUSTED, f"el lote supera {MAX_LOTE} autos")
        for car in request.items:
            price = self._predict_one(car, context)
            if price is None:
                return  # corta el stream; el error ya quedó seteado en el context
            yield car_price_pb2.Prediction(predicted_price=price, model_version=self.state.model_version)


def _credenciales_tls():
    try:
        with open(f"{CERTS}/servidor.key", "rb") as k, open(f"{CERTS}/servidor.crt", "rb") as c:
            return grpc.ssl_server_credentials([(k.read(), c.read())])
    except FileNotFoundError:
        logger.error("No están los certificados en %s: correr "
                     "`docker compose --profile seguridad run --rm seguridad-certs`", CERTS)
        sys.exit(1)


def serve():
    servicer = CarPriceServicer()
    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=10),
        interceptors=[InterceptorJWT(Auditor("grpc", lago.subir_bytes),
                                     version=lambda: servicer.state.model_version)],
        options=[("grpc.max_receive_message_length", MAX_MENSAJE)],
    )
    car_price_pb2_grpc.add_CarPriceServiceServicer_to_server(servicer, server)
    server.add_secure_port("[::]:50051", _credenciales_tls())
    server.start()
    logger.info("Servidor gRPC (solo TLS) escuchando en el puerto 50051...")
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
