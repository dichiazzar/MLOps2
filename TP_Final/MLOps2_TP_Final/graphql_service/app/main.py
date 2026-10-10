"""Capa GraphQL sobre el mismo modelo xgb_best (mini_tp2_actividad.ipynb aplicado al TP integrador).

No reimplementa la carga ni el scoring del modelo: reusa `load_production_model` y
`predict_price` de `api/app/predict.py` (MLOps1_final), igual que hace la API REST.
La diferencia con REST es el contrato: acá el cliente arma su propia consulta y
elige qué campos quiere de vuelta, en vez de recibir siempre la misma forma fija.

Clase 6: la consulta `prediccionesStreaming` lee del Data Lake las predicciones que
guardó la capa de streaming (s3://datalake/raw/streaming/fecha=.../). GraphQL usa
el lake como origen de verdad para datos que no viven en ningún otro servicio.

Clase 7 (seguridad, SAIF):
  - El usuario y el rol salen del JWT verificado (header Authorization), nunca de la consulta.
  - Permisos por campo (permission_classes) con la misma tabla que REST y gRPC.
  - Introspección apagada, profundidad máxima 5 y costo máximo 200 (app/costo.py).
  - GraphiQL apagado (sin introspección no sirve): las consultas de ejemplo están en el README.
  - Auditoría por operación, incluidas las rechazadas en la validación.
  - Query `auditoria` (solo admin): lee el registro de auditoría del lake.
"""

import json
import logging
from datetime import date, datetime, timezone
from enum import Enum
from typing import Optional

import pandas as pd

import strawberry
from fastapi import FastAPI, Request
from graphql import NoSchemaIntrospectionCustomRule
from strawberry.extensions import AddValidationRules, QueryDepthLimiter, SchemaExtension
from strawberry.fastapi import GraphQLRouter
from strawberry.permission import BasePermission
from strawberry.types import Info

