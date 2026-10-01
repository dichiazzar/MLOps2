import numpy as np
import pandas as pd

from common.preprocessing import (
    align_columns,
    build_feature_matrix,
    compute_top_brands,
    drop_km_outliers,
    drop_missing_technical_rows,
    encode_categoricals,
    extraer_columnas_tecnicas,
    extraer_marca_modelo,
    get_all_feature_columns,
    parse_torque,
    split_num_unidad,
)


def test_extraer_marca_modelo_standard():
    result = extraer_marca_modelo("Maruti Swift Dzire VDI")
    assert result.tolist() == ["Maruti", "Swift", "Dzire VDI"]


def test_extraer_marca_modelo_two_word_brand():
    result = extraer_marca_modelo("Land Rover Range Rover Sport")
    assert result.tolist() == ["Land Rover", "Range", "Rover Sport"]


def test_split_num_unidad_cc():
    serie = pd.Series(["1248 CC", "1498 CC"])
    num, unidad = split_num_unidad(serie)
    assert num.tolist() == [1248.0, 1498.0]
    assert unidad.tolist() == ["CC", "CC"]


def test_split_num_unidad_kmpl():
    serie = pd.Series(["23.4 kmpl"])
    num, unidad = split_num_unidad(serie)
    assert num.tolist() == [23.4]
    assert unidad.tolist() == ["kmpl"]


def test_parse_torque_nm():
    val, unit, rpm = parse_torque("190Nm@ 2000rpm")
    assert val == 190.0
    assert unit == "Nm"
    assert rpm == "2000"


def test_parse_torque_kgm():
    val, unit, rpm = parse_torque("11.5@ 4,500(kgm@ rpm)")
    assert val == 11.5
    assert unit == "kgm"


def test_extraer_columnas_tecnicas_car_age_and_torque_conversion():
    df = pd.DataFrame({
        "name": ["Maruti Swift Dzire VDI"],
        "year": [2014],
        "mileage": ["23.4 kmpl"],
        "engine": ["1248 CC"],
        "max_power": ["74 bhp"],
        "torque": ["190Nm@ 2000rpm"],
    })
    out = extraer_columnas_tecnicas(df)
    assert out.loc[0, "car_age"] == 2020 - 2014
    assert out.loc[0, "torque_nm"] == 190.0

    df_kgm = pd.DataFrame({
        "name": ["Test Car X"],
        "year": [2010],
        "mileage": ["20 kmpl"],
        "engine": ["1000 CC"],
        "max_power": ["50 bhp"],
        "torque": ["10kgm@ 2000rpm"],
    })
    out_kgm = extraer_columnas_tecnicas(df_kgm)
    assert out_kgm.loc[0, "torque_nm"] == 10 * 9.80665


def test_drop_missing_technical_rows_drops_nulls():
    df = pd.DataFrame({
        "mileage_value": [1.0, np.nan],
        "engine_value": [1.0, 1.0],
        "max_power_value": [1.0, 1.0],
        "torque_nm": [1.0, 1.0],
        "seats": [5, 5],
    })
    out = drop_missing_technical_rows(df)
    assert len(out) == 1


def test_drop_km_outliers():
    df = pd.DataFrame({"km_driven": [100, 2_000_000]})
    out = drop_km_outliers(df)
    assert out["km_driven"].tolist() == [100]


def test_compute_top_brands_orders_by_frequency():
    df = pd.DataFrame({"brand": ["Maruti"] * 3 + ["Honda"] * 2 + ["Tata"] * 1})
    top = compute_top_brands(df, n=2)
    assert top == ["Maruti", "Honda"]


def test_encode_categoricals_and_feature_matrix_end_to_end():
    df_train = pd.DataFrame({
        "brand": ["Maruti", "Honda", "Maruti"],
        "owner": ["First Owner", "Second Owner", "First Owner"],
        "transmission": ["Manual", "Automatic", "Manual"],
        "seller_type": ["Individual", "Dealer", "Individual"],
        "fuel": ["Petrol", "Diesel", "Petrol"],
        "car_age": [5, 3, 5],
        "km_driven": [10000, 20000, 10000],
        "mileage_value": [20.0, 18.0, 20.0],
        "engine_value": [1000, 1200, 1000],
        "max_power_value": [70, 90, 70],
        "torque_nm": [90.0, 110.0, 90.0],
        "seats": [5, 5, 5],
    })
    df_test = df_train.copy()

    top_brands = compute_top_brands(df_train, n=2)
    df_train_enc, df_test_enc = encode_categoricals(df_train, df_test, top_brands)

    assert df_train_enc.loc[0, "owner_num"] == 1
    assert df_train_enc.loc[0, "is_manual"] == 1
    assert df_train_enc.loc[0, "is_individual"] == 1

    all_features = get_all_feature_columns(df_train_enc)
    df_train_enc, df_test_enc = align_columns(df_train_enc, df_test_enc, all_features)

    X_train = build_feature_matrix(df_train_enc, all_features)
    X_test = build_feature_matrix(df_test_enc, all_features)

    assert list(X_train.columns) == all_features
    assert list(X_test.columns) == all_features
    assert "car_age" in X_train.columns
    assert "is_manual" in X_train.columns


def test_build_inference_features_produces_expected_columns():
    from common.preprocessing import build_inference_features
    from common.schemas import CarRawInput

    car = CarRawInput(
        name="Maruti Swift Dzire VDI",
        year=2014,
        km_driven=145500,
        fuel="Diesel",
        seller_type="Individual",
        transmission="Manual",
        owner="First Owner",
        mileage="23.4 kmpl",
        engine="1248 CC",
        max_power="74 bhp",
        torque="190Nm@ 2000rpm",
        seats=5,
    )
    all_features = [
        "car_age", "km_driven", "mileage_value", "engine_value", "max_power_value",
        "torque_nm", "seats", "owner_num", "is_manual", "is_individual",
        "fuel_Diesel", "fuel_LPG", "brand_grouped_Maruti", "brand_grouped_Other",
    ]
    top_brands = ["Maruti", "Hyundai"]

    row = build_inference_features(car, top_brands, all_features)

    assert list(row.columns) == all_features
    assert row.loc[0, "car_age"] == 2020 - 2014
    assert row.loc[0, "is_manual"] == 1
    assert row.loc[0, "fuel_Diesel"] == 1
    assert row.loc[0, "brand_grouped_Maruti"] == 1
