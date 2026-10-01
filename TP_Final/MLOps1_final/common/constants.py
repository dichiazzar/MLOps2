""" Valores constantes para el proyecto de predicción de precios de autos usados.

Estos valores fueron extraídos de la salida de la ejecución de Optuna en el notebook 
y de las celdas de feature-engineering; cambiarlos haría que las predicciones servidas 
divergieran de cómo se entrenó realmente ``xgb_best``.
"""

REFERENCE_YEAR = 2020

MARCAS_DOS_PALABRAS = {"Land Rover", "Ashok Leyland"}

OWNER_MAP = {
    "First Owner": 1,
    "Second Owner": 2,
    "Third Owner": 3,
    "Fourth & Above Owner": 4,
    "Test Drive Car": 5,
}

NULL_CHECK_COLUMNS = [
    "mileage_value",
    "engine_value",
    "max_power_value",
    "torque_nm",
    "seats",
]

KM_OUTLIER_THRESHOLD = 1_000_000

TORQUE_KGM_TO_NM = 9.80665

TOP_BRAND_COUNT = 10

NUMERIC_FEATURES = [
    "car_age",
    "km_driven",
    "mileage_value",
    "engine_value",
    "max_power_value",
    "torque_nm",
    "seats",
    "owner_num",
]

BINARY_FEATURES = ["is_manual", "is_individual"]

XGB_PARAMS = {
    "n_estimators": 400,
    "max_depth": 6,
    "learning_rate": 0.029282661153638836,
    "subsample": 0.6293325134244591,
    "colsample_bytree": 0.701705840244853,
    "min_child_weight": 3,
    "reg_alpha": 0.0037885398710451757,
    "reg_lambda": 0.0297461112545255,
    "random_state": 42,
    "n_jobs": -1,
    "objective": "reg:squarederror",
    "tree_method": "hist",
}

TRAIN_TEST_SPLIT_SEED = 42
TRAIN_TEST_SIZE = 0.25

MLFLOW_MODEL_NAME = "xgb_best"
