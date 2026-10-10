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

El consumidor usa un grupo y confirma a Redpanda hasta dónde leyó (commit) recién
DESPUÉS de guardar cada lote en el lake. Si se reinicia o se cae con eventos
juntados sin guardar, al volver los lee de nuevo y no se pierden. (Solo si se cae
justo entre guardar un lote y confirmarlo, ese lote puede quedar guardado dos veces.)

Clase 7 (seguridad): cada evento se valida antes de puntuarlo (app/validacion.py: firma
HMAC por productor, anti-replay, esquema estricto). Lo que no pasa NO se puntúa: va al
topic `autos-dlq` y al lake (raw/dlq/fecha=.../), y si más del 20 % de los últimos 50
eventos va a la DLQ se emite `ALERTA DLQ` (posible ataque en curso). Cada evento queda
en la auditoría con su productor y su destino.
"""

import json
import logging
import time
from collections import deque
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from kafka import KafkaConsumer, KafkaProducer, TopicPartition
from kafka.structs import OffsetAndMetadata

from app import lago

from app.predict import ModelState, load_production_model, predict_price, rangos_entrada
from app.seguridad import AlertaPorVentana, Auditor, EscritorPorLotes, Identidad, VistosRecientes, claves_hmac
from app.validacion import validar_evento

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BROKER = "redpanda:9092"
TOPIC = "autos"
TOPIC_DLQ = "autos-dlq"   # clase 7: eventos en cuarentena

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

    def __init__(self, consumer):
        self.consumer = consumer
        self.filas = []
        self.offsets = {}  # partición -> próximo offset a leer, de lo ya juntado
        self.lotes = 0
        self.ultimo_evento = time.time()
        # El bucket lo crea seguridad-minio (clase 7): el usuario de esta capa solo puede escribir.

    def marcar_leido(self, msg):
        """Registra hasta dónde se leyó, aunque el evento haya sido inválido."""
        self.offsets[(msg.topic, msg.partition)] = msg.offset + 1

    def agregar(self, fila: dict):
        self.filas.append(fila)
        self.ultimo_evento = time.time()
        if len(self.filas) >= LOTE_LAKE:
            self.guardar()

    def revisar_inactividad(self):
        if time.time() - self.ultimo_evento >= SEGUNDOS_SIN_EVENTOS:
            if self.filas:
                self.guardar()
            elif self.offsets:   # solo hubo eventos inválidos: igual se confirman
                self._confirmar()

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
        self._confirmar()

    def _confirmar(self):
        self.consumer.commit({
            TopicPartition(t, p): OffsetAndMetadata(o, None) for (t, p), o in self.offsets.items()
        })
        self.offsets = {}


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
        enable_auto_commit=False,   # se confirma a mano, después de guardar en el lake
        value_deserializer=lambda b: json.loads(b.decode("utf-8")),
    )

    latencias = []
    ventana = deque()  # (event_time, km_driven)
    procesados = 0
    t_inicio = time.time()
    lake = GuardadoEnLake(consumer)

    # Clase 7: validación de cada evento, cuarentena (DLQ), alerta y auditoría
    claves = claves_hmac()
    vistos = VistosRecientes()
    alerta = AlertaPorVentana(n=50, umbral=0.20)
    dlq_lake = EscritorPorLotes("raw/dlq", lago.subir_bytes, cada_n=100)
    auditor = Auditor("streaming", lago.subir_bytes, cada_n=500)
    dlq_topic = KafkaProducer(bootstrap_servers=BROKER,
                              value_serializer=lambda v: json.dumps(v, default=str).encode("utf-8"))
    en_dlq = 0

    for msg in _mensajes(consumer, lake):
        ev = msg.value
        lake.marcar_leido(msg)
        t0 = time.perf_counter()
        car, destino, motivo = validar_evento(ev, claves, vistos, rangos_entrada())
        productor = ev.get("_productor") if isinstance(ev, dict) else None
        auditor.registrar(Identidad(str(productor), "productor") if productor else None,
                          "evento", destino, entrada=ev, detalle=motivo, model_version=state.model_version)
        aviso = alerta.registrar(destino != "ok", destino, productor)
        if aviso and aviso["tipo"] == "INICIO":
            logger.warning("⚠ ALERTA DLQ: %.0f%% de los últimos 50 eventos fue a cuarentena "
                           "(motivos %s, productores %s) — posible ataque en curso.",
                           aviso["tasa"] * 100, aviso["motivos"], aviso["productores"])
        elif aviso:
            logger.info("Fin de la alerta DLQ: la tasa volvió a %.0f%%.", aviso["tasa"] * 100)
        if destino != "ok":
            en_dlq += 1
            registro = {"destino": destino, "motivo": motivo, "productor": productor,
                        "evento": ev, "recibido": time.time()}
            dlq_topic.send(TOPIC_DLQ, registro)
            dlq_lake.agregar(registro)
            continue
        try:
            price = predict_price(state, car)
        except Exception:
            logger.exception("Error al puntuar un evento válido")
            continue
        latencias.append((time.perf_counter() - t0) * 1000)
        lake.agregar({
            **{k: v for k, v in ev.items() if not k.startswith("_")},
            "predicted_price": price,
            "model_version": state.model_version,
            "productor": ev.get("_productor"),
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
                "evento %d | throughput=%.0f ev/s | p95=%.2fms | precio=%.0f | media_km(ventana)=%.0f | dlq=%d",
                procesados, throughput, p95, price, media_km, en_dlq,
            )
            if media_km > UMBRAL_KM_DRIFT:
                logger.warning(
                    "⚠ ALERTA DE DRIFT: media de km_driven en la ventana (%.0f) "
                    "supera el umbral (%.0f) — la distribución de entrada se corrió "
                    "de lo que el modelo vio en entrenamiento.",
                    media_km, UMBRAL_KM_DRIFT,
                )


def _mensajes(consumer, lake):
    """Devuelve los mensajes del topic uno por uno. Mientras espera, revisa si hay
    eventos juntados sin guardar en el lake (poll con timeout en vez de bloquear)."""
    while True:
        lotes = consumer.poll(timeout_ms=1000)
        if not lotes:
            lake.revisar_inactividad()
            continue
        for mensajes in lotes.values():
            yield from mensajes


if __name__ == "__main__":
    main()
