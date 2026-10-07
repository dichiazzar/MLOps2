"""Cliente federado: una concesionaria que entrena con sus propios autos.

Lee SOLO su parte de los datos (s3://federado/<particion>/cliente_<id>.csv).
Nunca manda filas al servidor. Lo único que sale de acá es:
  - antes de entrenar: conteo de autos por marca, y sumas por columna
    (para que el servidor arme las columnas comunes y la media/desvío global);
  - en cada ronda: los pesos del modelo entrenado localmente y cuántos autos usó.
"""

import json
import os
import time

import flwr as fl
import grpc
import numpy as np

from app import datos

CLIENTE_ID = int(os.environ["CLIENTE_ID"])
SERVIDOR = os.environ.get("SERVIDOR", "fl-servidor:8080")
log = datos.crear_logger(f"cliente_{CLIENTE_ID}")


class Concesionaria(fl.client.NumPyClient):
    def __init__(self):
        key = f"{datos.PARTICION}/cliente_{CLIENTE_ID}.csv"
        self.df = datos.limpiar(datos.leer_csv(key))
        self.y = datos.target(self.df)
        self.X = None   # se arma cuando llega el esquema común del servidor
        log.info("Datos locales: %d autos (%s)", len(self.df), key)

    # --- Paso previo: el servidor pide estadísticas, nunca filas ---
    def get_properties(self, config):
        if config["paso"] == "marcas":
            conteo = self.df["brand"].value_counts().to_dict()
            return {"marcas": json.dumps(conteo)}
        if config["paso"] == "estadisticas":
            X = datos.matriz_features(self.df, json.loads(config["top_brands"]))
            return {
                "n": len(X),
                "suma": json.dumps(X.sum(0).tolist()),
                "suma_cuad": json.dumps((X**2).sum(0).tolist()),
            }
        return {}

    # --- Cada ronda: entrenar local con los pesos globales y devolver los nuevos ---
    def fit(self, parameters, config):
        if self.X is None:
            X = datos.matriz_features(self.df, json.loads(config["top_brands"]))
            self.X = datos.estandarizar(X, json.loads(config["media"]), json.loads(config["desvio"]))
        w, b = parameters[0], float(parameters[1][0])
        w, b = datos.entrenar(w, b, self.X, self.y, int(config["epocas"]), float(config["lr"]))
        log.info("Ronda %s: entrené con %d autos | RMSE local %.4f",
                 config["ronda"], len(self.y), datos.rmse(w, b, self.X, self.y))
        return [w, np.array([b])], len(self.y), {}


if __name__ == "__main__":
    cliente = Concesionaria().to_client()
    # El servidor puede tardar unos segundos en arrancar: reintentar mientras no responda.
    for intento in range(1, 31):
        try:
            log.info("Conectando al servidor %s (intento %d)...", SERVIDOR, intento)
            fl.client.start_client(server_address=SERVIDOR, client=cliente)
            break
        except grpc.RpcError as e:
            if e.code() != grpc.StatusCode.UNAVAILABLE:
                raise
            time.sleep(3)
    else:
        raise SystemExit("No se pudo conectar al servidor.")
    log.info("El servidor terminó el entrenamiento. Cliente cerrado.")
