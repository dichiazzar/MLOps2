from datetime import datetime, timezone

from sqlalchemy import JSON, Column, DateTime, Float, Integer, String
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class PredictionLog(Base):
    __tablename__ = "prediction_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    input_json = Column(JSON, nullable=False)
    predicted_price = Column(Float, nullable=False)
    model_version = Column(String, nullable=False)
