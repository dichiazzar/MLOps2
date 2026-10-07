"""Consumidor con inferencia online + métricas por ventana (mini_tp4_actividad.ipynb
aplicado al TP integrador). Reusa `load_production_model` y `predict_price` de
api/app/predict.py — mismo modelo que REST, GraphQL y gRPC.

A diferencia de las otras tres capas, acá no hay un cliente que pregunte: el
consumidor puntúa cada evento a medida que llega del topic y agrega, sobre una
ventana deslizante de 1s, throughput, latencia p95 y la media de `km_driven`
como indicador simple de drift de entrada.
"""

import json
import logging
import time
from collections import deque

import numpy as np
from kafka import KafkaConsumer

from app.predict import ModelState, load_production_model, predict_price
from common.schemas import CarRawInput

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BROKER = "redpanda:9092"
TOPIC = "autos"

VENTANA_SEGUNDOS = 1.0
CADA_N_EVENTOS = 50
# Umbral de drift: el dataset de entrenamiento tiene km_driven con media ~70k.
# Si la media móvil de la ventana supera esto, algo cambió en la distribución
# de entrada respecto a lo que el modelo aprendió.
UMBRAL_KM_DRIFT = 150_000


def _car_from_event(ev: dict) -> CarRawInput:
    return CarRawInput(
        name=ev["name"],
        year=ev["year"],
        km_driven=ev["km_driven"],
        fuel=ev["fuel"],
        seller_type=ev["seller_type"],
        transmission=ev["transmission"],
        owner=ev["owner"],
        mileage=ev["mileage"],
        engine=ev["engine"],
        max_power=ev["max_power"],
        torque=ev["torque"],
        seats=ev["seats"],
    )


def main():
    state: ModelState = load_production_model()
    logger.info("Modelo cargado (versión %s). Escuchando topic '%s'...", state.model_version, TOPIC)

    consumer = KafkaConsumer(
        TOPIC,
        bootstrap_servers=BROKER,
        auto_offset_reset="earliest",
        value_deserializer=lambda b: json.loads(b.decode("utf-8")),
    )

    latencias = []
    ventana = deque()  # (event_time, km_driven)
    procesados = 0
    t_inicio = time.time()

    for msg in consumer:
        ev = msg.value
        t0 = time.perf_counter()
        try:
            car = _car_from_event(ev)
            price = predict_price(state, car)
        except Exception:
            logger.exception("Evento inválido, se descarta: %s", ev)
            continue
        latencias.append((time.perf_counter() - t0) * 1000)

        event_time = ev.get("_event_time", time.time())
        ventana.append((event_time, ev["km_driven"]))
        while ventana and event_time - ventana[0][0] > VENTANA_SEGUNDOS:
            ventana.popleft()

        procesados += 1
        if procesados % CADA_N_EVENTOS == 0:
            media_km = float(np.mean([w[1] for w in ventana]))
            throughput = len(latencias) / (time.time() - t_inicio)
            p95 = float(np.percentile(latencias, 95))
            logger.info(
                "evento %d | throughput=%.0f ev/s | p95=%.2fms | precio=%.0f | media_km(ventana)=%.0f",
                procesados, throughput, p95, price, media_km,
            )
            if media_km > UMBRAL_KM_DRIFT:
                logger.warning(
                    "⚠ ALERTA DE DRIFT: media de km_driven en la ventana (%.0f) "
                    "supera el umbral (%.0f) — la distribución de entrada se corrió "
                    "de lo que el modelo vio en entrenamiento.",
                    media_km, UMBRAL_KM_DRIFT,
                )


if __name__ == "__main__":
    main()
