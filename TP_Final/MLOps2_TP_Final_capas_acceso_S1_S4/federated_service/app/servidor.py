"""Servidor federado: junta los pesos de las concesionarias y los promedia (FedAvg).

Pasos:
  0. Espera a que se conecten todos los clientes.
  1. Arma un esquema común sin ver filas: les pide a los clientes el conteo de
     marcas (elige las 10 principales) y las sumas por columna (calcula media y desvío).
  2. Hace RONDAS rondas de FedAvg: manda los pesos globales, cada cliente entrena
     local y devuelve pesos; el servidor los promedia ponderando por cantidad de autos.
     Si SIGMA > 0, suma ruido a los pesos promediados (privacidad diferencial simple).
  3. En cada ronda mide el error (RMSE en log-precio) con su set de test.
  4. Registra todo en MLflow y guarda el modelo final como `linreg_federado`
     (separado de xgb_best: no reemplaza al modelo en producción).
"""

import json
import os
from collections import Counter

import flwr as fl
import mlflow
import mlflow.sklearn
import numpy as np
from flwr.common import GetPropertiesIns, ndarrays_to_parameters, parameters_to_ndarrays
from sklearn.linear_model import LinearRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from app import datos
from common.constants import TOP_BRAND_COUNT

log = datos.crear_logger("servidor")

NOMBRE_MODELO = "linreg_federado"
EXPERIMENTO = "federado_concesionarias"


class FedAvgConcesionarias(fl.server.strategy.FedAvg):
    def __init__(self):
        k = datos.NUM_CLIENTES
        super().__init__(
            fraction_fit=1.0,           # con 3 clientes, participan todos en cada ronda
            fraction_evaluate=0.0,      # la evaluación la hace el servidor con su test
            min_fit_clients=k,
            min_available_clients=k,
            on_fit_config_fn=self._config_ronda,
            evaluate_fn=self._evaluar,
        )
        self.rng = np.random.RandomState(datos.SEMILLA)
        test = datos.limpiar(datos.leer_csv("servidor/test.csv"), quitar_outliers=False)
        self.test = test
        self.y_test = datos.target(test)
        self.historial = []

    # ---- Paso 1: esquema común, a partir de estadísticas (no de filas) ----
    def initialize_parameters(self, client_manager):
        k = datos.NUM_CLIENTES
        log.info("Esperando a los %d clientes...", k)
        client_manager.wait_for(k)
        clientes = list(client_manager.all().values())

        conteo = Counter()
        for c in clientes:
            res = c.get_properties(GetPropertiesIns({"paso": "marcas"}), timeout=120, group_id=None)
            conteo.update(json.loads(res.properties["marcas"]))
        self.top_brands = [m for m, _ in conteo.most_common(TOP_BRAND_COUNT)]

        n, suma, suma_cuad = 0, 0.0, 0.0
        config = {"paso": "estadisticas", "top_brands": json.dumps(self.top_brands)}
        for c in clientes:
            p = c.get_properties(GetPropertiesIns(config), timeout=120, group_id=None).properties
            n += int(p["n"])
            suma = suma + np.array(json.loads(p["suma"]))
            suma_cuad = suma_cuad + np.array(json.loads(p["suma_cuad"]))
        self.n_total = n
        self.media, self.desvio = datos.media_y_desvio(n, suma, suma_cuad)
        log.info("Esquema común listo: %d autos en total, top marcas %s", n, self.top_brands)

        X_test = datos.matriz_features(self.test, self.top_brands)
        self.X_test = datos.estandarizar(X_test, self.media, self.desvio)
        self.X_test_crudo = X_test
        w, b = datos.init_modelo(X_test.shape[1])
        return ndarrays_to_parameters([w, np.array([b])])

    def _config_ronda(self, ronda):
        return {
            "ronda": ronda,
            "top_brands": json.dumps(self.top_brands),
            "media": json.dumps(self.media.tolist()),
            "desvio": json.dumps(self.desvio.tolist()),
            "epocas": datos.EPOCAS_LOCALES,
            "lr": datos.LR,
        }

    # ---- Paso 2: FedAvg (promedio ponderado por autos) + ruido opcional ----
    def aggregate_fit(self, server_round, results, failures):
        parametros, metricas = super().aggregate_fit(server_round, results, failures)
        if parametros is not None and datos.SIGMA > 0:
            w, b = parameters_to_ndarrays(parametros)
            w = w + self.rng.normal(0, datos.SIGMA, size=w.shape)
            b = b + self.rng.normal(0, datos.SIGMA, size=b.shape)
            parametros = ndarrays_to_parameters([w, b])
        return parametros, metricas

    # ---- Paso 3: error del modelo global en cada ronda ----
    def _evaluar(self, ronda, parameters, config):
        w, b = parameters[0], float(parameters[1][0])
        error = datos.rmse(w, b, self.X_test, self.y_test)
        self.modelo_final = (w, b)
        if ronda > 0:  # la ronda 0 es el modelo en cero, antes de entrenar
            self.historial.append(error)
            mlflow.log_metric("rmse_log", error, step=ronda)
            log.info("Ronda %2d | RMSE (log-precio) = %.4f", ronda, error)
        return error, {"rmse_log": error}


