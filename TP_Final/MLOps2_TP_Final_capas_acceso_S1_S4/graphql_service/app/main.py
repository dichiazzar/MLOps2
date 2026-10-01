"""Capa GraphQL sobre el mismo modelo xgb_best (mini_tp2_actividad.ipynb aplicado al TP integrador).

No reimplementa la carga ni el scoring del modelo: reusa `load_production_model` y
`predict_price` de `api/app/predict.py` (MLOps1_final), igual que hace la API REST.
La diferencia con REST es el contrato: acá el cliente arma su propia consulta y
elige qué campos quiere de vuelta, en vez de recibir siempre la misma forma fija.
"""

import logging
from enum import Enum
from typing import Optional

import strawberry
from fastapi import FastAPI
from strawberry.fastapi import GraphQLRouter

from app.predict import ModelState, load_production_model, predict_price
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
    @strawberry.field(description="Metadata del modelo en producción (mismo contenido que GET /model/info en REST).")
    def model_info(self) -> ModelInfo:
        state = get_state()
        return ModelInfo(
            model_name="xgb_best",
            model_version=state.model_version,
            n_features=len(state.all_features),
            top_brands=state.top_brands,
        )


@strawberry.type
class Mutation:
    @strawberry.mutation(description="Puntúa un auto con el modelo en producción (mismo scoring que POST /predict en REST).")
    def predict(self, car: CarInput) -> Prediction:
        state = get_state()
        car_raw = _to_car_raw_input(car)
        price = predict_price(state, car_raw)
        return Prediction(predicted_price=price, model_version=state.model_version)


schema = strawberry.Schema(query=Query, mutation=Mutation)
graphql_app = GraphQLRouter(schema)

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
