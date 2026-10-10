"""Seguridad común a las capas del TP integrador (clase 7, SAIF).

Se copia como `app/seguridad.py` en cada imagen (REST, GraphQL, gRPC, streaming,
lake-preparar y la imagen de herramientas), igual que `predict.py` y `lago.py`:
un solo código para los mismos controles en todas las capas (coherencia de controles).

Qué hay acá:
  - Tokens JWT con rol, y la tabla de permisos por acción.
  - Límite de pedidos por usuario.
  - Firma HMAC de eventos de streaming, anti-replay y alerta de cuarentena (DLQ).
  - Validación estricta de un auto (CarRawInput + rangos del entrenamiento).
  - Hash e integridad del modelo.
  - Escritura por lotes en el lake y auditoría.
"""

import hashlib
import hmac
import json
import logging
import os
import threading
import time
from collections import Counter, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

import jwt

logger = logging.getLogger(__name__)

# ======================= Tokens y permisos =======================


@dataclass(frozen=True)
class Identidad:
    usuario: str
    rol: str


class TokenInvalido(Exception):
    """El token falta, venció o su firma no coincide."""


def _secreto() -> str:
    s = os.environ.get("JWT_SECRET", "")
    if len(s) < 32:
        raise RuntimeError("JWT_SECRET no está definido o tiene menos de 32 caracteres (ver .env.example)")
    return s


def emitir_token(usuario: str, rol: str, minutos: Optional[int] = None, secreto: Optional[str] = None) -> str:
    minutos = int(os.environ.get("JWT_MINUTOS", "60")) if minutos is None else minutos
    exp = datetime.now(timezone.utc) + timedelta(minutes=minutos)
    return jwt.encode({"sub": usuario, "rol": rol, "exp": exp}, secreto or _secreto(), algorithm="HS256")


def verificar_token(token: Optional[str], secreto: Optional[str] = None) -> Identidad:
    token = (token or "").strip()
    if token[:7].lower() == "bearer ":
        token = token[7:].strip()
    elif token.lower() == "bearer":
        token = ""
    if not token:
        raise TokenInvalido("falta el token")
    try:
        # algorithms fijo: un token con alg "none" (sin firma) se rechaza.
        datos = jwt.decode(token, secreto or _secreto(), algorithms=["HS256"],
                           options={"require": ["exp", "sub"]})
    except jwt.ExpiredSignatureError:
        raise TokenInvalido("token vencido") from None
    except jwt.InvalidTokenError as e:
        raise TokenInvalido(f"token inválido ({type(e).__name__})") from None
    return Identidad(usuario=str(datos["sub"]), rol=str(datos.get("rol", "")))


# Una sola tabla para las 4 capas: acción -> roles que la pueden hacer.
PERMISOS = {
    "predecir": {"analista", "admin"},
    "ver_modelo": {"analista", "admin"},
    "ver_predicciones": {"analista", "admin"},
    "ver_predicciones_de_otros": {"admin"},
    "ver_auditoria": {"admin"},
}


def autorizado(identidad: Optional[Identidad], accion: str) -> bool:
    return identidad is not None and identidad.rol in PERMISOS.get(accion, set())


class LimiteDeTasa:
    """Ventana deslizante por usuario. En memoria: el límite es por contenedor."""

    def __init__(self, n: Optional[int] = None, segundos: float = 60.0, reloj=time.monotonic):
        self.n = int(os.environ.get("LIMITE_POR_MINUTO", "60")) if n is None else n
        self.segundos, self.reloj = segundos, reloj
        self._pedidos: dict = {}
        self._lock = threading.Lock()

    def permitir(self, clave: str) -> bool:
        ahora = self.reloj()
        with self._lock:
            v = self._pedidos.setdefault(clave, deque())
            while v and ahora - v[0] >= self.segundos:
                v.popleft()
            if len(v) >= self.n:
                return False
            v.append(ahora)
            return True


# ======================= Streaming: firma, replay y DLQ =======================

CAMPO_FIRMA = "_firma"


def canonico(evento: dict) -> bytes:
    sin_firma = {k: v for k, v in evento.items() if k != CAMPO_FIRMA}
    return json.dumps(sin_firma, sort_keys=True, separators=(",", ":"), default=str).encode()


def firmar(evento: dict, clave: str) -> str:
    return hmac.new(clave.encode(), canonico(evento), hashlib.sha256).hexdigest()


def claves_hmac() -> dict:
    return json.loads(os.environ.get("HMAC_CLAVES", "{}"))


def verificar_firma(evento: dict, claves: dict) -> Optional[str]:
    """None si la firma es válida; si no, el motivo del rechazo."""
    clave = claves.get(evento.get("_productor"))
    if clave is None:
        return "productor desconocido"
    firma = evento.get(CAMPO_FIRMA)
    if not isinstance(firma, str) or not hmac.compare_digest(firma, firmar(evento, clave)):
        return "firma inválida"
    return None


