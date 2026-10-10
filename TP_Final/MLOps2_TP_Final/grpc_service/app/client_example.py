"""Cliente de ejemplo: prueba unary (Predict) y streaming (PredictStream)
contra el servidor gRPC de este servicio. Correr desde dentro del contenedor
o con `python -m grpc_tools.protoc` corrido localmente para tener los stubs.

Clase 7: el canal es TLS (verifica el servidor con la CA de prueba del volumen `certs`)
y cada llamada manda el token JWT de la variable TOKEN:
    TOKEN=$(docker compose --profile manual run --rm emitir-token jaime analista | tail -1)
    docker compose exec -e TOKEN="$TOKEN" grpc python -m app.client_example
"""

import os
import sys

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


DESTINO = os.environ.get("DESTINO", "localhost:50051")
CA = os.environ.get("CA", "/certs/ca.crt")


def main():
    token = os.environ.get("TOKEN")
    if not token:
        sys.exit("Falta TOKEN: TOKEN=$(docker compose --profile manual run --rm emitir-token jaime analista | tail -1)")
    with open(CA, "rb") as f:
        canal = grpc.secure_channel(DESTINO, grpc.ssl_channel_credentials(root_certificates=f.read()))
    stub = car_price_pb2_grpc.CarPriceServiceStub(canal)
    md = [("authorization", f"Bearer {token}")]

    # --- unary ---
    car = car_price_pb2.Car(**EJEMPLO)
    r = stub.Predict(car, metadata=md)
    print(f"[unary] precio: {r.predicted_price:.2f} | modelo: {r.model_version}")

    # --- server streaming: mismo auto repetido, en un lote ---
    lote = car_price_pb2.CarBatch(items=[car_price_pb2.Car(**EJEMPLO) for _ in range(5)])
    print("[stream]")
    for pred in stub.PredictStream(lote, metadata=md):
        print(f"  precio: {pred.predicted_price:.2f} | modelo: {pred.model_version}")

    canal.close()


if __name__ == "__main__":
    main()
