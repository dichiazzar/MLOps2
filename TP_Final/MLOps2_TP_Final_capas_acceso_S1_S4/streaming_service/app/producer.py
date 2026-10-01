"""Productor de eventos de prueba para el topic `autos` (simula tráfico real,
igual que el productor en memoria de mini_tp4_actividad.ipynb, pero publicando
a un broker Kafka/Redpanda real en vez de una queue.Queue local).

A mitad de la corrida cambia la distribución de `km_driven` para poder ver
el indicador de drift dispararse del lado del consumidor.
"""

import json
import logging
import random
import time

from kafka import KafkaProducer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BROKER = "redpanda:9092"
TOPIC = "autos"
N_EVENTOS = 2000

FUEL = ["Petrol", "Diesel", "CNG", "LPG"]
SELLER = ["Individual", "Dealer", "Trustmark Dealer"]
TRANSMISSION = ["Manual", "Automatic"]
OWNER = ["First Owner", "Second Owner", "Third Owner"]


def _evento(km_mu: float) -> dict:
    return {
        "name": "Maruti Swift Dzire VDI",
        "year": random.randint(2008, 2022),
        "km_driven": max(0, int(random.gauss(km_mu, 20000))),
        "fuel": random.choice(FUEL),
        "seller_type": random.choice(SELLER),
        "transmission": random.choice(TRANSMISSION),
        "owner": random.choice(OWNER),
        "mileage": f"{random.uniform(12, 28):.1f} kmpl",
        "engine": f"{random.choice([998, 1197, 1248, 1498])} CC",
        "max_power": f"{random.uniform(60, 140):.1f} bhp",
        "torque": f"{random.randint(90, 250)}Nm@ 2000rpm",
        "seats": float(random.choice([5, 5, 5, 7])),
        "_event_time": time.time(),
    }


def main():
    prod = KafkaProducer(
        bootstrap_servers=BROKER,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
    )
    logger.info("Publicando %d eventos al topic '%s'...", N_EVENTOS, TOPIC)
    for i in range(N_EVENTOS):
        # drift a mitad de camino: autos con muchos más km de lo habitual
        # (ej. una flota que empieza a vender vehículos de alto kilometraje)
        km_mu = 60000 if i < N_EVENTOS // 2 else 220000
        prod.send(TOPIC, _evento(km_mu))
        time.sleep(0.01)
    prod.flush()
    prod.close()
    logger.info("Listo.")


if __name__ == "__main__":
    main()
