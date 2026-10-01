import logging

from fastapi import FastAPI, HTTPException, Query

from common.schemas import CarRawInput, PredictionResponse

from .db import SessionLocal, init_db
from .models_orm import PredictionLog
from .predict import ModelState, load_production_model, predict_price

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Car Price Prediction API", version="1.0.0")

_state: ModelState | None = None


@app.on_event("startup")
def startup_event():
    global _state
    init_db()
    try:
        _state = load_production_model()
        logger.info("Loaded model version %s from MLflow Registry", _state.model_version)
    except Exception:
        logger.exception("Failed to load model at startup; /predict will 503 until retried")
        _state = None


@app.get("/health")
def health():
    return {"status": "ok", "model_loaded": _state is not None}


@app.get("/model/info")
def model_info():
    if _state is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    return {
        "model_name": "xgb_best",
        "model_version": _state.model_version,
        "n_features": len(_state.all_features),
        "top_brands": _state.top_brands,
    }


@app.post("/predict", response_model=PredictionResponse)
def predict(car: CarRawInput):
    global _state
    if _state is None:
        try:
            _state = load_production_model()
        except Exception:
            raise HTTPException(status_code=503, detail="Model not available yet")

    predicted_price = predict_price(_state, car)

    session = SessionLocal()
    try:
        log = PredictionLog(
            input_json=car.model_dump(mode="json"),
            predicted_price=predicted_price,
            model_version=_state.model_version,
        )
        session.add(log)
        session.commit()
    finally:
        session.close()

    return PredictionResponse(predicted_price=predicted_price, model_version=_state.model_version)


@app.get("/predictions/recent")
def recent_predictions(limit: int = Query(10, ge=1, le=100)):
    session = SessionLocal()
    try:
        rows = (
            session.query(PredictionLog)
            .order_by(PredictionLog.created_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "id": r.id,
                "created_at": r.created_at.isoformat(),
                "input": r.input_json,
                "predicted_price": r.predicted_price,
                "model_version": r.model_version,
            }
            for r in rows
        ]
    finally:
        session.close()
