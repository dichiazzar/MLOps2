"""Validación de cada evento del stream (clase 7), en orden de lo más barato a lo más caro:

  1. firma HMAC con la clave del productor que dice ser      -> dlq_firma
  2. anti-replay: `_id` no visto y `_ts` dentro de la ventana -> dlq_replay
  3. esquema estricto del auto (CarRawInput + rangos)         -> dlq_esquema

El id se marca como visto solo si la firma es válida y el `_ts` está en la ventana
(un atacante sin clave no puede "quemar" ids de otros).
"""

from app.seguridad import EntradaInvalida, ts_en_ventana, validar_auto, verificar_firma

CAMPOS_AUTO = ["name", "year", "km_driven", "fuel", "seller_type", "transmission", "owner",
               "mileage", "engine", "max_power", "torque", "seats"]


def validar_evento(ev, claves, vistos, rangos):
    """Devuelve (auto, destino, motivo): destino 'ok' o 'dlq_firma' / 'dlq_replay' / 'dlq_esquema'."""
    if not isinstance(ev, dict):
        return None, "dlq_esquema", "el evento no es un objeto JSON"
    motivo = verificar_firma(ev, claves)
    if motivo:
        return None, "dlq_firma", motivo
    id_ = ev.get("_id")
    if not isinstance(id_, str) or not id_:
        return None, "dlq_replay", "evento sin _id"
    if not ts_en_ventana(ev.get("_ts")):
        return None, "dlq_replay", "_ts fuera de la ventana"
    if vistos.ya_visto(id_):
        return None, "dlq_replay", "_id ya procesado"
    try:
        car = validar_auto({k: ev.get(k) for k in CAMPOS_AUTO}, rangos)
    except EntradaInvalida as e:
        return None, "dlq_esquema", str(e)
    return car, "ok", None