from app import lago
from app.costo import LimiteCosto
from app.predict import ModelState, load_production_model, predict_price, rangos_entrada
from app.seguridad import Auditor, EntradaInvalida, TokenInvalido, autorizado, validar_auto, verificar_token
from common.schemas import (
    CarRawInput,
    FuelEnum,
    OwnerEnum,
    SellerTypeEnum,
    TransmissionEnum,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_state: Optional[ModelState] = None


def get_state() -> ModelState:
    global _state
    if _state is None:
        _state = load_production_model()
        logger.info("Loaded model version %s from MLflow Registry", _state.model_version)
    return _state


# --- Clase 7: seguridad ---
AUDITOR = Auditor("graphql", lago.subir_bytes)


def permiso(accion: str):
    """Permiso de strawberry para una acción de la tabla PERMISOS (seguridad.py)."""
    class Permiso(BasePermission):
        message = f"no autorizado: hace falta permiso para '{accion}'"

        def has_permission(self, source, info: Info, **kwargs) -> bool:
            return autorizado(info.context.get("identidad"), accion)
    Permiso.__name__ = f"Permiso_{accion}"
    return Permiso


async def contexto(request: Request) -> dict:
    """El rol sale del JWT verificado; sin token válido, la identidad es anónima (None)."""
    try:
        identidad = verificar_token(request.headers.get("authorization"))
        motivo = None
    except TokenInvalido as e:
        identidad, motivo = None, str(e)
    return {"identidad": identidad, "motivo_token": motivo}


class Auditoria(SchemaExtension):
    """Una fila de auditoría por operación (también si la validación la rechaza)."""

    def on_operation(self):
        yield
        ec = self.execution_context
        ctx = ec.context or {}
        errores = [e.message for e in (ec.errors or [])]
        if ec.result and ec.result.errors:
            errores += [e.message for e in ec.result.errors]
        try:
            tipo = ec.operation_type.value
        except Exception:   # la consulta no se pudo leer (error de sintaxis)
            tipo = "operacion"
        AUDITOR.registrar(
            ctx.get("identidad"),
            accion=ec.operation_name or tipo,
            resultado="ok" if not errores else "error",
            entrada=(ec.query or "").encode(),
            detalle="; ".join(dict.fromkeys(errores))[:300] or ctx.get("motivo_token"),
            model_version=_state.model_version if _state else None,
        )


# --- Tipos GraphQL: mismos enums/campos que CarRawInput (common/schemas.py), ---
# --- pero declarados para Strawberry porque no puede reflejar Enum de Pydantic directo. ---
FuelType = strawberry.enum(FuelEnum, name="FuelType")
SellerType = strawberry.enum(SellerTypeEnum, name="SellerType")
TransmissionType = strawberry.enum(TransmissionEnum, name="TransmissionType")
OwnerType = strawberry.enum(OwnerEnum, name="OwnerType")


@strawberry.input
class CarInput:
    name: str
    year: int
    km_driven: int
    fuel: FuelType
    seller_type: SellerType
    transmission: TransmissionType
    owner: OwnerType
    mileage: str
    engine: str
    max_power: str
    torque: str
    seats: float


@strawberry.type
class Prediction:
    predicted_price: float
    model_version: str


@strawberry.type
class ModelInfo:
    model_name: str
    model_version: str
    n_features: int
    top_brands: list[str]


@strawberry.type
class PrediccionStreaming:
    name: str
    year: int
    km_driven: int
    fuel: str
    predicted_price: float
    model_version: str
    event_time: Optional[str]


@strawberry.type
class ResumenStreaming:
    fecha: str
    archivos: int
    total: int
    items: list[PrediccionStreaming]


def _leer_predicciones_streaming(fecha: Optional[str], limite: int) -> ResumenStreaming:
    if fecha is None:
        fecha = datetime.now(timezone.utc).date().isoformat()
    else:
        try:  # valida y normaliza a AAAA-MM-DD (también evita armar rutas raras en S3)
            fecha = date.fromisoformat(fecha).isoformat()
        except ValueError:
            raise ValueError(f"fecha inválida: '{fecha}'. Usar el formato AAAA-MM-DD.") from None
    limite = max(1, min(limite, 500))
    claves = lago.listar(f"raw/streaming/fecha={fecha}/")
    if not claves:
        return ResumenStreaming(fecha=fecha, archivos=0, total=0, items=[])
    todas = pd.concat([lago.leer_parquet(k) for k in claves], ignore_index=True)
    df = todas.sort_values("scored_at", ascending=False).head(limite)
    items = [
        PrediccionStreaming(
            name=r.name, year=int(r.year), km_driven=int(r.km_driven), fuel=r.fuel,
            predicted_price=float(r.predicted_price), model_version=str(r.model_version),
            event_time=(datetime.fromtimestamp(r.event_time, timezone.utc).isoformat(timespec="seconds")
                        if pd.notna(r.event_time) else None),
        )
        for r in df.itertuples()
    ]
    return ResumenStreaming(fecha=fecha, archivos=len(claves), total=len(todas), items=items)


@strawberry.type
class EventoAuditoria:
    ts: str
    capa: str
    usuario: Optional[str]
    rol: Optional[str]
    accion: str
    resultado: str
    detalle: Optional[str]


@strawberry.type
class ResumenAuditoria:
    capa: str
    fecha: str
    archivos: int
    total: int
    items: list[EventoAuditoria]


CAPAS = {"rest", "graphql", "grpc", "streaming"}


def _leer_auditoria(capa: str, fecha: Optional[str], limite: int) -> ResumenAuditoria:
    if capa not in CAPAS:
        raise ValueError(f"capa inválida: '{capa}'. Opciones: {sorted(CAPAS)}")
    try:
        fecha = date.fromisoformat(fecha).isoformat() if fecha else datetime.now(timezone.utc).date().isoformat()
    except ValueError:
        raise ValueError(f"fecha inválida: '{fecha}'. Usar el formato AAAA-MM-DD.") from None
    limite = max(1, min(limite, 500))
    claves = lago.listar(f"raw/auditoria/capa={capa}/fecha={fecha}/")
    filas = [json.loads(linea) for k in claves for linea in lago.leer_bytes(k).decode().splitlines() if linea.strip()]
    filas.sort(key=lambda f: f["ts"], reverse=True)
    items = [EventoAuditoria(ts=f["ts"], capa=f["capa"], usuario=f.get("usuario"), rol=f.get("rol"),
                             accion=f["accion"], resultado=f["resultado"], detalle=f.get("detalle"))
             for f in filas[:limite]]
    return ResumenAuditoria(capa=capa, fecha=fecha, archivos=len(claves), total=len(filas), items=items)


def _to_car_raw_input(car: CarInput) -> CarRawInput:
    return CarRawInput(
        name=car.name,
        year=car.year,
        km_driven=car.km_driven,
        fuel=car.fuel.value,
        seller_type=car.seller_type.value,
        transmission=car.transmission.value,
        owner=car.owner.value,
        mileage=car.mileage,
        engine=car.engine,
        max_power=car.max_power,
        torque=car.torque,
        seats=car.seats,
    )


@strawberry.type
class Query:
    @strawberry.field(description="Metadata del modelo en producción (mismo contenido que GET /model/info en REST).",
                      permission_classes=[permiso("ver_modelo")])
    def model_info(self) -> ModelInfo:
        state = get_state()
        return ModelInfo(
            model_name="xgb_best",
            model_version=state.model_version,
            n_features=len(state.all_features),
            top_brands=state.top_brands,
        )

    @strawberry.field(description="Predicciones de la capa de streaming guardadas en el Data Lake para una fecha (AAAA-MM-DD, por defecto hoy en UTC), de la más reciente a la más vieja.",
                      permission_classes=[permiso("ver_predicciones")])
    def predicciones_streaming(self, fecha: Optional[str] = None, limite: int = 20) -> ResumenStreaming:
        return _leer_predicciones_streaming(fecha, limite)

    @strawberry.field(description="Registro de auditoría de una capa (rest, graphql, grpc, streaming) para una fecha (AAAA-MM-DD, por defecto hoy en UTC). Solo admin.",
                      permission_classes=[permiso("ver_auditoria")])
    def auditoria(self, capa: str, fecha: Optional[str] = None, limite: int = 50) -> ResumenAuditoria:
        return _leer_auditoria(capa, fecha, limite)


@strawberry.type
class Mutation:
    @strawberry.mutation(description="Puntúa un auto con el modelo en producción (mismo scoring que POST /predict en REST).",
                         permission_classes=[permiso("predecir")])
    def predict(self, car: CarInput) -> Prediction:
        state = get_state()
        # Clase 7: _to_car_raw_input valida los enums con Pydantic y validar_auto agrega km,
        # campos técnicos legibles y rangos de entrenamiento; los dos errores salen limpios.
        try:
            car_raw = validar_auto(_to_car_raw_input(car).model_dump(mode="json"), rangos_entrada())
        except EntradaInvalida as e:
            raise ValueError(f"entrada inválida: {e}") from None
        except ValueError as e:   # ValidationError de Pydantic (CarRawInput)
            msg = e.errors()[0]["msg"] if hasattr(e, "errors") else str(e)
            raise ValueError(f"entrada inválida: {msg}") from None
        price = predict_price(state, car_raw)
        return Prediction(predicted_price=price, model_version=state.model_version)


# Clase 7: QueryDepthLimiter y AddValidationRules van como instancias (no guardan estado por
# request); Auditoria va como clase porque strawberry la crea por operación.
schema = strawberry.Schema(
    query=Query,
    mutation=Mutation,
    extensions=[
        QueryDepthLimiter(max_depth=5),
        AddValidationRules([NoSchemaIntrospectionCustomRule, LimiteCosto]),
        Auditoria,
    ],
)
graphql_app = GraphQLRouter(schema, context_getter=contexto, graphiql=False)

app = FastAPI(title="Car Price Prediction API - GraphQL")
app.include_router(graphql_app, prefix="/graphql")


@app.on_event("startup")
def startup_event():
    global _state
    try:
        _state = load_production_model()
        logger.info("Modelo cargado al arrancar (versión %s)", _state.model_version)
    except Exception:
        logger.exception("No se pudo cargar el modelo al arrancar; se reintentará en la primera consulta")


@app.get("/health")
def health():
    return {"status": "ok", "model_loaded": _state is not None}
