"""Productor de eventos de prueba para el topic `autos` (simula tráfico real,
igual que el productor en memoria de mini_tp4_actividad.ipynb, pero publicando
a un broker Kafka/Redpanda real en vez de una queue.Queue local).

A mitad de la corrida cambia la distribución de `km_driven` para poder ver
el indicador de drift dispararse del lado del consumidor.

Clase 7: cada evento va firmado (HMAC) con la clave de su concesionaria
(`--productor`, claves en HMAC_CLAVES del .env) y lleva `_productor`, `_id` y `_ts`.
`--modo ataque` publica eventos que el consumidor debe mandar a la DLQ: sin firma,
alterados, de un productor desconocido, repetidos (replay), viejos y con datos absurdos.
"""

import argparse
import json
import logging
import random
import time
import uuid
from datetime import datetime, timedelta, timezone

from kafka import KafkaProducer

from app.seguridad import claves_hmac, firmar

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


def _firmado(ev: dict, productor: str, clave: str, ts=None) -> dict:
    ev = {**ev, "_productor": productor, "_id": uuid.uuid4().hex,
          "_ts": (ts or datetime.now(timezone.utc)).isoformat()}
    ev["_firma"] = firmar(ev, clave)
    return ev


def _ataque(clave: str, productor: str, n: int) -> list:
    """Rondas de 7 eventos: 6 que deben ir a la DLQ y 1 legítimo (que se manda dos veces)."""
    eventos = []
    for _ in range(n):
        base = _evento(60000)
        sin_firma = {**base, "_productor": productor, "_id": uuid.uuid4().hex,
                     "_ts": datetime.now(timezone.utc).isoformat()}
        alterado = _firmado(base, productor, clave)
        alterado["km_driven"] = 1                                   # cambiado después de firmar
        desconocido = _firmado(base, "concesionaria-trucha", "clave-inventada")
        legitimo = _firmado(base, productor, clave)
        viejo = _firmado(base, productor, clave, ts=datetime.now(timezone.utc) - timedelta(days=2))
        absurdo = _firmado({**base, "year": 3000, "fuel": "Nafta"}, productor, clave)
        eventos += [sin_firma, alterado, desconocido, legitimo, dict(legitimo), viejo, absurdo]  # dict(...) = replay
    return eventos


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--modo", choices=["normal", "ataque"], default="normal")
    p.add_argument("--productor", default="concesionaria-norte")
    p.add_argument("--n", type=int, default=None, help="cantidad de eventos (ataque: rondas de 7)")
    a = p.parse_args()
    claves = claves_hmac()
    if a.productor not in claves:
        raise SystemExit(f"'{a.productor}' no está en HMAC_CLAVES (.env): {sorted(claves)}")
    clave = claves[a.productor]

    prod = KafkaProducer(bootstrap_servers=BROKER, value_serializer=lambda v: json.dumps(v).encode("utf-8"))
    if a.modo == "ataque":
        eventos = _ataque(clave, a.productor, a.n or 20)
        logger.info("Modo ataque: publicando %d eventos que deberían ir a la DLQ (salvo 1 de cada 7)...",
                    len(eventos))
        for e in eventos:
            prod.send(TOPIC, e)
    else:
        n = a.n or N_EVENTOS
        logger.info("Publicando %d eventos firmados por '%s' al topic '%s'...", n, a.productor, TOPIC)
        for i in range(n):
            # drift a mitad de camino: autos con muchos más km de lo habitual
            # (ej. una flota que empieza a vender vehículos de alto kilometraje)
            km_mu = 60000 if i < n // 2 else 220000
            prod.send(TOPIC, _firmado(_evento(km_mu), a.productor, clave))
            time.sleep(0.01)
    prod.flush()
    prod.close()
    logger.info("Listo.")


if __name__ == "__main__":
    main()
