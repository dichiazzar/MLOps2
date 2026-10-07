"""Cliente de ejemplo: prueba unary (Predict) y streaming (PredictStream)
contra el servidor gRPC de este servicio. Correr desde dentro del contenedor
o con `python -m grpc_tools.protoc` corrido localmente para tener los stubs.
"""

import grpc

import car_price_pb2
import car_price_pb2_grpc

EJEMPLO = dict(
    name="Maruti Swift Dzire VDI",
    year=2014,
    km_driven=145500,
    fuel="Diesel",
    seller_type="Individual",
    transmission="Manual",
    owner="First Owner",
    mileage="23.4 kmpl",
    engine="1248 CC",
    max_power="74 bhp",
    torque="190Nm@ 2000rpm",
    seats=5,
)


def main():
    canal = grpc.insecure_channel("localhost:50051")
    stub = car_price_pb2_grpc.CarPriceServiceStub(canal)

    # --- unary ---
    car = car_price_pb2.Car(**EJEMPLO)
    r = stub.Predict(car)
    print(f"[unary] precio: {r.predicted_price:.2f} | modelo: {r.model_version}")

    # --- server streaming: mismo auto repetido, en un lote ---
    lote = car_price_pb2.CarBatch(items=[car_price_pb2.Car(**EJEMPLO) for _ in range(5)])
    print("[stream]")
    for pred in stub.PredictStream(lote):
        print(f"  precio: {pred.predicted_price:.2f} | modelo: {pred.model_version}")

    canal.close()


if __name__ == "__main__":
    main()
