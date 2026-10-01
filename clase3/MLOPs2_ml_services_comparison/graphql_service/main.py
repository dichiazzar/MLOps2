from fastapi import FastAPI
import strawberry
from strawberry.fastapi import GraphQLRouter
import joblib
import numpy as np
import os

MODEL_PATH = os.path.join(os.path.dirname(__file__), 'model.pkl')
model = joblib.load(MODEL_PATH)

@strawberry.type
class Prediction:
    class_id: int

@strawberry.type
class Query:
    @strawberry.field
    def predict(self, features: list[float]) -> Prediction:
        input_features = np.array(features).reshape(1, -1)
        prediction = model.predict(input_features)[0]
        return Prediction(class_id=int(prediction))

schema = strawberry.Schema(query=Query)
graphql_app = GraphQLRouter(schema)

app = FastAPI()
app.include_router(graphql_app, prefix="/graphql")

@app.get("/")
def read_root():
    return {"message": "GraphQL ML Service is running. Access /graphql"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
