"""Feature engineering traidas directamente del notebook de entrenamiento.

Cada regex, diccionario y umbral aquí coincide exactamente con el notebook
"""
import re

import numpy as np
import pandas as pd

from common.constants import (
    KM_OUTLIER_THRESHOLD,
    MARCAS_DOS_PALABRAS,
    NULL_CHECK_COLUMNS,
    OWNER_MAP,
    REFERENCE_YEAR,
    TOP_BRAND_COUNT,
    TORQUE_KGM_TO_NM,
)


def extraer_marca_modelo(name):
    if pd.isna(name):
        return pd.Series([np.nan, np.nan, np.nan])
    tokens = name.strip().split()
    dos = " ".join(tokens[:2])
    if dos in MARCAS_DOS_PALABRAS:
        marca = dos
        modelo = tokens[2] if len(tokens) > 2 else np.nan
        resto = " ".join(tokens[3:])
    else:
        marca = tokens[0]
        modelo = tokens[1] if len(tokens) > 1 else np.nan
        resto = " ".join(tokens[2:])
    return pd.Series([marca, modelo, resto if resto else np.nan])


def split_num_unidad(serie: pd.Series):
    num = pd.to_numeric(serie.astype(str).str.extract(r"(-?[\d.]+)")[0], errors="coerce")
    unidad = serie.astype(str).str.extract(r"[\d.]+\s*([A-Za-z/]+)")[0].str.strip()
    return num, unidad


def parse_torque(t):
    if pd.isna(t):
        return pd.Series([np.nan, np.nan, np.nan])
    s = str(t)
    m_val = re.search(r"([\d.]+)", s)
    val = float(m_val.group(1)) if m_val else np.nan
    unit = "kgm" if "kgm" in s.lower() else ("Nm" if "nm" in s.lower() else np.nan)
    rpm = re.search(r"([\d,\-\s]+)\s*rpm", s, re.IGNORECASE)
    rpm_txt = rpm.group(1).replace(",", "").strip() if rpm else np.nan
    return pd.Series([val, unit, rpm_txt])


def extraer_columnas_tecnicas(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df[["brand", "model", "variant"]] = df["name"].apply(extraer_marca_modelo)
    df["mileage_value"], df["mileage_unit"] = split_num_unidad(df["mileage"])
    df["engine_value"], df["engine_unit"] = split_num_unidad(df["engine"])
    df["max_power_value"], df["max_power_unit"] = split_num_unidad(df["max_power"])
    df[["torque_value", "torque_unit", "torque_rpm"]] = df["torque"].apply(parse_torque)
    df["torque_nm"] = np.where(
        df["torque_unit"] == "kgm",
        df["torque_value"] * TORQUE_KGM_TO_NM,
        df["torque_value"],
    )
    df["car_age"] = REFERENCE_YEAR - df["year"]
    return df


def drop_missing_technical_rows(df: pd.DataFrame) -> pd.DataFrame:
    return df.dropna(subset=NULL_CHECK_COLUMNS).reset_index(drop=True)


def drop_km_outliers(df_train: pd.DataFrame) -> pd.DataFrame:
    return df_train[df_train["km_driven"] <= KM_OUTLIER_THRESHOLD].copy()


def compute_top_brands(df_train: pd.DataFrame, n: int = TOP_BRAND_COUNT) -> list:
    return df_train["brand"].value_counts().head(n).index.tolist()


def encode_categoricals(df_train: pd.DataFrame, df_test: pd.DataFrame, top_brands: list):
    df_train = df_train.copy()
    df_test = df_test.copy()

    df_train["owner_num"] = df_train["owner"].map(OWNER_MAP)
    df_test["owner_num"] = df_test["owner"].map(OWNER_MAP)

    df_train["is_manual"] = (df_train["transmission"] == "Manual").astype(int)
    df_test["is_manual"] = (df_test["transmission"] == "Manual").astype(int)

    df_train["is_individual"] = (df_train["seller_type"] == "Individual").astype(int)
    df_test["is_individual"] = (df_test["seller_type"] == "Individual").astype(int)

    df_train["brand_grouped"] = df_train["brand"].where(df_train["brand"].isin(top_brands), "Other")
    df_test["brand_grouped"] = df_test["brand"].where(df_test["brand"].isin(top_brands), "Other")

    df_train_enc = pd.get_dummies(df_train, columns=["fuel", "brand_grouped"], drop_first=True, dtype=int)
    df_test_enc = pd.get_dummies(df_test, columns=["fuel", "brand_grouped"], drop_first=True, dtype=int)

    return df_train_enc, df_test_enc


def get_all_feature_columns(df_train_enc: pd.DataFrame) -> list:
    from common.constants import BINARY_FEATURES, NUMERIC_FEATURES

    features_fuel = [c for c in df_train_enc.columns if c.startswith("fuel_")]
    features_brand = [c for c in df_train_enc.columns if c.startswith("brand_grouped_")]
    return NUMERIC_FEATURES + BINARY_FEATURES + features_fuel + features_brand


def align_columns(df_train_enc: pd.DataFrame, df_test_enc: pd.DataFrame, all_features: list):
    for col in all_features:
        if col not in df_test_enc.columns:
            df_test_enc[col] = 0
        if col not in df_train_enc.columns:
            df_train_enc[col] = 0
    return df_train_enc, df_test_enc


def build_feature_matrix(df_enc: pd.DataFrame, all_features: list) -> pd.DataFrame:
    return df_enc[all_features].copy()


def build_inference_features(car, top_brands: list, all_features: list) -> pd.DataFrame:
    """Turn a single CarRawInput into a one-row model-ready feature DataFrame."""
    df = pd.DataFrame([{
        "name": car.name,
        "year": car.year,
        "km_driven": car.km_driven,
        "fuel": car.fuel.value,
        "seller_type": car.seller_type.value,
        "transmission": car.transmission.value,
        "owner": car.owner.value,
        "mileage": car.mileage,
        "engine": car.engine,
        "max_power": car.max_power,
        "torque": car.torque,
        "seats": car.seats,
    }])
    df = extraer_columnas_tecnicas(df)

    df["owner_num"] = df["owner"].map(OWNER_MAP)
    df["is_manual"] = (df["transmission"] == "Manual").astype(int)
    df["is_individual"] = (df["seller_type"] == "Individual").astype(int)
    df["brand_grouped"] = df["brand"].where(df["brand"].isin(top_brands), "Other")

    # drop_first=False (unlike encode_categoricals): a single-row frame only ever
    # has one observed category per column, so drop_first=True would silently
    # drop the only dummy column instead of a redundant reference category.
    df_enc = pd.get_dummies(df, columns=["fuel", "brand_grouped"], drop_first=False, dtype=int)

    for col in all_features:
        if col not in df_enc.columns:
            df_enc[col] = 0

    return df_enc[all_features].copy()
