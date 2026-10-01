from fastapi import FastAPI
from pydantic import BaseModel
import joblib
import numpy as np
import os

MODEL_PATH = os.path.join(os.path.dirname(__file__), 'model.pkl')
model = joblib.load(MODEL_PATH)

class Features(BaseModel):
    values: list[float]

app = FastAPI()

@app.post("/predict")
def predict(features: Features):
    input_features = np.array(features.values).reshape(1, -1)
    prediction = model.predict(input_features)[0]
    return {"class_id": int(prediction)}

@app.get("/")
def read_root():
    return {"message": "REST ML Service is running. Post to /predict"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
