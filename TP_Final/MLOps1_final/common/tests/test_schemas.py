import pytest
from pydantic import ValidationError

from common.schemas import CarRawInput, PredictionResponse

VALID_PAYLOAD = {
    "name": "Maruti Swift Dzire VDI",
    "year": 2014,
    "km_driven": 145500,
    "fuel": "Diesel",
    "seller_type": "Individual",
    "transmission": "Manual",
    "owner": "First Owner",
    "mileage": "23.4 kmpl",
    "engine": "1248 CC",
    "max_power": "74 bhp",
    "torque": "190Nm@ 2000rpm",
    "seats": 5,
}


def test_car_raw_input_accepts_valid_payload():
    car = CarRawInput(**VALID_PAYLOAD)
    assert car.year == 2014
    assert car.fuel == "Diesel"


def test_car_raw_input_rejects_invalid_fuel():
    payload = {**VALID_PAYLOAD, "fuel": "Nuclear"}
    with pytest.raises(ValidationError):
        CarRawInput(**payload)


def test_car_raw_input_rejects_negative_km_driven():
    payload = {**VALID_PAYLOAD, "km_driven": -100}
    with pytest.raises(ValidationError):
        CarRawInput(**payload)


def test_prediction_response_shape():
    resp = PredictionResponse(predicted_price=403823.11, model_version="3")
    assert resp.predicted_price == 403823.11
    assert resp.model_version == "3"