def modelo_sklearn(estrategia) -> Pipeline:
    """Arma un Pipeline de scikit-learn con la media/desvío y los pesos federados,
    para poder guardarlo en MLflow y cargarlo como cualquier otro modelo."""
    w, b = estrategia.modelo_final
    escalado = StandardScaler()
    escalado.mean_ = estrategia.media
    escalado.scale_ = estrategia.desvio
    escalado.var_ = estrategia.desvio**2
    escalado.n_features_in_ = len(w)
    escalado.n_samples_seen_ = estrategia.n_total
    regresion = LinearRegression()
    regresion.coef_ = np.asarray(w)
    regresion.intercept_ = float(b)
    regresion.n_features_in_ = len(w)
    return Pipeline([("escalado", escalado), ("regresion", regresion)])


def main():
    mlflow.set_tracking_uri(os.environ["MLFLOW_TRACKING_URI"])
    mlflow.set_experiment(EXPERIMENTO)
    baseline = datos.leer_json("servidor/baseline_centralizado.json")["rmse_log_centralizado"]

    nombre_run = f"{datos.PARTICION}-sigma{datos.SIGMA:g}"
    with mlflow.start_run(run_name=nombre_run):
        mlflow.log_params({
            "num_clientes": datos.NUM_CLIENTES,
            "rondas": datos.RONDAS,
            "epocas_locales": datos.EPOCAS_LOCALES,
            "lr": datos.LR,
            "particion": datos.PARTICION,
            "sigma": datos.SIGMA,
            "modelo": "regresion lineal (SGD)",
            "agregacion": "FedAvg",
        })
        mlflow.log_metric("rmse_log_centralizado", baseline)

        estrategia = FedAvgConcesionarias()
        fl.server.start_server(
            server_address="0.0.0.0:8080",
            config=fl.server.ServerConfig(num_rounds=datos.RONDAS),
            strategy=estrategia,
        )

        final = estrategia.historial[-1]
        mlflow.log_metrics({
            "rmse_log_final": final,
            "diferencia_vs_centralizado": final - baseline,
        })
        mlflow.log_dict(
            {"top_brands": estrategia.top_brands, "columnas": datos.columnas(estrategia.top_brands)},
            "esquema.json",
        )
        pipe = modelo_sklearn(estrategia)
        # chequeo: el Pipeline predice lo mismo que los pesos federados
        assert np.allclose(pipe.predict(estrategia.X_test_crudo),
                           estrategia.X_test @ estrategia.modelo_final[0] + estrategia.modelo_final[1])
        mlflow.sklearn.log_model(pipe, "model", registered_model_name=NOMBRE_MODELO)

        log.info("=" * 60)
        log.info("Partición %s, sigma %g", datos.PARTICION, datos.SIGMA)
        log.info("RMSE centralizado: %.4f | RMSE federado: %.4f | diferencia: %+.4f",
                 baseline, final, final - baseline)
        log.info("Modelo registrado en MLflow como '%s'", NOMBRE_MODELO)


if __name__ == "__main__":
    main()
