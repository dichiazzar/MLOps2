"""Prepara la simulación: reparte el dataset entre las concesionarias (clientes).

Se corre una sola vez, antes de entrenar. En la vida real este paso no existe:
cada concesionaria ya tiene sus propios datos. Acá lo simulamos así:

1. Baja de MinIO el mismo dataset crudo con el que se entrenó xgb_best.
2. Lo separa en entrenamiento y test (mismo split que el TP integrador).
3. Reparte el entrenamiento entre los clientes, de dos formas:
   - iid:    al azar, todos los clientes tienen autos parecidos.
   - no_iid: por rango de precio, cada cliente vende autos de un rango distinto.
4. Sube cada parte a s3://federado/<particion>/cliente_<k>.csv (filas crudas,
   cada cliente las limpia por su cuenta). El test queda para el servidor.
5. Entrena el mismo modelo de forma centralizada, como línea de base para comparar.
"""


import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

from app import datos
from common.constants import TOP_BRAND_COUNT, TRAIN_TEST_SIZE, TRAIN_TEST_SPLIT_SEED
from common.preprocessing import compute_top_brands

log = datos.crear_logger("particionar")


def particion_iid(df, k, rng):
    idx = rng.permutation(len(df))
    return [df.iloc[parte] for parte in np.array_split(idx, k)]


def particion_no_iid(df, k, rng, shards_por_cliente=2):
    # Igual que mini_tp5: ordenar por precio, cortar en shards y dar 2 shards a cada cliente.
    orden = np.argsort(df["selling_price"].to_numpy())
    shards = np.array_split(orden, k * shards_por_cliente)
    rng.shuffle(shards)
    return [
        df.iloc[np.concatenate(shards[i * shards_por_cliente:(i + 1) * shards_por_cliente])]
        for i in range(k)
    ]


def main():
    k = datos.NUM_CLIENTES
    s3 = datos.s3()
    datos.crear_bucket(s3)

    df_raw = datos.leer_csv("car_details_v3.csv", bucket="raw-data").drop_duplicates()
    df_raw = df_raw.reset_index(drop=True)
    bins = pd.qcut(df_raw["selling_price"], q=5, labels=False)
    df_train, df_test = train_test_split(
        df_raw, test_size=TRAIN_TEST_SIZE, stratify=bins, random_state=TRAIN_TEST_SPLIT_SEED
    )
    datos.subir_csv(df_test, "servidor/test.csv")
    log.info("Dataset: %d filas -> train %d / test %d", len(df_raw), len(df_train), len(df_test))

    for nombre, funcion in [("iid", particion_iid), ("no_iid", particion_no_iid)]:
        partes = funcion(df_train, k, np.random.RandomState(datos.SEMILLA))
        for i, parte in enumerate(partes):
            datos.subir_csv(parte, f"{nombre}/cliente_{i}.csv")
            log.info(
                "%-6s cliente_%d: %4d autos | precio promedio %10s",
                nombre, i, len(parte), f"{parte['selling_price'].mean():,.0f}",
            )

    # --- Línea de base: el mismo modelo, entrenado con todos los datos juntos ---
    # Mismo total de pasos de SGD que hace cada cliente en el federado (rondas x épocas).
    epocas = datos.RONDAS * datos.EPOCAS_LOCALES
    train = datos.limpiar(df_train)
    test = datos.limpiar(df_test, quitar_outliers=False)
    top_brands = compute_top_brands(train, TOP_BRAND_COUNT)
    X = datos.matriz_features(train, top_brands)
    media, desvio = datos.media_y_desvio(len(X), X.sum(0), (X**2).sum(0))
    Xtr = datos.estandarizar(X, media, desvio)
    Xte = datos.estandarizar(datos.matriz_features(test, top_brands), media, desvio)
    w, b = datos.init_modelo(Xtr.shape[1])
    w, b = datos.entrenar(w, b, Xtr, datos.target(train), epocas, datos.LR)
    rmse = datos.rmse(w, b, Xte, datos.target(test))
    datos.subir_json(
        {"rmse_log_centralizado": rmse, "epocas": epocas, "lr": datos.LR},
        "servidor/baseline_centralizado.json",
    )
    log.info("Línea de base centralizada: RMSE (log-precio) = %.4f", rmse)
    log.info("Listo. Datos repartidos en s3://%s/", datos.BUCKET)


if __name__ == "__main__":
    main()
