"""Consumidor con inferencia online + métricas por ventana (mini_tp4_actividad.ipynb
aplicado al TP integrador). Reusa `load_production_model` y `predict_price` de
api/app/predict.py — mismo modelo que REST, GraphQL y gRPC.

A diferencia de las otras tres capas, acá no hay un cliente que pregunte: el
consumidor puntúa cada evento a medida que llega del topic y agrega, sobre una
ventana deslizante de 1s, throughput, latencia p95 y la media de `km_driven`
como indicador simple de drift de entrada.

Clase 6: el stream es efímero (Redpanda borra los eventos al vencer la retención).
Para que no se pierdan, cada evento se guarda con su predicción en el Data Lake,
en Parquet, en la zona raw y separado por fecha:
    s3://datalake/raw/streaming/fecha=AAAA-MM-DD/lote-HHMMSS-N.parquet
Se guarda cada LOTE_LAKE eventos, o antes si pasan SEGUNDOS_SIN_EVENTOS sin que
llegue nada (para no dejar eventos sin guardar al final de una tanda).
"""

import json
import logging
import time
from collections import deque
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from kafka import KafkaConsumer

from app import lago

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

# Data Lake (clase 6)
LOTE_LAKE = 500
SEGUNDOS_SIN_EVENTOS = 10


class GuardadoEnLake:
    """Junta eventos puntuados y los guarda en el lake por lotes."""

    def __init__(self):
        self.filas = []
        self.lotes = 0
        self.ultimo_evento = time.time()

    def agregar(self, fila: dict):
        self.filas.append(fila)
        self.ultimo_evento = time.time()
        if len(self.filas) >= LOTE_LAKE:
            self.guardar()

    def revisar_inactividad(self):
        if self.filas and time.time() - self.ultimo_evento >= SEGUNDOS_SIN_EVENTOS:
            self.guardar()

    def guardar(self):
        ahora = datetime.now(timezone.utc)
        self.lotes += 1
        key = (f"raw/streaming/fecha={ahora:%Y-%m-%d}/"
               f"lote-{ahora:%H%M%S}-{self.lotes:04d}.parquet")
        try:
            lago.subir_parquet(pd.DataFrame(self.filas), key)
            logger.info("Lake: %d eventos guardados en s3://%s/%s", len(self.filas), lago.BUCKET, key)
        except Exception:
            # Si el lake falla, el scoring sigue: se pierde el lote, no el servicio.
            logger.exception("Lake: no se pudo guardar el lote (%d eventos)", len(self.filas))
        self.filas = []


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
        # Con grupo, Redpanda recuerda hasta dónde se leyó: al reiniciar el consumidor
        # sigue desde ahí y no vuelve a guardar en el lake eventos ya guardados.
        group_id="streaming-consumer",
        value_deserializer=lambda b: json.loads(b.decode("utf-8")),
    )

    latencias = []
    ventana = deque()  # (event_time, km_driven)
    procesados = 0
    t_inicio = time.time()
    lake = GuardadoEnLake()

    for ev in _eventos(consumer, lake):
        t0 = time.perf_counter()
        try:
            car = _car_from_event(ev)
            price = predict_price(state, car)
        except Exception:
            logger.exception("Evento inválido, se descarta: %s", ev)
            continue
        latencias.append((time.perf_counter() - t0) * 1000)
        lake.agregar({
            **{k: v for k, v in ev.items() if not k.startswith("_")},
            "predicted_price": price,
            "model_version": state.model_version,
            "event_time": ev.get("_event_time"),
            "scored_at": time.time(),
        })

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


def _eventos(consumer, lake):
    """Devuelve los eventos del topic uno por uno. Mientras espera, revisa si hay
    eventos juntados sin guardar en el lake (poll con timeout en vez de bloquear)."""
    while True:
        lotes = consumer.poll(timeout_ms=1000)
        if not lotes:
            lake.revisar_inactividad()
            continue
        for mensajes in lotes.values():
            for msg in mensajes:
                yield msg.value


if __name__ == "__main__":
    main()
