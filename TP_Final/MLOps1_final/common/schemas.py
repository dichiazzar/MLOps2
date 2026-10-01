from enum import Enum

from pydantic import BaseModel, Field


class FuelEnum(str, Enum):
    petrol = "Petrol"
    diesel = "Diesel"
    cng = "CNG"
    lpg = "LPG"
    electric = "Electric"


class SellerTypeEnum(str, Enum):
    individual = "Individual"
    dealer = "Dealer"
    trustmark_dealer = "Trustmark Dealer"


class TransmissionEnum(str, Enum):
    manual = "Manual"
    automatic = "Automatic"


class OwnerEnum(str, Enum):
    first = "First Owner"
    second = "Second Owner"
    third = "Third Owner"
    fourth_and_above = "Fourth & Above Owner"
    test_drive = "Test Drive Car"


class CarRawInput(BaseModel):
    name: str = Field(..., examples=["Maruti Swift Dzire VDI"])
    year: int = Field(..., ge=1980, le=2026)
    km_driven: int = Field(..., ge=0)
    fuel: FuelEnum
    seller_type: SellerTypeEnum
    transmission: TransmissionEnum
    owner: OwnerEnum
    mileage: str = Field(..., examples=["23.4 kmpl"])
    engine: str = Field(..., examples=["1248 CC"])
    max_power: str = Field(..., examples=["74 bhp"])
    torque: str = Field(..., examples=["190Nm@ 2000rpm"])
    seats: float = Field(..., ge=1, le=14)


class PredictionResponse(BaseModel):
    predicted_price: float
    model_version: str
