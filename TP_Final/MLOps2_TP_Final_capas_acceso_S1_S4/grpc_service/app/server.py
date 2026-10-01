"""Servidor gRPC sobre el mismo modelo xgb_best (mini_tp3_actividad.ipynb aplicado al TP integrador).

Reusa `load_production_model` y `predict_price` de api/app/predict.py — mismo
modelo, mismo scoring que REST y GraphQL. Lo que cambia acá es el transporte:
contrato .proto tipado, payload binario, canal persistente, y un método de
server-streaming para puntuar un lote de autos de una sola llamada.
"""

import logging
from concurrent import futures

import grpc

import car_price_pb2
import car_price_pb2_grpc
from app.predict import ModelState, load_production_model, predict_price
from common.schemas import CarRawInput

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _car_from_proto(car: "car_price_pb2.Car") -> CarRawInput:
    return CarRawInput(
        name=car.name,
        year=car.year,
        km_driven=car.km_driven,
        fuel=car.fuel,
        seller_type=car.seller_type,
        transmission=car.transmission,
        owner=car.owner,
        mileage=car.mileage,
        engine=car.engine,
        max_power=car.max_power,
        torque=car.torque,
        seats=car.seats,
    )


class CarPriceServicer(car_price_pb2_grpc.CarPriceServiceServicer):
    def __init__(self):
        self.state: ModelState = load_production_model()
        logger.info("Modelo cargado (versión %s)", self.state.model_version)

    def _predict_one(self, car_proto, context):
        try:
            car_raw = _car_from_proto(car_proto)
            price = predict_price(self.state, car_raw)
            return price
        except Exception as exc:  # entrada inválida, categoría desconocida, etc.
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details(str(exc))
            return None

    def Predict(self, request, context):
        price = self._predict_one(request, context)
        if price is None:
            return car_price_pb2.Prediction()
        return car_price_pb2.Prediction(
            predicted_price=price, model_version=self.state.model_version
        )

    def PredictStream(self, request, context):
        for car in request.items:
            price = self._predict_one(car, context)
            if price is None:
                return  # corta el stream; el error ya quedó seteado en el context
            yield car_price_pb2.Prediction(
                predicted_price=price, model_version=self.state.model_version
            )


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    car_price_pb2_grpc.add_CarPriceServiceServicer_to_server(CarPriceServicer(), server)
    server.add_insecure_port("[::]:50051")
    server.start()
    logger.info("Servidor gRPC escuchando en el puerto 50051...")
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