class VistosRecientes:
    """Ids ya procesados durante ttl_segundos (anti-replay)."""

    def __init__(self, ttl_segundos: float = 3600, reloj=time.monotonic):
        self.ttl, self.reloj = ttl_segundos, reloj
        self._vistos: dict = {}

    def ya_visto(self, id_: str) -> bool:
        ahora = self.reloj()
        if len(self._vistos) > 10_000:   # limpieza de vencidos, de vez en cuando
            self._vistos = {k: t for k, t in self._vistos.items() if ahora - t < self.ttl}
        t = self._vistos.get(id_)
        if t is not None and ahora - t < self.ttl:
            return True
        self._vistos[id_] = ahora
        return False


def ts_en_ventana(ts_iso, ahora: Optional[datetime] = None, atras_seg: int = 3600, adelante_seg: int = 300) -> bool:
    try:
        ts = datetime.fromisoformat(ts_iso)
    except (TypeError, ValueError):
        return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    ahora = ahora or datetime.now(timezone.utc)
    return ahora - timedelta(seconds=atras_seg) <= ts <= ahora + timedelta(seconds=adelante_seg)


class AlertaPorVentana:
    """Avisa cuando la tasa de DLQ en los últimos n eventos supera el umbral (y cuando vuelve)."""

    def __init__(self, n: int = 50, umbral: float = 0.20):
        self.n, self.umbral = n, umbral
        self.ventana = deque(maxlen=n)
        self.en_incidente = False

    def registrar(self, fue_dlq: bool, motivo: Optional[str] = None, productor: Optional[str] = None) -> Optional[dict]:
        self.ventana.append((fue_dlq, motivo, productor))
        if len(self.ventana) < self.n:
            return None
        malos = [(m, p) for d, m, p in self.ventana if d]
        tasa = len(malos) / len(self.ventana)
        if tasa > self.umbral and not self.en_incidente:
            self.en_incidente = True
            return {"tipo": "INICIO", "tasa": round(tasa, 2),
                    "motivos": dict(Counter(m for m, _ in malos).most_common(3)),
                    "productores": dict(Counter(p for _, p in malos).most_common(3))}
        if tasa <= self.umbral / 2 and self.en_incidente:
            self.en_incidente = False
            return {"tipo": "FIN", "tasa": round(tasa, 2)}
        return None


# ======================= Validación del auto =======================

COLUMNAS_RANGO = ["year", "km_driven", "mileage_value", "engine_value", "max_power_value", "torque_nm"]


class EntradaInvalida(ValueError):
    """El auto no pasa la validación (formato, rango o campos de más)."""


def validar_auto(datos, rangos: Optional[dict] = None):
    """CarRawInput + km razonables + campos técnicos legibles + rangos de entrenamiento."""
    import pandas as pd
    from pydantic import ValidationError

    from common.constants import KM_OUTLIER_THRESHOLD, NULL_CHECK_COLUMNS
    from common.preprocessing import extraer_columnas_tecnicas
    from common.schemas import CarRawInput

    if not isinstance(datos, dict):
        raise EntradaInvalida("el auto tiene que ser un objeto con sus campos")
    extra = set(datos) - set(CarRawInput.model_fields)
    if extra:
        raise EntradaInvalida(f"campos no permitidos: {sorted(extra)}")
    try:
        car = CarRawInput(**datos)
    except ValidationError as e:
        err = e.errors()[0]
        raise EntradaInvalida(f"{'.'.join(map(str, err['loc']))}: {err['msg']}") from None
    if car.km_driven > KM_OUTLIER_THRESHOLD:
        raise EntradaInvalida(f"km_driven: mayor que {KM_OUTLIER_THRESHOLD}")
    fila = extraer_columnas_tecnicas(pd.DataFrame([car.model_dump(mode="json")])).iloc[0]
    faltan = [c for c in NULL_CHECK_COLUMNS if pd.isna(fila[c])]
    if faltan:
        raise EntradaInvalida(f"no se pudieron leer: {faltan}")
    for col, (lo, hi) in (rangos or {}).items():
        valor = float(fila[col])
        if not lo <= valor <= hi:
            raise EntradaInvalida(f"{col}={valor:g} fuera del rango de entrenamiento [{lo:g}, {hi:g}]")
    return car


def calcular_rangos(df_tecnico, margen: float = 0.2) -> dict:
    """Mínimo y máximo de cada columna, ensanchados un `margen` del ancho (sin bajar de 0)."""
    rangos = {}
    for col in COLUMNAS_RANGO:
        serie = df_tecnico[col].dropna().astype(float)
        lo, hi = float(serie.min()), float(serie.max())
        extra = (hi - lo) * margen
        rangos[col] = [max(0.0, round(lo - extra, 2)), round(hi + extra, 2)]
    return rangos


# ======================= Integridad del modelo =======================

ARTEFACTO_SEGURIDAD = "seguridad_modelo.json"


class IntegridadRota(RuntimeError):
    """El modelo no coincide con su hash registrado (o no hay hash y se exige)."""


def hash_modelo(carpeta) -> dict:
    carpeta = Path(carpeta)
    archivos = {}
    for p in sorted(carpeta.rglob("*")):
        if p.is_file():
            archivos[p.relative_to(carpeta).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    total = hashlib.sha256("".join(f"{k}:{v}\n" for k, v in archivos.items()).encode()).hexdigest()
    return {"archivos": archivos, "sha256_total": total}


def exigir_integridad() -> bool:
    return os.environ.get("EXIGIR_INTEGRIDAD", "true").strip().lower() not in ("false", "0", "no")


def verificar_integridad(carpeta, seguridad: Optional[dict], exigir: bool) -> str:
    """'ok' si el hash coincide; 'sin_verificar' si no hay hash y no se exige."""
    if seguridad is None:
        if exigir:
            raise IntegridadRota(
                f"el run del modelo no tiene {ARTEFACTO_SEGURIDAD}: correr lake-preparar "
                "(o EXIGIR_INTEGRIDAD=false en desarrollo)")
        return "sin_verificar"
    actual = hash_modelo(carpeta)["sha256_total"]
    if actual != seguridad.get("sha256_total"):
        raise IntegridadRota(f"el modelo no coincide con su hash registrado ({actual[:12]}... != "
                             f"{str(seguridad.get('sha256_total'))[:12]}...): no se carga")
    return "ok"


# ======================= Lake por lotes y auditoría =======================


def hash_entrada(datos) -> Optional[str]:
    if datos is None:
        return None
    crudo = bytes(datos) if isinstance(datos, (bytes, bytearray)) else \
        json.dumps(datos, sort_keys=True, default=str).encode()
    return hashlib.sha256(crudo).hexdigest()[:16]


class EscritorPorLotes:
    """Junta filas y las sube al lake como JSON Lines cada `cada_n` filas o `cada_seg` segundos.

    Si el lake falla, las filas salen por el log y el servicio sigue.
    """

    def __init__(self, prefijo: str, subir: Callable[[bytes, str], None], cada_n: int = 50,
                 cada_seg: float = 10.0, iniciar_hilo: bool = True):
        self.prefijo, self.subir, self.cada_n, self.cada_seg = prefijo, subir, cada_n, cada_seg
        self._filas: list = []
        self._lotes = 0
        self._lock = threading.Lock()
        if iniciar_hilo:
            threading.Thread(target=self._cada_tanto, daemon=True).start()

    def agregar(self, fila: dict):
        with self._lock:
            self._filas.append(fila)
            lleno = len(self._filas) >= self.cada_n
        if lleno:
            self.vaciar()

    def vaciar(self) -> Optional[str]:
        with self._lock:
            if not self._filas:
                return None
            filas, self._filas = self._filas, []
            self._lotes += 1
            n = self._lotes
        ahora = datetime.now(timezone.utc)
        key = f"{self.prefijo}/fecha={ahora:%Y-%m-%d}/lote-{ahora:%H%M%S}-{os.getpid()}-{n:04d}.jsonl"
        cuerpo = "\n".join(json.dumps(f, default=str, ensure_ascii=False) for f in filas).encode()
        try:
            self.subir(cuerpo, key)
        except Exception:
            logger.exception("Lake: no se pudo subir %s (%d filas); van al log", key, len(filas))
            for f in filas:
                logger.warning("sin guardar en el lake: %s", json.dumps(f, default=str, ensure_ascii=False))
            return None
        return key

    def _cada_tanto(self):
        while True:
            time.sleep(self.cada_seg)
            self.vaciar()


class Auditor:
    """Registro de auditoría de una capa: raw/auditoria/capa=<capa>/fecha=.../lote-....jsonl"""

    def __init__(self, capa: str, subir: Callable[[bytes, str], None], **kw):
        self.capa = capa
        self.escritor = EscritorPorLotes(f"raw/auditoria/capa={capa}", subir, **kw)

    def registrar(self, identidad: Optional[Identidad], accion: str, resultado, entrada=None,
                  detalle: Optional[str] = None, model_version=None) -> dict:
        evento = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "capa": self.capa,
            "usuario": identidad.usuario if identidad else None,
            "rol": identidad.rol if identidad else None,
            "accion": accion,
            "resultado": str(resultado),
            "detalle": detalle,
            "hash_entrada": hash_entrada(entrada),
            "model_version": None if model_version is None else str(model_version),
        }
        self.escritor.agregar(evento)
        return evento
